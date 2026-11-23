import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from english_for_developers.storage.models import BrowserSession
from tests.integration import test_onboarding_http_flow as flow
from tests.integration import test_registration as registration

onboarding_client = flow.onboarding_client

NONCE_PATH = "/api/v1/auth/telegram/nonce"


@pytest.fixture
def telegram_client(onboarding_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("TELEGRAM_CLIENT_ID", "123456789")
    return onboarding_client


def _guest(db: Session, client: TestClient) -> BrowserSession:
    token_hash = sha256(client.cookies["eds_session_dev"].encode("ascii")).hexdigest()
    guest = db.scalar(select(BrowserSession).where(BrowserSession.token_hash == token_hash))
    assert guest is not None and guest.kind == "anonymous"
    return guest


def _snapshot(engine: Engine) -> list:
    table = BrowserSession.__table__
    with Session(engine) as db:
        return list(db.execute(select(table).order_by(table.c.id)))


def test_issues_nonce_for_guest_session(telegram_client: TestClient, test_engine: Engine) -> None:
    headers = flow._mutation_headers(telegram_client)

    before_request = datetime.now(UTC)
    response = telegram_client.post(NONCE_PATH, headers=headers, json={})
    after_request = datetime.now(UTC)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"nonce", "client_id"}
    assert body["client_id"] == "123456789"
    nonce = body["nonce"]
    assert isinstance(nonce, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", nonce)
    with Session(test_engine) as db:
        guest = _guest(db, telegram_client)
        assert guest.telegram_nonce_hash == sha256(nonce.encode("ascii")).hexdigest()
        expiry = guest.telegram_nonce_expires_at
        assert expiry is not None
        ttl = timedelta(minutes=10)
        assert before_request + ttl <= expiry <= after_request + ttl


def test_second_request_replaces_nonce(telegram_client: TestClient, test_engine: Engine) -> None:
    headers = flow._mutation_headers(telegram_client)
    first = telegram_client.post(NONCE_PATH, headers=headers, json={})
    assert first.status_code == 200

    second = telegram_client.post(NONCE_PATH, headers=headers, json={})

    assert second.status_code == 200
    nonce = second.json()["nonce"]
    assert nonce != first.json()["nonce"]
    with Session(test_engine) as db:
        guest = _guest(db, telegram_client)
        assert guest.telegram_nonce_hash == sha256(nonce.encode("ascii")).hexdigest()


@pytest.mark.parametrize("client_id", [None, "   "], ids=["unset", "blank"])
def test_disabled_telegram_keeps_session_unchanged(
    onboarding_client: TestClient,
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    client_id: str | None,
) -> None:
    if client_id is None:
        monkeypatch.delenv("TELEGRAM_CLIENT_ID", raising=False)
    else:
        monkeypatch.setenv("TELEGRAM_CLIENT_ID", client_id)
    headers = flow._mutation_headers(onboarding_client)
    before = _snapshot(test_engine)

    response = onboarding_client.post(NONCE_PATH, headers=headers, json={})

    assert response.status_code == 404
    assert response.json().get("code") == "telegram_disabled", response.text
    assert response.headers["cache-control"] == "no-store"
    assert _snapshot(test_engine) == before
    with Session(test_engine) as db:
        guest = _guest(db, onboarding_client)
        assert guest.telegram_nonce_hash is None
        assert guest.telegram_nonce_expires_at is None


@pytest.mark.parametrize(
    "header,value,code",
    [
        ("Origin", "https://foreign.example", "origin_not_allowed"),
        ("Origin", None, "origin_not_allowed"),
        ("X-CSRF-Token", "wrong", "csrf_not_allowed"),
        ("X-CSRF-Token", None, "csrf_not_allowed"),
    ],
    ids=["wrong-origin", "missing-origin", "wrong-csrf", "missing-csrf"],
)
def test_rejects_invalid_headers_without_storing_nonce(
    telegram_client: TestClient,
    test_engine: Engine,
    header: str,
    value: str | None,
    code: str,
) -> None:
    headers = flow._mutation_headers(telegram_client)
    if value is None:
        del headers[header]
    else:
        headers[header] = value
    before = _snapshot(test_engine)

    response = telegram_client.post(NONCE_PATH, headers=headers, json={})

    assert response.status_code == 403
    assert response.json()["code"] == code
    assert _snapshot(test_engine) == before


def test_requires_guest_cookie(telegram_client: TestClient, test_engine: Engine) -> None:
    headers = flow._mutation_headers(telegram_client)
    telegram_client.cookies.clear()
    before = _snapshot(test_engine)

    response = telegram_client.post(NONCE_PATH, headers=headers, json={})

    assert response.status_code == 403
    assert response.json()["code"] == "session_unavailable"
    assert _snapshot(test_engine) == before


@pytest.mark.parametrize("guest_state", ["expired", "revoked"])
def test_rejects_inactive_guest_without_storing_nonce(
    telegram_client: TestClient, test_engine: Engine, guest_state: str
) -> None:
    headers = flow._mutation_headers(telegram_client)
    with Session(test_engine) as db:
        guest = _guest(db, telegram_client)
        if guest_state == "expired":
            guest.expires_at = datetime.now(UTC) - timedelta(days=1)
        else:
            guest.revoked_at = datetime.now(UTC)
        db.commit()
    before = _snapshot(test_engine)

    response = telegram_client.post(NONCE_PATH, headers=headers, json={})

    assert response.status_code == 403
    assert response.json()["code"] == "session_unavailable"
    assert _snapshot(test_engine) == before


def test_rejects_authenticated_browser_without_storing_nonce(
    telegram_client: TestClient, test_engine: Engine
) -> None:
    headers, run = registration._complete(telegram_client)
    registered = registration._register(telegram_client, headers, run)
    assert registered.status_code == 201
    telegram_client.cookies.pop("eds_session_dev", None)
    assert set(telegram_client.cookies) == {"eds_auth_dev"}
    headers["X-CSRF-Token"] = registered.json()["csrf_token"]
    before = _snapshot(test_engine)

    response = telegram_client.post(NONCE_PATH, headers=headers, json={})

    assert response.status_code == 403
    assert response.json()["code"] == "session_unavailable"
    assert _snapshot(test_engine) == before
    sessions_with_nonce = select(BrowserSession.id).where(
        BrowserSession.telegram_nonce_hash.is_not(None)
        | BrowserSession.telegram_nonce_expires_at.is_not(None)
    )
    with Session(test_engine) as db:
        assert db.scalar(sessions_with_nonce) is None


def test_rejects_extra_body_fields(telegram_client: TestClient) -> None:
    headers = flow._mutation_headers(telegram_client)

    response = telegram_client.post(NONCE_PATH, headers=headers, json={"x": 1})

    assert response.status_code == 422
