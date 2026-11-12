"""Guest browser session endpoints."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import (
    hash_session_token,
    issue_csrf_secret,
    issue_session_token,
    require_origin,
    session_cookie_options,
)
from english_for_developers.api.dependencies import get_db, get_settings
from english_for_developers.api.schemas import (
    BrowserContextResponse,
    BrowserSessionResponse,
    EmptyBody,
)
from english_for_developers.settings import Settings
from english_for_developers.storage.models import BrowserSession

router = APIRouter(prefix="/api/v1")


def _now() -> datetime:
    return datetime.now(UTC)


def _active_session(db: Session, token: str | None, now: datetime) -> BrowserSession | None:
    if not token:
        return None
    session = db.scalar(
        select(BrowserSession).where(BrowserSession.token_hash == hash_session_token(token))
    )
    if session is None or session.kind != "anonymous":
        return None
    if session.revoked_at is not None or session.expires_at <= now:
        return None
    return session


def _ensure_session(
    db: Session, settings: Settings, token: str | None, now: datetime
) -> tuple[BrowserSession, str, bool]:
    existing = _active_session(db, token, now)
    if existing is not None:
        return existing, token or "", False

    raw_token = issue_session_token()
    session = BrowserSession(
        id=uuid4(),
        kind="anonymous",
        token_hash=hash_session_token(raw_token),
        csrf_secret=issue_csrf_secret(),
        created_at=now,
        expires_at=now + timedelta(days=settings.session_ttl_days),
    )
    db.add(session)
    db.commit()
    return session, raw_token, True


@router.post("/browser-session", response_model=BrowserSessionResponse, status_code=201)
def create_browser_session(
    body: EmptyBody,
    response: Response,
    request: Request,
    origin: str | None = Header(default=None),
    db: Session = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> BrowserSessionResponse:
    del body
    try:
        require_origin(origin, settings.expected_origin)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="origin not allowed") from exc

    now = _now()
    session, token, created = _ensure_session(
        db, settings, request.cookies.get(settings.session_cookie_name), now
    )
    if created:
        response.set_cookie(value=token, **session_cookie_options(settings))
        response.status_code = 201
    else:
        response.status_code = 200
    response.headers["Cache-Control"] = "no-store"
    return BrowserSessionResponse(
        session_id=session.id,
        session_type=session.kind,
        csrf_token=session.csrf_secret,
        expires_at=session.expires_at,
    )


@router.get("/context", response_model=BrowserContextResponse)
def get_context(
    response: Response,
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> BrowserContextResponse:
    response.headers["Cache-Control"] = "no-store"
    session = _active_session(db, request.cookies.get(settings.session_cookie_name), _now())
    if session is None:
        return BrowserContextResponse()
    return BrowserContextResponse(
        anonymous_session_id=session.id,
        csrf_token=session.csrf_secret,
    )
