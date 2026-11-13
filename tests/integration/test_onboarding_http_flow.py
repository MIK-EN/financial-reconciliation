import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from english_for_developers.app import create_app
from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.storage.models import BrowserSession, OnboardingRun

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


def _mutation_headers(client: TestClient) -> dict[str, str]:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={})
    assert session.status_code == 201
    return {**headers, "X-CSRF-Token": session.json()["csrf_token"]}


def test_completed_selection_is_persisted_across_http_requests(
    onboarding_client: TestClient,
) -> None:
    mutation_headers = _mutation_headers(onboarding_client)

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


def test_selection_on_foreign_active_or_unknown_run_is_rejected(
    onboarding_client: TestClient,
) -> None:
    owner_headers = _mutation_headers(onboarding_client)
    started = onboarding_client.post("/api/v1/onboarding", headers=owner_headers, json={})
    assert started.status_code == 201
    active = started.json()
    simplified = onboarding_client.post(
        f"/api/v1/onboarding/{active['id']}/answers",
        headers=owner_headers,
        json={
            "step_id": active["step"]["id"],
            "mode": "unknown_words",
            "word_ids": ["w1", "w2", "w3"],
            "content_version": active["bundle_version"],
        },
    )
    completed = onboarding_client.post(
        f"/api/v1/onboarding/{active['id']}/answers",
        headers=owner_headers,
        json={
            "step_id": simplified.json()["step"]["id"],
            "mode": "all_known",
            "word_ids": [],
            "content_version": active["bundle_version"],
        },
    )
    assert completed.status_code == 200
    completed_state = completed.json()

    with TestClient(onboarding_client.app, base_url="http://testserver") as other:
        other_headers = _mutation_headers(other)
        started_other = other.post("/api/v1/onboarding", headers=other_headers, json={})
        assert started_other.status_code == 201
        other_started = started_other.json()
        foreign_completed = other.put(
            f"/api/v1/onboarding/{completed_state['id']}/selection",
            headers=other_headers,
            json={
                "selected_level": "basic_docs",
                "expected_revision": completed_state["revision"],
            },
        )
        foreign_active = onboarding_client.put(
            f"/api/v1/onboarding/{other_started['id']}/selection",
            headers=owner_headers,
            json={
                "selected_level": "basic_docs",
                "expected_revision": other_started["revision"],
            },
        )
        own_active = other.put(
            f"/api/v1/onboarding/{other_started['id']}/selection",
            headers=other_headers,
            json={
                "selected_level": "basic_docs",
                "expected_revision": other_started["revision"],
            },
        )
        unknown = other.put(
            f"/api/v1/onboarding/{uuid4()}/selection",
            headers=other_headers,
            json={"selected_level": "basic_docs", "expected_revision": 0},
        )

        assert foreign_completed.status_code == 404
        assert foreign_completed.headers["cache-control"] == "no-store"
        assert foreign_completed.json()["code"] == "onboarding_not_found"
        assert foreign_active.status_code == 404
        assert foreign_active.headers["cache-control"] == "no-store"
        assert foreign_active.json()["code"] == "onboarding_not_found"
        assert own_active.status_code == 409
        assert own_active.headers["cache-control"] == "no-store"
        assert own_active.json()["code"] == "selection_conflict"
        assert unknown.status_code == 404
        assert unknown.headers["cache-control"] == "no-store"
        assert unknown.json()["code"] == "onboarding_not_found"

        restored_owner = onboarding_client.get(f"/api/v1/onboarding/{completed_state['id']}")
        restored_other = other.get(f"/api/v1/onboarding/{other_started['id']}")
        assert restored_owner.json() == completed_state
        assert restored_other.json() == other_started


def test_own_expired_selection_returns_gone_and_foreign_stays_hidden(
    onboarding_client: TestClient, test_engine: Engine
) -> None:
    mutation_headers = _mutation_headers(onboarding_client)
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
    completed_state = completed.json()

    with Session(test_engine) as setup:
        run = setup.get(OnboardingRun, UUID(completed_state["id"]))
        assert run is not None
        run.expires_at = datetime.now(UTC) - timedelta(days=1)
        setup.commit()

    own_expired = onboarding_client.put(
        f"/api/v1/onboarding/{completed_state['id']}/selection",
        headers=mutation_headers,
        json={
            "selected_level": "basic_docs",
            "expected_revision": completed_state["revision"],
        },
    )

    with TestClient(onboarding_client.app, base_url="http://testserver") as other:
        other_headers = _mutation_headers(other)
        foreign_expired = other.put(
            f"/api/v1/onboarding/{completed_state['id']}/selection",
            headers=other_headers,
            json={
                "selected_level": "basic_docs",
                "expected_revision": completed_state["revision"],
            },
        )

    assert own_expired.status_code == 410
    assert own_expired.headers["cache-control"] == "no-store"
    assert own_expired.json()["code"] == "run_expired"
    assert own_expired.json()["message"] == "Onboarding run has expired"
    assert len(own_expired.json()["request_id"]) == 32
    assert own_expired.headers["x-request-id"] == own_expired.json()["request_id"]
    assert foreign_expired.status_code == 404
    assert foreign_expired.headers["cache-control"] == "no-store"
    assert foreign_expired.json()["code"] == "onboarding_not_found"

    restored = onboarding_client.get(f"/api/v1/onboarding/{completed_state['id']}")
    assert restored.status_code == 200
    restored_state = restored.json()
    assert restored_state["id"] == completed_state["id"]
    assert restored_state["revision"] == completed_state["revision"]
    assert restored_state["selected_level"] == completed_state["selected_level"]
    assert restored_state["recommended_level"] == completed_state["recommended_level"]

    with Session(test_engine) as setup:
        for record in setup.scalars(select(BrowserSession)).all():
            record.expires_at = datetime.now(UTC) - timedelta(days=1)
        setup.commit()

    expired_cookie = onboarding_client.put(
        f"/api/v1/onboarding/{completed_state['id']}/selection",
        headers=mutation_headers,
        json={
            "selected_level": "basic_docs",
            "expected_revision": completed_state["revision"],
        },
    )

    assert expired_cookie.status_code == 403
    assert expired_cookie.json()["code"] == "session_unavailable"
