"""FastAPI application factory for the English onboarding service."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create the HTTP application with its route dependencies."""
    return FastAPI(title="English for Developers")
