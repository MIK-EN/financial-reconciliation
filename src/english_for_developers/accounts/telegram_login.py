"""Issue Telegram login nonces for anonymous browser sessions."""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import hash_session_token, require_csrf_token
from english_for_developers.api.errors import ApiError
from english_for_developers.storage.models import BrowserSession

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
