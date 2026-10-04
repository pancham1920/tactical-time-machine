"""Select a bounded view of checkpoint history without changing stored messages."""

import json
import os
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


class ContextLimitError(ValueError):
    """The current exchange cannot safely fit the configured input budget."""


CONTEXT_LIMIT_MESSAGE = "This exchange is too large. Narrow your question or start a new chat."


def context_budget() -> int:
    budget = int(os.getenv("AGENT_CONTEXT_MAX_CHARS", "64000"))
    if budget < 1:
        raise ValueError("AGENT_CONTEXT_MAX_CHARS must be positive")
    return budget


def message_size(message: BaseMessage) -> int: 
    # Character count is a transparent approximation, NOT Gemini token counting.
    return len(json.dumps({
        "type": message.type, "content": message.content,
        "tool_calls": getattr(message, "tool_calls", []),
        "tool_call_id": getattr(message, "tool_call_id", None),
    }, ensure_ascii=False, default=str))


def valid_turn(turn: Sequence[BaseMessage], *, completed: bool) -> bool:
    if not turn or not isinstance(turn[0], HumanMessage):
        return False
    pending = set()
    seen = set()
    for index, message in enumerate(turn[1:], start=1):
        if isinstance(message, AIMessage):
            if pending:
                return False
            calls = message.tool_calls
            if not calls:
                # A final answer must end the turn, not precede more tool activity.
                if index != len(turn) - 1:
                    return False
            for call in calls:
                call_id = call.get("id")
                if not call_id or call_id in seen:
                    return False
                pending.add(call_id)
                seen.add(call_id)
        elif isinstance(message, ToolMessage):
            if message.tool_call_id not in pending:
                return False
            pending.remove(message.tool_call_id)
        else:
            return False
    if pending:
        return False
    return not completed or (isinstance(turn[-1], AIMessage) and not turn[-1].tool_calls)


def select_model_messages(messages: Sequence[BaseMessage], budget: int) -> list[BaseMessage]:
    """Keep current turn and a recent contiguous suffix of complete prior turns."""
    turns = []
    for message in messages:
        if isinstance(message, HumanMessage):
            turns.append([])
        if not turns:
            raise ContextLimitError(CONTEXT_LIMIT_MESSAGE)
        turns[-1].append(message)
    if not turns or not valid_turn(turns[-1], completed=False):
        raise ContextLimitError("This exchange has incomplete tool context. Start a new chat.")
    current = turns[-1]
    used = sum(message_size(message) for message in current)
    if used > budget:
        raise ContextLimitError(CONTEXT_LIMIT_MESSAGE)
    selected = [current]
    for turn in reversed(turns[:-1]):
        # Do not cross an interrupted turn or a budget gap: this avoids pretending
        # that an older answer was the immediately preceding discussion.
        if not valid_turn(turn, completed=True):
            break
        size = sum(message_size(message) for message in turn)
        if used + size > budget:
            break
        selected.insert(0, turn)
        used += size
    return [message for turn in selected for message in turn]
