"""Transactional operations for anonymous onboarding runs."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from english_for_developers.content.schema import DisplaySegment
from english_for_developers.content.validation import validate_bundle
from english_for_developers.onboarding.rules import evaluate_answer, next_transition
from english_for_developers.storage.models import (
    BrowserSession,
    ContentBundle,
    ContentSettings,
    OnboardingRun,
    OnboardingStep,
)


@dataclass(frozen=True)
class ActiveRun:
    id: UUID
    revision: int
    bundle_version: str
    expires_at: datetime
    step_id: UUID
    ordinal: int
    text_id: str
    segments: tuple[DisplaySegment, ...]
    created: bool


def start_run(db: Session, browser_session: BrowserSession, now: datetime) -> ActiveRun:
    """Create an anonymous run once, or return its current active step."""
    locked_session = db.scalar(
        select(BrowserSession).where(BrowserSession.id == browser_session.id).with_for_update()
    )
    if (
        locked_session is None
        or locked_session.revoked_at is not None
        or locked_session.expires_at <= now
    ):
        raise ValueError("anonymous session is unavailable")

    existing = db.scalar(
        select(OnboardingRun)
        .where(OnboardingRun.anonymous_session_id == locked_session.id)
        .with_for_update()
    )
    if existing is not None:
        step = db.get(OnboardingStep, existing.current_step_id)
        if step is None:
            raise ValueError("active run has no current step")
        return _active_run(db, existing, step, created=False)

    settings = db.get(ContentSettings, 1)
    if settings is None:
        raise ValueError("no active content")
    bundle = db.get(ContentBundle, settings.active_version)
    if bundle is None:
        raise ValueError("active content is unavailable")
    text = validate_bundle(bundle.content_json).get_text("start")

    run_id, step_id = uuid4(), uuid4()
    run = OnboardingRun(
        id=run_id,
        anonymous_session_id=locked_session.id,
        user_id=None,
        content_version=bundle.version,
        normalization_version=bundle.normalization_version,
        policy_version=bundle.policy_version,
        threshold_percent=settings.threshold_percent,
        status="active",
        current_step_id=step_id,
        recommended_level=None,
        selected_level=None,
        reason_code=None,
        revision=0,
        created_at=now,
        completed_at=None,
        claimed_at=None,
        expires_at=locked_session.expires_at,
    )
    step = OnboardingStep(
        id=step_id,
        run_id=run_id,
        ordinal=1,
        text_id="start",
        answer_mode=None,
        unknown_word_ids=None,
        unknown_count=None,
        total_word_count=None,
        accessible=None,
        created_at=now,
        answered_at=None,
    )
    db.add(run)
    db.add(step)
    db.commit()
    return ActiveRun(
        id=run.id,
        revision=run.revision,
        bundle_version=run.content_version,
        expires_at=run.expires_at,
        step_id=step.id,
        ordinal=step.ordinal,
        text_id=step.text_id,
        segments=text.segments,
        created=True,
    )


def read_run(
    db: Session, browser_session: BrowserSession, run_id: UUID, now: datetime
) -> ActiveRun:
    """Return an active run only to its current anonymous-session owner."""
    if browser_session.revoked_at is not None or browser_session.expires_at <= now:
        raise ValueError("anonymous session is unavailable")
    run = db.scalar(
        select(OnboardingRun).where(
            OnboardingRun.id == run_id,
            OnboardingRun.anonymous_session_id == browser_session.id,
        )
    )
    if run is None or run.status != "active":
        raise ValueError("run is unavailable")
    step = db.get(OnboardingStep, run.current_step_id)
    if step is None:
        raise ValueError("active run has no current step")
    return _active_run(db, run, step, created=False)


def submit_answer(
    db: Session,
    browser_session: BrowserSession,
    run_id: UUID,
    step_id: UUID,
    mode: str,
    word_ids: list[str],
    content_version: str,
    now: datetime,
) -> ActiveRun:
    """Persist one answer and create the next active step."""
    run = db.scalar(
        select(OnboardingRun)
        .where(
            OnboardingRun.id == run_id,
            OnboardingRun.anonymous_session_id == browser_session.id,
        )
        .with_for_update()
    )
    if run is None or run.status != "active" or run.expires_at <= now:
        raise ValueError("run is unavailable")
    if run.content_version != content_version or run.current_step_id != step_id:
        raise ValueError("stale run state")
    step = db.get(OnboardingStep, step_id)
    bundle = db.get(ContentBundle, run.content_version)
    if step is None or bundle is None:
        raise ValueError("run state is unavailable")
    text = validate_bundle(bundle.content_json).get_text(step.text_id)
    evaluation = evaluate_answer(text, mode, word_ids, run.threshold_percent)  # type: ignore[arg-type]
    transition = next_transition(text.id, evaluation.accessible)
    if transition.next_text_id is None:
        raise ValueError("completed runs are not implemented")

    next_text = validate_bundle(bundle.content_json).get_text(transition.next_text_id)
    next_step = OnboardingStep(
        id=uuid4(),
        run_id=run.id,
        ordinal=step.ordinal + 1,
        text_id=next_text.id,
        answer_mode=None,
        unknown_word_ids=None,
        unknown_count=None,
        total_word_count=None,
        accessible=None,
        created_at=now,
        answered_at=None,
    )
    step.answer_mode = evaluation.mode
    step.unknown_word_ids = list(evaluation.word_ids)
    step.unknown_count = evaluation.unknown_count
    step.total_word_count = evaluation.total_count
    step.accessible = evaluation.accessible
    step.answered_at = now
    run.current_step_id = next_step.id
    run.revision += 1
    db.add(next_step)
    db.commit()
    return ActiveRun(
        id=run.id,
        revision=run.revision,
        bundle_version=run.content_version,
        expires_at=run.expires_at,
        step_id=next_step.id,
        ordinal=next_step.ordinal,
        text_id=next_step.text_id,
        segments=next_text.segments,
        created=False,
    )


def _active_run(
    db: Session, run: OnboardingRun, step: OnboardingStep, *, created: bool
) -> ActiveRun:
    bundle = db.get(ContentBundle, run.content_version)
    if bundle is None:
        raise ValueError("run content is unavailable")
    text = validate_bundle(bundle.content_json).get_text(step.text_id)
    return ActiveRun(
        id=run.id,
        revision=run.revision,
        bundle_version=run.content_version,
        expires_at=run.expires_at,
        step_id=step.id,
        ordinal=step.ordinal,
        text_id=step.text_id,
        segments=text.segments,
        created=created,
    )
