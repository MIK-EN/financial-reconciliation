from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token
from english_for_developers.storage.models import BrowserSession, OnboardingRun
from tests.integration import test_login as login

access_client = login.login_client


def test_account_reads_registered_result(access_client: TestClient) -> None:
    account = login._account(access_client)
    response = access_client.get(f"/api/v1/onboarding/{account['current_run_id']}")
    assert response.status_code == 200
    assert response.json()["saved_to_account"] is True
    assert response.json()["revision"] == 3


def _selection(
    client: TestClient, run_id: str, csrf: str, revision: int, level: str = "basic_docs"
):
    return client.put(
        f"/api/v1/onboarding/{run_id}/selection",
        headers={"Origin": "http://testserver", "X-CSRF-Token": csrf},
        json={"selected_level": level, "expected_revision": revision},
    )


def _auth_session(client: TestClient, db: Session) -> BrowserSession:
    session = db.scalar(
        select(BrowserSession).where(
            BrowserSession.token_hash == hash_session_token(client.cookies["eds_auth_dev"])
        )
    )
    assert session is not None
    return session


def test_account_selection_after_guest_expiry_and_revision_rules(
    access_client: TestClient, test_engine: Engine
) -> None:
    account = login._account(access_client)
    run_id, csrf = account["current_run_id"], account["csrf_token"]
    with Session(test_engine) as db:
        run = db.get(OnboardingRun, UUID(run_id))
        assert run is not None
        run.expires_at = datetime.now(UTC) - timedelta(days=1)
        original_recommendation = run.recommended_level
        db.commit()
    read = access_client.get(f"/api/v1/onboarding/{run_id}")
    assert read.status_code == 200 and read.headers["cache-control"] == "no-store"
    chosen = "foundations" if original_recommendation == "basic_docs" else "basic_docs"
    changed = _selection(access_client, run_id, csrf, 3, chosen)
    assert changed.status_code == 200
    assert changed.headers["cache-control"] == "no-store"
    assert changed.json()["revision"] == 4
    assert changed.json()["selected_level"] == chosen
    assert changed.json()["recommended_level"] == original_recommendation
    same = _selection(access_client, run_id, csrf, 3, chosen)
    assert same.status_code == 200 and same.json()["revision"] == 4
    stale = _selection(access_client, run_id, csrf, 3, original_recommendation)
    assert stale.status_code == 409 and stale.json()["code"] == "selection_conflict"
    assert stale.headers["cache-control"] == "no-store"
    assert access_client.get(f"/api/v1/onboarding/{run_id}").json()["revision"] == 4


def test_account_csrf_and_inactive_session_leave_selection_unchanged(
    access_client: TestClient, test_engine: Engine
) -> None:
    account = login._account(access_client)
    run_id = account["current_run_id"]
    for csrf in ("incorrect", ""):
        response = _selection(access_client, run_id, csrf, 3)
        assert response.status_code == 403 and response.json()["code"] == "csrf_not_allowed"
        assert response.headers["cache-control"] == "no-store"
    with Session(test_engine) as db:
        auth = _auth_session(access_client, db)
        auth.revoked_at = datetime.now(UTC)
        db.commit()
    assert access_client.get(f"/api/v1/onboarding/{run_id}").status_code == 404
    denied = _selection(access_client, run_id, account["csrf_token"], 3)
    assert denied.status_code == 403 and denied.headers["cache-control"] == "no-store"
    with Session(test_engine) as db:
        run = db.get(OnboardingRun, UUID(run_id))
        assert run is not None and run.revision == 3


def test_expired_auth_then_fresh_login_restores_saved_run(
    access_client: TestClient, test_engine: Engine
) -> None:
    account = login._account(access_client)
    run_id = account["current_run_id"]
    with Session(test_engine) as db:
        auth = _auth_session(access_client, db)
        auth.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert access_client.get(f"/api/v1/onboarding/{run_id}").status_code == 404
    assert _selection(access_client, run_id, account["csrf_token"], 3).status_code == 403
    access_client.cookies.clear()
    headers, _ = login.registration._complete(access_client)
    logged_in = login._login(access_client, headers)
    assert logged_in.status_code == 200
    assert access_client.get(f"/api/v1/onboarding/{run_id}").status_code == 200
    assert _selection(access_client, run_id, logged_in.json()["csrf_token"], 3).status_code == 200


