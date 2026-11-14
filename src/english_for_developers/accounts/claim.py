"""Atomic transfer of a completed anonymous result to an existing account."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token, require_csrf_token
from english_for_developers.api.errors import ApiError
from english_for_developers.onboarding.service import CompletedRun, _completed_run
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User


def _require_sessions(
    auth: BrowserSession | None,
    guest: BrowserSession | None,
    csrf_token: str | None,
    now: datetime,
) -> None:
    if (
        auth is None
        or auth.kind != "authenticated"
        or auth.user_id is None
        or auth.revoked_at is not None
        or auth.expires_at <= now
    ):
        raise ApiError(401, "authentication_required", "Authentication is required")
    try:
        require_csrf_token(csrf_token, auth.csrf_secret)
    except (ValueError, TypeError) as exc:
        raise ApiError(403, "csrf_not_allowed", "CSRF token is invalid") from exc
    if (
        guest is None
        or guest.kind != "anonymous"
        or guest.revoked_at is not None
        or guest.expires_at <= now
    ):
        raise ApiError(403, "session_unavailable", "Anonymous session is unavailable")


def claim_run(
    db: Session,
    auth_token: str | None,
    guest_token: str | None,
    run_id: UUID,
    expected_revision: int,
    csrf_token: str | None,
    now: datetime,
) -> CompletedRun:
    """Resolve cookie tokens server-side and recheck all access under row locks."""
    auth_hash, guest_hash = (
        hash_session_token(token) if token and token.isascii() else None
        for token in (auth_token, guest_token)
    )
    with db.begin():
        sessions = db.scalars(
            select(BrowserSession)
            .where(BrowserSession.token_hash.in_([auth_hash, guest_hash]))
            .order_by(BrowserSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        auth = next((s for s in sessions if s.token_hash == auth_hash), None)
        guest = next((s for s in sessions if s.token_hash == guest_hash), None)
        _require_sessions(auth, guest, csrf_token, datetime.now(UTC))
        assert auth is not None and guest is not None
        user = db.scalar(
            select(User)
            .where(User.id == auth.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        _require_sessions(auth, guest, csrf_token, datetime.now(UTC))
        if user is None:
            raise ApiError(401, "authentication_required", "Authentication is required")
        run = db.scalar(
            select(OnboardingRun)
            .where(OnboardingRun.id == run_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = datetime.now(UTC)
        _require_sessions(auth, guest, csrf_token, now)
        if run is None or run.anonymous_session_id != guest.id or run.user_id is not None:
            raise ApiError(404, "onboarding_not_found", "Onboarding resource was not found")
        if run.expires_at <= now:
            raise ApiError(410, "run_expired", "Onboarding run has expired")
        if run.status != "completed" or run.revision != expected_revision:
            raise ApiError(409, "claim_conflict", "Result cannot be saved")
        run.user_id, run.claimed_at = user.id, now
        run.revision += 1
        user.current_run_id = run.id
        guest.revoked_at = now
        result = _completed_run(db, run)
    return result
