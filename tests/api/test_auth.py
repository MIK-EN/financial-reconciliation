import pytest
from fastapi.testclient import TestClient

from english_for_developers.api.dependencies import get_db
from english_for_developers.app import create_app


@pytest.mark.parametrize(
    "body",
    [
        {"username": "reader", "password": "tiny-secret", "run_id": "invalid"},
        {
            "username": "reader",
            "password": "synthetic password",
            "run_id": "00000000-0000-0000-0000-000000000000",
            "user_id": "forbidden",
        },
        {
            "username": "invalid!",
            "password": "synthetic password",
            "run_id": "00000000-0000-0000-0000-000000000000",
        },
    ],
)
def test_registration_validation_never_reflects_password(body: dict) -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert body["password"] not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"username": "invalid!", "password": "synthetic password"},
        {"username": "reader", "password": "tiny-secret"},
        {"username": "reader", "password": "synthetic password", "user_id": "forbidden"},
    ],
)
def test_login_validation_never_reflects_password(body: dict) -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/auth/login", json=body)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["code"] == "validation_error"
    assert body["password"] not in response.text


@pytest.mark.parametrize("status", [413, 500])
@pytest.mark.parametrize("route", ["login", "logout"])
def test_auth_error_responses_disable_caching(status: int, route: str) -> None:
    app = create_app()

    def unexpected_database_error() -> None:
        raise RuntimeError("private failure details")

    app.dependency_overrides[get_db] = unexpected_database_error
    password = "x" * 17000 if status == 413 else "synthetic password"
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/api/v1/auth/{route}",
            json={"username": "reader", "password": password}
            if route == "login"
            else ({"extra": password} if status == 413 else {}),
        )
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert password not in response.text and "private failure details" not in response.text


def test_logout_rejects_extra_fields_without_deleting_cookie() -> None:
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/auth/logout", json={"extra": "forbidden"})
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
