from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from english_for_developers.accounts.passwords import verify_password
from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.api.dependencies import get_settings
from english_for_developers.settings import Settings
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User
from tests.integration import test_onboarding_http_flow as flow

registration_client = flow.onboarding_client

PASSWORD = "synthetic password for tests"


def _complete(client: TestClient) -> tuple[dict[str, str], dict]:
    headers = flow._mutation_headers(client)
    run = client.post("/api/v1/onboarding", headers=headers, json={}).json()
    for mode, words in [("unknown_words", ["w1", "w2", "w3"]), ("all_known", [])]:
        result = client.post(
            f"/api/v1/onboarding/{run['id']}/answers",
            headers=headers,
            json={
                "step_id": run["step"]["id"],
                "mode": mode,
                "word_ids": words,
                "content_version": run["bundle_version"],
            },
        )
        assert result.status_code == 200
        run = result.json()
    assert run["status"] == "completed"
    return headers, run


def _register(client: TestClient, headers: dict[str, str], run: dict):
    return client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={"username": "  Reader_ONE  ", "password": PASSWORD, "run_id": run["id"]},
    )


def test_registration_commits_account_session_and_result(
    registration_client: TestClient,
    test_engine: Engine,
) -> None:
    headers, state = _complete(registration_client)
    anonymous = registration_client.cookies["eds_session_dev"]
    response = _register(registration_client, headers, state)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"user_id", "username", "csrf_token", "current_run_id", "expires_at"}
    assert body["username"] == "reader_one"
    assert body["current_run_id"] == state["id"]
    assert PASSWORD not in response.text
    token = registration_client.cookies["eds_auth_dev"]
    assert token != anonymous
    assert token not in response.text
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert "Max-Age=604800" in cookie and "Secure" not in cookie
    with Session(test_engine) as db:
        user = db.get(User, UUID(body["user_id"]))
        assert user is not None and user.username == "reader_one"
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(PASSWORD, user.password_hash)
        assert user.password_hash not in response.text
        run = db.get(OnboardingRun, UUID(state["id"]))
        assert run is not None and run.user_id == user.id and run.claimed_at is not None
        assert run.revision == state["revision"] + 1 and user.current_run_id == run.id
        assert run.expires_at == datetime.fromisoformat(state["expires_at"].replace("Z", "+00:00"))
        guest = db.scalar(
            select(BrowserSession).where(BrowserSession.token_hash == hash_session_token(anonymous))
        )
        auth = db.scalar(
            select(BrowserSession).where(BrowserSession.token_hash == hash_session_token(token))
        )
        assert guest is not None and guest.kind == "anonymous" and guest.revoked_at is not None
        assert auth is not None and auth.kind == "authenticated" and auth.user_id == user.id
        assert auth.csrf_secret == body["csrf_token"] != headers["X-CSRF-Token"]
        assert auth.expires_at == datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        assert (auth.expires_at - auth.created_at).days == 7


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("csrf", 403, "csrf_not_allowed"),
        ("origin", 403, "origin_not_allowed"),
        ("missing_guest", 403, "session_unavailable"),
        ("expired_guest", 403, "session_unavailable"),
        ("revoked_guest", 403, "session_unavailable"),
        ("foreign", 404, "onboarding_not_found"),
        ("owned", 404, "onboarding_not_found"),
        ("unknown", 404, "onboarding_not_found"),
        ("active", 409, "registration_conflict"),
        ("expired", 410, "run_expired"),
        ("duplicate", 409, "username_unavailable"),
    ],
)
def test_rejected_registration_leaves_no_partial_state(
    registration_client: TestClient,
    test_engine: Engine,
    case: str,
    status: int,
    code: str,
) -> None:
    headers, state = _complete(registration_client)
    with Session(test_engine) as db:
        run = db.get(OnboardingRun, UUID(state["id"]))
        guest = db.scalar(select(BrowserSession))
        assert run is not None and guest is not None
        if case == "foreign":
            other = BrowserSession(
                id=uuid4(),
                kind="anonymous",
                token_hash="0" * 64,
                csrf_secret="other",
                created_at=guest.created_at,
                expires_at=guest.expires_at,
            )
            db.add(other)
            db.flush()
            run.anonymous_session_id = other.id
        if case == "active":
            run.status, run.completed_at = "active", None
            run.recommended_level = run.selected_level = run.reason_code = None
        if case == "expired":
            run.expires_at = datetime.now(UTC) - timedelta(days=1)
        if case == "expired_guest":
            guest.expires_at = datetime.now(UTC) - timedelta(days=1)
        if case == "revoked_guest":
            guest.revoked_at = datetime.now(UTC)
        if case in {"duplicate", "owned"}:
            owner = User(
                id=uuid4(),
                username="reader_one" if case == "duplicate" else "owner",
                password_hash="unused",
                created_at=datetime.now(UTC),
            )
            db.add(owner)
            db.flush()
            if case == "owned":
                run.user_id, run.claimed_at = owner.id, datetime.now(UTC)
        db.commit()
    if case == "csrf":
        headers["X-CSRF-Token"] = "wrong"
    if case == "origin":
        headers["Origin"] = "https://foreign.example"
    if case == "missing_guest":
        registration_client.cookies.clear()
    if case == "unknown":
        state["id"] = str(uuid4())
    with Session(test_engine) as db:
        before = _snapshot(db)
    response = _register(registration_client, headers, state)
    assert response.status_code == status and response.json()["code"] == code
    assert "set-cookie" not in response.headers and PASSWORD not in response.text
    assert response.headers["cache-control"] == "no-store"
    with Session(test_engine) as db:
        assert _snapshot(db) == before


