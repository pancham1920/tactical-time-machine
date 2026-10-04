"""Test the HTTP contract without an API key, live model, or football data."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace
from uuid import uuid4, UUID

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from src.api import main as api


class ApiTests(unittest.TestCase):
    def setUp(self):
        # Patch the graph for every test so none can issue a real Gemini call.
        self.agent = MagicMock()
        self.agent.ainvoke = AsyncMock()
        self.agent.aget_state = AsyncMock()
        self.stream_updates = []
        self.stream_error = None

        async def stream(*args, **kwargs):
            if self.stream_error:
                raise self.stream_error
            for update in self.stream_updates:
                yield update

        self.agent.astream.side_effect = stream
        graph_patch = patch.object(api.app.state, "agent", self.agent, create=True)
        graph_patch.start()
        self.addCleanup(graph_patch.stop)
        active_patch = patch.object(api.app.state, "active_conversations", set(), create=True)
        active_patch.start()
        self.addCleanup(active_patch.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def test_health_does_not_run_the_agent(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.agent.ainvoke.assert_not_called()
        self.agent.astream.assert_not_called()

    def test_invalid_chat_bodies_are_rejected_before_agent_execution(self):
        bodies = [{}, {"message": ""}, {"message": "   "}, {"message": []}, {"message": "x" * 2001},
                  {"message": "hello", "conversation_id": "not-a-uuid"}]
        for endpoint in ("/chat", "/chat/stream"):
            for body in bodies:
                with self.subTest(endpoint=endpoint, body=body):
                    response = self.client.post(endpoint, json=body)
                    self.assertEqual(response.status_code, 422)
        self.agent.ainvoke.assert_not_called()
        self.agent.astream.assert_not_called()

    def test_chat_returns_the_final_agent_answer(self):
        self.agent.ainvoke.return_value = {
            "messages": [AIMessage(content="There are 3 test matches.")]
        }
        response = self.client.post("/chat", json={"message": "Count matches"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "There are 3 test matches.")
        UUID(response.json()["conversation_id"])
        input_state = self.agent.ainvoke.call_args.args[0]
        self.assertEqual(input_state["messages"][0].content, "Count matches")
        self.assertEqual(self.agent.ainvoke.call_args.args[1], api.thread_config(response.json()["conversation_id"]))
        self.assertFalse(api.app.state.active_conversations)

    def test_chat_failure_returns_generic_502(self):
        self.agent.ainvoke.side_effect = RuntimeError("Internal test-only detail")
        response = self.client.post("/chat", json={"message": "Count matches"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {"detail": "The football agent could not complete this request."},
        )
        self.assertNotIn("Internal test-only detail", response.text)
        self.assertFalse(api.app.state.active_conversations)

    @staticmethod
    def parse_events(response):
        events = []
        for frame in response.text.strip().split("\n\n"):
            event_line, data_line = frame.split("\n")
            events.append(
                (
                    event_line.removeprefix("event: "),
                    json.loads(data_line.removeprefix("data: ")),
                )
            )
        return events

    def test_stream_reports_tool_activity_and_final_answer(self):
        tool_result = {
            "columns": ["matches"],
            "rows": [{"matches": 3}],
            "truncated": False,
        }
        tool_request = AIMessage(
            content="",
            tool_calls=[{
                "name": "execute_sql",
                "id": "test-query",
                "args": {"query": "SELECT COUNT(*) AS matches FROM games"},
            }],
        )
        tool_message = ToolMessage(
            content=json.dumps(tool_result), tool_call_id="test-query"
        )
        self.stream_updates = [
            {"agent": {"messages": [tool_request]}},
            {"tools": {"messages": [tool_message]}},
            {"agent": {"messages": [AIMessage(content="3 test matches.")]}},
        ]

        response = self.client.post("/chat/stream", json={"message": "Count matches"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        events = self.parse_events(response)
        self.assertEqual([name for name, _ in events], [
            "connected", "tool_call", "tool_result", "final_answer", "complete",
        ])
        self.assertEqual(events[1][1], {"tools": ["execute_sql"]})
        self.assertEqual(events[2][1], {
            "tool_call_id": "test-query", "tool": "execute_sql", "result": tool_result,
        })
        self.assertEqual(events[3][1], {"answer": "3 test matches."})

    def test_stream_failure_emits_error_without_success_event(self):
        self.stream_error = RuntimeError("Model unavailable in test")
        response = self.client.post("/chat/stream", json={"message": "Count matches"})
        # The stream has already started, so failure is communicated as an event.
        self.assertEqual(response.status_code, 200)
        events = self.parse_events(response)
        self.assertEqual([name for name, _ in events], ["connected", "error"])
        self.assertIn("message", events[-1][1])
        self.assertNotIn("Model unavailable in test", response.text)
        self.assertFalse(api.app.state.active_conversations)

    def test_stream_emits_every_tool_result_and_sanitizes_errors(self):
        contents = [
            json.dumps({"columns": ["count"], "rows": [{"count": 0}], "truncated": False}),
            json.dumps({"error": "SQL failed at /private/path"}),
            "not JSON",
            json.dumps({"columns": [], "rows": [], "truncated": False}),
        ]
        self.stream_updates = [
            {"tools": {"messages": [
                ToolMessage(content=content, tool_call_id=f"query-{index}", name="execute_sql")
                for index, content in enumerate(contents)
            ]}},
            {"agent": {"messages": [AIMessage(content="Finished.")]}},
        ]
        response = self.client.post("/chat/stream", json={"message": "Count matches"})
        results = [data for name, data in self.parse_events(response) if name == "tool_result"]
        self.assertEqual([item["tool_call_id"] for item in results], [f"query-{i}" for i in range(4)])
        self.assertEqual(results[0]["result"]["rows"], [{"count": 0}])
        self.assertIn("error", results[1]["result"])
        self.assertIn("error", results[2]["result"])
        self.assertEqual(results[3]["result"]["rows"], [])
        self.assertNotIn("/private/path", response.text)

    def test_invalid_tool_result_shapes_become_safe_errors(self):
        for content in ['[]', '{}', '{"columns": ["x"], "rows": "bad", "truncated": false}',
                        '{"columns": ["x"], "rows": [{"x": NaN}], "truncated": false}']:
            with self.subTest(content=content):
                payload = api.tool_result_payload(ToolMessage(content=content, tool_call_id="test"))
                self.assertIn("error", payload["result"])

    def test_existing_id_is_forwarded_and_omitted_ids_are_fresh(self):
        self.stream_updates = [{"agent": {"messages": [AIMessage(content="Answer")]}}]
        conversation_id = str(uuid4())
        response = self.client.post("/chat/stream", json={"message": "  Follow up  ", "conversation_id": conversation_id})
        self.assertEqual(self.parse_events(response)[0][1]["conversation_id"], conversation_id)
        args = self.agent.astream.call_args.args
        self.assertEqual(len(args[0]["messages"]), 1)
        self.assertEqual(args[0]["messages"][0].content, "Follow up")
        self.assertEqual(args[1], api.thread_config(conversation_id))
        ids = [self.parse_events(self.client.post("/chat/stream", json={"message": "Hello"}))[0][1]["conversation_id"] for _ in range(2)]
        self.assertNotEqual(*ids)
        self.assertFalse(api.app.state.active_conversations)

    def test_busy_conversation_rejected_before_stream_headers(self):
        conversation_id = str(uuid4())
        api.app.state.active_conversations.add(conversation_id)
        for endpoint in ("/chat", "/chat/stream"):
            response = self.client.post(endpoint, json={"message": "Hi", "conversation_id": conversation_id})
            self.assertEqual(response.status_code, 409)
        self.agent.ainvoke.assert_not_called()
        self.agent.astream.assert_not_called()

    def test_context_limit_is_explicit_and_releases_guard(self):
        self.stream_error = api.ContextLimitError("Narrow the question")
        response = self.client.post("/chat/stream", json={"message": "Hi"})
        self.assertEqual(self.parse_events(response)[-1][1]["code"], "context_limit")
        self.assertFalse(api.app.state.active_conversations)
        self.agent.ainvoke.side_effect = api.ContextLimitError("Narrow the question")
        self.assertEqual(self.client.post("/chat", json={"message": "Hi"}).status_code, 413)
        self.assertFalse(api.app.state.active_conversations)

    def test_history_returns_only_projected_messages_without_model_calls(self):
        from langchain_core.messages import HumanMessage, SystemMessage
        conversation_id = str(uuid4())
        self.agent.aget_state.return_value = SimpleNamespace(values={"messages": [
            SystemMessage(content="Private instructions"),
            HumanMessage(content="Count", id="human-1"),
            AIMessage(content="", tool_calls=[{"name": "execute_sql", "args": {"query": "SELECT 3"}, "id": "q1"}]),
            ToolMessage(content='{"columns":["count"],"rows":[{"count":3}],"truncated":false}', tool_call_id="q1"),
            AIMessage(content=[{"type": "text", "text": "Three"}, {"type": "thinking", "text": "private reasoning"}]),
        ]})
        response = self.client.get(f"/conversations/{conversation_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        messages = response.json()["messages"]
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertEqual(messages[1]["content"], "Three")
        self.assertEqual(messages[1]["results"][0]["result"]["rows"], [{"count": 3}])
        self.assertEqual(messages[1]["status"], "complete")
        self.assertNotIn("Private instructions", response.text)
        self.assertNotIn("private reasoning", response.text)
        self.assertNotIn("SELECT 3", response.text)
        self.agent.ainvoke.assert_not_called()
        self.agent.astream.assert_not_called()
        self.agent.aget_state.assert_awaited_once_with(api.thread_config(conversation_id))
        self.assertFalse(api.app.state.active_conversations)

    def test_history_unknown_invalid_busy_and_storage_errors(self):
        conversation_id = str(uuid4())
        self.agent.aget_state.return_value = SimpleNamespace(values={})
        self.assertEqual(self.client.get(f"/conversations/{conversation_id}").status_code, 404)
        self.assertEqual(self.client.get("/conversations/invalid").status_code, 422)
        api.app.state.active_conversations.add(conversation_id)
        self.assertEqual(self.client.get(f"/conversations/{conversation_id}").status_code, 409)
        api.app.state.active_conversations.clear()
        self.agent.aget_state.side_effect = RuntimeError("private database path")
        response = self.client.get(f"/conversations/{conversation_id}")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private database path", response.text)
        self.assertFalse(api.app.state.active_conversations)

    def test_sql_stop_node_is_streamed_as_final_answer(self):
        self.stream_updates = [{"sql_stop": {"messages": [AIMessage(content="SQL correction limit reached.")]}}]
        response = self.client.post("/chat/stream", json={"message": "Count matches"})
        events = self.parse_events(response)
        self.assertEqual([name for name, _ in events], ["connected", "final_answer", "complete"])
        self.assertEqual(events[1][1]["answer"], "SQL correction limit reached.")


if __name__ == "__main__":
    unittest.main()
