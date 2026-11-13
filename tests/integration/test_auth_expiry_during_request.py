"""Advance time at real Argon2/SQL boundaries without changing stored deadlines."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session

from english_for_developers.accounts import service as accounts
from english_for_developers.api import dependencies
from english_for_developers.onboarding import service as onboarding
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User
from tests.integration import test_account_onboarding_access as access
from tests.integration import test_login as login

expiry_client = login.login_client


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch):
    class Clock(datetime):
        value = datetime.now(UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.value

    for module in (dependencies, accounts, onboarding):
        monkeypatch.setattr(module, "datetime", Clock)
    return Clock


@pytest.fixture
def advance_after_lock(clock):
    listeners = []

    def install(table: str, instant: datetime) -> None:
        def after_lock(connection, cursor, statement, parameters, context, executemany):
            if "FOR UPDATE" in statement and f"FROM {table}" in statement:
                clock.value = instant

        event.listen(Engine, "after_cursor_execute", after_lock)
        listeners.append(after_lock)

    yield install
    for listener in listeners:
        event.remove(Engine, "after_cursor_execute", listener)


def _prepare(client, operation):
    if operation == "register":
        headers, run = login.registration._complete(client)
        return headers, run
    account = login._account(client)
    if operation == "login":
        return login.registration.flow._mutation_headers(client), account
    return {"Origin": "http://testserver", "X-CSRF-Token": account["csrf_token"]}, account


def _request(client, operation, headers, state):
    if operation == "register":
        return login.registration._register(client, headers, state)
    if operation == "login":
        return login._login(client, headers)
    if operation == "selection":
        return access._selection(client, state["current_run_id"], state["csrf_token"], 3)
    return client.post("/api/v1/auth/logout", headers=headers, json={})


@pytest.mark.parametrize(
    "operation,boundary",
    [
        ("register", "argon2"),
        ("register", "browser_sessions"),
        ("register", "onboarding_runs"),
        ("login", "argon2"),
        ("login", "browser_sessions"),
        ("login", "users"),
        ("selection", "browser_sessions"),
        ("selection", "onboarding_runs"),
        ("logout", "browser_sessions"),
    ],
)
def test_expiry_during_request_prevents_mutation(
    expiry_client: TestClient,
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    clock,
    advance_after_lock,
    operation: str,
    boundary: str,
) -> None:
    headers, state = _prepare(expiry_client, operation)
    with Session(test_engine) as db:
        before = login.registration._snapshot(db)
        kind = "anonymous" if operation in {"register", "login"} else "authenticated"
        session = db.scalars(
            select(BrowserSession).where(
                BrowserSession.kind == kind, BrowserSession.revoked_at.is_(None)
            )
        ).one()
        deadline = session.expires_at
    clock.value = deadline - timedelta(seconds=1)
    if boundary == "argon2":
        name = "hash_password" if operation == "register" else "verify_password"
        original = getattr(accounts, name)

        def advance_after_argon2(*args):
            result = original(*args)
            clock.value = deadline
            return result

        monkeypatch.setattr(accounts, name, advance_after_argon2)
    else:
        advance_after_lock(boundary, deadline)
    response = _request(expiry_client, operation, headers, state)
    if operation == "logout":
        assert response.status_code == 204
        assert "Max-Age=0" in response.headers["set-cookie"]
    else:
        assert response.status_code == 403
        assert response.json()["code"] == "session_unavailable"
        assert "set-cookie" not in response.headers
    with Session(test_engine) as db:
        assert login.registration._snapshot(db) == before


@pytest.mark.parametrize(
    "operation,boundary",
    [("register", "onboarding_runs"), ("login", "users"), ("logout", "browser_sessions")],
)
def test_mutation_timestamps_use_time_after_final_lock(
    expiry_client: TestClient,
    test_engine: Engine,
    clock,
    advance_after_lock,
    operation: str,
    boundary: str,
) -> None:
    headers, state = _prepare(expiry_client, operation)
    after_wait = clock.value + timedelta(seconds=5)
    advance_after_lock(boundary, after_wait)
    response = _request(expiry_client, operation, headers, state)
    assert response.status_code == {"register": 201, "login": 200, "logout": 204}[operation]
    with Session(test_engine) as db:
        sessions = db.scalars(select(BrowserSession)).all()
        if operation == "logout":
            auth = next(s for s in sessions if s.kind == "authenticated")
            assert auth.revoked_at == after_wait
        else:
            auth = next(s for s in sessions if s.kind == "authenticated" and not s.revoked_at)
            assert auth.created_at == after_wait
            assert auth.expires_at == after_wait + timedelta(days=7)
            if operation == "register":
                run = db.scalars(select(OnboardingRun)).one()
                user = db.scalars(select(User)).one()
                assert run.claimed_at == user.created_at == after_wait
                assert next(s for s in sessions if s.kind == "anonymous").revoked_at == after_wait
            else:
                assert (
                    next(
                        s for s in sessions if s.kind == "authenticated" and s.revoked_at
                    ).revoked_at
                    == after_wait
                )
