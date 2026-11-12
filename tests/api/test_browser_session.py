from typing import Any


def test_browser_session_is_created_and_reused(client: Any) -> None:
    headers = {"Origin": "http://testserver"}

    first = client.post("/api/v1/browser-session", headers=headers, json={})

    assert first.status_code == 201
    first_body = first.json()
    assert first_body["session_type"] == "anonymous"
    assert first_body["csrf_token"]
    assert first.headers.get_list("set-cookie")

    repeated = client.post("/api/v1/browser-session", headers=headers, json={})

    assert repeated.status_code == 200
    assert repeated.json()["csrf_token"] == first_body["csrf_token"]
    assert not repeated.headers.get_list("set-cookie")


def test_context_is_available_after_session_creation(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    created = client.post("/api/v1/browser-session", headers=headers, json={})
    assert created.status_code == 201

    response = client.get("/api/v1/context")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
