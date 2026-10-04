import unittest
import httpx
from scripts.check_deployment import check, origin


class DeploymentCheckTests(unittest.TestCase):
    def test_checks_never_submit_a_valid_question(self):
        calls = []
        def handler(request):
            calls.append(request)
            if request.method == "POST":
                self.assertEqual(request.content, b"{}")
                return httpx.Response(503 if "authorization" in request.headers else 401)
            if request.method == "OPTIONS":
                return httpx.Response(200, headers={"access-control-allow-origin": "https://demo.vercel.app"})
            return httpx.Response(200, json={"status": "ok"})
        check("https://demo.onrender.com", "https://demo.vercel.app", "test-code", httpx.MockTransport(handler))
        self.assertEqual(len(calls), 6)

    def test_unsafe_origins_are_rejected(self):
        for value in ("http://example.com", "https://user:pass@example.com", "https://example.com/chat", "https://example.com?secret=x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                origin(value)

    def test_redirect_is_not_followed_with_invitation(self):
        def handler(request):
            return httpx.Response(302, headers={"location": "https://other.example"})
        with self.assertRaises(ValueError):
            check("https://demo.onrender.com", "https://demo.vercel.app", "test", httpx.MockTransport(handler))
