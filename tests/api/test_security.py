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


def test_extra_fields_are_rejected_without_echoing_secret_input(client: Any) -> None:
    response = client.post(
        "/api/v1/browser-session",
        headers={"Origin": "http://testserver"},
        json={"secret": "do-not-echo"},
    )

    assert response.status_code == 422
    assert "do-not-echo" not in response.text
