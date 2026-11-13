from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from english_for_developers.api.dependencies import get_db


def _assert_api_error(response: Any, status_code: int, code: str, message: str) -> dict[str, Any]:
    body = response.json()
    assert response.status_code == status_code
    assert body["code"] == code
    assert body["message"] == message
    assert len(body["request_id"]) == 32
    assert response.headers["x-request-id"] == body["request_id"]
    return body


def _start_onboarding(client: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={}).json()
    run = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    ).json()
    return session, run


def test_missing_origin_is_rejected(client: Any) -> None:
    response = client.post("/api/v1/browser-session", json={})

    _assert_api_error(response, 403, "origin_not_allowed", "Request origin is not allowed")


def test_null_and_foreign_origin_are_rejected(client: Any) -> None:
    for origin in ("null", "https://evil.example"):
        response = client.post("/api/v1/browser-session", headers={"Origin": origin}, json={})

        _assert_api_error(response, 403, "origin_not_allowed", "Request origin is not allowed")


def test_reused_browser_session_requires_matching_csrf_token(client: Any) -> None:
    origin = "http://testserver"
    created = client.post("/api/v1/browser-session", headers={"Origin": origin}, json={})

    assert created.status_code == 201

    for csrf_token in (None, "wrong-token"):
        headers = {"Origin": origin}
        if csrf_token is not None:
            headers["X-CSRF-Token"] = csrf_token

        response = client.post("/api/v1/browser-session", headers=headers, json={})

        _assert_api_error(response, 403, "csrf_not_allowed", "CSRF token is invalid")


def test_extra_fields_are_rejected_without_echoing_secret_input(client: Any) -> None:
    response = client.post(
        "/api/v1/browser-session",
        headers={"Origin": "http://testserver"},
        json={"secret": "do-not-echo"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.json()["message"] == "Request validation failed"
    assert len(response.json()["request_id"]) == 32
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

    _assert_api_error(response, 413, "request_too_large", "Request body is too large")


def test_database_failure_returns_safe_service_unavailable(app: Any, client: Any) -> None:
    def unavailable_database() -> None:
        raise OperationalError(
            "SELECT secret_database_value",
            {},
            RuntimeError("private-database-host"),
        )

    app.dependency_overrides[get_db] = unavailable_database

    response = client.post(
        "/api/v1/browser-session",
        headers={"Origin": "http://testserver"},
        json={},
    )

    _assert_api_error(response, 503, "database_unavailable", "Database is unavailable")
    assert "secret_database_value" not in response.text
    assert "private-database-host" not in response.text
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("endpoint", ["start", "answer", "selection"])
@pytest.mark.parametrize(
    ("security_case", "expected_code", "expected_message"),
    [
        ("missing_origin", "origin_not_allowed", "Request origin is not allowed"),
        ("wrong_csrf", "csrf_not_allowed", "CSRF token is invalid"),
    ],
)
def test_onboarding_mutations_return_stable_security_errors(
    client: Any,
    endpoint: str,
    security_case: str,
    expected_code: str,
    expected_message: str,
) -> None:
    session, run = _start_onboarding(client)
    headers = {
        "Origin": "http://testserver",
        "X-CSRF-Token": session["csrf_token"],
    }
    if security_case == "missing_origin":
        del headers["Origin"]
    else:
        headers["X-CSRF-Token"] = "wrong-token"

    if endpoint == "start":
        response = client.post("/api/v1/onboarding", headers=headers, json={})
    elif endpoint == "answer":
        response = client.post(
            f"/api/v1/onboarding/{run['id']}/answers",
            headers=headers,
            json={
                "step_id": run["step"]["id"],
                "mode": "all_known",
                "word_ids": [],
                "content_version": run["bundle_version"],
            },
        )
    else:
        response = client.put(
            f"/api/v1/onboarding/{run['id']}/selection",
            headers=headers,
            json={"selected_level": "foundations", "expected_revision": 0},
        )

    _assert_api_error(response, 403, expected_code, expected_message)
