"""Exercise the SQL tool using synthetic data in a temporary database."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine

from src.tools import db_tools


class DatabaseToolTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database_path = Path(directory.name) / "test.db"
        self.engine = create_engine(f"sqlite:///{database_path}")
        self.addCleanup(self.engine.dispose)

        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE players (player_id INTEGER PRIMARY KEY, name TEXT)"
            )
            connection.exec_driver_sql(
                "INSERT INTO players (player_id, name) VALUES (?, ?)",
                [(number, f"Test Player {number}") for number in range(1, 106)],
            )

        engine_patch = patch.object(
            db_tools, "get_database_engine", return_value=self.engine
        )
        self.engine_factory = engine_patch.start()
        self.addCleanup(engine_patch.stop)

    def invoke_query(self, query):
        return json.loads(db_tools.execute_sql.invoke({"query": query}))

    def test_select_returns_serializable_rows(self):
        result = self.invoke_query("SELECT COUNT(*) AS players FROM players")
        self.assertEqual(result["columns"], ["players"])
        self.assertEqual(result["rows"], [{"players": 105}])
        self.assertFalse(result["truncated"])

    def test_read_only_cte_is_accepted(self):
        result = self.invoke_query(
            "WITH first_player AS (SELECT name FROM players WHERE player_id = 1) "
            "SELECT name FROM first_player"
        )
        self.assertEqual(result["rows"], [{"name": "Test Player 1"}])

    def test_writes_and_multiple_statements_never_reach_database(self):
        queries = [
            "DELETE FROM players",
            "UPDATE players SET name = 'changed'",
            "DROP TABLE players",
            "WITH ids AS (SELECT player_id FROM players) DELETE FROM players",
            "SELECT 1; SELECT 2",
            "PRAGMA table_info(players)",
            "",
        ]
        for query in queries:
            with self.subTest(query=query):
                self.engine_factory.reset_mock()
                self.assertIn("error", self.invoke_query(query))
                self.engine_factory.assert_not_called()

        # Confirm the original records survived every rejected request.
        result = self.invoke_query("SELECT COUNT(*) AS players FROM players")
        self.assertEqual(result["rows"], [{"players": 105}])

    def test_invalid_sql_is_returned_as_an_error(self):
        result = self.invoke_query("SELECT name FROM missing_table")
        self.assertIn("error", result)
        self.assertIn("no such table", result["error"])

    def test_large_result_is_capped_and_marked_truncated(self):
        result = self.invoke_query(
            "SELECT player_id FROM players ORDER BY player_id"
        )
        self.assertEqual(len(result["rows"]), 100)
        self.assertEqual(result["rows"][-1], {"player_id": 100})
        self.assertTrue(result["truncated"])

    def test_exactly_one_hundred_rows_is_not_truncated(self):
        result = self.invoke_query(
            "SELECT player_id FROM players ORDER BY player_id LIMIT 100"
        )
        self.assertEqual(len(result["rows"]), 100)
        self.assertFalse(result["truncated"])


if __name__ == "__main__":
    unittest.main()
