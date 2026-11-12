"""Construct a synchronous SQLAlchemy session factory for PostgreSQL."""

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    """Create a factory; callers own each session and its transaction scope."""
    url = make_url(database_url)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("database_url must use the synchronous postgresql+psycopg driver")
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
