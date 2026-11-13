"""Concurrent selections of one browser session serialize in the documented lock order.

The external completed-run lock keeps the overlap observable in PostgreSQL; the
session-first lock is what serializes writers of the same anonymous run.
"""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Queue
from threading import Barrier
from time import monotonic
from uuid import UUID, uuid4

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.onboarding.service import (
    CompletedRun,
    select_level,
    start_run,
    submit_answer,
)
from english_for_developers.storage.models import BrowserSession, OnboardingRun

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"


def _completed_run(test_engine: Engine, now: datetime) -> tuple[UUID, CompletedRun]:
    owner_id = uuid4()
    bundle = validate_bundle(json.loads(CONTENT_PATH.read_text(encoding="utf-8")))
    with Session(test_engine) as setup:
        import_bundle(setup, bundle, activate=True, threshold_percent=20)
        owner = BrowserSession(
            id=owner_id,
            kind="anonymous",
            token_hash=uuid4().hex + uuid4().hex,
            csrf_secret="synthetic-csrf-secret",
            created_at=now,
            expires_at=now + timedelta(days=7),
        )
        setup.add(owner)
        setup.commit()
        started = start_run(setup, owner, now)
        simplified = submit_answer(
            setup,
            owner,
            started.id,
            started.step_id,
            "unknown_words",
            ["w1", "w2", "w3"],
            started.bundle_version,
            now,
        )
        assert not isinstance(simplified, CompletedRun)
        completed = submit_answer(
            setup,
            owner,
            simplified.id,
            simplified.step_id,
            "all_known",
            [],
            started.bundle_version,
            now,
        )
        assert isinstance(completed, CompletedRun)
        assert completed.revision == 2
        assert completed.recommended_level == "foundations"
    return owner_id, completed


def _concurrent_selections(
    test_engine: Engine,
    owner_id: UUID,
    run_id: UUID,
    expected_revision: int,
    levels: tuple[str, str],
) -> list[dict[str, object]]:
    ready = Barrier(3, timeout=10)
    backend_pids: Queue[int] = Queue()

    def choose(level: str) -> dict[str, object]:
        with Session(test_engine) as worker:
            # Bound database waits as well as Python waits, including failure cleanup.
            worker.execute(text("SET LOCAL statement_timeout = '15s'"))
            pid = worker.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            owner = worker.get(BrowserSession, owner_id)
            assert owner is not None
            backend_pids.put(pid)
            ready.wait()
            try:
                result = select_level(
                    worker, owner, run_id, level, expected_revision, datetime.now(UTC)
                )
            except ValueError as exc:
                return {"status": "rejected", "level": level, "detail": str(exc)}
            return {"status": "accepted", "level": level, "detail": result.revision}

    with ThreadPoolExecutor(max_workers=2) as executor:
        # Hold the completed run before starting either request, then prove both
        # workers wait in PostgreSQL before releasing it. A barrier alone could
        # run them sequentially.
        with Session(test_engine) as blocker:
            blocker.scalar(
                select(OnboardingRun).where(OnboardingRun.id == run_id).with_for_update()
            )
            futures = [executor.submit(choose, level) for level in levels]
            try:
                ready.wait()
                first_pid = backend_pids.get(timeout=10)
                second_pid = backend_pids.get(timeout=10)
                assert first_pid != second_pid
                deadline = monotonic() + 5
                with test_engine.connect() as observer:
                    while True:
                        blocked = observer.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE pid IN (:first_pid, :second_pid) "
                                "AND cardinality(pg_blocking_pids(pid)) > 0"
                            ),
                            {"first_pid": first_pid, "second_pid": second_pid},
                        )
                        if blocked == 2:
                            break
                        assert monotonic() < deadline, "Both selections must overlap at a row lock"
                        for future in futures:
                            if future.done():
                                future.result()  # Surface worker errors instead of a timeout.
            finally:
                blocker.rollback()
        return [future.result(timeout=20) for future in futures]


def test_concurrent_different_selections_accept_one_value(test_engine: Engine) -> None:
    now = datetime.now(UTC)
    owner_id, completed = _completed_run(test_engine, now)

    outcome = _concurrent_selections(
        test_engine,
        owner_id,
        completed.id,
        completed.revision,
        ("basic_docs", "complex_texts"),
    )

    accepted = next(item for item in outcome if item["status"] == "accepted")
    rejected = next(item for item in outcome if item["status"] == "rejected")
    assert accepted["detail"] == completed.revision + 1
    assert rejected["detail"] == "stale revision"

    with Session(test_engine) as verification:
        run = verification.get(OnboardingRun, completed.id)
        assert run is not None
        assert run.revision == completed.revision + 1
        assert run.selected_level == accepted["level"]
        assert run.recommended_level == "foundations"
        assert run.status == "completed"


def test_concurrent_identical_selections_do_not_increment_twice(test_engine: Engine) -> None:
    now = datetime.now(UTC)
    owner_id, completed = _completed_run(test_engine, now)

    outcome = _concurrent_selections(
        test_engine,
        owner_id,
        completed.id,
        completed.revision,
        ("basic_docs", "basic_docs"),
    )

    assert [item["status"] for item in outcome] == ["accepted", "accepted"]
    assert {item["detail"] for item in outcome} == {completed.revision + 1}

    with Session(test_engine) as verification:
        run = verification.get(OnboardingRun, completed.id)
        assert run is not None
        assert run.revision == completed.revision + 1
        assert run.selected_level == "basic_docs"
        assert run.recommended_level == "foundations"
