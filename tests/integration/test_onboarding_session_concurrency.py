"""Session revocation must win before an onboarding answer locks its run."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Queue
from time import monotonic
from uuid import uuid4

from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.onboarding.service import start_run, submit_answer
from english_for_developers.storage.models import BrowserSession, OnboardingRun, OnboardingStep

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"


def test_answer_rechecks_revoked_session_after_waiting_for_its_lock(
    test_engine: Engine,
) -> None:
    now = datetime.now(UTC)
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
        initial = start_run(setup, owner, now)

    backend_pid: Queue[int] = Queue()

    def answer() -> str:
        with Session(test_engine) as worker:
            worker.execute(text("SET LOCAL statement_timeout = '15s'"))
            owner = worker.get(BrowserSession, owner_id)
            assert owner is not None and owner.revoked_at is None
            pid = worker.scalar(text("SELECT pg_backend_pid()"))
            assert isinstance(pid, int)
            backend_pid.put(pid)
            try:
                submit_answer(
                    worker,
                    owner,
                    initial.id,
                    initial.step_id,
                    "all_known",
                    [],
                    initial.bundle_version,
                    now,
                )
            except ValueError as exc:
                return str(exc)
            return "accepted"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with Session(test_engine) as revoker:
            locked_owner = revoker.scalar(
                select(BrowserSession).where(BrowserSession.id == owner_id).with_for_update()
            )
            assert locked_owner is not None
            locked_owner.revoked_at = now
            revoker.flush()
            future = executor.submit(answer)
            pid = backend_pid.get(timeout=5)

            deadline = monotonic() + 5
            with test_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
                while True:
                    blocked = observer.scalar(
                        text(
                            "SELECT cardinality(pg_blocking_pids(:pid)) > 0 "
                            "FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": pid},
                    )
                    if blocked:
                        break
                    assert not future.done(), "answer must wait for the browser session row lock"
                    assert monotonic() < deadline, (
                        "answer must wait for the browser session row lock"
                    )
            revoker.commit()

        assert future.result(timeout=20) == "anonymous session is unavailable"

    with Session(test_engine) as verification:
        run = verification.get(OnboardingRun, initial.id)
        assert run is not None
        assert run.revision == 0
        assert run.current_step_id == initial.step_id
        steps = verification.scalars(
            select(OnboardingStep).where(OnboardingStep.run_id == initial.id)
        ).all()
        assert len(steps) == 1
        assert steps[0].answered_at is None
