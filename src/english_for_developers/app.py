"""FastAPI application factory for the English onboarding service."""

from fastapi import FastAPI

from english_for_developers.api.browser_routes import router as browser_router


def create_app() -> FastAPI:
    """Create the HTTP application with its route dependencies."""
    app = FastAPI(title="English for Developers")
    app.include_router(browser_router)
    return app
