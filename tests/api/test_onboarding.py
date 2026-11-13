from typing import Any

import pytest


def test_start_creates_active_run_for_browser_session(client: Any) -> None:
    created_session = client.post(
        "/api/v1/browser-session",
        headers={"Origin": "http://testserver"},
        json={},
    )
    assert created_session.status_code == 201

    response = client.post(
        "/api/v1/onboarding",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": created_session.json()["csrf_token"],
        },
        json={},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "active"
    assert body["revision"] == 0
    assert body["bundle_version"] == "onboarding-v1"
    assert body["step"]["ordinal"] == 1
    assert body["step"]["text_id"] == "start"
    assert body["step"]["segments"]


def test_owner_reads_active_run_after_start(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    created_session = client.post("/api/v1/browser-session", headers=headers, json={})
    assert created_session.status_code == 201

    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": created_session.json()["csrf_token"]},
        json={},
    )
    assert started.status_code == 201

    response = client.get(f"/api/v1/onboarding/{started.json()['id']}")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["id"] == started.json()["id"]
    assert response.json()["status"] == "active"
    assert response.json()["step"]["text_id"] == "start"


def test_answer_moves_run_to_next_text(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    created_session = client.post("/api/v1/browser-session", headers=headers, json={})
    csrf_token = created_session.json()["csrf_token"]
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": csrf_token},
        json={},
    )
    initial = started.json()

    response = client.post(
        f"/api/v1/onboarding/{initial['id']}/answers",
        headers={**headers, "X-CSRF-Token": csrf_token},
        json={
            "step_id": initial["step"]["id"],
            "mode": "all_known",
            "word_ids": [],
            "content_version": initial["bundle_version"],
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["revision"] == 1
    assert response.json()["step"]["ordinal"] == 2
    assert response.json()["step"]["text_id"] == "installation"


def test_repeating_same_answer_returns_current_state(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    created_session = client.post("/api/v1/browser-session", headers=headers, json={})
    csrf_token = created_session.json()["csrf_token"]
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": csrf_token},
        json={},
    ).json()
    answer = {
        "step_id": started["step"]["id"],
        "mode": "all_known",
        "word_ids": [],
        "content_version": started["bundle_version"],
    }

    first = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": csrf_token},
        json=answer,
    )
    repeated = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": csrf_token},
        json=answer,
    )

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["revision"] == 1
    assert repeated.json()["step"]["text_id"] == "installation"


def test_retry_start_with_ten_unknown_after_simplified(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={}).json()
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    ).json()
    answer = {
        "step_id": started["step"]["id"],
        "mode": "unknown_words",
        "word_ids": ["w10", "w9", "w8", "w7", "w6", "w5", "w4", "w3", "w2", "w1"],
        "content_version": started["bundle_version"],
    }

    first = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json=answer,
    )
    repeated = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            **answer,
            "word_ids": ["w1", "w2", "w3", "w4", "w5", "w6", "w7", "w8", "w9", "w10"],
        },
    )

    assert first.status_code == 200
    assert first.json()["step"]["text_id"] == "simplified"
    assert repeated.status_code == 200
    assert repeated.json() == first.json()
    assert repeated.json()["revision"] == 1


def test_last_answer_completes_run_with_recommendation(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={}).json()
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    ).json()
    simplified = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            "step_id": started["step"]["id"],
            "mode": "unknown_words",
            "word_ids": ["w1", "w2", "w3"],
            "content_version": started["bundle_version"],
        },
    ).json()

    response = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            "step_id": simplified["step"]["id"],
            "mode": "all_known",
            "word_ids": [],
            "content_version": started["bundle_version"],
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["revision"] == 2
    assert response.json()["recommended_level"] == "foundations"
    assert response.json()["selected_level"] == "foundations"
    assert response.json()["reason_code"] == "simplified_accessible"
    assert response.json()["explanation"] == (
        "В коротком тексте о действиях с файлом знакомых слов оказалось больше. "
        "Начнём с простых команд и частой лексики"
    )
    assert response.json()["saved_to_account"] is False

    reread = client.get(f"/api/v1/onboarding/{started['id']}")
    assert reread.status_code == 200
    assert reread.json()["status"] == "completed"
    assert reread.json()["recommended_level"] == "foundations"


