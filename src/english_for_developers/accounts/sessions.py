"""Opaque browser session and CSRF token helpers."""

import secrets
from hashlib import sha256

from english_for_developers.settings import Settings

TOKEN_BYTES = 32


def issue_session_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def issue_csrf_secret() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def require_origin(origin: str | None, expected_origin: str) -> None:
    if origin != expected_origin:
        raise ValueError("origin not allowed")


def session_cookie_options(settings: Settings) -> dict[str, object]:
    return {
        "key": settings.session_cookie_name,
        "httponly": True,
        "secure": settings.environment == "production",
        "samesite": "lax",
        "path": "/",
        "max_age": settings.session_ttl_days * 24 * 60 * 60,
    }
