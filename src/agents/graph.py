from typing import Annotated, Sequence, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from src.agents.config import get_llm_client
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
    messages = state["messages"]

    # Provide schema and analyst guidance on every call; prompts are not enforcement.
    system_message = SystemMessage(content=SYSTEM_PROMPT)
    response = llm.invoke([system_message] + list(messages))

    return {"messages": [response]}


# 3. Define the Router Edge logic
def should_continue(state: AgentState):
    last_message = state["messages"][-1]

    # If the model requests a tool action, we route it onward
    if last_message.tool_calls:
        return "continue"

    # If it writes a conversational final message, we stop execution
    return "end"


# 4. Construct and Compile the State Machine Structure
workflow = StateGraph(AgentState)

# Register our agent execution node
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(TOOLS))
workflow.set_entry_point("agent")

# Set up routing conditional paths
workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "continue": "tools",
        "end": END,
    },
)
workflow.add_edge("tools", "agent")

# Compile graph app execution target
agent_app = workflow.compile()
