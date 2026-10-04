"""Verify secret configuration using dummy values, without calling Gemini."""

from io import StringIO
import os
import unittest
from unittest.mock import patch

from dotenv import load_dotenv

from src.agents.config import get_llm_client


class AgentConfigTests(unittest.TestCase):
    def test_missing_blank_and_placeholder_keys_are_rejected(self):
        for value in (None, "", "   ", "replace_with_your_gemini_api_key"):
            environment = {} if value is None else {"GEMINI_API_KEY": value}
            with self.subTest(value=value), patch.dict(os.environ, environment, clear=True):
                with patch("src.agents.config.ChatGoogleGenerativeAI") as client:
                    with self.assertRaisesRegex(ValueError, "backend environment"):
                        get_llm_client()
                    client.assert_not_called()

    def test_key_and_model_are_passed_to_backend_client(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": " test-only-key ",
                                     "GEMINI_MODEL": "test-model"}, clear=True):
            with patch("src.agents.config.ChatGoogleGenerativeAI") as client:
                self.assertIs(get_llm_client(), client.return_value)
                client.assert_called_once_with(model="test-model",
                                               google_api_key="test-only-key", temperature=0.0,
                                               max_retries=0, max_output_tokens=2048, timeout=30)

    def test_default_model_is_preserved(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-only-key"}, clear=True):
            with patch("src.agents.config.ChatGoogleGenerativeAI") as client:
                get_llm_client()
                self.assertEqual(client.call_args.kwargs["model"], "gemini-2.5-flash")

    def test_hosted_secret_takes_precedence_over_dotenv(self):
        # In-memory .env content: never read or modify the developer's real file.
        with patch.dict(os.environ, {"GEMINI_API_KEY": "hosted-test-key"}, clear=True):
            load_dotenv(stream=StringIO("GEMINI_API_KEY=local-test-key\n"), override=False)
            with patch("src.agents.config.ChatGoogleGenerativeAI") as client:
                get_llm_client()
                self.assertEqual(client.call_args.kwargs["google_api_key"], "hosted-test-key")
