"""Guest browser session endpoints."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from english_for_developers.accounts.sessions import (
    hash_session_token,
    issue_csrf_secret,
    issue_session_token,
    require_csrf_token,
    require_origin,
    session_cookie_options,
)
from english_for_developers.api.dependencies import get_db, get_now, get_settings
from english_for_developers.api.schemas import (
    ActiveRunResponse,
    ActiveStepResponse,
    AnswerRequest,
    BrowserContextResponse,
    BrowserSessionResponse,
    CompletedRunResponse,
    EmptyBody,
    SegmentResponse,
    SelectionRequest,
)
from english_for_developers.onboarding.service import (
    ActiveRun,
    CompletedRun,
    InvalidAnswer,
    OnboardingNotFound,
    read_run,
    select_level,
    start_run,
    submit_answer,
)
from english_for_developers.settings import Settings
from english_for_developers.storage.models import BrowserSession

router = APIRouter(prefix="/api/v1")


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
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> BrowserSessionResponse:
    del body
    try:
        require_origin(origin, settings.expected_origin)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="origin not allowed") from exc

    existing = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
    if existing is not None:
        try:
            require_csrf_token(csrf_token, existing.csrf_secret)
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="csrf token not allowed") from exc
        session, token, created = existing, "", False
    else:
        session, token, created = _ensure_session(db, settings, None, now)
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
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> BrowserContextResponse:
    response.headers["Cache-Control"] = "no-store"
    session = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
    if session is None:
        return BrowserContextResponse()
    return BrowserContextResponse(
        anonymous_session_id=session.id,
        csrf_token=session.csrf_secret,
    )


@router.post(
    "/onboarding", response_model=ActiveRunResponse | CompletedRunResponse, status_code=200
)
def create_onboarding_run(
    body: EmptyBody,
    response: Response,
    request: Request,
    origin: str | None = Header(default=None),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ActiveRunResponse | CompletedRunResponse:
    del body
    try:
        require_origin(origin, settings.expected_origin)
        session = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
        if session is None:
            raise ValueError("anonymous session is unavailable")
        require_csrf_token(csrf_token, session.csrf_secret)
        run = start_run(db, session, now)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="onboarding access not allowed") from exc

    response.status_code = 201 if isinstance(run, ActiveRun) and run.created else 200
    response.headers["Cache-Control"] = "no-store"
    return _run_response(run)


@router.get("/onboarding/{run_id}", response_model=ActiveRunResponse | CompletedRunResponse)
def get_onboarding_run(
    run_id: UUID,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ActiveRunResponse | CompletedRunResponse:
    session = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
    if session is None:
        raise HTTPException(status_code=404, detail="onboarding run not found")
    try:
        run = read_run(db, session, run_id, now)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="onboarding run not found") from exc
    response.headers["Cache-Control"] = "no-store"
    return _run_response(run)


@router.post(
    "/onboarding/{run_id}/answers", response_model=ActiveRunResponse | CompletedRunResponse
)
def create_answer(
    run_id: UUID,
    body: AnswerRequest,
    response: Response,
    request: Request,
    origin: str | None = Header(default=None),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> ActiveRunResponse | CompletedRunResponse:
    try:
        require_origin(origin, settings.expected_origin)
        session = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
        if session is None:
            raise ValueError("anonymous session is unavailable")
        require_csrf_token(csrf_token, session.csrf_secret)
        run = submit_answer(
            db,
            session,
            run_id,
            body.step_id,
            body.mode,
            body.word_ids,
            body.content_version,
            now,
        )
    except OnboardingNotFound as exc:
        raise HTTPException(status_code=404, detail="onboarding resource not found") from exc
    except InvalidAnswer as exc:
        raise HTTPException(status_code=422, detail="invalid answer") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="answer cannot be accepted") from exc
    response.headers["Cache-Control"] = "no-store"
    return _run_response(run)


@router.put("/onboarding/{run_id}/selection", response_model=CompletedRunResponse)
def update_selection(
    run_id: UUID,
    body: SelectionRequest,
    request: Request,
    origin: str | None = Header(default=None),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> CompletedRunResponse:
    try:
        require_origin(origin, settings.expected_origin)
        session = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
        if session is None:
            raise ValueError("anonymous session is unavailable")
        require_csrf_token(csrf_token, session.csrf_secret)
        run = select_level(db, session, run_id, body.selected_level, body.expected_revision, now)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="selection cannot be accepted") from exc
    return _completed_run_response(run)


def _active_run_response(run: ActiveRun) -> ActiveRunResponse:
    return ActiveRunResponse(
        id=run.id,
        revision=run.revision,
        bundle_version=run.bundle_version,
        expires_at=run.expires_at,
        step=ActiveStepResponse(
            id=run.step_id,
            ordinal=run.ordinal,
            text_id=run.text_id,
            segments=[
                SegmentResponse(text=segment.text, word_id=segment.word_id)
                for segment in run.segments
            ],
        ),
    )


def _run_response(run: ActiveRun | CompletedRun) -> ActiveRunResponse | CompletedRunResponse:
    if isinstance(run, CompletedRun):
        return _completed_run_response(run)
    return _active_run_response(run)


def _completed_run_response(run: CompletedRun) -> CompletedRunResponse:
    return CompletedRunResponse(
        id=run.id,
        revision=run.revision,
        bundle_version=run.bundle_version,
        expires_at=run.expires_at,
        recommended_level=run.recommended_level,
        selected_level=run.selected_level,
        reason_code=run.reason_code,
        explanation=run.explanation,
        saved_to_account=run.saved_to_account,
    )
