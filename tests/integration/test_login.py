from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from english_for_developers.accounts import service
from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.storage.models import BrowserSession
from tests.integration import test_registration as registration

login_client = registration.registration_client
PASSWORD = registration.PASSWORD


def _account(client: TestClient) -> dict:
    headers, run = registration._complete(client)
    response = registration._register(client, headers, run)
    assert response.status_code == 201
    return response.json()


def _login(
    client: TestClient,
    headers: dict[str, str],
    username: str = "  READER_one ",
    password: str = PASSWORD,
):
    return client.post(
        "/api/v1/auth/login", headers=headers, json={"username": username, "password": password}
    )


def test_login_recovers_lost_registration_cookie_and_rotates_without_claim(
    login_client: TestClient, test_engine: Engine
) -> None:
    account = _account(login_client)
    lost_token = login_client.cookies["eds_auth_dev"]
    login_client.cookies.clear()  # Registration committed; its HTTP response was lost.
    headers, guest_run = registration._complete(login_client)
    guest_token = login_client.cookies["eds_session_dev"]
    with Session(test_engine) as db:
        before = registration._snapshot(db)
    previous_token = None
    for _ in range(2):
        response = _login(login_client, headers)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert set(body) == set(account)
        assert body["user_id"] == account["user_id"]
        assert body["username"] == "reader_one"
        assert body["current_run_id"] == account["current_run_id"] != guest_run["id"]
        token = login_client.cookies["eds_auth_dev"]
        assert token not in {guest_token, lost_token, previous_token}
        assert PASSWORD not in response.text and token not in response.text
        assert body["csrf_token"] != headers["X-CSRF-Token"]
        cookie = response.headers["set-cookie"]
        assert all(flag in cookie for flag in ("HttpOnly", "SameSite=lax", "Path=/"))
        with Session(test_engine) as db:
            after = registration._snapshot(db)
            assert after[0] == before[0] and after[2] == before[2]
            guest = db.scalar(
                select(BrowserSession).where(
                    BrowserSession.token_hash == hash_session_token(guest_token)
                )
            )
            assert guest is not None
            assert next(row for row in after[1] if row.id == guest.id) == next(
                row for row in before[1] if row.id == guest.id
            )
            auth = db.scalar(
                select(BrowserSession).where(BrowserSession.token_hash == hash_session_token(token))
            )
            assert auth is not None and auth.user_id == UUID(account["user_id"])
            assert auth.kind == "authenticated" and auth.revoked_at is None
            assert auth.csrf_secret == body["csrf_token"]
            assert auth.expires_at == datetime.fromisoformat(
                body["expires_at"].replace("Z", "+00:00")
            )
            assert auth.expires_at - auth.created_at == timedelta(days=7)
            historical = db.scalar(
                select(BrowserSession).where(
                    BrowserSession.token_hash == hash_session_token(lost_token)
                )
            )
            assert historical is not None and historical.revoked_at is None
            if previous_token:
                previous = db.scalar(
                    select(BrowserSession).where(
                        BrowserSession.token_hash == hash_session_token(previous_token)
                    )
                )
                assert previous is not None and previous.revoked_at is not None
        previous_token = token


@pytest.mark.parametrize(
    "case", ["missing_guest", "expired_guest", "revoked_guest", "csrf", "origin"]
)
def test_login_rejects_invalid_browser_without_changes(
    login_client: TestClient, test_engine: Engine, case: str
) -> None:
    _account(login_client)
    headers = registration.flow._mutation_headers(login_client)
    if case == "missing_guest":
        login_client.cookies.delete("eds_session_dev")
    if case in {"expired_guest", "revoked_guest"}:
        with Session(test_engine) as db:
            guest = db.scalar(
                select(BrowserSession).where(
                    BrowserSession.token_hash
                    == hash_session_token(login_client.cookies["eds_session_dev"])
                )
            )
            assert guest is not None
            if case == "expired_guest":
                guest.expires_at = datetime.now(UTC) - timedelta(days=1)
            else:
                guest.revoked_at = datetime.now(UTC)
            db.commit()
    if case == "csrf":
        headers["X-CSRF-Token"] = "incorrect"
    if case == "origin":
        headers["Origin"] = "https://foreign.example"
    with Session(test_engine) as db:
        before = registration._snapshot(db)
    response = _login(login_client, headers)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == {
        "csrf": "csrf_not_allowed",
        "origin": "origin_not_allowed",
    }.get(case, "session_unavailable")
    assert "set-cookie" not in response.headers and PASSWORD not in response.text
    with Session(test_engine) as db:
        assert registration._snapshot(db) == before


def test_missing_user_and_wrong_password_have_identical_safe_errors(
    login_client: TestClient, test_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _account(login_client)
    headers = registration.flow._mutation_headers(login_client)
    with Session(test_engine) as db:
        before = registration._snapshot(db)
    verified_hashes = []
    verify = service.verify_password

    def record_verification(password: str, encoded: str) -> bool:
        verified_hashes.append(encoded)
        return verify(password, encoded)

    monkeypatch.setattr(service, "verify_password", record_verification)
    errors = []
    for username in ("reader_one", "absent_user"):
        response = _login(login_client, headers, username, "incorrect synthetic password")
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers
        assert "incorrect synthetic password" not in response.text
        error = response.json()
        assert set(error) == {"code", "message", "request_id"}
        assert error.pop("request_id") == response.headers["x-request-id"]
        errors.append(error)
    assert (
        errors == [{"code": "invalid_credentials", "message": "Invalid username or password"}] * 2
    )
    assert len(verified_hashes) == 2 and all(h.startswith("$argon2id$") for h in verified_hashes)
    assert verified_hashes[0] != verified_hashes[1]
    with Session(test_engine) as db:
        assert registration._snapshot(db) == before


@pytest.mark.parametrize("change", ["guest", "csrf", "password"])
def test_login_rechecks_state_after_password_verification(
    login_client: TestClient, test_engine: Engine, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    _account(login_client)
    headers = registration.flow._mutation_headers(login_client)
    verify = service.verify_password
    changed_state = []

    def change_after_verification(password: str, encoded: str) -> bool:
        accepted = verify(password, encoded)
        # Independent connection can update these rows while Argon2 runs: no row locks held.
        with Session(test_engine) as db:
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
            if change == "password":
                user = db.scalar(select(registration.User))
                assert user is not None
                user.password_hash = "changed"
            else:
                guest = db.scalar(
                    select(BrowserSession).where(
                        BrowserSession.token_hash
                        == hash_session_token(login_client.cookies["eds_session_dev"])
                    )
                )
                assert guest is not None
                if change == "guest":
                    guest.revoked_at = datetime.now(UTC)
                else:
                    guest.csrf_secret = "changed"
            db.commit()
            changed_state.extend(registration._snapshot(db))
        return accepted

    monkeypatch.setattr(service, "verify_password", change_after_verification)
    response = _login(login_client, headers)
    assert response.status_code == (401 if change == "password" else 403)
    assert "set-cookie" not in response.headers
    with Session(test_engine) as db:
        assert registration._snapshot(db) == changed_state


def test_login_token_collision_rolls_back_revocation(
    login_client: TestClient, test_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    _account(login_client)
    existing_token = login_client.cookies["eds_auth_dev"]
    headers = registration.flow._mutation_headers(login_client)
    with Session(test_engine) as db:
        before = registration._snapshot(db)
    monkeypatch.setattr(service, "issue_session_token", lambda: existing_token)
    response = _login(login_client, headers)
    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert "set-cookie" not in response.headers and "uq_" not in response.text
    with Session(test_engine) as db:
        assert registration._snapshot(db) == before
