import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.accounts.telegram import TELEGRAM_ISSUER, TelegramTokenVerifier
from english_for_developers.storage.models import AuthIdentity, BrowserSession, OnboardingRun, User
from tests.integration import test_registration as registration

registration_client = registration.registration_client

SIGNIN_PATH = "/api/v1/auth/telegram"
NONCE_PATH = f"{SIGNIN_PATH}/nonce"
CLIENT_ID = "123456789"
SUBJECT = "synthetic-telegram-subject"
GUEST_COOKIE = "eds_session_dev"
AUTH_COOKIE = "eds_auth_dev"


@pytest.fixture(scope="module")
def private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def telegram_client(
    registration_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    private_key: rsa.RSAPrivateKey,
    request: pytest.FixtureRequest,
) -> TestClient:
    from english_for_developers.api import dependencies

    def unavailable(token: str) -> rsa.RSAPublicKey:
        raise jwt.PyJWKClientConnectionError("Synthetic JWKS outage")

    monkeypatch.setenv("TELEGRAM_CLIENT_ID", CLIENT_ID)
    public_key = private_key.public_key()
    if getattr(request, "param", None) == "unavailable":
        verifier = TelegramTokenVerifier(CLIENT_ID, key_resolver=unavailable)
    else:
        verifier = TelegramTokenVerifier(CLIENT_ID, key_resolver=lambda token: public_key)
    monkeypatch.setitem(
        registration_client.app.dependency_overrides,
        dependencies.get_telegram_verifier,
        lambda: verifier,
    )
    return registration_client


def _add_identity(db: Session, user_id: UUID) -> None:
    db.add(
        AuthIdentity(
            id=uuid4(),
            user_id=user_id,
            provider="telegram",
            subject=SUBJECT,
            created_at=datetime.now(UTC),
        )
    )


@pytest.fixture
def known_user_id(test_engine: Engine) -> UUID:
    user_id = uuid4()
    with Session(test_engine) as db:
        db.add(
            User(
                id=user_id,
                username=None,
                password_hash=None,
                current_run_id=None,
                created_at=datetime.now(UTC),
            )
        )
        db.flush()
        _add_identity(db, user_id)
        db.commit()
    return user_id


