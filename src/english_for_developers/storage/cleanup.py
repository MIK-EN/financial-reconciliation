"""Retention cleanup for expired anonymous onboarding data."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, Delete, delete, exists, select, update
from sqlalchemy.orm import Session

from english_for_developers.storage.models import (
    BrowserSession,
    OnboardingRun,
    OnboardingStep,
)

RETENTION_AFTER_EXPIRY = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class CleanupResult:
    runs: int
    steps: int
    sessions: int


def cleanup_expired_sessions(session: Session, now: datetime) -> CleanupResult:
    """Delete unclaimed runs kept past retention and their unreferenced sessions.

    The caller owns the transaction and must commit or roll it back as one unit.
    """
    cutoff = now - RETENTION_AFTER_EXPIRY
    run_ids = list(
        session.scalars(
            select(OnboardingRun.id).where(
                OnboardingRun.user_id.is_(None),
                OnboardingRun.claimed_at.is_(None),
                OnboardingRun.expires_at < cutoff,
            )
        )
    )
    steps_deleted = 0
    runs_deleted = 0
    if run_ids:
        # ON DELETE RESTRICT on the current-step reference is checked immediately,
        # so the pointer must be cleared before its steps can be deleted.
        session.execute(
            update(OnboardingRun)
            .where(
                OnboardingRun.id.in_(run_ids),
                OnboardingRun.current_step_id.is_not(None),
            )
            .values(current_step_id=None)
            .execution_options(synchronize_session=False)
        )
        steps_deleted = _delete(
            session,
            delete(OnboardingStep).where(OnboardingStep.run_id.in_(run_ids)),
        )
        runs_deleted = _delete(
            session,
            delete(OnboardingRun).where(OnboardingRun.id.in_(run_ids)),
        )

    referenced = exists().where(OnboardingRun.anonymous_session_id == BrowserSession.id)
    sessions_deleted = _delete(
        session,
        delete(BrowserSession).where(BrowserSession.expires_at < cutoff, ~referenced),
    )

    return CleanupResult(runs=runs_deleted, steps=steps_deleted, sessions=sessions_deleted)


def _delete(session: Session, statement: Delete) -> int:
    statement = statement.execution_options(synchronize_session=False)
    result = cast(CursorResult[Any], session.execute(statement))
    return result.rowcount
