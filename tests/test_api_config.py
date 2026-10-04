"""Production-origin configuration tests: no database or model required."""

import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from src.api.config import allowed_origins


class ApiConfigTests(unittest.TestCase):
    def test_default_is_local_frontend(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(allowed_origins(), ["http://localhost:5173"])

    def test_explicit_origins_replace_default_and_deduplicate(self):
        with patch.dict(os.environ, {
            "CORS_ALLOWED_ORIGINS": " https://demo.vercel.app,https://other.example,https://demo.vercel.app "
        }):
            self.assertEqual(allowed_origins(), ["https://demo.vercel.app", "https://other.example"])

    def test_invalid_configuration_fails_early(self):
        for value in ("", "*", "null", "ftp://example.com", "https://example.com/",
                      "https://example.com/chat", "https://user:pass@example.com",
                      "https://example.com?x=1", "https://example.com#fragment",
                      "https://*.example.com", "https://example.com:bad",
                      "https://example.com:99999", "https://example.com,",
                      "https://exa mple.com"):
            with self.subTest(value=value), patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": value}):
                with self.assertRaisesRegex(ValueError, "CORS_ALLOWED_ORIGINS"):
                    allowed_origins()

    def test_preflight_allows_only_configured_origin(self):
        with patch.dict(os.environ, {"CORS_ALLOWED_ORIGINS": "https://demo.vercel.app"}):
            app = FastAPI()
            app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(),
                               allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
        with TestClient(app) as client:
            for endpoint in ("/chat", "/chat/stream", "/conversations/test"):
                for origin, expected in (("https://demo.vercel.app", 200),
                                         ("http://localhost:5173", 400),
                                         ("https://untrusted.example", 400)):
                    with self.subTest(endpoint=endpoint, origin=origin):
                        response = client.options(endpoint, headers={
                            "Origin": origin,
                            "Access-Control-Request-Method": "GET" if "conversations" in endpoint else "POST",
                            "Access-Control-Request-Headers": "content-type",
                        })
                        self.assertEqual(response.status_code, expected)
                        self.assertEqual(response.headers.get("access-control-allow-origin"),
                                         origin if expected == 200 else None)
