"""FastAPI application factory for the English onboarding service."""

from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError

from english_for_developers.api.auth_routes import router as auth_router
from english_for_developers.api.browser_routes import router as browser_router
from english_for_developers.api.errors import ApiError

MAX_JSON_BODY_BYTES = 16 * 1024


def _requires_no_store(request: Request) -> bool:
    return (
        request.method == "PUT"
        and request.url.path.startswith("/api/v1/onboarding/")
        and request.url.path.endswith("/selection")
    ) or request.url.path in {"/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/logout"}


def create_app() -> FastAPI:
    """Create the HTTP application with its route dependencies."""
    app = FastAPI(title="English for Developers")

    @app.middleware("http")
    async def limit_json_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        disable_caching = _requires_no_store(request)
        content_type = request.headers.get("content-type", "")
        if request.method in {"POST", "PUT", "PATCH"} and content_type.startswith(
            "application/json"
        ):
            body = await request.body()
            if len(body) > MAX_JSON_BODY_BYTES:
                error_response = JSONResponse(
                    status_code=413,
                    content={
                        "code": "request_too_large",
                        "message": "Request body is too large",
                        "request_id": request_id,
                    },
                )
                error_response.headers["X-Request-ID"] = request_id
                if disable_caching:
                    error_response.headers["Cache-Control"] = "no-store"
                return error_response
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if disable_caching:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(DBAPIError)
    async def handle_database_error(request: Request, _exc: DBAPIError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "code": "database_unavailable",
                "message": "Database is unavailable",
                "request_id": request.state.request_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Request validation failed",
                "request_id": request.state.request_id,
                "fields": safe_errors,
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, _exc: Exception) -> JSONResponse:
        request_id = request.state.request_id
        response = JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Internal server error",
                "request_id": request_id,
            },
        )
        response.headers["X-Request-ID"] = request_id
        if _requires_no_store(request):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(auth_router)
    app.include_router(browser_router)
    return app
