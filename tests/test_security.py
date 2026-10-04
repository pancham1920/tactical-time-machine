"""Invite access and chat isolation without network or model calls."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from src.api import main as api, security

CODE = "test-only-long-random-code-123456789"


class InviteTests(unittest.TestCase):
    def setUp(self):
        change = patch.dict(os.environ, {"AUTH_MODE": "invite", "DEMO_ACCESS_CODE": CODE, "DEMO_CHAT_ENABLED": "true"})
        change.start()
        self.addCleanup(change.stop)
        api.app.middleware_stack = None
        self.agent = MagicMock()
        self.agent.ainvoke = AsyncMock(return_value={"messages": [AIMessage(content="Answer")]})
        self.agent.aget_state = AsyncMock(return_value=SimpleNamespace(values={}))
        for name, value in (("agent", self.agent), ("active_conversations", set())):
            change = patch.object(api.app.state, name, value, create=True)
            change.start()
            self.addCleanup(change.stop)
        self.client = TestClient(api.app)
        self.addCleanup(self.client.close)
        self.headers = {"Authorization": "Bearer " + CODE, "X-Demo-Session": "a" * 64}

    def test_missing_wrong_and_valid_codes(self):
        self.assertEqual(self.client.get("/access").status_code, 401)
        self.assertEqual(self.client.get("/access", headers={**self.headers, "Authorization": "Bearer wrong"}).status_code, 401)
        self.assertEqual(self.client.get("/access", headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.agent.ainvoke.assert_not_called()

    def test_same_conversation_id_is_isolated_by_browser_secret(self):
        conversation = str(uuid4())
        response = self.client.post("/chat", headers=self.headers, json={"message": "Hi", "conversation_id": conversation})
        self.assertEqual(response.status_code, 200)
        first = self.agent.ainvoke.call_args.args[1]
        self.agent.aget_state.side_effect = lambda config: SimpleNamespace(values={"messages": [AIMessage(content="Private")]} if config == first else {})
        response = self.client.get(f"/conversations/{conversation}", headers={**self.headers, "X-Demo-Session": "b" * 64})
        self.assertEqual(response.status_code, 404)

    def test_chat_limit_and_kill_switch(self):
        for _ in range(2):
            self.assertEqual(self.client.post("/chat", headers=self.headers, json={"message": "Hi"}).status_code, 200)
        self.assertEqual(self.client.post("/chat", headers=self.headers, json={"message": "Hi"}).status_code, 429)
        with patch.dict(os.environ, {"DEMO_CHAT_ENABLED": "false"}):
            self.assertEqual(self.client.post("/chat", headers=self.headers, json={"message": "Hi"}).status_code, 503)

    def test_missing_configuration_and_hosted_bypass_fail_closed(self):
        with patch.dict(os.environ, {"DEMO_ACCESS_CODE": ""}):
            self.assertEqual(self.client.get("/access", headers=self.headers).status_code, 503)
        with patch.dict(os.environ, {"AUTH_MODE": "local", "RENDER": "true"}):
            self.assertEqual(self.client.get("/access").status_code, 503)

    def test_rotation_changes_namespace_and_session_is_required(self):
        first = security.verify_access(CODE, "a" * 64)
        with self.assertRaises(HTTPException):
            security.verify_access(CODE, "")
        with patch.dict(os.environ, {"DEMO_ACCESS_CODE": CODE + "new"}):
            self.assertNotEqual(first, security.verify_access(CODE + "new", "a" * 64))

    def test_global_budget(self):
        budget = security.Budget()
        budget.take("global-day", 1, 86400)
        with self.assertRaises(HTTPException):
            budget.take("global-day", 1, 86400)
