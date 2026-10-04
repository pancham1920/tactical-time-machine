"""Environment settings for the HTTP boundary, separate from model settings."""

import os
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()


def allowed_origins() -> list[str]:
    """Read exact browser origins; an explicit setting replaces local defaults."""
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    origins = []
    for value in raw.split(","):
        origin = value.strip()
        try:
            parsed = urlsplit(origin)
            valid = (
                parsed.scheme in ("http", "https")
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.path
                and not parsed.query
                and not parsed.fragment
                and not any(char.isspace() for char in origin)
                and not any(char in origin for char in ("*", "\\", "?", "#"))
                and parsed.port != 0
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must contain comma-separated HTTP(S) origins "
                "without paths, trailing slashes, credentials, or wildcards."
            )
        if origin not in origins:
            origins.append(origin)
    return origins
