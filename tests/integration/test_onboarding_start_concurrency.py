"""Real PostgreSQL contention when one browser starts onboarding twice."""

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
from english_for_developers.onboarding.service import ActiveRun, start_run
from english_for_developers.storage.models import BrowserSession, OnboardingRun, OnboardingStep

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"


def test_concurrent_starts_create_one_run_and_one_first_step(test_engine: Engine) -> None:
    now = datetime(2026, 11, 12, tzinfo=UTC)
    session_id = uuid4()
    bundle = validate_bundle(json.loads(CONTENT_PATH.read_text(encoding="utf-8")))
    # Unlike db_session's savepoint, committed setup is visible to both connections.
    with Session(test_engine) as setup:
        import_bundle(setup, bundle, activate=True, threshold_percent=20)
        setup.add(
            BrowserSession(
                id=session_id,
                kind="anonymous",
                token_hash="a" * 64,
                csrf_secret="synthetic-csrf-secret",
                created_at=now,
                expires_at=now + timedelta(days=7),
            )
        )
        setup.commit()

    ready = Barrier(3, timeout=5)
    backend_pids: Queue[int] = Queue()

    def start() -> ActiveRun:
        # Session objects and their identity maps must not cross thread boundaries.
        with Session(test_engine) as db:
            db.execute(text("SET LOCAL lock_timeout = '10s'"))
            db.execute(text("SET LOCAL statement_timeout = '15s'"))
            browser_session = db.get(BrowserSession, session_id)
            assert browser_session is not None
            backend_pids.put(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
            ready.wait()
            return start_run(db, browser_session, now)

    with ThreadPoolExecutor(max_workers=2) as executor:
        with Session(test_engine) as blocker:
            blocker.scalar(
                select(BrowserSession).where(BrowserSession.id == session_id).with_for_update()
            )
            futures = [executor.submit(start) for _ in range(2)]
            try:
                pids = [backend_pids.get(timeout=5) for _ in range(2)]
                assert pids[0] != pids[1]
                ready.wait()
                # Hold the row until both starts are genuinely waiting in PostgreSQL.
                # AUTOCOMMIT refreshes pg_stat_activity on each observation; no sleeps
                # or scheduler timing assumptions are needed to establish contention.
                with test_engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                ) as observer:
                    observer.execute(text("SET statement_timeout = '5s'"))
                    try:
                        deadline = monotonic() + 5
                        while True:
                            waiting = observer.execute(
                                text(
                                    "SELECT count(*) FROM pg_stat_activity "
                                    "WHERE pid IN (:first, :second) "
                                    "AND wait_event_type = 'Lock' "
                                    "AND cardinality(pg_blocking_pids(pid)) > 0"
                                ),
                                {"first": pids[0], "second": pids[1]},
                            ).scalar_one()
                            if waiting == 2:
                                break
                            assert monotonic() < deadline, "both starts must wait for the row lock"
                    finally:
                        observer.execute(text("RESET statement_timeout"))
            finally:
                # Release even on assertion failure, before executor joins its workers.
                blocker.rollback()
        results = [future.result(timeout=20) for future in futures]

    first, repeated = results
    assert first.id == repeated.id
    assert first.step_id == repeated.step_id
    assert sorted(result.created for result in results) == [False, True]
    for result in results:
        assert result.revision == 0
        assert result.ordinal == 1
        assert result.text_id == "start"
        assert result.bundle_version == bundle.bundle_version

    with Session(test_engine) as verification:
        assert verification.scalar(select(func.count()).select_from(OnboardingRun)) == 1
        assert verification.scalar(select(func.count()).select_from(OnboardingStep)) == 1
        run = verification.get(OnboardingRun, first.id)
        step = verification.get(OnboardingStep, first.step_id)
        assert run is not None and step is not None
        assert run.anonymous_session_id == session_id
        assert run.status == "active"
        assert run.revision == 0
        assert run.current_step_id == step.id
        assert step.run_id == run.id
        assert step.ordinal == 1
        assert step.text_id == "start"
        assert step.answered_at is None
        assert step.answer_mode is None
