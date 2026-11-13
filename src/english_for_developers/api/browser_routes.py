"""Guest browser session endpoints."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Request, Response
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
from english_for_developers.api.errors import ApiError
from english_for_developers.api.schemas import (
    AccountContext,
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
    ContentVersionMismatch,
    InvalidAnswer,
    OnboardingNotFound,
    RunExpired,
    SessionUnavailable,
    read_run,
    select_level,
    start_run,
    submit_answer,
)
from english_for_developers.settings import Settings
from english_for_developers.storage.models import BrowserSession, OnboardingRun, User

router = APIRouter(prefix="/api/v1")


def _require_allowed_origin(origin: str | None, expected_origin: str) -> None:
    try:
        require_origin(origin, expected_origin)
    except ValueError as exc:
        raise ApiError(403, "origin_not_allowed", "Request origin is not allowed") from exc


def _require_matching_csrf(csrf_token: str | None, expected_token: str) -> None:
    try:
        require_csrf_token(csrf_token, expected_token)
    except ValueError as exc:
        raise ApiError(403, "csrf_not_allowed", "CSRF token is invalid") from exc


def _active_session(db: Session, token: str | None, now: datetime) -> BrowserSession | None:
    if not token or not token.isascii():
        return None
    session = db.scalar(
        select(BrowserSession).where(BrowserSession.token_hash == hash_session_token(token))
    )
    if session is None or session.kind != "anonymous":
        return None
    if session.revoked_at is not None or session.expires_at <= now:
        return None
    return session


def _active_auth_session(db: Session, token: str | None, now: datetime) -> BrowserSession | None:
    if not token or not token.isascii():
        return None
    session = db.scalar(
        select(BrowserSession).where(BrowserSession.token_hash == hash_session_token(token))
    )
    if (
        session is None
        or session.kind != "authenticated"
        or session.revoked_at is not None
        or session.expires_at <= now
    ):
        return None
    return session


def _run_owner_session(
    db: Session, request: Request, settings: Settings, run_id: UUID, now: datetime
) -> tuple[BrowserSession | None, BrowserSession | None]:
    guest = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
    auth = _active_auth_session(db, request.cookies.get(settings.auth_cookie_name), now)
    candidate = db.scalar(select(OnboardingRun).where(OnboardingRun.id == run_id))
    if candidate is not None:
        if auth is not None and candidate.user_id == auth.user_id:
            return auth, auth
        if (
            guest is not None
            and candidate.user_id is None
            and candidate.anonymous_session_id == guest.id
        ):
            return guest, guest
    return None, auth or guest


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


def _require_onboarding_mutation_access(
    db: Session,
    settings: Settings,
    request: Request,
    origin: str | None,
    csrf_token: str | None,
    now: datetime,
) -> BrowserSession:
    _require_allowed_origin(origin, settings.expected_origin)
    session = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
    if session is None:
        raise ApiError(403, "session_unavailable", "Anonymous session is unavailable")
    _require_matching_csrf(csrf_token, session.csrf_secret)
    return session


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
    _require_allowed_origin(origin, settings.expected_origin)

    existing = _active_session(db, request.cookies.get(settings.session_cookie_name), now)
    if existing is not None:
        _require_matching_csrf(csrf_token, existing.csrf_secret)
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
    guest_token = request.cookies.get(settings.session_cookie_name)
    session = _active_session(
        db, guest_token if guest_token and guest_token.isascii() else None, now
    )
    context = BrowserContextResponse()
    if session is not None:
        run = db.scalar(
            select(OnboardingRun).where(OnboardingRun.anonymous_session_id == session.id)
        )
        context.anonymous_session_id = session.id
        context.csrf_token = session.csrf_secret
        context.anonymous_run_id = run.id if run is not None else None
    auth_token = request.cookies.get(settings.auth_cookie_name)
    if not auth_token or not auth_token.isascii():
        return context
    auth = db.scalar(
        select(BrowserSession).where(
            BrowserSession.token_hash == hash_session_token(auth_token),
            BrowserSession.kind == "authenticated",
            BrowserSession.expires_at > now,
            BrowserSession.revoked_at.is_(None),
        )
    )
    if auth is not None:
        user = db.execute(select(User).where(User.id == auth.user_id)).scalar_one()
        context.account = AccountContext(
            user_id=user.id,
            username=user.username,
            csrf_token=auth.csrf_secret,
            current_run_id=user.current_run_id,
            expires_at=auth.expires_at,
        )
        context.saved_run_ids = list(
            db.scalars(
                select(OnboardingRun.id)
                .where(OnboardingRun.user_id == user.id)
                .order_by(OnboardingRun.created_at, OnboardingRun.id)
            )
        )
    return context


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
    session = _require_onboarding_mutation_access(db, settings, request, origin, csrf_token, now)
    try:
        run = start_run(db, session, now)
    except ValueError as exc:
        raise ApiError(409, "onboarding_start_conflict", "Onboarding cannot be started") from exc

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
    session, _ = _run_owner_session(db, request, settings, run_id, now)
    if session is None:
        raise ApiError(404, "onboarding_not_found", "Onboarding resource was not found")
    try:
        run = read_run(db, session, run_id, now)
    except ValueError as exc:
        raise ApiError(404, "onboarding_not_found", "Onboarding resource was not found") from exc
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
    session = _require_onboarding_mutation_access(db, settings, request, origin, csrf_token, now)
    try:
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
        raise ApiError(404, "onboarding_not_found", "Onboarding resource was not found") from exc
    except InvalidAnswer as exc:
        raise ApiError(422, "invalid_answer", "Answer is invalid") from exc
    except ContentVersionMismatch as exc:
        raise ApiError(409, "content_version_mismatch", "Content version does not match") from exc
    except ValueError as exc:
        raise ApiError(409, "answer_conflict", "Answer cannot be accepted") from exc
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
    _require_allowed_origin(origin, settings.expected_origin)
    owner, fallback = _run_owner_session(db, request, settings, run_id, now)
    session = owner or fallback
    if session is None:
        raise ApiError(403, "session_unavailable", "Browser session is unavailable")
    _require_matching_csrf(csrf_token, session.csrf_secret)
    try:
        run = select_level(db, session, run_id, body.selected_level, body.expected_revision, now)
    # OnboardingNotFound subclasses ValueError: map the hidden resource before the conflict.
    except OnboardingNotFound as exc:
        raise ApiError(404, "onboarding_not_found", "Onboarding resource was not found") from exc
    except RunExpired as exc:
        raise ApiError(410, "run_expired", "Onboarding run has expired") from exc
    except SessionUnavailable as exc:
        raise ApiError(403, "session_unavailable", "Browser session is unavailable") from exc
    except ValueError as exc:
        raise ApiError(409, "selection_conflict", "Selection cannot be accepted") from exc
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
