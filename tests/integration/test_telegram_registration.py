from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from queue import Queue
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.api.dependencies import get_db
from english_for_developers.storage.models import AuthIdentity, BrowserSession, OnboardingRun, User
from tests.integration import test_registration as registration
from tests.integration import test_telegram_signin as signin

private_key = signin.private_key
registration_client = signin.registration_client
telegram_client = signin.telegram_client


def test_first_signin_claims_run_and_recovers_through_login(
    telegram_client: TestClient, test_engine: Engine, private_key: rsa.RSAPrivateKey
) -> None:
    headers, state = registration._complete(telegram_client)
    guest_token = telegram_client.cookies[signin.GUEST_COOKIE]
    nonce = signin._issue_nonce(telegram_client, headers)
    token = signin._sign_token(private_key, nonce)
    before = signin._snapshot(test_engine)

    missing_run = telegram_client.post(
        signin.SIGNIN_PATH, headers=headers, json={"id_token": token}
    )

    assert missing_run.status_code == 409
    assert missing_run.json()["code"] == "registration_conflict"
    assert signin._snapshot(test_engine) == before
    with Session(test_engine) as db:
        guest = signin._session(db, guest_token)
        assert guest.telegram_nonce_hash == hash_session_token(nonce)
        assert guest.telegram_nonce_expires_at is not None

    request_body = {"id_token": token, "run_id": state["id"]}
    created = telegram_client.post(signin.SIGNIN_PATH, headers=headers, json=request_body)

    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    body = created.json()
    assert body["username"] is None
    assert body["current_run_id"] == state["id"]
    auth_token = created.cookies[signin.AUTH_COOKIE]
    assert telegram_client.cookies[signin.AUTH_COOKIE] == auth_token != guest_token
    with Session(test_engine) as db:
        user = db.scalars(select(User)).one()
        assert str(user.id) == body["user_id"]
        assert user.username is None and user.password_hash is None
        identity = db.scalars(select(AuthIdentity)).one()
        assert (identity.provider, identity.subject, identity.user_id) == (
            "telegram",
            signin.SUBJECT,
            user.id,
        )
        run = db.get(OnboardingRun, UUID(state["id"]))
        assert run is not None and run.user_id == user.id and run.claimed_at is not None
        assert run.revision == state["revision"] + 1 and user.current_run_id == run.id
        guest = signin._session(db, guest_token)
        assert guest.id == run.anonymous_session_id and guest.revoked_at is not None
        assert guest.telegram_nonce_hash is None and guest.telegram_nonce_expires_at is None
        auth = signin._session(db, auth_token)
        assert auth.kind == "authenticated" and auth.user_id == user.id
        assert auth.revoked_at is None and auth.expires_at > datetime.now(UTC)
        assert auth.csrf_secret == body["csrf_token"]

    before_replay = signin._snapshot(test_engine)
    replayed = telegram_client.post(signin.SIGNIN_PATH, headers=headers, json=request_body)

    assert (replayed.status_code, replayed.json()["code"]) in {
        (401, "invalid_telegram_token"),
        (403, "session_unavailable"),
    }
    assert signin._snapshot(test_engine) == before_replay

    telegram_client.cookies.clear()
    headers = registration.flow._mutation_headers(telegram_client)
    assert telegram_client.cookies[signin.GUEST_COOKIE] != guest_token
    fresh_nonce = signin._issue_nonce(telegram_client, headers)
    assert fresh_nonce != nonce
    recovered = telegram_client.post(
        signin.SIGNIN_PATH,
        headers=headers,
        json={"id_token": signin._sign_token(private_key, fresh_nonce)},
    )

    assert recovered.status_code == 200
    assert recovered.json()["user_id"] == body["user_id"]
    assert recovered.json()["current_run_id"] == state["id"]
    with Session(test_engine) as db:
        assert str(db.scalars(select(User)).one().id) == body["user_id"]
        assert str(db.scalars(select(AuthIdentity)).one().user_id) == body["user_id"]


