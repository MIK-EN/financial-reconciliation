"""Real PostgreSQL evidence for registration races and atomic rollback."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from queue import Queue
from threading import Barrier
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.orm import Session

from english_for_developers.api.dependencies import get_db
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User
from tests.integration import test_registration as registration

registration_client = registration.registration_client


def test_concurrent_normalized_usernames_have_one_atomic_winner(
    registration_client: TestClient,
    test_engine: Engine,
) -> None:
    ready = Barrier(2, timeout=10)
    backend_pids: Queue[int] = Queue()

    def before_user_insert(db: Session, *_: object) -> None:
        if any(isinstance(row, User) for row in db.new):
            # Both requests have observed the username as free, hold their own
            # guest/run locks, and cannot insert until both reach this point.
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

    with TestClient(registration_client.app, base_url="http://testserver") as other:
        clients = [registration_client, other]
        completed = [registration._complete(client) for client in clients]
        guest_tokens = [client.cookies["eds_session_dev"] for client in clients]
        registration_client.app.dependency_overrides[get_db] = concurrent_db
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        client.post,
                        "/api/v1/auth/register",
                        headers=headers,
                        json={
                            "username": username,
                            "password": registration.PASSWORD,
                            "run_id": state["id"],
                        },
                    )
                    for client, (headers, state), username in zip(
                        clients, completed, [" Reader_ONE ", "reader_one"], strict=True
                    )
                ]
                responses = [future.result(timeout=25) for future in futures]
        finally:
            registration_client.app.dependency_overrides.pop(get_db)

        assert backend_pids.qsize() == 2
        assert backend_pids.get_nowait() != backend_pids.get_nowait()
        assert sorted(response.status_code for response in responses) == [201, 409]
        winner = next(i for i, response in enumerate(responses) if response.status_code == 201)
        loser = 1 - winner
        assert responses[loser].json()["code"] == "username_unavailable"
        assert "set-cookie" not in responses[loser].headers
        assert "eds_auth_dev" not in clients[loser].cookies
        token = clients[winner].cookies["eds_auth_dev"]
        with Session(test_engine) as fresh:
            users = fresh.scalars(select(User)).all()
            sessions = fresh.scalars(select(BrowserSession)).all()
            auth_sessions = [row for row in sessions if row.kind == "authenticated"]
            assert len(users) == len(auth_sessions) == 1
            assert len(sessions) == 3
            user, auth = users[0], auth_sessions[0]
            assert user.username == "reader_one"
            assert auth.user_id == user.id and auth.revoked_at is None
            assert auth.token_hash == sha256(token.encode("ascii")).hexdigest()
            assert token not in str(registration._snapshot(fresh))
            assert str(user.id) == responses[winner].json()["user_id"]
            assert len(fresh.scalars(select(OnboardingRun)).all()) == 2
            for i, ((_, state), guest_token) in enumerate(
                zip(completed, guest_tokens, strict=True)
            ):
                run = fresh.get(OnboardingRun, UUID(state["id"]))
                guest = next(
                    row
                    for row in sessions
                    if row.token_hash == sha256(guest_token.encode("ascii")).hexdigest()
                )
                assert run is not None and run.anonymous_session_id == guest.id
                assert run.status == "completed" and guest.kind == "anonymous"
                assert run.user_id == (user.id if i == winner else None)
                assert (run.claimed_at is not None) == (i == winner)
                assert (guest.revoked_at is not None) == (i == winner)
                assert run.revision == state["revision"] + (i == winner)
                if i == winner:
                    assert user.current_run_id == run.id
                    assert responses[winner].json()["current_run_id"] == str(run.id)


def test_failure_after_flush_before_commit_rolls_back_without_auth_cookie(
    registration_client: TestClient,
    test_engine: Engine,
) -> None:
    headers, state = registration._complete(registration_client)
    with Session(test_engine) as fresh:
        before = registration._snapshot(fresh)
    injected: list[UUID] = []

    def fail_before_commit(db: Session) -> None:
        # This is the real request transaction, after every pending mutation
        # has reached PostgreSQL, but before the actual COMMIT is sent.
        db.flush()
        user = db.scalars(select(User)).one()
        auth = db.scalars(
            select(BrowserSession).where(BrowserSession.kind == "authenticated")
        ).one()
        run = db.get(OnboardingRun, UUID(state["id"]))
        assert run is not None
        guest = db.get(BrowserSession, run.anonymous_session_id)
        assert guest is not None and guest.revoked_at is not None
        assert auth.user_id == run.user_id == user.id
        assert user.current_run_id == run.id and run.claimed_at is not None
        assert run.revision == state["revision"] + 1
        injected.append(user.id)
        raise RuntimeError("synthetic failure before registration commit")

    def failing_db() -> Iterator[Session]:
        with Session(test_engine) as db:
            event.listen(db, "before_commit", fail_before_commit)
            yield db

    registration_client.app.dependency_overrides[get_db] = failing_db
    try:
        with TestClient(
            registration_client.app, base_url="http://testserver", raise_server_exceptions=False
        ) as client:
            client.cookies.update(registration_client.cookies)
            response = registration._register(client, headers, state)
            assert response.status_code == 500
            assert "set-cookie" not in response.headers
            assert "eds_auth_dev" not in client.cookies
    finally:
        registration_client.app.dependency_overrides.pop(get_db)
    assert len(injected) == 1
    with Session(test_engine) as fresh:
        assert registration._snapshot(fresh) == before
