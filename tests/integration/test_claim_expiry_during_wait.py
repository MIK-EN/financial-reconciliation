"""Claim must recheck deadlines and timestamps after observed PostgreSQL waits."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from queue import Queue
from time import monotonic
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from english_for_developers.accounts import claim
from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.api import dependencies
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User
from tests.integration import test_claim_concurrency as concurrency
from tests.integration import test_login as login

claim_client = login.login_client


def _assert_locked(engine: Engine, model, row_id: UUID) -> None:
    # NOWAIT proves each earlier row is locked without creating another wait.
    with Session(engine) as probe:
        with pytest.raises(OperationalError) as error:
            probe.scalar(select(model).where(model.id == row_id).with_for_update(nowait=True))
        assert error.value.orig.sqlstate == "55P03"


@pytest.mark.parametrize("scenario", ["auth_after_user", "guest_after_run", "fresh_timestamp"])
def test_claim_rechecks_time_after_real_lock_wait(
    claim_client: TestClient,
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    account = login._account(claim_client)
    claim_client.cookies.clear()
    guest_headers, state = login.registration._complete(claim_client)
    logged_in = login._login(claim_client, guest_headers)
    assert logged_in.status_code == 200
    headers = {**guest_headers, "X-CSRF-Token": logged_in.json()["csrf_token"]}
    run_id, user_id = UUID(state["id"]), UUID(account["user_id"])
    with Session(test_engine) as db:
        run = db.get(OnboardingRun, run_id)
        assert run is not None and run.anonymous_session_id is not None
        guest = db.get(BrowserSession, run.anonymous_session_id)
        auth = db.scalars(
            select(BrowserSession).where(
                BrowserSession.token_hash
                == hash_session_token(claim_client.cookies["eds_auth_dev"])
            )
        ).one()
        assert guest is not None and guest.revoked_at is None
        guest_id, auth_id = guest.id, auth.id
        initial = min(auth.expires_at, guest.expires_at) - timedelta(seconds=1)
        after_wait = {
            "auth_after_user": auth.expires_at,
            "guest_after_run": guest.expires_at,
            "fresh_timestamp": datetime.now(UTC) + timedelta(seconds=5),
        }[scenario]
        if scenario == "fresh_timestamp":
            initial = datetime.now(UTC)
            assert initial < after_wait < min(auth.expires_at, guest.expires_at)
    before = concurrency._snapshot(test_engine)
    cookies = dict(claim_client.cookies)

    class Clock(datetime):
        value = initial

        @classmethod
        def now(cls, tz=None):
            return cls.value

    # Only the claim and its HTTP time dependency use the controlled clock.
    monkeypatch.setattr(claim, "datetime", Clock)
    monkeypatch.setattr(dependencies, "datetime", Clock)
    backend_pid: Queue[int] = Queue()

    def worker_db() -> Iterator[Session]:
        with Session(test_engine) as db:

            @event.listens_for(db, "after_begin")
            def configure_transaction(session, transaction, connection):
                connection.exec_driver_sql("SET LOCAL lock_timeout = '12s'")
                connection.exec_driver_sql("SET LOCAL statement_timeout = '15s'")
                backend_pid.put(connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())

            yield db

    claim_client.app.dependency_overrides[dependencies.get_db] = worker_db
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with Session(test_engine) as user_blocker, Session(test_engine) as run_blocker:
                try:
                    run_blocker.execute(text("SET LOCAL statement_timeout = '15s'"))
                    run_pid = run_blocker.scalar(text("SELECT pg_backend_pid()"))
                    assert (
                        run_blocker.scalar(
                            select(OnboardingRun)
                            .where(OnboardingRun.id == run_id)
                            .with_for_update()
                        )
                        is not None
                    )
                    blocker_pid = run_pid
                    blocker_pids = [run_pid]
                    if scenario == "auth_after_user":
                        user_blocker.execute(text("SET LOCAL statement_timeout = '15s'"))
                        blocker_pid = user_blocker.scalar(text("SELECT pg_backend_pid()"))
                        blocker_pids.append(blocker_pid)
                        assert (
                            user_blocker.scalar(
                                select(User).where(User.id == user_id).with_for_update()
                            )
                            is not None
                        )
                    future = executor.submit(
                        claim_client.post,
                        f"/api/v1/onboarding/{run_id}/claim",
                        headers=headers,
                        json={"expected_revision": state["revision"]},
                    )
                    pid = backend_pid.get(timeout=5)
                    assert len(set([pid, *blocker_pids])) == 1 + len(blocker_pids)
                    deadline = monotonic() + 5
                    with test_engine.connect().execution_options(
                        isolation_level="AUTOCOMMIT"
                    ) as observer:
                        observer.exec_driver_sql("SET statement_timeout = '5s'")
                        try:
                            while blocker_pid not in observer.scalar(
                                text("SELECT pg_blocking_pids(:pid)"), {"pid": pid}
                            ):
                                assert not future.done(), "Claim did not wait for the target row"
                                assert monotonic() < deadline, "PostgreSQL wait was not observed"
                        finally:
                            observer.exec_driver_sql("RESET statement_timeout")
                    _assert_locked(test_engine, BrowserSession, auth_id)
                    _assert_locked(test_engine, BrowserSession, guest_id)
                    if scenario != "auth_after_user":
                        _assert_locked(test_engine, User, user_id)
                    assert Clock.value == initial
                    Clock.value = after_wait  # Advance only after PostgreSQL proved the wait.
                    if scenario == "auth_after_user":
                        user_blocker.rollback()
                        # Auth expiry must return before trying the still-locked run.
                        response = future.result(timeout=5)
                    else:
                        run_blocker.rollback()
                        response = future.result(timeout=10)
                finally:
                    user_blocker.rollback()
                    run_blocker.rollback()
    finally:
        claim_client.app.dependency_overrides.pop(dependencies.get_db)

    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert dict(claim_client.cookies) == cookies
    after = concurrency._snapshot(test_engine)
    if scenario != "fresh_timestamp":
        status, code, message = {
            "auth_after_user": (401, "authentication_required", "Authentication is required"),
            "guest_after_run": (403, "session_unavailable", "Anonymous session is unavailable"),
        }[scenario]
        assert response.status_code == status, response.text
        assert response.json() == {
            "code": code,
            "message": message,
            "request_id": response.headers["x-request-id"],
        }
        assert after == before
    else:
        assert response.status_code == 200, response.text
        assert response.json() == {
            **state,
            "revision": state["revision"] + 1,
            "saved_to_account": True,
        }
        expected = deepcopy(before)
        for row in expected[0]:
            if row["id"] == user_id:
                row["current_run_id"] = run_id
        for row in expected[1]:
            if row["id"] == guest_id:
                row["revoked_at"] = after_wait
        for row in expected[2]:
            if row["id"] == run_id:
                row.update(user_id=user_id, claimed_at=after_wait, revision=state["revision"] + 1)
        assert after == expected
    # Exact JSON checks above exclude passwords, hashes and session/CSRF secrets.