@pytest.mark.parametrize("auth_state", ["active", "expired", "revoked"])
def test_first_signin_checks_existing_auth_cookie(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    auth_state: str,
) -> None:
    headers, state = registration._complete(telegram_client)
    registered = registration._register(telegram_client, headers, state)
    assert registered.status_code == 201
    previous_auth_token = registered.cookies[signin.AUTH_COOKIE]
    previous_guest_token = telegram_client.cookies[signin.GUEST_COOKIE]
    with Session(test_engine) as db, db.begin():
        auth = signin._session(db, previous_auth_token)
        if auth_state == "expired":
            auth.expires_at = datetime.now(UTC) - timedelta(days=1)
        elif auth_state == "revoked":
            auth.revoked_at = datetime.now(UTC)
    headers, state = registration._complete(telegram_client)
    assert telegram_client.cookies[signin.AUTH_COOKIE] == previous_auth_token
    assert telegram_client.cookies[signin.GUEST_COOKIE] != previous_guest_token
    nonce = signin._issue_nonce(telegram_client, headers)
    before = signin._snapshot(test_engine)

    response = telegram_client.post(
        signin.SIGNIN_PATH,
        headers=headers,
        json={"id_token": signin._sign_token(private_key, nonce), "run_id": state["id"]},
    )

    if auth_state == "active":
        assert response.status_code == 409
        assert response.json()["code"] == "already_authenticated"
        assert signin._snapshot(test_engine) == before
    else:
        assert response.status_code == 201
        assert response.json()["user_id"] != registered.json()["user_id"]
        assert response.json()["current_run_id"] == state["id"]


def test_first_signin_rejects_incomplete_foreign_and_missing_runs(
    telegram_client: TestClient, test_engine: Engine, private_key: rsa.RSAPrivateKey
) -> None:
    _, foreign = registration._complete(telegram_client)
    with TestClient(telegram_client.app, base_url="http://testserver") as other:
        headers = registration.flow._mutation_headers(other)
        started = other.post("/api/v1/onboarding", headers=headers, json={})
        assert started.status_code == 201 and started.json()["status"] == "active"
        nonce = signin._issue_nonce(other, headers)
        token = signin._sign_token(private_key, nonce)
        before = signin._snapshot(test_engine)

        for run_id, status, code in [
            (started.json()["id"], 409, "registration_conflict"),
            (foreign["id"], 404, "onboarding_not_found"),
            (str(uuid4()), 404, "onboarding_not_found"),
        ]:
            response = other.post(
                signin.SIGNIN_PATH, headers=headers, json={"id_token": token, "run_id": run_id}
            )

            assert response.status_code == status and response.json()["code"] == code
            assert signin._snapshot(test_engine) == before


def test_first_signin_rejects_expired_run_with_valid_guest(
    telegram_client: TestClient, test_engine: Engine, private_key: rsa.RSAPrivateKey
) -> None:
    headers, state = registration._complete(telegram_client)
    nonce = signin._issue_nonce(telegram_client, headers)
    with Session(test_engine) as db, db.begin():
        run = db.get(OnboardingRun, UUID(state["id"]))
        assert run is not None
        run.expires_at = datetime.now(UTC) - timedelta(days=1)
    before = signin._snapshot(test_engine)

    response = telegram_client.post(
        signin.SIGNIN_PATH,
        headers=headers,
        json={"id_token": signin._sign_token(private_key, nonce), "run_id": state["id"]},
    )

    assert response.status_code == 410
    assert response.json()["code"] == "run_expired"
    assert signin._snapshot(test_engine) == before


