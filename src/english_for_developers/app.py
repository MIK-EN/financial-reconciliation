"""FastAPI application factory for the English onboarding service."""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from english_for_developers.api.browser_routes import router as browser_router

MAX_JSON_BODY_BYTES = 16 * 1024


def create_app() -> FastAPI:
    """Create the HTTP application with its route dependencies."""
    app = FastAPI(title="English for Developers")

    @app.middleware("http")
    async def limit_json_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_type = request.headers.get("content-type", "")
        if request.method in {"POST", "PUT", "PATCH"} and content_type.startswith(
            "application/json"
        ):
            body = await request.body()
            if len(body) > MAX_JSON_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "request body too large"})
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": safe_errors})

    app.include_router(browser_router)
    return app
