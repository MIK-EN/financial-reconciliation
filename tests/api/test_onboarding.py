from typing import Any


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

    reread = client.get(f"/api/v1/onboarding/{started['id']}")
    assert reread.status_code == 200
    assert reread.json()["status"] == "completed"
    assert reread.json()["recommended_level"] == "foundations"


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
