from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.api.dependencies import get_now, get_settings
from english_for_developers.settings import Settings
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User
from tests.integration import test_login as login

context_client = login.login_client
EMPTY = {
    "anonymous_session_id": None,
    "csrf_token": None,
    "anonymous_run_id": None,
    "account": None,
    "saved_run_ids": [],
}


def _context(client: TestClient) -> dict:
    response = client.get("/api/v1/context")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    return response.json()


def test_context_guest_before_start_and_after_completion(context_client: TestClient) -> None:
    assert _context(context_client) == EMPTY
    headers = login.registration.flow._mutation_headers(context_client)
    guest = _context(context_client)
    assert guest["anonymous_session_id"] and guest["csrf_token"] == headers["X-CSRF-Token"]
    assert guest == {**EMPTY, **{key: guest[key] for key in ("anonymous_session_id", "csrf_token")}}
    active = context_client.post("/api/v1/onboarding", headers=headers, json={}).json()
    assert _context(context_client) == {**guest, "anonymous_run_id": active["id"]}
    for words in (["w1", "w2", "w3"], []):
        active = context_client.post(
            f"/api/v1/onboarding/{active['id']}/answers",
            headers=headers,
            json={
                "step_id": active["step"]["id"],
                "mode": "unknown_words" if words else "all_known",
                "word_ids": words,
                "content_version": active["bundle_version"],
            },
        ).json()
    assert active["status"] == "completed"
    assert _context(context_client) == {**guest, "anonymous_run_id": active["id"]}


@pytest.mark.parametrize("production", [False, True])
def test_context_account_and_guest_are_independent_and_read_only(
    context_client: TestClient, test_engine: Engine, production: bool
) -> None:
    account = login._account(context_client)
    assert _context(context_client) == {
        **EMPTY,
        "account": account,
        "saved_run_ids": [account["current_run_id"]],
    }
    headers, run = login.registration._complete(context_client)
    account = login._login(context_client, headers).json()
    guest_token, auth_token = (
        context_client.cookies[name] for name in ("eds_session_dev", "eds_auth_dev")
    )
    if production:
        context_client.cookies.clear()
        context_client.cookies.set("__Host-eds_session", guest_token)
        context_client.cookies.set("__Host-eds_auth", auth_token)
        settings = Settings.from_env()
        context_client.app.dependency_overrides[get_settings] = lambda: Settings(
            database_url=settings.database_url, environment="production"
        )
    with Session(test_engine) as db:
        before = login.registration._snapshot(db)
        user = db.get(User, UUID(account["user_id"]))
        assert user is not None
        password_hash = user.password_hash
    body = _context(context_client)
    assert body["account"] == account
    assert body["anonymous_run_id"] == run["id"]
    assert body["anonymous_session_id"]
    assert body["csrf_token"] == headers["X-CSRF-Token"] != account["csrf_token"]
    assert body["saved_run_ids"] == [account["current_run_id"]]
    for secret in (guest_token, auth_token, password_hash, login.PASSWORD):
        assert secret not in str(body)
    with Session(test_engine) as db:
        assert login.registration._snapshot(db) == before
    response = context_client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://testserver", "X-CSRF-Token": account["csrf_token"]},
        json={},
    )
    assert response.status_code == 204
    assert _context(context_client) == {**body, "account": None, "saved_run_ids": []}


@pytest.mark.parametrize("cookie", ["eds_session_dev", "eds_auth_dev"])
@pytest.mark.parametrize("state", ["missing", "unknown", "non_ascii", "expired", "revoked", "kind"])
def test_context_invalid_cookie_does_not_hide_other_session(
    context_client: TestClient, test_engine: Engine, cookie: str, state: str
) -> None:
    login._account(context_client)
    login.registration._complete(context_client)
    baseline = _context(context_client)
    now = datetime.now(UTC)
    context_client.app.dependency_overrides[get_now] = lambda: now
    if state in {"expired", "revoked"}:
        with Session(test_engine) as db:
            session = db.scalar(
                select(BrowserSession).where(
                    BrowserSession.token_hash == hash_session_token(context_client.cookies[cookie])
                )
            )
            assert session is not None
            if state == "expired":
                session.expires_at = now
            else:
                session.revoked_at = datetime.now(UTC)
            db.commit()
    else:
        other_cookie = "eds_auth_dev" if cookie == "eds_session_dev" else "eds_session_dev"
        token = {
            "unknown": "unknown",
            "non_ascii": '"\\351"',  # ASCII header decoded by the server's cookie parser.
            "kind": context_client.cookies[other_cookie],
        }
        context_client.cookies.delete(cookie)
        if state != "missing":
            context_client.cookies.set(cookie, token[state])
    expected = (
        {"account": None, "saved_run_ids": []}
        if cookie == "eds_auth_dev"
        else {"anonymous_session_id": None, "csrf_token": None, "anonymous_run_id": None}
    )
    assert _context(context_client) == {**baseline, **expected}


def test_context_saved_runs_are_owned_and_ordered(
    context_client: TestClient, test_engine: Engine
) -> None:
    account = login._account(context_client)
    context_client.cookies.delete("eds_session_dev")
    _, first = login.registration._complete(context_client)
    context_client.cookies.delete("eds_session_dev")
    _, second = login.registration._complete(context_client)
    with TestClient(context_client.app, base_url="http://testserver") as foreign:
        headers, run = login.registration._complete(foreign)
        registered = foreign.post(
            "/api/v1/auth/register",
            headers=headers,
            json={"username": "other_reader", "password": login.PASSWORD, "run_id": run["id"]},
        )
        assert registered.status_code == 201
    with Session(test_engine) as db:
        original = db.get(OnboardingRun, UUID(account["current_run_id"]))
        assert original is not None
        for state in (first, second):
            saved = db.get(OnboardingRun, UUID(state["id"]))
            assert saved is not None
            saved.user_id, saved.claimed_at = UUID(account["user_id"]), datetime.now(UTC)
            saved.created_at = original.created_at - timedelta(days=1)
        db.commit()
    context_client.cookies.delete("eds_session_dev")
    login.registration._complete(context_client)  # Another unclaimed guest run.
    expected = sorted([first["id"], second["id"]]) + [account["current_run_id"]]
    assert _context(context_client)["saved_run_ids"] == expected
    assert _context(context_client)["saved_run_ids"] == expected


def test_context_missing_user_returns_safe_error(
    context_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    login._account(context_client)
    # Simulate a broken FK without disabling real PostgreSQL integrity constraints.
    execute = Session.execute

    def missing_user(db, statement, *args, **kwargs):
        if statement.column_descriptions[0].get("entity") is User:
            statement = statement.where(User.id.is_(None))
        return execute(db, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "execute", missing_user)
    with TestClient(context_client.app, raise_server_exceptions=False) as client:
        client.cookies.update(context_client.cookies)
        response = client.get("/api/v1/context")
    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert set(response.json()) == {"code", "message", "request_id"}
