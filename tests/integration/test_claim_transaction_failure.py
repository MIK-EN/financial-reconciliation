"""A flushed claim must roll back completely if commit has not happened."""

from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from english_for_developers.api.dependencies import get_db
from english_for_developers.storage.models import (
    BrowserSession,
    OnboardingRun,
    OnboardingStep,
    User,
)
from tests.integration import test_login as login

claim_client = login.login_client


def _snapshot(db: Session) -> list:
    return [
        list(db.execute(select(*model.__table__.columns).order_by(model.id)))
        for model in (User, BrowserSession, OnboardingRun, OnboardingStep)
    ]


@pytest.mark.parametrize(
    "fault,status,code,message",
    [
        ("internal", 500, "internal_error", "Internal server error"),
        ("database", 503, "database_unavailable", "Database is unavailable"),
    ],
)
def test_claim_failure_after_flush_rolls_back_and_allows_retry(
    claim_client: TestClient,
    test_engine: Engine,
    fault: str,
    status: int,
    code: str,
    message: str,
) -> None:
    account = login._account(claim_client)
    claim_client.cookies.clear()
    guest_headers, state = login.registration._complete(claim_client)
    logged_in = login._login(claim_client, guest_headers)
    assert logged_in.status_code == 200
    headers = {**guest_headers, "X-CSRF-Token": logged_in.json()["csrf_token"]}
    path = f"/api/v1/onboarding/{state['id']}/claim"
    payload = {"expected_revision": state["revision"]}
    run_id, user_id = UUID(state["id"]), UUID(account["user_id"])
    with Session(test_engine) as fresh:
        before = _snapshot(fresh)
        run = fresh.get(OnboardingRun, run_id)
        assert run is not None and run.user_id is None and run.claimed_at is None
        guest_id = run.anonymous_session_id
        assert guest_id is not None
        guest = fresh.get(BrowserSession, guest_id)
        assert guest is not None and guest.revoked_at is None
    assert account["current_run_id"] != state["id"]
    flushed: list[UUID] = []

    def fail_before_commit(db: Session) -> None:
        db.flush()
        # Core SELECTs read real PostgreSQL values, not the ORM identity map.
        connection = db.connection()
        run_row = connection.execute(
            select(*OnboardingRun.__table__.columns).where(OnboardingRun.id == run_id)
        ).one()
        current_run_id = connection.scalar(select(User.current_run_id).where(User.id == user_id))
        revoked_at = connection.scalar(
            select(BrowserSession.revoked_at).where(BrowserSession.id == guest_id)
        )
        assert run_row.user_id == user_id and current_run_id == run_id
        assert run_row.claimed_at is not None and run_row.claimed_at == revoked_at
        assert run_row.revision == state["revision"] + 1
        flushed.append(run_id)
        detail = "synthetic secret; UPDATE onboarding_runs; constraint claim_owner"
        if fault == "database":
            raise OperationalError("UPDATE onboarding_runs", {}, RuntimeError(detail))
        raise RuntimeError(detail)

    def failing_db() -> Iterator[Session]:
        with Session(test_engine) as db:
            event.listen(db, "before_commit", fail_before_commit)
            yield db

    claim_client.app.dependency_overrides[get_db] = failing_db
    try:
        with TestClient(
            claim_client.app, base_url="http://testserver", raise_server_exceptions=False
        ) as client:
            client.cookies.update(claim_client.cookies)
            cookies = dict(client.cookies)
            response = client.post(path, headers=headers, json=payload)
            assert response.status_code == status
            assert response.json() == {
                "code": code,
                "message": message,
                "request_id": response.headers["x-request-id"],
            }
            assert response.json()["request_id"]
            assert response.headers["cache-control"] == "no-store"
            assert "set-cookie" not in response.headers
            assert dict(client.cookies) == cookies
    finally:
        claim_client.app.dependency_overrides.pop(get_db)
    assert flushed == [run_id]
    with Session(test_engine) as fresh:
        assert _snapshot(fresh) == before

    retry = claim_client.post(path, headers=headers, json=payload)
    assert retry.status_code == 200
    assert retry.json() == {**state, "revision": state["revision"] + 1, "saved_to_account": True}
    with Session(test_engine) as fresh:
        run = fresh.get(OnboardingRun, run_id)
        user = fresh.get(User, user_id)
        guest = fresh.get(BrowserSession, guest_id)
        assert run is not None and user is not None and guest is not None
        assert run.user_id == user_id and user.current_run_id == run_id
        assert run.claimed_at is not None and run.claimed_at == guest.revoked_at
        assert run.revision == state["revision"] + 1
        after = _snapshot(fresh)
    repeated = claim_client.post(path, headers=headers, json=payload)
    assert repeated.status_code == 200 and repeated.json() == retry.json()
    with Session(test_engine) as fresh:
        assert _snapshot(fresh) == after
