import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from english_for_developers.app import create_app
from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"
HEADERS = {"Origin": "http://testserver"}


@dataclass(frozen=True)
class Owner:
    client: TestClient
    csrf_token: str
    run: dict[str, Any]


def _start_owner(client: TestClient) -> Owner:
    session = client.post("/api/v1/browser-session", headers=HEADERS, json={})
    assert session.status_code == 201
    csrf_token = session.json()["csrf_token"]
    started = client.post(
        "/api/v1/onboarding",
        headers={**HEADERS, "X-CSRF-Token": csrf_token},
        json={},
    )
    assert started.status_code == 201
    return Owner(client, csrf_token, started.json())


@pytest.fixture
def owners(test_engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Owner, Owner]]:
    database_url = os.environ.get("TEST_DATABASE_URL")
    assert database_url is not None
    monkeypatch.setenv("DATABASE_URL", database_url)
    bundle = validate_bundle(json.loads(CONTENT_PATH.read_text(encoding="utf-8")))
    with Session(test_engine) as setup:
        import_bundle(setup, bundle, activate=True, threshold_percent=20)
        setup.commit()

    app = create_app()
    with (
        TestClient(app, base_url="http://testserver") as first_client,
        TestClient(app, base_url="http://testserver") as second_client,
    ):
        yield _start_owner(first_client), _start_owner(second_client)


def _assert_unchanged(owner: Owner) -> None:
    state = owner.client.get(f"/api/v1/onboarding/{owner.run['id']}")
    assert state.status_code == 200
    assert state.json()["revision"] == 0
    assert state.json()["step"] == owner.run["step"]


def test_answer_to_foreign_run_is_not_found(owners: tuple[Owner, Owner]) -> None:
    first, second = owners

    response = first.client.post(
        f"/api/v1/onboarding/{second.run['id']}/answers",
        headers={**HEADERS, "X-CSRF-Token": first.csrf_token},
        json={
            "step_id": second.run["step"]["id"],
            "mode": "all_known",
            "word_ids": [],
            "content_version": second.run["bundle_version"],
        },
    )

    assert response.status_code == 404
    _assert_unchanged(first)
    _assert_unchanged(second)


def test_answer_with_foreign_step_is_not_found(owners: tuple[Owner, Owner]) -> None:
    first, second = owners

    response = first.client.post(
        f"/api/v1/onboarding/{first.run['id']}/answers",
        headers={**HEADERS, "X-CSRF-Token": first.csrf_token},
        json={
            "step_id": second.run["step"]["id"],
            "mode": "all_known",
            "word_ids": [],
            "content_version": first.run["bundle_version"],
        },
    )

    assert response.status_code == 404
    _assert_unchanged(first)
    _assert_unchanged(second)
