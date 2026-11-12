"""Opaque browser session and CSRF token helpers."""

import secrets
from hashlib import sha256
from typing import Literal, TypedDict

from english_for_developers.settings import Settings

TOKEN_BYTES = 32


class SessionCookieOptions(TypedDict):
    key: str
    httponly: bool
    secure: bool
    samesite: Literal["lax", "strict", "none"]
    path: str
    max_age: int


def issue_session_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def issue_csrf_secret() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def require_origin(origin: str | None, expected_origin: str) -> None:
    if origin != expected_origin:
        raise ValueError("origin not allowed")


def require_csrf_token(token: str | None, expected_token: str) -> None:
    if token is None or not secrets.compare_digest(token, expected_token):
        raise ValueError("csrf token not allowed")


def session_cookie_options(settings: Settings) -> SessionCookieOptions:
    return {
        "key": settings.session_cookie_name,
        "httponly": True,
        "secure": settings.environment == "production",
        "samesite": "lax",
        "path": "/",
        "max_age": settings.session_ttl_days * 24 * 60 * 60,
    }
