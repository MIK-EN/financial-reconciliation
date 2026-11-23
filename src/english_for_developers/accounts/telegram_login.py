"""Issue Telegram login nonces and sign in or register Telegram identities."""

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from english_for_developers.accounts.service import _require_login_guest
from english_for_developers.accounts.sessions import (
    hash_session_token,
    issue_csrf_secret,
    issue_session_token,
    require_csrf_token,
)
from english_for_developers.accounts.telegram import TelegramClaims
from english_for_developers.api.errors import ApiError
from english_for_developers.api.schemas import AccountContext
from english_for_developers.storage.models import AuthIdentity, BrowserSession, OnboardingRun, User

NONCE_TTL = timedelta(minutes=10)


def issue_telegram_nonce(
    db: Session, guest_token: str | None, csrf_token: str | None, now: datetime
) -> str:
    guest_hash = hash_session_token(guest_token) if guest_token and guest_token.isascii() else None
    with db.begin():
        guest = db.scalar(
            select(BrowserSession)
            .where(BrowserSession.token_hash == guest_hash, BrowserSession.expires_at > now)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        locked_at = datetime.now(UTC)
        if (
            guest is None
            or guest.kind != "anonymous"
            or guest.revoked_at is not None
            or guest.expires_at <= locked_at
        ):
            raise ApiError(403, "session_unavailable", "Anonymous session is unavailable")
        try:
            require_csrf_token(csrf_token, guest.csrf_secret)
        except (ValueError, TypeError) as exc:
            raise ApiError(403, "csrf_not_allowed", "CSRF token is invalid") from exc
        nonce = secrets.token_urlsafe(32)
        guest.telegram_nonce_hash = hash_session_token(nonce)
        guest.telegram_nonce_expires_at = locked_at + NONCE_TTL
    return nonce


def telegram_sign_in(
    db: Session,
    claims: TelegramClaims,
    run_id: UUID | None,
    guest_token: str | None,
    auth_token: str | None,
    csrf_token: str | None,
    now: datetime,
    ttl_days: int,
) -> tuple[AccountContext, str, bool]:
    """Sign in an existing account or register one by claiming a completed guest run."""
    guest_hash, auth_hash = (
        hash_session_token(token) if token and token.isascii() else None
        for token in (guest_token, auth_token)
    )
    try:
        with db.begin():
            sessions = db.scalars(
                select(BrowserSession)
                .where(BrowserSession.token_hash.in_([guest_hash, auth_hash]))
                .order_by(BrowserSession.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
            now = datetime.now(UTC)
            guest = next((s for s in sessions if s.token_hash == guest_hash), None)
            _require_login_guest(guest, csrf_token, now)
            assert guest is not None
            if (
                guest.telegram_nonce_hash is None
                or guest.telegram_nonce_expires_at is None
                or guest.telegram_nonce_expires_at <= now
                or not claims.nonce.isascii()
                or not secrets.compare_digest(
                    guest.telegram_nonce_hash, hash_session_token(claims.nonce)
                )
            ):
                raise ApiError(401, "invalid_telegram_token", "Telegram token is invalid")
            guest.telegram_nonce_hash = None
            guest.telegram_nonce_expires_at = None

            identity = db.scalar(
                select(AuthIdentity)
                .where(AuthIdentity.provider == "telegram", AuthIdentity.subject == claims.subject)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            run = None
            user: User | None
            if identity is None:
                if any(
                    s.token_hash == auth_hash
                    and s.kind == "authenticated"
                    and s.revoked_at is None
                    and s.expires_at > now
                    for s in sessions
                ):
                    raise ApiError(409, "already_authenticated", "Already authenticated")
                if run_id is None:
                    raise ApiError(409, "registration_conflict", "A completed result is required")
                run = db.scalar(
                    select(OnboardingRun)
                    .where(OnboardingRun.id == run_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                now = datetime.now(UTC)
                _require_login_guest(guest, csrf_token, now)
                if run is None or run.anonymous_session_id != guest.id or run.user_id is not None:
                    raise ApiError(404, "onboarding_not_found", "Onboarding resource was not found")
                if run.expires_at <= now:
                    raise ApiError(410, "run_expired", "Onboarding run has expired")
                if run.status != "completed":
                    raise ApiError(409, "registration_conflict", "A completed result is required")
                user = User(id=uuid4(), username=None, password_hash=None, created_at=now)
                db.add(user)
                db.flush()
                db.add(
                    AuthIdentity(
                        id=uuid4(),
                        user_id=user.id,
                        provider="telegram",
                        subject=claims.subject,
                        created_at=now,
                    )
                )
            else:
                user = db.scalar(
                    select(User)
                    .where(User.id == identity.user_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                now = datetime.now(UTC)
                _require_login_guest(guest, csrf_token, now)
                assert user is not None  # The locked identity has a foreign key to its user.

                for previous in sessions:
                    if (
                        previous.token_hash == auth_hash
                        and previous.kind == "authenticated"
                        and previous.revoked_at is None
                        and previous.expires_at > now
                    ):
                        previous.revoked_at = now

            token = issue_session_token()
            auth = BrowserSession(
                id=uuid4(),
                kind="authenticated",
                user_id=user.id,
                token_hash=hash_session_token(token),
                csrf_secret=issue_csrf_secret(),
                created_at=now,
                expires_at=now + timedelta(days=ttl_days),
            )
            db.add(auth)
            if run is not None:
                run.user_id, run.claimed_at = user.id, now
                run.revision += 1
                user.current_run_id = run.id
                guest.revoked_at = now
            context = AccountContext(
                user_id=user.id,
                username=user.username,
                csrf_token=auth.csrf_secret,
                current_run_id=user.current_run_id,
                expires_at=auth.expires_at,
            )
        return context, token, identity is None
    except IntegrityError as exc:
        constraint_name = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
        if constraint_name == "uq_auth_identities_provider_subject":
            raise ApiError(
                409, "identity_conflict", "Telegram identity is already registered"
            ) from exc
        raise
