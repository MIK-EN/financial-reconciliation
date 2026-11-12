from typing import Any


def test_missing_origin_is_rejected(client: Any) -> None:
    response = client.post("/api/v1/browser-session", json={})

    assert response.status_code == 403
    assert response.json()["detail"] == "origin not allowed"


def test_null_and_foreign_origin_are_rejected(client: Any) -> None:
    for origin in ("null", "https://evil.example"):
        response = client.post("/api/v1/browser-session", headers={"Origin": origin}, json={})

        assert response.status_code == 403
        assert response.json()["detail"] == "origin not allowed"


def test_reused_browser_session_requires_matching_csrf_token(client: Any) -> None:
    origin = "http://testserver"
    created = client.post("/api/v1/browser-session", headers={"Origin": origin}, json={})

    assert created.status_code == 201

    for csrf_token in (None, "wrong-token"):
        headers = {"Origin": origin}
        if csrf_token is not None:
            headers["X-CSRF-Token"] = csrf_token

        response = client.post("/api/v1/browser-session", headers=headers, json={})

        assert response.status_code == 403
        assert response.json()["detail"] == "csrf token not allowed"


def test_extra_fields_are_rejected_without_echoing_secret_input(client: Any) -> None:
    response = client.post(
        "/api/v1/browser-session",
        headers={"Origin": "http://testserver"},
        json={"secret": "do-not-echo"},
    )

    assert response.status_code == 422
    assert "do-not-echo" not in response.text


def test_json_body_limit_does_not_trust_content_length(client: Any) -> None:
    oversized = b'{"padding":"' + (b"x" * (16 * 1024)) + b'"}'
    response = client.post(
        "/api/v1/browser-session",
        headers={
            "Origin": "http://testserver",
            "Content-Type": "application/json",
            "Content-Length": "0",
        },
        content=oversized,
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "request body too large"}
