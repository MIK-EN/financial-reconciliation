from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from english_for_developers.api import browser_routes
from english_for_developers.api.dependencies import get_db
from english_for_developers.api.errors import ApiError

CLAIM_PATH = "/api/v1/onboarding/00000000-0000-0000-0000-000000000000/claim"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"expected_revision": True},
        {"expected_revision": 2.0},
        {"expected_revision": "private-revision"},
        {"expected_revision": "2"},
        {"expected_revision": 2, "extra": "private-extra"},
        {"expected_revision": 2, "user_id": "private-user"},
    ],
)
def test_claim_strict_validation_rejects_input_before_service(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, body: dict
) -> None:
    def unexpected_claim(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Invalid claim body reached the production service")

    monkeypatch.setattr(browser_routes, "claim_run", unexpected_claim)
    response = client.post(CLAIM_PATH, headers={"Origin": "http://testserver"}, json=body)
    assert response.status_code == 422
    result = response.json()
    assert result["code"] == "validation_error"
    assert response.headers["x-request-id"] == result["request_id"]
    assert result["fields"]
    assert all(set(error) <= {"type", "loc", "msg"} for error in result["fields"])
    assert "private-" not in response.text
    assert "set-cookie" not in response.headers
    assert response.headers.get("cache-control") == "no-store"


def test_claim_accepts_integer_revision(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def rejected_claim(db, auth, guest, run_id, expected_revision, csrf, now):
        assert type(expected_revision) is int and expected_revision == 2
        raise ApiError(409, "claim_conflict", "Result cannot be saved")

    monkeypatch.setattr(browser_routes, "claim_run", rejected_claim)
    response = client.post(
        CLAIM_PATH, headers={"Origin": "http://testserver"}, json={"expected_revision": 2}
    )
    assert response.status_code == 409 and response.json()["code"] == "claim_conflict"
    assert response.headers.get("cache-control") == "no-store"


@pytest.mark.parametrize(
    "status,code",
    [(413, "request_too_large"), (500, "internal_error"), (503, "database_unavailable")],
)
def test_claim_infrastructure_errors_disable_caching(app: Any, status: int, code: str) -> None:
    def unavailable_database() -> None:
        if status == 503:
            raise OperationalError("private-query", {}, RuntimeError("private-host"))
        raise RuntimeError("private-failure")

    app.dependency_overrides[get_db] = unavailable_database
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            CLAIM_PATH,
            json={"padding": "x" * 17000} if status == 413 else {"expected_revision": 2},
        )
    assert response.status_code == status and response.json()["code"] == code
    assert "private-" not in response.text and "set-cookie" not in response.headers
    assert response.headers["x-request-id"] == response.json()["request_id"]
    assert response.headers.get("cache-control") == "no-store"
