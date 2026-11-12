"""Public DTOs for the browser session API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BrowserSessionResponse(BaseModel):
    session_id: UUID
    session_type: str
    csrf_token: str
    expires_at: datetime


class BrowserContextResponse(BaseModel):
    anonymous_session_id: UUID | None = None
    csrf_token: str | None = None
    saved_run_ids: list[UUID] = []
