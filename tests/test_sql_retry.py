import json
import sqlite3
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.exc import OperationalError

from src.agents import graph
from src.agents.sql_retry import query_fingerprint, STOP_TEXT
from src.tools.db_tools import classify_sql_error


def call(query, ident):
    return AIMessage(content="", tool_calls=[{"id": ident, "name": "execute_sql", "args": {"query": query}}])


ERROR = {"error": "no such column: wrong", "error_code": "invalid_sql", "retryable": True}
SUCCESS = {"columns": ["count"], "rows": [{"count": 3}], "truncated": False}


class RetryTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, responses, results, checkpointer=None, config=None):
        with patch.object(graph, "get_llm_client") as factory, patch("src.agents.sql_retry.execute_sql") as tool:
            execute = tool.invoke
            model = factory.return_value.bind_tools.return_value
            model.ainvoke = AsyncMock(side_effect=responses)
            execute.side_effect = [json.dumps(result) for result in results]
            agent = graph.build_agent(checkpointer)
            state = await agent.ainvoke({"messages": [HumanMessage(content="Count matches")]}, config)
            return state, execute.call_count, model.ainvoke.call_count

    async def test_failure_then_success_returns_answer(self):
        state, tools, models = await self.run_case(
            [call("SELECT wrong", "a"), call("SELECT count(*) FROM games", "b"), AIMessage(content="Three")], [ERROR, SUCCESS])
        self.assertEqual(state["messages"][-1].content, "Three")
        self.assertEqual((tools, models), (2, 3))
        self.assertEqual(len([m for m in state["messages"] if isinstance(m, ToolMessage)]), 2)

    async def test_two_corrections_then_stop_without_fourth_model_call(self):
        state, tools, models = await self.run_case([call(f"SELECT wrong{i}", str(i)) for i in range(3)], [ERROR] * 3)
        self.assertEqual(state["messages"][-1].content, STOP_TEXT["retry_exhausted"])
        self.assertEqual((tools, models), (3, 3))

    async def test_repeated_failed_query_stops_before_database(self):
        state, tools, models = await self.run_case([call("SELECT wrong", "a"), call(" select   WRONG ; ", "b")], [ERROR])
        self.assertEqual(tools, 1)
        self.assertEqual(state["messages"][-1].content, STOP_TEXT["repeated_query"])

    async def test_nonretryable_and_safety_errors_stop_immediately(self):
        for code, reason in [("database_setup", "database_error"), ("query_rejected", "query_rejected")]:
            with self.subTest(code=code):
                state, tools, models = await self.run_case([call("SELECT x", "a")], [{"error": "failed", "error_code": code, "retryable": False}])
                self.assertEqual((tools, models), (1, 1))
                self.assertEqual(state["messages"][-1].content, STOP_TEXT[reason])

    async def test_empty_results_are_success_not_retry_failure(self):
        state, tools, models = await self.run_case([call("SELECT 1 WHERE 0", "a"), AIMessage(content="No matching records")],
            [{"columns": [], "rows": [], "truncated": False}])
        self.assertEqual(state["messages"][-1].content, "No matching records")
        self.assertEqual(tools, 1)

    async def test_multi_call_batch_is_bounded_and_all_calls_receive_results(self):
        batch = AIMessage(content="", tool_calls=[{"id": str(i), "name": "execute_sql", "args": {"query": f"SELECT wrong{i}"}} for i in range(6)])
        state, tools, models = await self.run_case([batch], [ERROR] * 3)
        self.assertEqual(tools, 3)
        results = [m for m in state["messages"] if isinstance(m, ToolMessage)]
        self.assertEqual(len(results), 6)
        self.assertEqual([m.tool_call_id for m in results], [str(i) for i in range(6)])

    async def test_successful_queries_hit_total_limit_not_retry_budget(self):
        state, tools, models = await self.run_case([call(f"SELECT {i}", str(i)) for i in range(9)], [SUCCESS] * 8)
        self.assertEqual(tools, 8)
        self.assertEqual(state["messages"][-1].content, STOP_TEXT["tool_limit"])

    async def test_new_question_resets_budget_even_with_checkpoint_history(self):
        with patch.object(graph, "get_llm_client") as factory, patch("src.agents.sql_retry.execute_sql") as tool:
            execute = tool.invoke
            execute.return_value = json.dumps(ERROR)
            model = factory.return_value.bind_tools.return_value
            model.ainvoke = AsyncMock(side_effect=[call(f"SELECT wrong{i}", str(i)) for i in range(6)])
            agent = graph.build_agent(InMemorySaver())
            config = {"configurable": {"thread_id": "test"}}
            for question in ("First", "Second"):
                state = await agent.ainvoke({"messages": [HumanMessage(content=question)]}, config)
                self.assertEqual(state["messages"][-1].content, STOP_TEXT["retry_exhausted"])
            self.assertEqual(execute.call_count, 6)

    async def test_success_does_not_reset_spent_correction_budget(self):
        responses = [call(f"SELECT value{i}", str(i)) for i in range(5)]
        state, tools, models = await self.run_case(responses, [ERROR, SUCCESS, ERROR, SUCCESS, ERROR])
        self.assertEqual((tools, models), (5, 5))
        self.assertEqual(state["messages"][-1].content, STOP_TEXT["retry_exhausted"])

    def test_classifier_distinguishes_query_errors_from_infrastructure(self):
        cases = [
            ("no such column: match_date", True), ("no such table: matches", True),
            ("no such function: YEAR", True), ("ambiguous column name: name", True),
            ('near "TOP": syntax error', True), ("misuse of aggregate: COUNT()", True),
            ("no such table: games", False), ("database is locked", False),
            ("unable to open database file", False), ("disk I/O error", False),
        ]
        for detail, expected in cases:
            with self.subTest(detail=detail):
                result = classify_sql_error(OperationalError("SELECT secret", {}, sqlite3.OperationalError(detail)))
                self.assertEqual(result["retryable"], expected)
                self.assertNotIn("SELECT secret", result["error"])

    def test_fingerprint_does_not_merge_different_string_literals(self):
        self.assertEqual(query_fingerprint("SELECT name FROM players;"), query_fingerprint(" select NAME from players "))
        self.assertNotEqual(query_fingerprint("SELECT 'Arsenal'"), query_fingerprint("SELECT 'arsenal'"))
