"""Application-owned SQLite checkpoint connection; never exposed as a SQL tool."""

from contextlib import asynccontextmanager
import os
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

MEMORY_PATH = Path(__file__).resolve().parents[2] / "conversation_memory.db"
PROJECT_ROOT = MEMORY_PATH.parent


def checkpoint_path() -> Path:
    """Resolve the checkpoint location without changing the local default."""
    setting = os.getenv("CONVERSATION_DB_PATH", str(MEMORY_PATH)).strip()
    if not setting or setting == ":memory:":
        raise ValueError("CONVERSATION_DB_PATH must name a separate SQLite file.")
    path = Path(setting)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path = path.resolve()
    football = PROJECT_ROOT / "football_vault.db"
    if path == football.resolve() or (
        path.exists() and football.exists() and path.samefile(football)
    ):
        raise ValueError("Conversation storage must be separate from football data.")
    if path.is_dir():
        raise ValueError("CONVERSATION_DB_PATH must name a file, not a directory.")
    return path


@asynccontextmanager
async def open_checkpointer(path: Path | None = None):
    database = checkpoint_path() if path is None else path
    database.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(database)) as saver:
        # A startup read initializes storage through the saver before serving traffic.
        await saver.aget_tuple({"configurable": {"thread_id": "__startup__"}})
        yield saver
