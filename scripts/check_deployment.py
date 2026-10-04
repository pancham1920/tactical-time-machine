"""Read-only hosted checks. Never submits a valid model question."""

import argparse
from getpass import getpass
import secrets
from urllib.parse import urlsplit

import httpx


def origin(value: str) -> str:
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Provide an HTTPS origin, without credentials, path, or query.")
    return value.rstrip("/")


def check(backend: str, frontend: str, code: str | None = None, transport=None):
    backend, frontend = origin(backend), origin(frontend)
    # Never forward credentials across redirects. Render cold starts may need a rerun.
    with httpx.Client(timeout=30, follow_redirects=False, transport=transport) as client:
        response = client.get(backend + "/health")
        if response.status_code != 200 or response.json() != {"status": "ok"}:
            raise ValueError("Backend liveness check failed; if cold, wait and rerun.")
        if client.get(frontend).status_code != 200:
            raise ValueError("Frontend is not reachable.")
        if client.post(backend + "/chat", json={}).status_code != 401:
            raise ValueError("Unauthenticated chat was not rejected; do not launch.")
        response = client.options(backend + "/chat/stream", headers={
            "Origin": frontend, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,x-demo-session,content-type",
        })
        if response.status_code != 200 or response.headers.get("access-control-allow-origin") != frontend:
            raise ValueError("Frontend CORS preflight failed.")
        if code:
            headers = {"Authorization": "Bearer " + code, "X-Demo-Session": secrets.token_hex(32)}
            if client.get(backend + "/access", headers=headers).status_code != 200:
                raise ValueError("Invite access check failed.")
            # An invalid body cannot invoke Gemini even when live chat is enabled.
            status = client.post(backend + "/chat", headers=headers, json={}).status_code
            if status not in (422, 503):
                raise ValueError("Authenticated request guard check failed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True)
    parser.add_argument("--frontend", required=True)
    parser.add_argument("--check-access", action="store_true", help="Prompt privately for the invitation code")
    args = parser.parse_args()
    try:
        check(args.backend, args.frontend, getpass("Demo access code: ") if args.check_access else None)
    except (ValueError, httpx.HTTPError):
        raise SystemExit("Deployment checks failed. Check service availability, invite configuration, and CORS. No model question was sent.")
    print("Hosted checks passed. No Gemini calls. Live answer quality and billing status were NOT checked.")
