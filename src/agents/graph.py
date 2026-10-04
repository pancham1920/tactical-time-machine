from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from src.agents.config import get_llm_client
from src.agents.context import context_budget, select_model_messages
from src.agents.prompts import SYSTEM_PROMPT
from src.tools.db_tools import execute_sql


TOOLS = [execute_sql]


# 1. Define the Application Memory State
class AgentState(TypedDict):
    # add_messages appends new interactions rather than overwriting history
    messages: Annotated[Sequence[BaseMessage], add_messages]


# 2. Define the Execution Node
def call_model(state: AgentState):
    llm = get_llm_client().bind_tools(TOOLS)
    response = llm.invoke(model_messages(state))

    return {"messages": [response]}


def model_messages(state: AgentState):
    # Reserve room for the system prompt and tool schemas/serialization overhead.
    remaining = context_budget() - len(SYSTEM_PROMPT) - 8000
    messages = select_model_messages(state["messages"], remaining)
    return [SystemMessage(content=SYSTEM_PROMPT), *messages]


async def acall_model(state: AgentState):
    llm = get_llm_client().bind_tools(TOOLS)
    response = await llm.ainvoke(model_messages(state))
    return {"messages": [response]}


# 3. Define the Router Edge logic
def should_continue(state: AgentState):
    last_message = state["messages"][-1]

    # If the model requests a tool action, we route it onward
    if last_message.tool_calls:
        return "continue"

    # If it writes a conversational final message, we stop execution
    return "end"


def build_agent(checkpointer=None):
    workflow = StateGraph(AgentState)
    # The API uses the async implementation; the CLI can still invoke synchronously.
    workflow.add_node("agent", RunnableLambda(call_model, afunc=acall_model))
    workflow.add_node("tools", ToolNode(TOOLS))
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent", should_continue, {"continue": "tools", "end": END},
    )
    workflow.add_edge("tools", "agent")
    return workflow.compile(checkpointer=checkpointer)


# Nonpersistent graph for the CLI smoke test; API owns its persistent instance.
agent_app = build_agent()
