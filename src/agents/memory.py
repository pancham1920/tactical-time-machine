"""Application-owned SQLite checkpoint connection; never exposed as a SQL tool."""

from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

MEMORY_PATH = Path(__file__).resolve().parents[2] / "conversation_memory.db"


@asynccontextmanager
async def open_checkpointer(path: Path = MEMORY_PATH):
    async with AsyncSqliteSaver.from_conn_string(str(path)) as saver:
        # A startup read initializes storage through the saver before serving traffic.
        await saver.aget_tuple({"configurable": {"thread_id": "__startup__"}})
        yield saver
