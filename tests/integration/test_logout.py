from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.api.dependencies import get_settings
from english_for_developers.settings import Settings
from english_for_developers.storage.models import BrowserSession
from tests.integration import test_login as login

logout_client = login.login_client
ORIGIN = {"Origin": "http://testserver"}


@pytest.mark.parametrize("production", [False, True])
def test_logout_revokes_only_presented_auth_after_commit(
    logout_client: TestClient, test_engine: Engine, production: bool
) -> None:
    login._account(logout_client)
    logout_client.cookies.delete("eds_auth_dev")  # Preserve an unpresented active auth.
    headers = login.registration.flow._mutation_headers(logout_client)
    account = login._login(logout_client, headers).json()
    token = logout_client.cookies["eds_auth_dev"]
    cookie_name = "__Host-eds_auth" if production else "eds_auth_dev"
    if production:
        logout_client.cookies.set(cookie_name, token)
        # Keep the test database while selecting production cookie options.
        settings = Settings.from_env()
        logout_client.app.dependency_overrides[get_settings] = lambda: Settings(
            database_url=settings.database_url, environment="production"
        )
    with Session(test_engine) as db:
        before = login.registration._snapshot(db)
    response = logout_client.post(
        "/api/v1/auth/logout",
        headers={**ORIGIN, "X-CSRF-Token": account["csrf_token"]},
        json={},
    )
    assert response.status_code == 204 and response.content == b""
    assert response.headers["cache-control"] == "no-store"
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f'{cookie_name}="";')
    assert all(flag in cookie for flag in ("HttpOnly", "SameSite=lax", "Path=/", "Max-Age=0"))
    assert "expires=" in cookie and "Domain=" not in cookie
    assert ("Secure" in cookie) == production
    with Session(test_engine) as db:
        after = login.registration._snapshot(db)
        assert before[0] == after[0] and before[2] == after[2]
        for old, new in zip(before[1], after[1], strict=True):
            if old.token_hash == hash_session_token(token):
                assert new.revoked_at is not None
                assert {**old._mapping, "revoked_at": new.revoked_at} == new._mapping
            else:
                assert old == new
        assert any(row.kind == "anonymous" and row.revoked_at is None for row in after[1])
        assert any(row.kind == "authenticated" and row.revoked_at is None for row in after[1])


@pytest.mark.parametrize("case", ["repeat", "missing", "unknown", "expired", "revoked", "guest"])
def test_inactive_logout_is_idempotent_without_csrf(
    logout_client: TestClient, test_engine: Engine, case: str
) -> None:
    account = login._account(logout_client)
    if case == "repeat":
        assert (
            logout_client.post(
                "/api/v1/auth/logout",
                headers={**ORIGIN, "X-CSRF-Token": account["csrf_token"]},
                json={},
            ).status_code
            == 204
        )
        assert "eds_auth_dev" not in logout_client.cookies
    elif case == "missing":
        logout_client.cookies.delete("eds_auth_dev")
    elif case in {"unknown", "guest"}:
        token = "unknown" if case == "unknown" else logout_client.cookies["eds_session_dev"]
        logout_client.cookies.clear()
        logout_client.cookies.set("eds_auth_dev", token)
    else:
        with Session(test_engine) as db:
            auth = db.scalar(select(BrowserSession).where(BrowserSession.kind == "authenticated"))
            assert auth is not None
            if case == "expired":
                auth.expires_at = datetime.now(UTC) - timedelta(days=1)
            else:
                auth.revoked_at = datetime.now(UTC)
            db.commit()
    with Session(test_engine) as db:
        before = login.registration._snapshot(db)
    response = logout_client.post("/api/v1/auth/logout", headers=ORIGIN, json={})
    assert response.status_code == 204 and response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert "Max-Age=0" in response.headers["set-cookie"]
    with Session(test_engine) as db:
        assert login.registration._snapshot(db) == before


@pytest.mark.parametrize("case", ["origin", "missing_origin", "missing_csrf", "wrong_csrf"])
def test_logout_security_failure_preserves_sessions_and_cookies(
    logout_client: TestClient, test_engine: Engine, case: str
) -> None:
    account = login._account(logout_client)
    headers = {**ORIGIN, "X-CSRF-Token": account["csrf_token"]}
    if case == "origin":
        headers["Origin"] += "/"
    elif case == "missing_origin":
        del headers["Origin"]
    elif case == "missing_csrf":
        del headers["X-CSRF-Token"]
    else:
        headers["X-CSRF-Token"] = "incorrect"
    with Session(test_engine) as db:
        before = login.registration._snapshot(db)
    response = logout_client.post("/api/v1/auth/logout", headers=headers, json={})
    assert response.status_code == 403
    assert response.json()["code"] == (
        "origin_not_allowed" if "origin" in case else "csrf_not_allowed"
    )
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    with Session(test_engine) as db:
        assert login.registration._snapshot(db) == before
    if "origin" in case:
        logout_client.cookies.clear()
        assert (
            logout_client.post("/api/v1/auth/logout", headers=headers, json={}).status_code == 403
        )


@pytest.mark.parametrize("database_error", [False, True])
def test_logout_commit_failure_rolls_back_without_deleting_cookie(
    logout_client: TestClient, test_engine: Engine, database_error: bool
) -> None:
    account = login._account(logout_client)
    with Session(test_engine) as db:
        before = login.registration._snapshot(db)

    def fail_commit(_db: Session) -> None:
        _db.flush()  # Exercise rollback after PostgreSQL has received the revocation.
        if database_error:
            raise OperationalError("private SQL", {}, RuntimeError("private database details"))
        raise RuntimeError("private failure details")

    event.listen(Session, "before_commit", fail_commit)
    try:
        with TestClient(logout_client.app, raise_server_exceptions=False) as client:
            client.cookies.update(logout_client.cookies)
            response = client.post(
                "/api/v1/auth/logout",
                headers={**ORIGIN, "X-CSRF-Token": account["csrf_token"]},
                json={},
            )
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == (503 if database_error else 500)
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers and "private" not in response.text
    with Session(test_engine) as db:
        assert login.registration._snapshot(db) == before
