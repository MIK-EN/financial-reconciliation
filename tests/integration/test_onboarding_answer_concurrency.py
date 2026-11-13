"""Identical answers must serialize against the same PostgreSQL run row."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Queue
from threading import Barrier
from time import monotonic
from uuid import uuid4

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.onboarding.service import ActiveRun, start_run, submit_answer
from english_for_developers.storage.models import BrowserSession, OnboardingRun, OnboardingStep

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"


def test_concurrent_identical_answers_create_one_transition(test_engine: Engine) -> None:
    now = datetime.now(UTC)
    bundle = validate_bundle(json.loads(CONTENT_PATH.read_text(encoding="utf-8")))
    owner_id = uuid4()
    # Setup must be committed: each worker uses an independent connection/transaction.
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
        initial = start_run(setup, owner, now)
        assert initial.revision == 0
        assert initial.text_id == "start"

    ready = Barrier(3, timeout=10)
    backend_pids: Queue[int] = Queue()

    def answer() -> ActiveRun:
        with Session(test_engine) as worker:
            # Bound database waits as well as Python waits, including failure cleanup.
            worker.execute(text("SET LOCAL statement_timeout = '15s'"))
            pid = worker.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            owner = worker.get(BrowserSession, owner_id)
            assert owner is not None
            backend_pids.put(pid)
            ready.wait()
            result = submit_answer(
                worker,
                owner,
                initial.id,
                initial.step_id,
                "all_known",
                [],
                initial.bundle_version,
                now,
            )
            assert isinstance(result, ActiveRun)
            return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        # Hold the run before starting either request, then prove both are waiting
        # in PostgreSQL before releasing it. A barrier alone could run sequentially.
        with Session(test_engine) as blocker:
            blocker.scalar(
                select(OnboardingRun).where(OnboardingRun.id == initial.id).with_for_update()
            )
            futures = [executor.submit(answer) for _ in range(2)]
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
                        assert monotonic() < deadline, "Both answers must overlap at the row lock"
                        for future in futures:
                            if future.done():
                                future.result()  # Surface worker errors instead of a lock timeout.
            finally:
                blocker.rollback()
        first, repeated = [future.result(timeout=20) for future in futures]

    assert first == repeated
    assert first.id == initial.id
    assert first.revision == initial.revision + 1
    assert first.ordinal == 2
    assert first.text_id == "installation"
    assert first.step_id != initial.step_id

    # Read through a fresh session so identity-map state cannot hide persisted errors.
    with Session(test_engine) as verification:
        run = verification.get(OnboardingRun, initial.id)
        assert run is not None
        assert run.anonymous_session_id == owner_id
        assert run.status == "active"
        assert run.revision == 1
        assert run.current_step_id == first.step_id
        steps = verification.scalars(
            select(OnboardingStep)
            .where(OnboardingStep.run_id == initial.id)
            .order_by(OnboardingStep.ordinal)
        ).all()
        assert len(steps) == 2
        answered, current = steps
        assert answered.id == initial.step_id
        assert answered.ordinal == 1
        assert answered.answer_mode == "all_known"
        assert answered.unknown_word_ids == []
        assert answered.unknown_count == 0
        assert answered.accessible is True
        assert answered.answered_at == now
        assert current.id == first.step_id
        assert current.ordinal == 2
        assert current.text_id == "installation"
        assert current.answer_mode is None
        assert current.answered_at is None


def test_concurrent_different_answers_allow_only_one_transition(test_engine: Engine) -> None:
    now = datetime.now(UTC)
    bundle = validate_bundle(json.loads(CONTENT_PATH.read_text(encoding="utf-8")))
    owner_id = uuid4()
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
        initial = start_run(setup, owner, now)

    ready = Barrier(3, timeout=10)
    backend_pids: Queue[int] = Queue()

    def answer(mode: str, word_ids: list[str]) -> str:
        with Session(test_engine) as worker:
            worker.execute(text("SET LOCAL statement_timeout = '15s'"))
            pid = worker.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            owner = worker.get(BrowserSession, owner_id)
            assert owner is not None
            backend_pids.put(pid)
            ready.wait()
            try:
                submit_answer(
                    worker,
                    owner,
                    initial.id,
                    initial.step_id,
                    mode,
                    word_ids,
                    initial.bundle_version,
                    now,
                )
                return "accepted"
            except ValueError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        with Session(test_engine) as blocker:
            blocker.scalar(
                select(OnboardingRun).where(OnboardingRun.id == initial.id).with_for_update()
            )
            futures = [
                executor.submit(answer, "all_known", []),
                executor.submit(answer, "unknown_words", ["w1"]),
            ]
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
                        assert monotonic() < deadline, "Both answers must overlap at the row lock"
                        for future in futures:
                            if future.done():
                                future.result()
            finally:
                blocker.rollback()
        results = [future.result(timeout=20) for future in futures]

    assert sorted(results) == ["accepted", "conflict"]
    with Session(test_engine) as verification:
        run = verification.get(OnboardingRun, initial.id)
        assert run is not None
        assert run.revision == 1
        assert (
            verification.scalar(
                select(func.count())
                .select_from(OnboardingStep)
                .where(OnboardingStep.run_id == initial.id)
            )
            == 2
        )
