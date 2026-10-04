import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.agents.history import conversation_messages
from src.api.main import tool_result_payload


class HistoryTests(unittest.TestCase):
    def test_multiple_turns_results_and_interruption_are_projected_with_stable_ids(self):
        messages = [HumanMessage(content="First", id="a"), AIMessage(content="First answer"),
                    HumanMessage(content="Second", id="b"),
                    ToolMessage(content='{"error":"private SQL error"}', tool_call_id="q1"),
                    ToolMessage(content='{"columns":[],"rows":[],"truncated":false}', tool_call_id="q2")]
        first = conversation_messages(messages, tool_result_payload)
        self.assertEqual(first, conversation_messages(messages, tool_result_payload))
        self.assertEqual(len(first), 4)
        self.assertEqual(first[1]["status"], "complete")
        self.assertEqual(first[3]["status"], "error")
        self.assertEqual(len(first[3]["results"]), 2)
        self.assertNotIn("private SQL error", str(first))
        self.assertEqual(first[1]["results"], [])

    def test_pending_tool_calls_and_thinking_are_not_exposed(self):
        messages = [HumanMessage(content="Question"), AIMessage(content="internal intermediate text", tool_calls=[{
            "name": "execute_sql", "args": {"query": "SELECT secret"}, "id": "q1",
        }])]
        projected = conversation_messages(messages, tool_result_payload)
        self.assertEqual(projected[1]["status"], "error")
        self.assertEqual(projected[1]["content"], "")
        self.assertNotIn("SELECT secret", str(projected))
