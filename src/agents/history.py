"""Project checkpoint messages into UI data, never raw graph/internal state."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def visible_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(block["text"] for block in content
                         if isinstance(block, dict) and block.get("type") == "text"
                         and isinstance(block.get("text"), str))
    return ""


def conversation_messages(messages, format_result) -> list[dict]:
    """One user/assistant pair per turn; unfinished turns retain partial results."""
    output = []
    assistant = None
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            turn_id = str(message.id or f"turn-{index}")
            output.append({"id": f"user-{turn_id}", "role": "user",
                           "content": visible_text(message.content)})
            assistant = {"id": f"assistant-{turn_id}", "role": "assistant",
                         "content": "", "results": [], "status": "error"}
            output.append(assistant)
        elif assistant is not None and isinstance(message, ToolMessage):
            if message.name not in (None, "execute_sql"):
                continue
            payload = format_result(message)
            assistant["results"] = [item for item in assistant["results"]
                                    if item["tool_call_id"] != payload["tool_call_id"]]
            assistant["results"].append(payload)
        elif assistant is not None and isinstance(message, AIMessage) and not message.tool_calls:
            text = visible_text(message.content)
            if text.strip():
                assistant["content"] = text
                assistant["status"] = "complete"
    return output
