"""Exercise real SQLite connection safeguards, not a patched query engine."""

from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy.exc import DatabaseError
from src.tools import db_tools


class SqlSafetyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "football.db"
        connection = sqlite3.connect(self.path)
        connection.executescript("CREATE TABLE players (name TEXT); INSERT INTO players VALUES ('Test'); CREATE TABLE private_data (secret TEXT);")
        connection.close()
        change = patch.object(db_tools, "DATABASE_PATH", self.path)
        change.start()
        self.addCleanup(change.stop)

    def test_read_succeeds_and_unlisted_tables_and_functions_are_denied(self):
        self.assertEqual(db_tools.run_query("SELECT COUNT(*) AS count FROM players")["rows"], [{"count": 1}])
        for query in ("SELECT * FROM private_data", "SELECT * FROM sqlite_master", "SELECT load_extension('x')", "SELECT randomblob(1000000000)"):
            with self.subTest(query=query):
                self.assertIn("error", db_tools.run_query(query))

    def test_write_is_denied_even_without_regex_guard(self):
        engine = db_tools.get_database_engine()
        try:
            with engine.connect() as connection:
                with self.assertRaises(DatabaseError):
                    connection.exec_driver_sql("DELETE FROM players")
        finally:
            engine.dispose()
        self.assertEqual(db_tools.run_query("SELECT COUNT(*) AS count FROM players")["rows"], [{"count": 1}])

    def test_recursive_query_is_interrupted_by_execution_deadline(self):
        with patch.object(db_tools, "SQL_TIMEOUT_SECONDS", 0):
            result = db_tools.run_query("WITH RECURSIVE numbers(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM numbers) SELECT SUM(n) FROM numbers")
        self.assertIn("error", result)
        self.assertFalse(result["retryable"])
