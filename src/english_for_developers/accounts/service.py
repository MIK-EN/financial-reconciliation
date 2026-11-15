"""Atomic account registration and browser login."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from english_for_developers.accounts.passwords import (
    hash_password,
    normalize_username,
    verify_password,
)
from english_for_developers.accounts.sessions import (
    hash_session_token,
    issue_csrf_secret,
    issue_session_token,
    require_csrf_token,
)
from english_for_developers.api.errors import ApiError
from english_for_developers.api.schemas import AccountContext
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User

# A valid Argon2 hash makes absent usernames use the same expensive verification path.
_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$DXvk7PsddTiUIJj7kE22xg$"
    "1hnX3khd2wKNg/c+R8+VCCHEQ2f/kLjfCO2E6seqwtU"
)


def logout(db: Session, auth_token: str | None, csrf_token: str | None, now: datetime) -> None:
    if not auth_token or not auth_token.isascii():
        return
    statement = select(BrowserSession).where(
        BrowserSession.token_hash == hash_session_token(auth_token),
        BrowserSession.kind == "authenticated",
        BrowserSession.revoked_at.is_(None),
        BrowserSession.expires_at > now,
    )
    with db.begin():
        auth = db.scalar(statement)
        if auth is None:
            return
        try:
            require_csrf_token(csrf_token, auth.csrf_secret)
            auth = db.scalar(statement.with_for_update().execution_options(populate_existing=True))
            now = datetime.now(UTC)
            if auth is None or auth.expires_at <= now:
                return
            require_csrf_token(csrf_token, auth.csrf_secret)
        except (ValueError, TypeError) as exc:
            raise ApiError(403, "csrf_not_allowed", "CSRF token is invalid") from exc
        auth.revoked_at = now


def _require_login_guest(
    guest: BrowserSession | None, csrf_token: str | None, now: datetime
) -> None:
    if (
        guest is None
        or guest.kind != "anonymous"
        or guest.revoked_at is not None
        or guest.expires_at <= now
    ):
        raise ApiError(403, "session_unavailable", "Anonymous session is unavailable")
    try:
        require_csrf_token(csrf_token, guest.csrf_secret)
    except (ValueError, TypeError) as exc:
        raise ApiError(403, "csrf_not_allowed", "CSRF token is invalid") from exc


def login(
    db: Session,
    username: str,
    password: str,
    guest_token: str | None,
    auth_token: str | None,
    csrf_token: str | None,
    now: datetime,
    ttl_days: int,
) -> tuple[AccountContext, str]:
    username = normalize_username(username)
    guest_hash, auth_hash = (
        hash_session_token(token) if token and token.isascii() else None
        for token in (guest_token, auth_token)
    )
    with db.begin():
        guest = db.scalar(select(BrowserSession).where(BrowserSession.token_hash == guest_hash))
        _require_login_guest(guest, csrf_token, now)
        credentials = db.execute(
            select(User.id, User.password_hash).where(User.username == username)
        ).one_or_none()
    # The read transaction has ended. Argon2 runs without any row locks.
    password_hash = credentials.password_hash if credentials else _DUMMY_PASSWORD_HASH
    verified = verify_password(password, password_hash)
    if credentials is None or not verified:
        raise ApiError(401, "invalid_credentials", "Invalid username or password")
    token = issue_session_token()
    with db.begin():
        sessions = db.scalars(
            select(BrowserSession)
            .where(BrowserSession.token_hash.in_([guest_hash, auth_hash]))
            .order_by(BrowserSession.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
        guest = next((s for s in sessions if s.token_hash == guest_hash), None)
        _require_login_guest(guest, csrf_token, datetime.now(UTC))
        user = db.scalar(
            select(User)
            .where(User.id == credentials.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        # The user lock may have waited after the session lock was acquired.
        now = datetime.now(UTC)
        _require_login_guest(guest, csrf_token, now)
        if user is None or user.password_hash != password_hash or user.username != username:
            raise ApiError(401, "invalid_credentials", "Invalid username or password")
        for previous in sessions:
            if (
                previous.token_hash == auth_hash
                and previous.kind == "authenticated"
                and previous.revoked_at is None
                and previous.expires_at > now
            ):
                previous.revoked_at = now
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
        context = AccountContext(
            user_id=user.id,
            username=user.username,
            csrf_token=auth.csrf_secret,
            current_run_id=user.current_run_id,
            expires_at=auth.expires_at,
        )
    # Constraint errors roll back and are mapped to a safe 503 by the API handler.
    return context, token


def register(
    db: Session,
    username: str,
    password: str,
    run_id: UUID,
    guest_token: str | None,
    auth_token: str | None,
    csrf_token: str | None,
    now: datetime,
    ttl_days: int,
) -> tuple[AccountContext, str]:
    username = normalize_username(username)
    password_hash = hash_password(password)  # Expensive work precedes all row locks.
    guest_hash, auth_hash = (
        hash_session_token(token) if token and token.isascii() else None
        for token in (guest_token, auth_token)
    )
    token = issue_session_token()
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
            if any(
                s.token_hash == auth_hash
                and s.kind == "authenticated"
                and s.revoked_at is None
                and s.expires_at > now
                for s in sessions
            ):
                raise ApiError(409, "already_authenticated", "Already authenticated")
            guest = next((s for s in sessions if s.token_hash == guest_hash), None)
            if (
                guest is None
                or guest.kind != "anonymous"
                or guest.revoked_at is not None
                or guest.expires_at <= now
            ):
                raise ApiError(403, "session_unavailable", "Anonymous session is unavailable")
            try:
                require_csrf_token(csrf_token, guest.csrf_secret)
            except (ValueError, TypeError) as exc:
                raise ApiError(403, "csrf_not_allowed", "CSRF token is invalid") from exc
            existing = db.scalar(select(User).where(User.username == username).with_for_update())
            if existing is not None:
                raise ApiError(409, "username_unavailable", "Username is unavailable")
            run = db.scalar(
                select(OnboardingRun)
                .where(OnboardingRun.id == run_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            # Recheck time after the last lock, including any wait for the run.
            now = datetime.now(UTC)
            _require_login_guest(guest, csrf_token, now)
            if run is None or run.anonymous_session_id != guest.id or run.user_id is not None:
                raise ApiError(404, "onboarding_not_found", "Onboarding resource was not found")
            if run.expires_at <= now:
                raise ApiError(410, "run_expired", "Onboarding run has expired")
            if run.status != "completed":
                raise ApiError(409, "registration_conflict", "A completed result is required")
            user = User(id=uuid4(), username=username, password_hash=password_hash, created_at=now)
            db.add(user)
            db.flush()
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
            # expires_at remains the historical guest deadline; owned runs do not expire.
            run.user_id, run.claimed_at = user.id, now
            run.revision += 1
            user.current_run_id = run.id
            guest.revoked_at = now
            context = AccountContext(
                user_id=user.id,
                username=username,
                csrf_token=auth.csrf_secret,
                current_run_id=run.id,
                expires_at=auth.expires_at,
            )
        return context, token
    except IntegrityError as exc:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_users_username":
            raise ApiError(409, "username_unavailable", "Username is unavailable") from exc
        raise
