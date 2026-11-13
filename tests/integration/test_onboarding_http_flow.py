import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from english_for_developers.app import create_app
from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"


@pytest.fixture
def onboarding_client(monkeypatch: pytest.MonkeyPatch, test_engine: Engine) -> Iterator[TestClient]:
    database_url = os.environ["TEST_DATABASE_URL"]
    with Session(test_engine) as session:
        raw_bundle = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
        import_bundle(
            session,
            validate_bundle(raw_bundle),
            activate=True,
            threshold_percent=20,
        )
        session.commit()

    monkeypatch.setenv("DATABASE_URL", database_url)
    with TestClient(create_app(), base_url="http://testserver") as client:
        yield client


def test_completed_selection_is_persisted_across_http_requests(
    onboarding_client: TestClient,
) -> None:
    origin_headers = {"Origin": "http://testserver"}
    browser_session = onboarding_client.post(
        "/api/v1/browser-session", headers=origin_headers, json={}
    )
    assert browser_session.status_code == 201
    mutation_headers = {
        **origin_headers,
        "X-CSRF-Token": browser_session.json()["csrf_token"],
    }

    started = onboarding_client.post("/api/v1/onboarding", headers=mutation_headers, json={})
    assert started.status_code == 201
    active = started.json()

    simplified = onboarding_client.post(
        f"/api/v1/onboarding/{active['id']}/answers",
        headers=mutation_headers,
        json={
            "step_id": active["step"]["id"],
            "mode": "unknown_words",
            "word_ids": ["w1", "w2", "w3"],
            "content_version": active["bundle_version"],
        },
    )
    assert simplified.status_code == 200
    assert simplified.json()["step"]["text_id"] == "simplified"

    completed = onboarding_client.post(
        f"/api/v1/onboarding/{active['id']}/answers",
        headers=mutation_headers,
        json={
            "step_id": simplified.json()["step"]["id"],
            "mode": "all_known",
            "word_ids": [],
            "content_version": active["bundle_version"],
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["selected_level"] == "foundations"
    assert completed.json()["revision"] == 2

    selected = onboarding_client.put(
        f"/api/v1/onboarding/{active['id']}/selection",
        headers=mutation_headers,
        json={
            "selected_level": "basic_docs",
            "expected_revision": completed.json()["revision"],
        },
    )
    assert selected.status_code == 200
    assert selected.json()["selected_level"] == "basic_docs"
    assert selected.json()["revision"] == 3

    reread = onboarding_client.get(f"/api/v1/onboarding/{active['id']}")

    assert reread.status_code == 200
    assert reread.json() == selected.json()
