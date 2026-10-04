"""Invite-code verification and bounded, single-worker demo admission."""

import hashlib
import hmac
import os
import re
import time

import anyio
from fastapi import HTTPException
from starlette.responses import JSONResponse

REQUEST_TIMEOUT_SECONDS = 90


def auth_mode() -> str:
    mode = os.getenv("AUTH_MODE", "invite")
    if mode not in ("invite", "local") or (mode == "local" and os.getenv("RENDER")):
        raise HTTPException(503, "Authentication configuration is invalid.")
    return mode


def access_code() -> str:
    code = os.getenv("DEMO_ACCESS_CODE", "")
    if len(code) < 24 or code != code.strip() or code == "replace_with_a_random_access_code":
        raise HTTPException(503, "Demo access code is not configured.")
    return code


def verify_access(token: str, session: str) -> str:
    secret = access_code()
    if not hmac.compare_digest(token.encode(), secret.encode()) or not re.fullmatch(r"[a-f0-9]{64}", session):
        raise HTTPException(401, "Invalid access code or browser session.")
    return hmac.new(secret.encode(), session.encode(), hashlib.sha256).hexdigest()


def owned_thread(user_id: str, conversation_id: str) -> str:
    # Old local threads are never reachable through a hosted account.
    if user_id == "local":
        return conversation_id
    return "user:" + hashlib.sha256(f"{user_id}:{conversation_id}".encode()).hexdigest()


class Budget:
    """Fixed-window limits. Process-local; resets on restart, not a billing cap."""

    def __init__(self):
        self.counters = {}

    def take(self, key: str, maximum: int, seconds: int):
        now = time.time()
        self.counters = {k: v for k, v in self.counters.items() if v[1] > now}
        count, end = self.counters.get(key, (0, (int(now) // seconds + 1) * seconds))
        if count >= maximum:
            raise HTTPException(429, "Demo usage limit reached. Try later.",
                                headers={"Retry-After": str(max(1, int(end - now)))})
        self.counters[key] = (count + 1, end)


class SecurityMiddleware:
    """Protect all non-health HTTP routes before body parsing; retain SSE streaming."""

    def __init__(self, app):
        self.app = app
        self.budget = Budget()
        self.inflight = 0
        self.chat_users = set()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/health" or scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        try:
            mode = auth_mode()
            if mode == "local":
                # Explicit development bypass, never enable on a public bind.
                scope.setdefault("state", {})["user_id"] = "local"
                return await self.app(scope, receive, send)
            self.budget.take("incoming", 60, 60)
            if self.inflight >= 4:
                raise HTTPException(429, "Demo is busy. Try later.", headers={"Retry-After": "10"})
        except HTTPException as exc:
            return await JSONResponse({"detail": exc.detail}, exc.status_code, headers=exc.headers)(scope, receive, send)

        self.inflight += 1
        chat_owner = None
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message.setdefault("headers", []).extend([
                    (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
                ])
            await send(message)

        try:
            with anyio.fail_after(REQUEST_TIMEOUT_SECONDS):
                headers = dict(scope["headers"])
                authorization = headers.get(b"authorization", b"").decode("latin1")
                if not authorization.startswith("Bearer ") or not 1 <= len(authorization[7:]) <= 8192:
                    raise HTTPException(401, "Enter the demo access code to continue.", headers={"WWW-Authenticate": "Bearer"})
                session = headers.get(b"x-demo-session", b"").decode("latin1")
                user_id = verify_access(authorization[7:], session)
                scope.setdefault("state", {})["user_id"] = user_id
                self.budget.take("requests:" + user_id, 30, 60)
                is_chat = scope["method"] == "POST" and scope["path"] in ("/chat", "/chat/stream")
                if is_chat:
                    if os.getenv("DEMO_CHAT_ENABLED", "false") != "true":
                        raise HTTPException(503, "Live demo chat is disabled until free-tier settings are verified.")
                    if user_id in self.chat_users or len(self.chat_users) >= 2:
                        raise HTTPException(429, "A chat is already running or the demo is busy.", headers={"Retry-After": "10"})
                    self.budget.take("chat-minute:" + user_id, 2, 60)
                    self.budget.take("chat-day:" + user_id, 10, 86400)
                    self.budget.take("global-day", 30, 86400)
                    self.chat_users.add(user_id)
                    chat_owner = user_id
                # Buffer at most 16 KiB, including chunked bodies, before FastAPI parses JSON.
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    body.extend(message.get("body", b""))
                    if len(body) > 16 * 1024:
                        raise HTTPException(413, "Request body is too large.")
                    if not message.get("more_body", False):
                        break
                delivered = False

                async def buffered_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, buffered_receive, tracked_send)
        except HTTPException as exc:
            if not started:
                await JSONResponse({"detail": exc.detail}, exc.status_code, headers=exc.headers)(scope, receive, send)
        except TimeoutError:
            if not started:
                await JSONResponse({"detail": "Request timed out."}, 504)(scope, receive, send)
            else:
                # End an already-started stream as interrupted, never claim completion.
                await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            if chat_owner:
                self.chat_users.discard(chat_owner)
            self.inflight -= 1
