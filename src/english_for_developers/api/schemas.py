"""Public DTOs for the browser session API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from english_for_developers.accounts.passwords import normalize_username


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BrowserSessionResponse(BaseModel):
    session_id: UUID
    session_type: str
    csrf_token: str
    expires_at: datetime


class AccountContext(BaseModel):
    user_id: UUID
    username: str
    csrf_token: str
    current_run_id: UUID | None
    expires_at: datetime


class BrowserContextResponse(BaseModel):
    anonymous_session_id: UUID | None = None
    csrf_token: str | None = None
    saved_run_ids: list[UUID] = []
    anonymous_run_id: UUID | None = None
    account: AccountContext | None = None


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
    explanation: str
    saved_to_account: bool


class SelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    selected_level: Literal["foundations", "basic_docs", "confident_reading", "complex_texts"]
    expected_revision: int


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    step_id: UUID
    mode: Literal["all_known", "unknown_words"]
    word_ids: list[str]
    content_version: str


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    username: str
    password: str = Field(min_length=15, max_length=128, repr=False)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return normalize_username(value)


class RegistrationRequest(LoginRequest):
    run_id: UUID
