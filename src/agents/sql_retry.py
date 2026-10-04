"""Deterministic per-question SQL limits, independent of model compliance."""

import json
import re

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.tools.db_tools import execute_sql

MAX_CORRECTIONS = 2
MAX_TOOL_CALLS = 8
STOP_TEXT = {
    "retry_exhausted": "I could not retrieve a reliable answer after two SQL correction attempts. Please narrow or rephrase the question.",
    "repeated_query": "I stopped because the agent repeated a failed SQL query. I could not complete the analysis; please rephrase the question.",
    "tool_limit": "I stopped at the query limit for this question. Please narrow its scope. Any results shown are partial analysis.",
    "query_rejected": "I could not complete this request because a query failed the read-only safety checks. Those checks cannot be bypassed.",
    "database_error": "I could not complete the analysis because the database or tool was unavailable. Check the database setup before trying again.",
}


def current_turn(messages):
    start = next((i for i in range(len(messages) - 1, -1, -1) if isinstance(messages[i], HumanMessage)), 0)
    return messages[start:]


def query_fingerprint(query: str) -> tuple:
    # Preserve quoted literals/identifiers; normalize case and whitespace elsewhere.
    tokens = re.findall(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`[^`]*`|\[[^\]]*\]|\w+|[^\s]", query)
    while tokens and tokens[-1] == ";":
        tokens.pop()
    return tuple(token if token[0] in "'\"`[" else token.lower() for token in tokens)


def result_data(message):
    try:
        data = json.loads(message.content)
        if isinstance(data, dict):
            return data
    except (TypeError, ValueError):
        pass
    return {"error": "Invalid tool response", "retryable": False}


def retry_state(messages):
    calls = {}
    failed = set()
    count = 0
    corrections = 0
    correcting = False
    for message in current_turn(messages):
        if isinstance(message, AIMessage):
            calls.update({call["id"]: call for call in message.tool_calls})
        elif isinstance(message, ToolMessage):
            call = calls.get(message.tool_call_id)
            if not call:
                continue
            count += 1
            if correcting:
                corrections += 1
            data = result_data(message)
            if "error" in data:
                query = call.get("args", {}).get("query")
                if isinstance(query, str):
                    failed.add(query_fingerprint(query))
                correcting = True
            else:
                correcting = False
    return count, corrections, correcting, failed


def guarded_tools(state):
    """Run calls sequentially, accounting for each one (including multi-call batches)."""
    messages = list(state["messages"])
    count, corrections, correcting, failed = retry_state(messages)
    outputs = []
    stop = None
    for call in messages[-1].tool_calls:
        query = call.get("args", {}).get("query")
        if stop is None:
            if count >= MAX_TOOL_CALLS:
                stop = "tool_limit"
            elif correcting and corrections >= MAX_CORRECTIONS:
                stop = "retry_exhausted"
            elif call["name"] != "execute_sql" or not isinstance(query, str):
                stop = "query_rejected"
            elif query_fingerprint(query) in failed:
                stop = "repeated_query"
        if stop is None:
            if correcting:
                corrections += 1
            count += 1
            try:
                content = execute_sql.invoke({"query": query})
                message = ToolMessage(content=content, tool_call_id=call["id"], name="execute_sql")
                data = result_data(message)
            except Exception:
                data = {"error": "SQL tool execution failed", "retryable": False}
            if "error" in data:
                failed.add(query_fingerprint(query))
                correcting = True
                if not data.get("retryable", False):
                    stop = "query_rejected" if data.get("error_code") == "query_rejected" else "database_error"
                elif corrections >= MAX_CORRECTIONS:
                    stop = "retry_exhausted"
            else:
                correcting = False
        else:
            data = {"error": "Query not executed: SQL recovery stopped.", "retryable": False}
        if stop:
            data = {**data, "stop_reason": stop, "retryable": False}
        outputs.append(ToolMessage(content=json.dumps(data), tool_call_id=call["id"], name=call["name"]))
    return {"messages": outputs}


def after_tools(state):
    for message in reversed(state["messages"]):
        if not isinstance(message, ToolMessage):
            break
        if result_data(message).get("stop_reason"):
            return "stop"
    return "continue"


def stop_sql(state):
    reason = result_data(state["messages"][-1]).get("stop_reason", "database_error")
    return {"messages": [AIMessage(content=STOP_TEXT.get(reason, STOP_TEXT["database_error"]))]}
