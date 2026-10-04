import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from src.agents.context import ContextLimitError, message_size, select_model_messages


def exchange():
    return [HumanMessage(content="Count matches"), AIMessage(content="", tool_calls=[
        {"name": "execute_sql", "args": {"query": "SELECT 1"}, "id": "a"},
        {"name": "execute_sql", "args": {"query": "SELECT 2"}, "id": "b"},
    ]), ToolMessage(content="2", tool_call_id="b"), ToolMessage(content="1", tool_call_id="a"),
        AIMessage(content="Three matches")]


class ContextTests(unittest.TestCase):
    def test_complete_tool_turns_are_preserved_without_mutating_history(self):
        messages = exchange() + [HumanMessage(content="Which teams?")]
        before = list(messages)
        self.assertEqual(select_model_messages(messages, 10000), messages)
        self.assertEqual(messages, before)

    def test_budget_removes_whole_turn_not_tool_pair(self):
        recent = exchange() + [HumanMessage(content="Follow up")]
        old = [HumanMessage(content="Old"), AIMessage(content="Old answer")]
        budget = sum(map(message_size, recent))
        self.assertEqual(select_model_messages(old + recent, budget), recent)
        self.assertEqual(select_model_messages(recent, budget - 1), recent[-1:])

    def test_oversized_current_turn_fails_without_slicing_evidence(self):
        current = exchange()[:-1]
        with self.assertRaises(ContextLimitError):
            select_model_messages(current, sum(map(message_size, current)) - 1)

    def test_interrupted_prior_turn_and_older_context_are_omitted(self):
        current = HumanMessage(content="New question")
        for incomplete in [exchange()[:1], exchange()[:2], exchange()[:3], exchange()[:-1]]:
            self.assertEqual(select_model_messages(exchange() + incomplete + [current], 10000), [current])

    def test_orphan_missing_duplicate_and_out_of_order_tool_results_rejected(self):
        for turn in [exchange()[:2], exchange()[:3],
                     [HumanMessage(content="Hi"), ToolMessage(content="1", tool_call_id="unknown")],
                     exchange()[:4] + [ToolMessage(content="1", tool_call_id="a")],
                     exchange()[:2] + [AIMessage(content="premature")]]:
            with self.subTest(turn=turn), self.assertRaises(ContextLimitError):
                select_model_messages(turn, 10000)

    def test_current_user_message_always_retained(self):
        question = HumanMessage(content="Hi")
        self.assertEqual(select_model_messages([question], message_size(question)), [question])