def test_repeating_last_answer_returns_completed_state(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={}).json()
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    ).json()
    simplified = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            "step_id": started["step"]["id"],
            "mode": "unknown_words",
            "word_ids": ["w1", "w2", "w3"],
            "content_version": started["bundle_version"],
        },
    ).json()
    last_answer = {
        "step_id": simplified["step"]["id"],
        "mode": "all_known",
        "word_ids": [],
        "content_version": started["bundle_version"],
    }

    completed = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json=last_answer,
    )
    repeated = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json=last_answer,
    )

    assert completed.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json() == completed.json()
    assert repeated.json()["revision"] == 2


def test_start_recovers_completed_run_after_lost_terminal_response(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={}).json()
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    ).json()
    simplified = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            "step_id": started["step"]["id"],
            "mode": "unknown_words",
            "word_ids": ["w1", "w2", "w3"],
            "content_version": started["bundle_version"],
        },
    ).json()
    completed = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            "step_id": simplified["step"]["id"],
            "mode": "all_known",
            "word_ids": [],
            "content_version": started["bundle_version"],
        },
    )

    recovered = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    )

    assert completed.status_code == 200
    assert recovered.status_code == 200
    assert recovered.json() == completed.json()


def test_completed_run_allows_level_selection(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={}).json()
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    ).json()
    simplified = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            "step_id": started["step"]["id"],
            "mode": "unknown_words",
            "word_ids": ["w1", "w2", "w3"],
            "content_version": started["bundle_version"],
        },
    ).json()
    completed = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            "step_id": simplified["step"]["id"],
            "mode": "all_known",
            "word_ids": [],
            "content_version": started["bundle_version"],
        },
    ).json()

    response = client.put(
        f"/api/v1/onboarding/{started['id']}/selection",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={"selected_level": "basic_docs", "expected_revision": completed["revision"]},
    )

    assert response.status_code == 200
    assert response.json()["selected_level"] == "basic_docs"
    assert response.json()["revision"] == 3


def test_unknown_word_id_is_rejected_without_changing_run(client: Any) -> None:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={}).json()
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    ).json()

    response = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={
            "step_id": started["step"]["id"],
            "mode": "unknown_words",
            "word_ids": ["unknown"],
            "content_version": started["bundle_version"],
        },
    )
    state = client.get(f"/api/v1/onboarding/{started['id']}")

    assert response.status_code == 422
    assert state.json()["revision"] == 0
    assert state.json()["step"]["text_id"] == "start"


@pytest.mark.parametrize(
    ("answer_override", "expected_status", "expected_code"),
    [
        pytest.param(
            {"word_ids": ["w1", "w1"]},
            422,
            "invalid_answer",
            id="duplicate-word-ids",
        ),
        pytest.param(
            {"content_version": "stale-version"},
            409,
            "content_version_mismatch",
            id="content-version-mismatch",
        ),
    ],
)
def test_invalid_answer_does_not_change_run(
    client: Any,
    answer_override: dict[str, object],
    expected_status: int,
    expected_code: str,
) -> None:
    headers = {"Origin": "http://testserver"}
    session = client.post("/api/v1/browser-session", headers=headers, json={}).json()
    started = client.post(
        "/api/v1/onboarding",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json={},
    ).json()
    answer = {
        "step_id": started["step"]["id"],
        "mode": "unknown_words",
        "word_ids": ["w1"],
        "content_version": started["bundle_version"],
        **answer_override,
    }

    response = client.post(
        f"/api/v1/onboarding/{started['id']}/answers",
        headers={**headers, "X-CSRF-Token": session["csrf_token"]},
        json=answer,
    )
    state = client.get(f"/api/v1/onboarding/{started['id']}")

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert len(response.json()["request_id"]) == 32
    assert response.headers["x-request-id"] == response.json()["request_id"]
    assert state.json()["revision"] == 0
    assert state.json()["step"] == started["step"]
