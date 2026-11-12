from typing import Any


def test_start_creates_active_run_for_browser_session(client: Any) -> None:
    created_session = client.post(
        "/api/v1/browser-session",
        headers={"Origin": "http://testserver"},
        json={},
    )
    assert created_session.status_code == 201

    response = client.post(
        "/api/v1/onboarding",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": created_session.json()["csrf_token"],
        },
        json={},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "active"
    assert body["revision"] == 0
    assert body["bundle_version"] == "onboarding-v1"
    assert body["step"]["ordinal"] == 1
    assert body["step"]["text_id"] == "start"
    assert body["step"]["segments"]
