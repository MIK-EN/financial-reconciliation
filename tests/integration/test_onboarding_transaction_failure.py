"""Failures before commit must not leave partial onboarding state."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from english_for_developers.content.importer import import_bundle
from english_for_developers.content.validation import validate_bundle
from english_for_developers.onboarding.service import ActiveRun, start_run, submit_answer
from english_for_developers.storage.models import BrowserSession, OnboardingRun, OnboardingStep

CONTENT_PATH = Path(__file__).resolve().parents[2] / "content" / "onboarding-v1.json"


def test_answer_failure_before_commit_rolls_back_transition(
    test_engine: Engine, monkeypatch: pytest.MonkeyPatch
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
        assert isinstance(initial, ActiveRun)

    with Session(test_engine) as worker:
        owner = worker.get(BrowserSession, owner_id)
        assert owner is not None

        def fail_before_commit() -> None:
            worker.flush()
            raise RuntimeError("injected failure before commit")

        monkeypatch.setattr(worker, "commit", fail_before_commit)
        with pytest.raises(RuntimeError, match="injected failure before commit"):
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

    with Session(test_engine) as verification:
        run = verification.get(OnboardingRun, initial.id)
        assert run is not None
        assert run.revision == 0
        assert run.current_step_id == initial.step_id
        steps = verification.scalars(
            select(OnboardingStep).where(OnboardingStep.run_id == initial.id)
        ).all()
        assert len(steps) == 1
        assert steps[0].id == initial.step_id
        assert steps[0].answered_at is None
        assert steps[0].answer_mode is None
