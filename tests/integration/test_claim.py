from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User
from tests.integration import test_login as login

claim_client = login.login_client


def test_claim_makes_guest_result_current_and_preserves_saved_result(
    claim_client: TestClient, test_engine: Engine
) -> None:
    account = login._account(claim_client)
    old_id = account["current_run_id"]
    old_response = claim_client.get(f"/api/v1/onboarding/{old_id}").json()
    with Session(test_engine) as db:
        old_row = db.execute(
            select(*OnboardingRun.__table__.columns).where(OnboardingRun.id == UUID(old_id))
        ).one()
    claim_client.cookies.clear()
    guest_headers, guest_run = login.registration._complete(claim_client)
    guest_token = claim_client.cookies["eds_session_dev"]
    logged_in = login._login(claim_client, guest_headers)
    assert logged_in.status_code == 200
    assert logged_in.json()["current_run_id"] == old_id != guest_run["id"]
    response = claim_client.post(
        f"/api/v1/onboarding/{guest_run['id']}/claim",
        headers={"Origin": guest_headers["Origin"], "X-CSRF-Token": logged_in.json()["csrf_token"]},
        json={"expected_revision": guest_run["revision"]},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        **guest_run,
        "revision": guest_run["revision"] + 1,
        "saved_to_account": True,
    }
    context = claim_client.get("/api/v1/context").json()
    assert context["account"]["current_run_id"] == guest_run["id"]
    assert set(context["saved_run_ids"]) == {old_id, guest_run["id"]}
    assert context["anonymous_session_id"] is None
    assert claim_client.get(f"/api/v1/onboarding/{old_id}").json() == old_response
    assert claim_client.get(f"/api/v1/onboarding/{guest_run['id']}").json() == response.json()
    with Session(test_engine) as db:
        user = db.get(User, UUID(account["user_id"]))
        run = db.get(OnboardingRun, UUID(guest_run["id"]))
        guest = db.scalar(
            select(BrowserSession).where(
                BrowserSession.token_hash == hash_session_token(guest_token)
            )
        )
        assert user is not None and run is not None and guest is not None
        assert run.user_id == user.id and user.current_run_id == run.id
        assert run.claimed_at is not None and run.claimed_at == guest.revoked_at
        assert run.revision == guest_run["revision"] + 1
        assert (
            db.execute(
                select(*OnboardingRun.__table__.columns).where(OnboardingRun.id == UUID(old_id))
            ).one()
            == old_row
        )


@pytest.mark.parametrize(
    "case,status,code",
    [
        ("active", 409, "claim_conflict"),
        ("expired", 410, "run_expired"),
        ("foreign", 404, "onboarding_not_found"),
        ("foreign_expired", 404, "onboarding_not_found"),
        ("unknown", 404, "onboarding_not_found"),
        ("owned", 404, "onboarding_not_found"),
        ("owned_expired", 404, "onboarding_not_found"),
        ("revision", 409, "claim_conflict"),
        ("missing_auth", 401, "authentication_required"),
        ("expired_auth", 401, "authentication_required"),
        ("revoked_auth", 401, "authentication_required"),
        ("csrf", 403, "csrf_not_allowed"),
        ("guest_csrf", 403, "csrf_not_allowed"),
        ("missing_guest", 403, "session_unavailable"),
        ("expired_guest", 403, "session_unavailable"),
        ("revoked_guest", 403, "session_unavailable"),
        ("missing_origin", 403, "origin_not_allowed"),
        ("foreign_origin", 403, "origin_not_allowed"),
        ("null_origin", 403, "origin_not_allowed"),
    ],
)
def test_rejected_claim_preserves_all_account_session_and_run_rows(
    claim_client: TestClient, test_engine: Engine, case: str, status: int, code: str
) -> None:
    login._account(claim_client)
    claim_client.cookies.clear()
    guest_headers, state = login.registration._complete(claim_client)
    logged_in = login._login(claim_client, guest_headers)
    assert logged_in.status_code == 200
    headers = {**guest_headers, "X-CSRF-Token": logged_in.json()["csrf_token"]}
    with Session(test_engine) as db:
        run = db.get(OnboardingRun, UUID(state["id"]))
        sessions = {
            kind: db.scalar(
                select(BrowserSession).where(
                    BrowserSession.token_hash == hash_session_token(claim_client.cookies[cookie])
                )
            )
            for kind, cookie in (("auth", "eds_auth_dev"), ("guest", "eds_session_dev"))
        }
        assert run is not None
        if case.startswith("foreign"):
            guest = sessions["guest"]
            assert guest is not None
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
        if case.startswith("owned"):
            owner = User(
                id=uuid4(),
                username="other_reader",
                password_hash="unused",
                created_at=datetime.now(UTC),
            )
            db.add(owner)
            db.flush()
            run.user_id, run.claimed_at = owner.id, datetime.now(UTC)
        if case == "active":
            run.status, run.completed_at = "active", None
            run.recommended_level = run.selected_level = run.reason_code = None
        if case in {"expired", "foreign_expired", "owned_expired"}:
            run.expires_at = datetime.now(UTC) - timedelta(days=1)
        for kind, session in sessions.items():
            assert session is not None
            if case == f"expired_{kind}":
                session.expires_at = datetime.now(UTC) - timedelta(days=1)
            if case == f"revoked_{kind}":
                session.revoked_at = datetime.now(UTC)
        db.commit()
        before = login.registration._snapshot(db)
    if case in {"missing_auth", "missing_guest"}:
        claim_client.cookies.delete("eds_auth_dev" if case == "missing_auth" else "eds_session_dev")
    if case in {"csrf", "guest_csrf"}:
        headers["X-CSRF-Token"] = "wrong" if case == "csrf" else guest_headers["X-CSRF-Token"]
    if case == "missing_origin":
        del headers["Origin"]
    if case in {"foreign_origin", "null_origin"}:
        headers["Origin"] = "https://foreign.example" if case == "foreign_origin" else "null"
    run_id = str(uuid4()) if case == "unknown" else state["id"]
    response = claim_client.post(
        f"/api/v1/onboarding/{run_id}/claim",
        headers=headers,
        json={"expected_revision": state["revision"] + (1 if case == "revision" else 0)},
    )
    assert response.status_code == status and response.json()["code"] == code
    assert "set-cookie" not in response.headers
    assert response.headers["x-request-id"] == response.json()["request_id"]
    with Session(test_engine) as db:
        assert login.registration._snapshot(db) == before
    assert response.headers.get("cache-control") == "no-store"
