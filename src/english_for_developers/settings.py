"""Runtime settings for the HTTP service."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str = ""
    expected_origin: str = "http://testserver"
    environment: str = "development"
    session_ttl_days: int = 7

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", ""),
            expected_origin=os.environ.get("EXPECTED_ORIGIN", "http://testserver"),
            environment=os.environ.get("APP_ENV", "development"),
        )

    @property
    def session_cookie_name(self) -> str:
        return "__Host-eds_session" if self.environment == "production" else "eds_session_dev"

    @property
    def auth_cookie_name(self) -> str:
        return "__Host-eds_auth" if self.environment == "production" else "eds_auth_dev"
