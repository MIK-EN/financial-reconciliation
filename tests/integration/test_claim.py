from uuid import UUID

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
