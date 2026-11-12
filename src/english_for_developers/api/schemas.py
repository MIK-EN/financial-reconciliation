"""Public DTOs for the browser session API."""

from datetime import datetime
from typing import Literal
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


class SegmentResponse(BaseModel):
    text: str
    word_id: str | None


class ActiveStepResponse(BaseModel):
    id: UUID
    ordinal: int
    text_id: str
    segments: list[SegmentResponse]


class ActiveRunResponse(BaseModel):
    id: UUID
    status: str = "active"
    revision: int
    bundle_version: str
    expires_at: datetime
    step: ActiveStepResponse


class CompletedRunResponse(BaseModel):
    id: UUID
    status: Literal["completed"] = "completed"
    revision: int
    bundle_version: str
    expires_at: datetime
    recommended_level: str
    selected_level: str
    reason_code: str


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    step_id: UUID
    mode: Literal["all_known", "unknown_words"]
    word_ids: list[str]
    content_version: str
