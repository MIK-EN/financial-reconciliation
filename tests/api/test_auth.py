import pytest
from fastapi.testclient import TestClient

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