def test_foreign_guest_unknown_and_logout_hide_account_run(access_client: TestClient) -> None:
    account = login._account(access_client)
    run_id = account["current_run_id"]
    with TestClient(access_client.app, base_url="http://testserver") as foreign:
        headers, state = login.registration._complete(foreign)
        for hidden in (run_id, str(uuid4())):
            denied = foreign.get(f"/api/v1/onboarding/{hidden}")
            assert denied.status_code == 404 and denied.json()["code"] == "onboarding_not_found"
            rejected = _selection(foreign, hidden, headers["X-CSRF-Token"], 3)
            assert rejected.status_code == 404 and rejected.json()["code"] == "onboarding_not_found"
        registered = foreign.post(
            "/api/v1/auth/register",
            headers=headers,
            json={"username": "another_reader", "password": login.PASSWORD, "run_id": state["id"]},
        )
        assert registered.status_code == 201
        assert foreign.get(f"/api/v1/onboarding/{run_id}").status_code == 404
        assert _selection(foreign, run_id, registered.json()["csrf_token"], 3).status_code == 404
    logout = access_client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "http://testserver", "X-CSRF-Token": account["csrf_token"]},
        json={},
    )
    assert logout.status_code == 204
    assert access_client.get(f"/api/v1/onboarding/{run_id}").status_code == 404


def test_both_cookies_choose_actual_owner(access_client: TestClient) -> None:
    account = login._account(access_client)
    access_client.cookies.clear()
    guest_headers, guest_run = login.registration._complete(access_client)
    # Restore an independent valid auth cookie alongside the new guest cookie.
    login._login(access_client, guest_headers)
    auth_csrf = access_client.get("/api/v1/context").json()["account"]["csrf_token"]
    assert access_client.get(f"/api/v1/onboarding/{guest_run['id']}").status_code == 200
    assert access_client.get(f"/api/v1/onboarding/{account['current_run_id']}").status_code == 200
    guest_selection = _selection(access_client, guest_run["id"], guest_headers["X-CSRF-Token"], 2)
    assert guest_selection.status_code == 200
    auth_selection = _selection(access_client, account["current_run_id"], auth_csrf, 3)
    assert auth_selection.status_code == 200
    wrong = _selection(
        access_client, guest_run["id"], auth_csrf, guest_selection.json()["revision"]
    )
    assert wrong.status_code == 403
    access_client.cookies.set("eds_auth_dev", "invalid-auth-cookie")
    assert access_client.get(f"/api/v1/onboarding/{guest_run['id']}").status_code == 200
    assert (
        _selection(
            access_client,
            guest_run["id"],
            guest_headers["X-CSRF-Token"],
            guest_selection.json()["revision"],
        ).status_code
        == 200
    )


def test_invalid_guest_cookie_does_not_mask_account_and_auth_cannot_answer(
    access_client: TestClient,
) -> None:
    account = login._account(access_client)
    run_id = account["current_run_id"]
    access_client.cookies.set("eds_session_dev", "invalid-guest-cookie")
    assert access_client.get(f"/api/v1/onboarding/{run_id}").status_code == 200
    assert _selection(access_client, run_id, account["csrf_token"], 3).status_code == 200
    access_client.cookies.delete("eds_session_dev")
    headers = {"Origin": "http://testserver", "X-CSRF-Token": account["csrf_token"]}
    start = access_client.post("/api/v1/onboarding", headers=headers, json={})
    answer = access_client.post(
        f"/api/v1/onboarding/{run_id}/answers",
        headers=headers,
        json={
            "step_id": str(uuid4()),
            "mode": "all_known",
            "word_ids": [],
            "content_version": "onboarding-v1",
        },
    )
    assert start.status_code == answer.status_code == 403
    assert start.json()["code"] == answer.json()["code"] == "session_unavailable"


def test_both_cookies_hide_foreign_and_unknown_with_either_valid_csrf(
    access_client: TestClient,
) -> None:
    login._account(access_client)
    access_client.cookies.clear()
    guest_headers, _ = login.registration._complete(access_client)
    authenticated = login._login(access_client, guest_headers)
    assert authenticated.status_code == 200
    auth_csrf = authenticated.json()["csrf_token"]
    with TestClient(access_client.app, base_url="http://testserver") as foreign:
        headers, foreign_run = login.registration._complete(foreign)
        registered = foreign.post(
            "/api/v1/auth/register",
            headers=headers,
            json={
                "username": "foreign_reader",
                "password": login.PASSWORD,
                "run_id": foreign_run["id"],
            },
        )
        assert registered.status_code == 201
        for hidden in (foreign_run["id"], str(uuid4())):
            for csrf in (guest_headers["X-CSRF-Token"], auth_csrf):
                denied = _selection(access_client, hidden, csrf, 3)
                assert denied.status_code == 404
                assert denied.json()["code"] == "onboarding_not_found"
                assert denied.headers["cache-control"] == "no-store"
            invalid = _selection(access_client, hidden, "invalid-csrf", 3)
            assert invalid.status_code == 403
            assert invalid.json()["code"] == "csrf_not_allowed"