def _issue_nonce(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(NONCE_PATH, headers=headers, json={})
    assert response.status_code == 200
    return response.json()["nonce"]


def _sign_token(private_key: rsa.RSAPrivateKey, nonce: str, **claims: object) -> str:
    now = datetime.now(UTC)
    payload = {
        "iss": TELEGRAM_ISSUER,
        "aud": CLIENT_ID,
        "sub": SUBJECT,
        "iat": int((now - timedelta(minutes=2)).timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "nonce": nonce,
    }
    return jwt.encode(payload | claims, private_key, algorithm="RS256")


def _session(db: Session, token: str) -> BrowserSession:
    browser_session = db.scalar(
        select(BrowserSession).where(BrowserSession.token_hash == hash_session_token(token))
    )
    assert browser_session is not None
    return browser_session


def _snapshot(engine: Engine) -> list:
    with Session(engine) as db:
        identities = list(
            db.execute(select(*AuthIdentity.__table__.columns).order_by(AuthIdentity.id))
        )
        return [*registration._snapshot(db), identities]


def test_signs_in_known_identity_and_consumes_nonce(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    known_user_id: UUID,
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)
    nonce = _issue_nonce(telegram_client, headers)
    guest_token = telegram_client.cookies[GUEST_COOKIE]

    response = telegram_client.post(
        SIGNIN_PATH, headers=headers, json={"id_token": _sign_token(private_key, nonce)}
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"user_id", "username", "csrf_token", "current_run_id", "expires_at"}
    assert body["user_id"] == str(known_user_id)
    assert body["username"] is None
    assert body["current_run_id"] is None
    auth_token = response.cookies[AUTH_COOKIE]
    assert auth_token != guest_token
    cookie = response.headers["set-cookie"]
    assert all(flag in cookie for flag in ("HttpOnly", "SameSite=lax", "Path=/"))
    assert telegram_client.cookies[GUEST_COOKIE] == guest_token
    with Session(test_engine) as db:
        auth = _session(db, auth_token)
        assert auth.kind == "authenticated" and auth.user_id == known_user_id
        assert auth.revoked_at is None and auth.expires_at > datetime.now(UTC)
        assert auth.csrf_secret == body["csrf_token"] != headers["X-CSRF-Token"]
        assert auth.expires_at == datetime.fromisoformat(body["expires_at"])
        guest = _session(db, guest_token)
        assert guest.kind == "anonymous" and guest.revoked_at is None
        assert guest.expires_at > datetime.now(UTC)
        assert guest.telegram_nonce_hash is None and guest.telegram_nonce_expires_at is None


def test_rejects_replayed_token_without_changes(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    known_user_id: UUID,
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)
    nonce = _issue_nonce(telegram_client, headers)
    body = {"id_token": _sign_token(private_key, nonce)}
    first = telegram_client.post(SIGNIN_PATH, headers=headers, json=body)
    assert first.status_code == 200
    before = _snapshot(test_engine)

    response = telegram_client.post(SIGNIN_PATH, headers=headers, json=body)

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_telegram_token"
    assert _snapshot(test_engine) == before


def test_revokes_this_browsers_previous_auth_session(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    known_user_id: UUID,
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)
    first_nonce = _issue_nonce(telegram_client, headers)
    first = telegram_client.post(
        SIGNIN_PATH, headers=headers, json={"id_token": _sign_token(private_key, first_nonce)}
    )
    assert first.status_code == 200
    previous_token = telegram_client.cookies[AUTH_COOKIE]
    with Session(test_engine) as db:
        previous = _session(db, previous_token)
        assert previous.user_id == known_user_id and previous.revoked_at is None
    nonce = _issue_nonce(telegram_client, headers)

    response = telegram_client.post(
        SIGNIN_PATH, headers=headers, json={"id_token": _sign_token(private_key, nonce)}
    )

    assert response.status_code == 200
    new_token = response.cookies[AUTH_COOKIE]
    assert new_token != previous_token
    with Session(test_engine) as db:
        assert _session(db, previous_token).revoked_at is not None
        new_auth = _session(db, new_token)
        assert new_auth.user_id == known_user_id and new_auth.kind == "authenticated"
        assert new_auth.revoked_at is None and new_auth.expires_at > datetime.now(UTC)


def test_returns_saved_run_without_claiming_completed_guest_run(
    telegram_client: TestClient, test_engine: Engine, private_key: rsa.RSAPrivateKey
) -> None:
    headers, saved_run = registration._complete(telegram_client)
    registered = registration._register(telegram_client, headers, saved_run)
    assert registered.status_code == 201
    account = registered.json()
    with Session(test_engine) as db:
        _add_identity(db, UUID(account["user_id"]))
        db.commit()
    telegram_client.cookies.clear()
    headers, guest_run = registration._complete(telegram_client)
    nonce = _issue_nonce(telegram_client, headers)

    response = telegram_client.post(
        SIGNIN_PATH,
        headers=headers,
        json={"id_token": _sign_token(private_key, nonce), "run_id": guest_run["id"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == account["user_id"]
    assert body["username"] == account["username"] == "reader_one"
    assert body["current_run_id"] == saved_run["id"] != guest_run["id"]
    with Session(test_engine) as db:
        run = db.get(OnboardingRun, UUID(guest_run["id"]))
        assert run is not None and run.user_id is None and run.claimed_at is None


@pytest.mark.parametrize("case", ["mismatched", "expired", "missing"])
def test_rejects_invalid_nonce_without_changes(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    known_user_id: UUID,
    case: str,
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)
    nonce = "unissued-test-nonce"
    if case != "missing":
        issued_nonce = _issue_nonce(telegram_client, headers)
        nonce = f"{issued_nonce}-different" if case == "mismatched" else issued_nonce
    if case == "expired":
        with Session(test_engine) as db:
            guest = _session(db, telegram_client.cookies[GUEST_COOKIE])
            guest.telegram_nonce_expires_at = datetime.now(UTC) - timedelta(minutes=1)
            db.commit()
    before = _snapshot(test_engine)

    response = telegram_client.post(
        SIGNIN_PATH, headers=headers, json={"id_token": _sign_token(private_key, nonce)}
    )

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_telegram_token"
    assert _snapshot(test_engine) == before


@pytest.mark.parametrize("case", ["wrong-signature", "wrong-audience", "expired-token"])
def test_rejects_invalid_token_without_consuming_nonce(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    known_user_id: UUID,
    case: str,
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)
    nonce = _issue_nonce(telegram_client, headers)
    if case == "wrong-signature":
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _sign_token(other_key, nonce)
    elif case == "wrong-audience":
        token = _sign_token(private_key, nonce, aud="987654321")
    else:
        expired = datetime.now(UTC) - timedelta(minutes=1)
        token = _sign_token(private_key, nonce, exp=int(expired.timestamp()))
    before = _snapshot(test_engine)

    response = telegram_client.post(SIGNIN_PATH, headers=headers, json={"id_token": token})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_telegram_token"
    assert _snapshot(test_engine) == before


@pytest.mark.parametrize("telegram_client", ["unavailable"], indirect=True)
def test_returns_service_unavailable_when_jwks_cannot_be_fetched(
    telegram_client: TestClient, private_key: rsa.RSAPrivateKey, known_user_id: UUID
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)
    nonce = _issue_nonce(telegram_client, headers)

    response = telegram_client.post(
        SIGNIN_PATH, headers=headers, json={"id_token": _sign_token(private_key, nonce)}
    )

    assert response.status_code == 503
    assert response.json()["code"] == "telegram_unavailable"
    assert response.headers["cache-control"] == "no-store"


def test_telegram_signin_is_disabled_without_client_id(
    registration_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_CLIENT_ID", raising=False)
    headers = registration.flow._mutation_headers(registration_client)

    response = registration_client.post(
        SIGNIN_PATH, headers=headers, json={"id_token": "synthetic-token"}
    )

    assert response.status_code == 404
    assert response.json().get("code") == "telegram_disabled", response.text


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("wrong-origin", "origin_not_allowed"),
        ("wrong-csrf", "csrf_not_allowed"),
        ("missing-guest", "session_unavailable"),
        ("revoked-guest", "session_unavailable"),
    ],
)
def test_rejects_invalid_browser_without_changes(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    known_user_id: UUID,
    case: str,
    code: str,
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)
    nonce = _issue_nonce(telegram_client, headers)
    if case == "wrong-origin":
        headers["Origin"] = "https://foreign.example"
    elif case == "wrong-csrf":
        headers["X-CSRF-Token"] = "wrong-test-csrf"
    elif case == "missing-guest":
        telegram_client.cookies.delete(GUEST_COOKIE)
    else:
        with Session(test_engine) as db:
            guest = _session(db, telegram_client.cookies[GUEST_COOKIE])
            guest.revoked_at = datetime.now(UTC)
            db.commit()
    before = _snapshot(test_engine)

    response = telegram_client.post(
        SIGNIN_PATH, headers=headers, json={"id_token": _sign_token(private_key, nonce)}
    )

    assert response.status_code == 403
    assert response.json()["code"] == code
    assert _snapshot(test_engine) == before


@pytest.mark.parametrize("with_run", [False, True], ids=["without-run", "with-completed-run"])
def test_rejects_unknown_identity_without_consuming_nonce(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    with_run: bool,
) -> None:
    if with_run:
        headers, completed = registration._complete(telegram_client)
        body = {"run_id": completed["id"]}
    else:
        headers = registration.flow._mutation_headers(telegram_client)
        body = {}
    nonce = _issue_nonce(telegram_client, headers)
    body["id_token"] = _sign_token(private_key, nonce)
    before = _snapshot(test_engine)

    response = telegram_client.post(SIGNIN_PATH, headers=headers, json=body)

    assert response.status_code == 409
    assert response.json()["code"] == "registration_conflict"
    assert _snapshot(test_engine) == before


@pytest.mark.parametrize(
    "body",
    [
        {"id_token": "synthetic-extra-field-token", "extra": True},
        {"id_token": ""},
        {"id_token": "t" * 8193},
        {"id_token": "synthetic-invalid-run-token", "run_id": "x"},
    ],
    ids=["extra-field", "empty-token", "oversized-token", "invalid-run"],
)
def test_rejects_invalid_body_without_echoing_token(
    telegram_client: TestClient, body: dict[str, str | bool]
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)

    response = telegram_client.post(SIGNIN_PATH, headers=headers, json=body)

    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["fields"])
    token = body["id_token"]
    assert isinstance(token, str)
    if token:
        assert token not in response.text


def test_successful_signin_logs_no_token_nonce_or_subject(
    telegram_client: TestClient,
    private_key: rsa.RSAPrivateKey,
    known_user_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers = registration.flow._mutation_headers(telegram_client)
    nonce = _issue_nonce(telegram_client, headers)
    token = _sign_token(private_key, nonce)
    logger_name = "english_for_developers.request"
    caplog.clear()
    caplog.set_level(logging.INFO, logger=logger_name)

    response = telegram_client.post(SIGNIN_PATH, headers=headers, json={"id_token": token})

    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records if record.name == logger_name]
    assert any(f"route={SIGNIN_PATH} status=200" in message for message in messages)
    for secret in (token, nonce, SUBJECT):
        assert all(secret not in message for message in messages)
