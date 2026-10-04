"""Real SQLite checkpoints with fake model calls; never touches football data."""

import asyncio
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents import graph
from src.agents.memory import open_checkpointer
from src.api import main as api


class MemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        environment = patch.dict(os.environ, {"AUTH_MODE": "local", "RENDER": ""})
        environment.start()
        self.addCleanup(environment.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "memory.db"
        self.model = MagicMock()
        self.model.ainvoke = AsyncMock(side_effect=lambda *args, **kwargs: AIMessage(content="Saved answer"))
        factory_patch = patch.object(graph, "get_llm_client")
        self.factory = factory_patch.start()
        self.addCleanup(factory_patch.stop)
        self.factory.return_value.bind_tools.return_value = self.model

    async def test_persistence_after_reopen_and_thread_isolation_no_duplicate_inputs(self):
        config = api.thread_config(str(uuid4()))
        async with open_checkpointer(self.path) as saver:
            agent = graph.build_agent(saver)
            await agent.ainvoke({"messages": [HumanMessage(content="Remember Arsenal")]}, config)

        async with open_checkpointer(self.path) as saver:
            agent = graph.build_agent(saver)
            self.model.ainvoke.return_value = AIMessage(content="Follow-up answer")
            await agent.ainvoke({"messages": [HumanMessage(content="Which club?")]}, config)
            sent = self.model.ainvoke.call_args.args[0]
            self.assertEqual([m.content for m in sent if isinstance(m, HumanMessage)],
                             ["Remember Arsenal", "Which club?"])
            snapshot = await agent.aget_state(config)
            self.assertEqual(len(snapshot.values["messages"]), 4)
            other = api.thread_config(str(uuid4()))
            await agent.ainvoke({"messages": [HumanMessage(content="New chat")]}, other)
            sent = self.model.ainvoke.call_args.args[0]
            self.assertEqual([m.content for m in sent if isinstance(m, HumanMessage)], ["New chat"])

    async def test_actual_async_tool_loop_persists_evidence_for_followup(self):
        tool_call = AIMessage(content="", tool_calls=[{
            "name": "execute_sql", "args": {"query": "SELECT 1"}, "id": "count-query",
        }])
        self.model.ainvoke.side_effect = [tool_call, AIMessage(content="There are 3 matches"), AIMessage(content="Three")]
        config = api.thread_config(str(uuid4()))
        with patch("src.tools.db_tools.run_query", return_value={"rows": [{"count": 3}], "truncated": False}):
            async with open_checkpointer(self.path) as saver:
                agent = graph.build_agent(saver)
                updates = [update async for update in agent.astream(
                    {"messages": [HumanMessage(content="Count matches")]}, config, stream_mode="updates")]
                self.assertEqual([next(iter(item)) for item in updates], ["agent", "tools", "agent"])
                await agent.ainvoke({"messages": [HumanMessage(content="Repeat that count")]}, config)
                sent = self.model.ainvoke.call_args.args[0]
                evidence = [message for message in sent if isinstance(message, ToolMessage)]
                self.assertEqual(len(evidence), 1)
                self.assertIn('"count": 3', evidence[0].content)

    async def test_failed_turn_does_not_replay_or_poison_next_question(self):
        config = api.thread_config(str(uuid4()))
        self.model.ainvoke.side_effect = RuntimeError("Model failed")
        async with open_checkpointer(self.path) as saver:
            agent = graph.build_agent(saver)
            with self.assertRaises(RuntimeError):
                await agent.ainvoke({"messages": [HumanMessage(content="Interrupted question")]}, config)
        self.model.ainvoke.side_effect = None
        self.model.ainvoke.return_value = AIMessage(content="Recovered answer")
        async with open_checkpointer(self.path) as saver:
            agent = graph.build_agent(saver)
            await agent.ainvoke({"messages": [HumanMessage(content="New question")]}, config)
            sent = self.model.ainvoke.call_args.args[0]
            self.assertEqual([m.content for m in sent if isinstance(m, HumanMessage)], ["New question"])
            snapshot = await agent.aget_state(config)
            self.assertEqual([m.content for m in snapshot.values["messages"] if isinstance(m, HumanMessage)],
                             ["Interrupted question", "New question"])

    async def test_api_lifespan_uses_disk_memory_and_survives_restart(self):
        config_id = str(uuid4())
        with patch.object(api, "open_checkpointer", side_effect=lambda: open_checkpointer(self.path)):
            for question in ("Remember Arsenal", "Which club?"):
                async with api.app.router.lifespan_context(api.app):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
                        response = await client.post("/chat", json={"message": question, "conversation_id": config_id})
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(response.json()["conversation_id"], config_id)
                        calls = self.model.ainvoke.call_count
                        history = await client.get(f"/conversations/{config_id}")
                        self.assertEqual(history.status_code, 200)
                        self.assertEqual(history.json()["messages"][-2]["content"], question)
                        self.assertEqual(history.json()["messages"][-1]["status"], "complete")
                        self.assertEqual(self.model.ainvoke.call_count, calls)
            sent = self.model.ainvoke.call_args.args[0]
            self.assertEqual([m.content for m in sent if isinstance(m, HumanMessage)], ["Remember Arsenal", "Which club?"])

    async def test_pending_tool_checkpoint_is_not_replayed_on_new_input(self):
        config = api.thread_config(str(uuid4()))
        pending = AIMessage(content="", tool_calls=[{
            "name": "execute_sql", "args": {"query": "SELECT 1"}, "id": "interrupted-tool",
        }])
        async with open_checkpointer(self.path) as saver:
            agent = graph.build_agent(saver)
            await agent.aupdate_state(config, {"messages": [HumanMessage(content="Old question"), pending]}, as_node="agent")
        with patch("src.tools.db_tools.run_query", side_effect=AssertionError("Old tool must not replay")) as query:
            async with open_checkpointer(self.path) as saver:
                agent = graph.build_agent(saver)
                await agent.ainvoke({"messages": [HumanMessage(content="Fresh question")]}, config)
                query.assert_not_called()
                sent = self.model.ainvoke.call_args.args[0]
                self.assertEqual([m.content for m in sent if isinstance(m, HumanMessage)], ["Fresh question"])
                self.assertFalse(any(isinstance(m, ToolMessage) for m in sent))


class ConcurrentApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        environment = patch.dict(os.environ, {"AUTH_MODE": "local", "RENDER": ""})
        environment.start()
        self.addCleanup(environment.stop)

    async def test_stream_holds_guard_but_different_thread_can_run(self):
        started, release = asyncio.Event(), asyncio.Event()
        fake = MagicMock()
        fake.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="Other answer")]})

        async def updates(*args, **kwargs):
            started.set()
            await release.wait()
            yield {"agent": {"messages": [AIMessage(content="Stream answer")]}}

        fake.astream.side_effect = updates
        active = set()
        with patch.object(api.app.state, "agent", fake, create=True), patch.object(api.app.state, "active_conversations", active, create=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
                conversation_id = str(uuid4())
                body = {"message": "Wait", "conversation_id": conversation_id}
                task = asyncio.create_task(client.post("/chat/stream", json=body))
                try:
                    await asyncio.wait_for(started.wait(), 3)
                    for endpoint in ("/chat", "/chat/stream"):
                        self.assertEqual((await client.post(endpoint, json=body)).status_code, 409)
                    self.assertEqual((await client.post("/chat", json={"message": "Other"})).status_code, 200)
                finally:
                    release.set()
                    response = await task
                self.assertEqual(response.status_code, 200)
                self.assertFalse(active)
                self.assertEqual((await client.post("/chat", json=body)).status_code, 200)

    async def test_cancelled_stream_closes_graph_and_releases_guard(self):
        started, closed = asyncio.Event(), asyncio.Event()
        fake = MagicMock()

        async def updates(*args, **kwargs):
            try:
                started.set()
                await asyncio.Event().wait()
                yield {}  # Makes this a generator; never reached.
            finally:
                closed.set()

        fake.astream.side_effect = updates
        active = set()
        with patch.object(api.app.state, "agent", fake, create=True), patch.object(api.app.state, "active_conversations", active, create=True):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api.app), base_url="http://test") as client:
                task = asyncio.create_task(client.post("/chat/stream", json={"message": "Wait"}))
                await asyncio.wait_for(started.wait(), 3)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertTrue(closed.is_set())
                self.assertFalse(active)

    async def test_response_releases_guard_if_sending_headers_fails(self):
        active = {"test"}
        async def events():
            yield "test"
        response = api.ConversationStreamResponse(events(), active, "test")
        async def send(message):
            raise OSError("Disconnected before first event")
        async def receive():
            return {"type": "http.disconnect"}
        with self.assertRaises(Exception):
            await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
        self.assertFalse(active)
