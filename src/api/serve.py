"""Hosted entry point: run from the repository root with python -m src.api.serve."""

import os

import uvicorn
from src.api.security import auth_mode


def server_port() -> int:
    """Use the hosting platform's port, rejecting invalid settings early."""
    try:
        port = int(os.getenv("PORT", "8000"))
    except ValueError:
        raise ValueError("PORT must be an integer between 1 and 65535.") from None
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535.")
    return port


def main() -> None:
    if auth_mode() == "local":
        raise ValueError("The hosted entry point requires invite access. Use loopback Uvicorn for local development.")
    uvicorn.run(
        "src.api.main:app",
        host="0.0.0.0",
        port=server_port(),
        workers=1,
        reload=False,
        # URLs include conversation IDs; avoid putting them in access logs.
        access_log=False,
    )


if __name__ == "__main__":
    main()
