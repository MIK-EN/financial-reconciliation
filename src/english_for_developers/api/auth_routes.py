"""Browser account registration and login endpoints."""

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.orm import Session

from english_for_developers.accounts.service import login, logout, register
from english_for_developers.accounts.sessions import session_cookie_options
from english_for_developers.accounts.telegram import (
    TelegramClaims,
    TelegramTokenInvalid,
    TelegramTokenVerifier,
    TelegramUnavailable,
)
from english_for_developers.accounts.telegram_login import issue_telegram_nonce, telegram_sign_in
from english_for_developers.api.browser_routes import _require_allowed_origin
from english_for_developers.api.dependencies import (
    get_db,
    get_now,
    get_settings,
    get_telegram_verifier,
)
from english_for_developers.api.errors import ApiError
from english_for_developers.api.schemas import (
    AccountContext,
    EmptyBody,
    LoginRequest,
    RegistrationRequest,
    TelegramNonceResponse,
    TelegramSignInRequest,
)
from english_for_developers.settings import Settings

router = APIRouter(prefix="/api/v1/auth")


def _require_telegram_login(
    origin: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Settings:
    _require_allowed_origin(origin, settings.expected_origin)
    if settings.telegram_client_id == "":
        raise ApiError(404, "telegram_disabled", "Telegram login is disabled")
    return settings


@router.post("/telegram/nonce", response_model=TelegramNonceResponse)
def create_telegram_nonce(
    body: EmptyBody,
    request: Request,
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    settings: Settings = Depends(_require_telegram_login),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> TelegramNonceResponse:
    nonce = issue_telegram_nonce(
        db, request.cookies.get(settings.session_cookie_name), csrf_token, now
    )
    return TelegramNonceResponse(nonce=nonce, client_id=settings.telegram_client_id)


def _verify_telegram_sign_in(
    body: TelegramSignInRequest,
    origin: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),  # noqa: B008
    verifier: TelegramTokenVerifier | None = Depends(get_telegram_verifier),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
) -> tuple[TelegramClaims, UUID | None]:
    _require_allowed_origin(origin, settings.expected_origin)
    if verifier is None:
        raise ApiError(404, "telegram_disabled", "Telegram login is disabled")
    try:
        claims = verifier.verify(body.id_token, now)
    except TelegramTokenInvalid:
        raise ApiError(401, "invalid_telegram_token", "Telegram token is invalid") from None
    except TelegramUnavailable:
        raise ApiError(
            503, "telegram_unavailable", "Telegram signing keys are unavailable"
        ) from None
    return claims, body.run_id


@router.post("/telegram", response_model=AccountContext)
def log_in_with_telegram(
    request: Request,
    response: Response,
    verified: tuple[TelegramClaims, UUID | None] = Depends(_verify_telegram_sign_in),  # noqa: B008
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AccountContext:
    claims, run_id = verified
    context, token = telegram_sign_in(
        db,
        claims,
        run_id,
        request.cookies.get(settings.session_cookie_name),
        request.cookies.get(settings.auth_cookie_name),
        csrf_token,
        now,
        settings.session_ttl_days,
    )
    options = session_cookie_options(settings)
    options["key"] = settings.auth_cookie_name
    response.set_cookie(value=token, **options)  # The transaction has committed.
    response.headers["Cache-Control"] = "no-store"
    return context


@router.post("/logout", status_code=204)
def log_out(
    body: EmptyBody,
    request: Request,
    origin: str | None = Header(default=None),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> Response:
    _require_allowed_origin(origin, settings.expected_origin)
    logout(db, request.cookies.get(settings.auth_cookie_name), csrf_token, now)
    options = session_cookie_options(settings)
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path=options["path"],
        secure=options["secure"],
        httponly=options["httponly"],
        samesite=options["samesite"],
    )  # The transaction has committed.
    return response


@router.post("/login", response_model=AccountContext)
def log_in(
    body: LoginRequest,
    request: Request,
    response: Response,
    origin: str | None = Header(default=None),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AccountContext:
    _require_allowed_origin(origin, settings.expected_origin)
    context, token = login(
        db,
        body.username,
        body.password,
        request.cookies.get(settings.session_cookie_name),
        request.cookies.get(settings.auth_cookie_name),
        csrf_token,
        now,
        settings.session_ttl_days,
    )
    options = session_cookie_options(settings)
    options["key"] = settings.auth_cookie_name
    response.set_cookie(value=token, **options)  # The transaction has committed.
    response.headers["Cache-Control"] = "no-store"
    return context


@router.post("/register", response_model=AccountContext, status_code=201)
def create_account(
    body: RegistrationRequest,
    request: Request,
    response: Response,
    origin: str | None = Header(default=None),
    csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    db: Session = Depends(get_db),  # noqa: B008
    now: datetime = Depends(get_now),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> AccountContext:
    _require_allowed_origin(origin, settings.expected_origin)
    context, token = register(
        db,
        body.username,
        body.password,
        body.run_id,
        request.cookies.get(settings.session_cookie_name),
        request.cookies.get(settings.auth_cookie_name),
        csrf_token,
        now,
        settings.session_ttl_days,
    )
    options = session_cookie_options(settings)
    options["key"] = settings.auth_cookie_name
    response.set_cookie(value=token, **options)  # The transaction has committed.
    response.headers["Cache-Control"] = "no-store"
    return context