def test_concurrent_first_signins_have_one_atomic_winner(
    telegram_client: TestClient,
    test_engine: Engine,
    private_key: rsa.RSAPrivateKey,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = Barrier(2, timeout=10)
    backend_pids: Queue[int] = Queue()

    def before_user_insert(db: Session, *_: object) -> None:
        if any(isinstance(row, User) for row in db.new):
            # Both requests passed the identity lookup before either can insert.
            pid = db.connection().exec_driver_sql("SELECT pg_backend_pid()").scalar_one()
            backend_pids.put(pid)
            ready.wait()

    def concurrent_db() -> Iterator[Session]:
        with Session(test_engine) as db:
            event.listen(db, "before_flush", before_user_insert)

            @event.listens_for(db, "after_begin")
            def bound_waits(session, transaction, connection):
                connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")

            yield db

    with TestClient(telegram_client.app, base_url="http://testserver") as other:
        clients = [telegram_client, other]
        completed = [registration._complete(client) for client in clients]
        guest_tokens = [client.cookies[signin.GUEST_COOKIE] for client in clients]
        nonces = [
            signin._issue_nonce(client, headers)
            for client, (headers, _) in zip(clients, completed, strict=True)
        ]
        with Session(test_engine) as db:
            nonce_deadlines = [
                signin._session(db, token).telegram_nonce_expires_at for token in guest_tokens
            ]
        with monkeypatch.context() as overrides:
            overrides.setitem(telegram_client.app.dependency_overrides, get_db, concurrent_db)
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        client.post,
                        signin.SIGNIN_PATH,
                        headers=headers,
                        json={
                            "id_token": signin._sign_token(private_key, nonce),
                            "run_id": state["id"],
                        },
                    )
                    for client, (headers, state), nonce in zip(
                        clients, completed, nonces, strict=True
                    )
                ]
                responses = [future.result(timeout=25) for future in futures]

        assert sorted(response.status_code for response in responses) == [201, 409]
        assert backend_pids.qsize() == 2
        assert backend_pids.get_nowait() != backend_pids.get_nowait()
        winner = next(i for i, response in enumerate(responses) if response.status_code == 201)
        loser = 1 - winner
        assert responses[loser].json()["code"] == "identity_conflict"
        assert "set-cookie" not in responses[loser].headers
        assert signin.AUTH_COOKIE not in clients[loser].cookies
        with Session(test_engine) as db:
            user = db.scalars(select(User)).one()
            identity = db.scalars(select(AuthIdentity)).one()
            assert (identity.provider, identity.subject, identity.user_id) == (
                "telegram",
                signin.SUBJECT,
                user.id,
            )
            auth = db.scalars(
                select(BrowserSession).where(BrowserSession.kind == "authenticated")
            ).one()
            assert auth.user_id == user.id
            assert str(user.id) == responses[winner].json()["user_id"]
            won_run = db.get(OnboardingRun, UUID(completed[winner][1]["id"]))
            assert won_run is not None and won_run.user_id == user.id
            assert user.current_run_id == won_run.id
            lost_state = completed[loser][1]
            lost_run = db.get(OnboardingRun, UUID(lost_state["id"]))
            guest = signin._session(db, guest_tokens[loser])
            assert lost_run is not None and lost_run.anonymous_session_id == guest.id
            assert lost_run.user_id is None and lost_run.claimed_at is None
            assert lost_run.revision == lost_state["revision"]
            assert guest.revoked_at is None
            assert guest.telegram_nonce_hash == hash_session_token(nonces[loser])
            assert guest.telegram_nonce_expires_at == nonce_deadlines[loser] is not None


def test_password_registration_and_login_after_telegram_registration(
    telegram_client: TestClient, private_key: rsa.RSAPrivateKey
) -> None:
    headers, state = registration._complete(telegram_client)
    nonce = signin._issue_nonce(telegram_client, headers)
    telegram_account = telegram_client.post(
        signin.SIGNIN_PATH,
        headers=headers,
        json={"id_token": signin._sign_token(private_key, nonce), "run_id": state["id"]},
    )
    assert telegram_account.status_code == 201

    telegram_client.cookies.clear()
    headers, state = registration._complete(telegram_client)
    registered = registration._register(telegram_client, headers, state)
    assert registered.status_code == 201

    telegram_client.cookies.clear()
    headers = registration.flow._mutation_headers(telegram_client)
    logged_in = telegram_client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={"username": "reader_one", "password": registration.PASSWORD},
    )

    assert logged_in.status_code == 200
    assert logged_in.json()["user_id"] == registered.json()["user_id"]
    assert logged_in.json()["current_run_id"] == state["id"]
