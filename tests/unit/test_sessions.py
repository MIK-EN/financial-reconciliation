from datetime import timedelta

import pytest

from english_for_developers.accounts.sessions import (
    hash_session_token,
    issue_csrf_secret,
    issue_session_token,
    require_origin,
    session_cookie_options,
)
from english_for_developers.settings import Settings


def test_session_tokens_are_opaque_and_hashable() -> None:
    token = issue_session_token()

    assert len(token) >= 40
    assert hash_session_token(token) == hash_session_token(token)
    assert hash_session_token(token) != hash_session_token(issue_session_token())
    assert len(issue_csrf_secret()) >= 40


def test_origin_must_match_exactly() -> None:
    require_origin("https://example.test", "https://example.test")

    with pytest.raises(ValueError, match="origin not allowed"):
        require_origin(None, "https://example.test")
    with pytest.raises(ValueError, match="origin not allowed"):
        require_origin("https://evil.test", "https://example.test")


def test_production_cookie_has_host_prefix_and_secure_flags() -> None:
    options = session_cookie_options(Settings(environment="production"))

    assert options["key"] == "__Host-eds_session"
    assert options["secure"] is True
    assert options["httponly"] is True
    assert options["samesite"] == "lax"
    assert options["path"] == "/"
    assert options["max_age"] == int(timedelta(days=7).total_seconds())
