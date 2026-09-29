"""FastAPI application entry point for the football agent backend."""

from collections.abc import AsyncIterator
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from src.agents.graph import agent_app


app = FastAPI(title="Tactical Time-Machine API")

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


async def stream_agent_updates(message: str) -> AsyncIterator[dict]:
    """Yield each LangGraph update produced while answering one message."""
    input_state = {"messages": [HumanMessage(content=message)]}

    for update in agent_app.stream(input_state, stream_mode="updates"):
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


async def stream_sse_events(message: str) -> AsyncIterator[str]:
    """Convert LangGraph updates into browser-readable SSE events."""
    yield format_sse_event("connected", {"message": "Agent started"})

    try:
        async for update in stream_agent_updates(message):
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
    except Exception as exc:
        yield format_sse_event("error", {"message": str(exc)})
    else:
        yield format_sse_event("complete", {})


@app.get("/health")
def health_check() -> dict[str, str]:
    """Report whether the API server is running."""
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, str]:
    """Run one football-agent question and return its final answer as JSON."""
    try:
        final_state = agent_app.invoke(
            {"messages": [HumanMessage(content=request.message)]}
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="The football agent could not complete this request.",
        ) from exc

    answer = final_state["messages"][-1].content
    return {"answer": answer}


@app.post("/chat/stream")
async def stream_chat(request: ChatRequest) -> StreamingResponse:
    """Stream one football-agent response as Server-Sent Events."""
    return StreamingResponse(
        stream_sse_events(request.message),
        media_type="text/event-stream",
    )
