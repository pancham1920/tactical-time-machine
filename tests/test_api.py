"""Test the HTTP contract without an API key, live model, or football data."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from src.api import main as api


class ApiTests(unittest.TestCase):
    def setUp(self):
        # Patch the graph for every test so none can issue a real Gemini call.
        graph_patch = patch.object(api, "agent_app")
        self.agent = graph_patch.start()
        self.addCleanup(graph_patch.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)

    def test_health_does_not_run_the_agent(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})
        self.agent.invoke.assert_not_called()
        self.agent.stream.assert_not_called()

    def test_invalid_chat_bodies_are_rejected_before_agent_execution(self):
        bodies = [{}, {"message": ""}, {"message": []}, {"message": "x" * 2001}]
        for endpoint in ("/chat", "/chat/stream"):
            for body in bodies:
                with self.subTest(endpoint=endpoint, body=body):
                    response = self.client.post(endpoint, json=body)
                    self.assertEqual(response.status_code, 422)
        self.agent.invoke.assert_not_called()
        self.agent.stream.assert_not_called()

    def test_chat_returns_the_final_agent_answer(self):
        self.agent.invoke.return_value = {
            "messages": [AIMessage(content="There are 3 test matches.")]
        }
        response = self.client.post("/chat", json={"message": "Count matches"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"answer": "There are 3 test matches."})
        input_state = self.agent.invoke.call_args.args[0]
        self.assertEqual(input_state["messages"][0].content, "Count matches")

    def test_chat_failure_returns_generic_502(self):
        self.agent.invoke.side_effect = RuntimeError("Internal test-only detail")
        response = self.client.post("/chat", json={"message": "Count matches"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {"detail": "The football agent could not complete this request."},
        )
        self.assertNotIn("Internal test-only detail", response.text)

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
        self.agent.stream.return_value = iter([
            {"agent": {"messages": [tool_request]}},
            {"tools": {"messages": [tool_message]}},
            {"agent": {"messages": [AIMessage(content="3 test matches.")]}},
        ])

        response = self.client.post("/chat/stream", json={"message": "Count matches"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        events = self.parse_events(response)
        self.assertEqual([name for name, _ in events], [
            "connected", "tool_call", "tool_result", "final_answer", "complete",
        ])
        self.assertEqual(events[1][1], {"tools": ["execute_sql"]})
        self.assertEqual(json.loads(events[2][1]["result"]), tool_result)
        self.assertEqual(events[3][1], {"answer": "3 test matches."})

    def test_stream_failure_emits_error_without_success_event(self):
        self.agent.stream.side_effect = RuntimeError("Model unavailable in test")
        response = self.client.post("/chat/stream", json={"message": "Count matches"})
        # The stream has already started, so failure is communicated as an event.
        self.assertEqual(response.status_code, 200)
        events = self.parse_events(response)
        self.assertEqual([name for name, _ in events], ["connected", "error"])
        self.assertIn("message", events[-1][1])


if __name__ == "__main__":
    unittest.main()
