"""FastAPI application factory for the English onboarding service."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from english_for_developers.api.browser_routes import router as browser_router


def create_app() -> FastAPI:
    """Create the HTTP application with its route dependencies."""
    app = FastAPI(title="English for Developers")

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
