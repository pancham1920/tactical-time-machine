"""Full invite/API/graph/SQL/checkpoint flow, with only Gemini mocked."""

import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage
from src.agents import graph
from src.agents.memory import open_checkpointer
from src.api import main as api
from src.tools import db_tools


class InviteFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_invite_stream_sql_history_and_other_browser_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            football = root / "football.db"
            connection = sqlite3.connect(football)
            connection.executescript("CREATE TABLE players (name TEXT); INSERT INTO players VALUES ('Test');")
            connection.close()
            model = MagicMock()
            model.ainvoke = AsyncMock(side_effect=[
                AIMessage(content="", tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT COUNT(*) AS players FROM players"}, "id": "query-1"}]),
                AIMessage(content="There is 1 player."),
            ])
            code = "test-only-invitation-code-123456789"
            with patch.dict(os.environ, {"AUTH_MODE": "invite", "DEMO_ACCESS_CODE": code, "DEMO_CHAT_ENABLED": "true"}), \
                 patch.object(db_tools, "DATABASE_PATH", football), \
                 patch.object(graph, "get_llm_client") as factory, \
                 patch.object(api, "open_checkpointer", side_effect=lambda: open_checkpointer(root / "memory.db")):
                factory.return_value.bind_tools.return_value = model
                api.app.middleware_stack = None
                async with api.app.router.lifespan_context(api.app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
                        headers = {"Authorization": "Bearer " + code, "X-Demo-Session": "a" * 64}
                        self.assertEqual((await client.get("/access", headers=headers)).status_code, 200)
                        identifier = str(uuid4())
                        response = await client.post("/chat/stream", headers=headers,
                                                     json={"message": "Count players", "conversation_id": identifier})
                        self.assertEqual(response.status_code, 200)
                        self.assertIn("event: tool_result", response.text)
                        self.assertIn("There is 1 player.", response.text)
                        self.assertIn("event: complete", response.text)
                        history = await client.get(f"/conversations/{identifier}", headers=headers)
                        self.assertEqual(history.status_code, 200)
                        self.assertEqual(history.json()["messages"][-1]["content"], "There is 1 player.")
                        other = await client.get(f"/conversations/{identifier}", headers={**headers, "X-Demo-Session": "b" * 64})
                        self.assertEqual(other.status_code, 404)
                        self.assertEqual(model.ainvoke.await_count, 2)
                        self.assertFalse(api.app.state.active_conversations)
