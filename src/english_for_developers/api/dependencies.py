"""FastAPI dependencies for settings and database sessions."""

from collections.abc import Iterator

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from english_for_developers.settings import Settings
from english_for_developers.storage.database import make_session_factory


def get_settings() -> Settings:
    return Settings.from_env()


def get_db(settings: Settings = Depends(get_settings)) -> Iterator[Session]:  # noqa: B008
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database unavailable")
    session_factory = make_session_factory(settings.database_url)
    with session_factory() as session:
        yield session