def _snapshot(db: Session) -> list:
    return [
        list(db.execute(select(*model.__table__.columns).order_by(model.id)))
        for model in (User, BrowserSession, OnboardingRun)
    ]


@pytest.mark.parametrize("auth_state", ["active", "expired", "revoked"])
def test_existing_auth_cookie_is_rechecked(
    registration_client: TestClient,
    test_engine: Engine,
    auth_state: str,
) -> None:
    headers, state = _complete(registration_client)
    assert _register(registration_client, headers, state).status_code == 201
    with Session(test_engine) as db:
        auth = db.scalar(select(BrowserSession).where(BrowserSession.kind == "authenticated"))
        assert auth is not None
        if auth_state == "expired":
            auth.expires_at = datetime.now(UTC) - timedelta(days=1)
        if auth_state == "revoked":
            auth.revoked_at = datetime.now(UTC)
        db.commit()
    headers, state = _complete(registration_client)
    with Session(test_engine) as db:
        before = _snapshot(db)
    response = registration_client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={"username": "second_reader", "password": PASSWORD, "run_id": state["id"]},
    )
    assert response.status_code == (409 if auth_state == "active" else 201)
    if auth_state == "active":
        assert response.json()["code"] == "already_authenticated"
        assert "set-cookie" not in response.headers
        with Session(test_engine) as db:
            assert _snapshot(db) == before


def test_registration_uses_separate_secure_production_cookie(
    registration_client: TestClient,
) -> None:
    headers, state = _complete(registration_client)
    guest = registration_client.cookies["eds_session_dev"]
    registration_client.cookies.clear()
    registration_client.cookies.set("__Host-eds_session", guest)
    settings = Settings.from_env()
    registration_client.app.dependency_overrides[get_settings] = lambda: Settings(
        database_url=settings.database_url,
        environment="production",
    )
    response = _register(registration_client, headers, state)
    assert response.status_code == 201
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("__Host-eds_auth=")
    assert all(
        flag in cookie
        for flag in ("Secure", "HttpOnly", "Path=/", "SameSite=lax", "Max-Age=604800")
    )
    assert "Domain=" not in cookie


def test_registration_repeat_with_active_auth_and_revoked_guest_is_conflict(
    registration_client: TestClient,
    test_engine: Engine,
) -> None:
    headers, state = _complete(registration_client)
    assert _register(registration_client, headers, state).status_code == 201
    cookies = dict(registration_client.cookies)
    with Session(test_engine) as db:
        before = _snapshot(db)
    repeated = _register(registration_client, headers, state)
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "already_authenticated"
    assert "set-cookie" not in repeated.headers
    assert dict(registration_client.cookies) == cookies
    with Session(test_engine) as db:
        assert _snapshot(db) == before
