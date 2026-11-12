import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from english_for_developers.app import create_app
from english_for_developers.storage.models import BrowserSession


@pytest.fixture
def integration_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.fail("TEST_DATABASE_URL must point to the migrated disposable database")
    monkeypatch.setenv("DATABASE_URL", database_url)
    with TestClient(create_app(), base_url="http://testserver") as client:
        yield client


def test_browser_session_is_persisted_and_reused(
    integration_client: TestClient, db_session: Session
) -> None:
    headers = {"Origin": "http://testserver"}

    first = integration_client.post("/api/v1/browser-session", headers=headers, json={})
    repeated = integration_client.post(
        "/api/v1/browser-session",
        headers={**headers, "X-CSRF-Token": first.json()["csrf_token"]},
        json={},
    )

    assert first.status_code == 201
    assert repeated.status_code == 200
    assert repeated.json()["session_id"] == first.json()["session_id"]
    assert db_session.scalar(select(func.count()).select_from(BrowserSession)) == 1


def test_browser_session_rejects_missing_origin_before_writing(
    integration_client: TestClient, db_session: Session
) -> None:
    response = integration_client.post("/api/v1/browser-session", json={})

    assert response.status_code == 403
    assert db_session.scalar(select(func.count()).select_from(BrowserSession)) == 0
