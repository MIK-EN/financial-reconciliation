import pytest
from sqlalchemy.engine import Engine

from english_for_developers.storage.database import make_session_factory


def test_session_factory_uses_sync_psycopg_and_explicit_session_settings() -> None:
    factory = make_session_factory(
        "postgresql+psycopg://reader:secret@localhost/english_for_developers"
    )
    engine = factory.kw["bind"]
    assert isinstance(engine, Engine)
    assert engine.pool._pre_ping
    assert factory.kw["autoflush"] is False
    assert factory.kw["expire_on_commit"] is False
    engine.dispose()


def test_session_factory_rejects_non_postgresql_drivers() -> None:
    with pytest.raises(ValueError, match="postgresql\\+psycopg"):
        make_session_factory("sqlite+pysqlite:///:memory:")
