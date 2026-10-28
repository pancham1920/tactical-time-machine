import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.create_sample_db import create_sample
from scripts.evaluate_agent import CASES, score_answer, summarize, verify_gold
from src.tools.db_tools import run_query
from src.agents.memory import checkpoint_path


class EvaluationTests(unittest.TestCase):
    def test_sample_cannot_be_used_as_checkpoint_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sample.db"
            create_sample(database)
            with patch.dict(os.environ, {
                "FOOTBALL_DB_PATH": str(database),
                "CONVERSATION_DB_PATH": str(database),
            }):
                with self.assertRaisesRegex(ValueError, "separate"):
                    checkpoint_path()

    def test_all_forty_gold_cases_and_protected_sql_executor(self):
        cases = json.loads(CASES.read_text())
        self.assertEqual(len(cases), 40)
        self.assertEqual(len({c['id'] for c in cases}), 40)
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "sample.db"
            create_sample(database)
            verify_gold(database, cases)
            with patch.dict(os.environ, {"FOOTBALL_DB_PATH": str(database)}):
                for case in cases:
                    with self.subTest(case=case["id"]):
                        result = run_query(case["sql"])
                        self.assertNotIn("error", result)
                        self.assertEqual(next(iter(result["rows"][0].values())), case["expected"])
            with self.assertRaises(FileExistsError):
                create_sample(database)

    def test_numeric_scoring_does_not_accept_incidental_numbers(self):
        self.assertTrue(score_answer("There are eight.\nRESULT: 8", 8))
        self.assertFalse(score_answer("8 matches in 2024", 8))
        self.assertFalse(score_answer("RESULT: 80", 8))
        self.assertFalse(score_answer("RESULT: 8\nRESULT: 9", 8))

    def test_unrun_cases_are_not_counted_as_model_results(self):
        result = summarize([{"status": "not_run"}])
        self.assertEqual(result["attempted"], 0)
        self.assertIsNone(result["answer_correctness_of_attempted"])
