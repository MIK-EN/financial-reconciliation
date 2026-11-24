"""FastAPI dependencies for settings and database sessions."""

from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from english_for_developers.accounts.telegram import TelegramTokenVerifier, make_jwks_resolver
from english_for_developers.settings import Settings
from english_for_developers.storage.database import make_session_factory


def get_settings() -> Settings:
    return Settings.from_env()


def get_now() -> datetime:
    return datetime.now(UTC)


@lru_cache(maxsize=4)
def _telegram_verifier(client_id: str) -> TelegramTokenVerifier:
    return TelegramTokenVerifier(client_id, make_jwks_resolver())


def get_telegram_verifier(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> TelegramTokenVerifier | None:
    if settings.telegram_client_id == "":
        return None
    return _telegram_verifier(settings.telegram_client_id)


def get_db(settings: Settings = Depends(get_settings)) -> Iterator[Session]:  # noqa: B008
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="database unavailable")
    session_factory = make_session_factory(settings.database_url)
    with session_factory() as session:
        yield session
