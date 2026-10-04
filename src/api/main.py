"""FastAPI application entry point for the football agent backend."""

from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
import json
from uuid import UUID, uuid4

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, field_validator

from src.agents.graph import build_agent
from src.agents.memory import open_checkpointer
from src.agents.context import ContextLimitError, context_budget
from src.agents.history import conversation_messages


@asynccontextmanager
async def lifespan(app: FastAPI):
    context_budget()  # Fail early on invalid configuration.
    async with open_checkpointer() as saver:
        app.state.agent = build_agent(saver)
        app.state.active_conversations = set()
        yield


app = FastAPI(title="Tactical Time-Machine API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    """JSON body accepted by the chat endpoint."""

    message: str = Field(min_length=1, max_length=2_000)
    conversation_id: UUID | None = None

    @field_validator("message")
    @classmethod
    def nonblank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message cannot be blank")
        return value.strip()


def thread_config(conversation_id: str) -> dict:
    return {"configurable": {"thread_id": conversation_id}}


def reserve_conversation(request: Request, body: ChatRequest) -> str:
    conversation_id = str(body.conversation_id or uuid4())
    acquire_conversation(request.app.state.active_conversations, conversation_id)
    return conversation_id


def acquire_conversation(active: set, conversation_id: str):
    # No await between check and add: atomic on this single event loop/worker.
    if conversation_id in active:
        raise HTTPException(status_code=409, detail="This conversation is busy. Try again shortly.")
    active.add(conversation_id)


async def stream_agent_updates(agent, message: str, conversation_id: str) -> AsyncIterator[dict]:
    """Yield each LangGraph update produced while answering one message."""
    input_state = {"messages": [HumanMessage(content=message)]}

    async with aclosing(agent.astream(input_state, thread_config(conversation_id), stream_mode="updates")) as updates:
        async for update in updates:
            yield update


def format_sse_event(event: str, data: dict) -> str:
    """Format one browser-readable Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def tool_result_payload(message) -> dict:
    """Decode tool JSON at the HTTP boundary; never expose raw tool errors."""
    try:
        result = json.loads(message.content)
        if not isinstance(result, dict) or "error" in result:
            raise ValueError("Tool failed")
        columns = result["columns"]
        rows = result["rows"]
        if (
            not isinstance(columns, list)
            or not all(isinstance(column, str) for column in columns)
            or len(set(columns)) != len(columns)
            or not isinstance(rows, list)
            or not all(isinstance(row, dict) for row in rows)
            or not isinstance(result.get("truncated"), bool)
        ):
            raise ValueError("Invalid result structure")
        # Round-trip strictly: non-finite numbers are not valid browser JSON.
        result = {"columns": columns, "rows": rows, "truncated": result["truncated"]}
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError, KeyError):
        result = {"error": "This database query could not produce displayable results."}
    return {
        "tool_call_id": message.tool_call_id,
        "tool": message.name or "execute_sql",
        "result": result,
    }


async def stream_sse_events(agent, message: str, conversation_id: str) -> AsyncIterator[str]:
    """Convert LangGraph updates into browser-readable SSE events."""
    yield format_sse_event("connected", {"message": "Agent started", "conversation_id": conversation_id})

    try:
        async with aclosing(stream_agent_updates(agent, message, conversation_id)) as updates:
            async for update in updates:
                for node_name, state_data in update.items():
                    if node_name == "tools":
                        for tool_message in state_data["messages"]:
                            yield format_sse_event("tool_result", tool_result_payload(tool_message))
                        continue
                    last_message = state_data["messages"][-1]

                    if node_name == "agent" and last_message.tool_calls:
                        tool_names = [call["name"] for call in last_message.tool_calls]
                        yield format_sse_event("tool_call", {"tools": tool_names})
                    elif node_name == "agent":
                        yield format_sse_event(
                            "final_answer", {"answer": last_message.content}
                        )
    except ContextLimitError as exc:
        yield format_sse_event("error", {"code": "context_limit", "message": str(exc)})
    except Exception:
        yield format_sse_event("error", {"message": "The football agent could not complete this request."})
    else:
        yield format_sse_event("complete", {})


@app.get("/health")
def health_check() -> dict[str, str]:
    """Report whether the API server is running."""
    return {"status": "ok"}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: UUID, request: Request):
    """Restore a local conversation without invoking the model or returning metadata."""
    thread_id = str(conversation_id)
    active = request.app.state.active_conversations
    acquire_conversation(active, thread_id)
    try:
        snapshot = await request.app.state.agent.aget_state(thread_config(thread_id))
        messages = snapshot.values.get("messages", [])
        if not messages:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return JSONResponse({
            "conversation_id": thread_id,
            "messages": conversation_messages(messages, tool_result_payload),
        }, headers={"Cache-Control": "no-store"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Conversation history is unavailable. Try again.") from exc
    finally:
        active.discard(thread_id)


@app.post("/chat")
async def chat(body: ChatRequest, request: Request) -> dict:
    """Run one football-agent question and return its final answer as JSON."""
    conversation_id = reserve_conversation(request, body)
    try:
        final_state = await request.app.state.agent.ainvoke(
            {"messages": [HumanMessage(content=body.message)]}, thread_config(conversation_id),
        )
        answer = final_state["messages"][-1].content
        return {"answer": answer, "conversation_id": conversation_id}
    except ContextLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The football agent could not complete this request.",
        ) from exc

    finally:
        request.app.state.active_conversations.discard(conversation_id)


class ConversationStreamResponse(StreamingResponse):
    """Release the busy guard even if disconnect occurs before iteration starts."""

    def __init__(self, content, active: set, conversation_id: str):
        super().__init__(content, media_type="text/event-stream")
        self.active = active
        self.conversation_id = conversation_id

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Ensure nested graph iterators finish cleanup before releasing the guard.
            try:
                with anyio.CancelScope(shield=True):
                    await self.body_iterator.aclose()
            finally:
                self.active.discard(self.conversation_id)


@app.post("/chat/stream")
async def stream_chat(body: ChatRequest, request: Request) -> StreamingResponse:
    """Stream one football-agent response as Server-Sent Events."""
    conversation_id = reserve_conversation(request, body)
    return ConversationStreamResponse(
        stream_sse_events(request.app.state.agent, body.message, conversation_id),
        request.app.state.active_conversations, conversation_id,
    )
