"""Checkpoint location and ephemeral storage behaviour without model calls."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.agents import memory


class MemoryConfigTests(unittest.IsolatedAsyncioTestCase):
    def test_default_remains_local(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(memory.checkpoint_path(), memory.MEMORY_PATH)

    def test_relative_path_is_rooted_in_project(self):
        with patch.dict(os.environ, {"CONVERSATION_DB_PATH": "runtime/chat.db"}):
            self.assertEqual(memory.checkpoint_path(), memory.PROJECT_ROOT / "runtime/chat.db")

    def test_invalid_paths_are_rejected(self):
        for path in ("", " ", ":memory:", "football_vault.db", str(memory.PROJECT_ROOT)):
            with self.subTest(path=path), patch.dict(os.environ, {"CONVERSATION_DB_PATH": path}):
                with self.assertRaises(ValueError):
                    memory.checkpoint_path()

    async def test_configured_path_creates_parent_and_fresh_storage_has_no_history(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime" / "chat.db"
            with patch.dict(os.environ, {"CONVERSATION_DB_PATH": str(path)}):
                async with memory.open_checkpointer() as saver:
                    self.assertIsNone(await saver.aget_tuple({"configurable": {"thread_id": "old-browser-id"}}))
            self.assertTrue(path.is_file())
