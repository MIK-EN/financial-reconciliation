"""Versioned, immutable learning content; no browser or database dependencies."""

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]


class Definition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Option(Definition):
    id: Identifier
    text: ShortText
    explanation: ShortText


class Exercise(Definition):
    id: Identifier
    title: ShortText
    level: Literal["A2", "B1"]
    situation: ShortText
    prompt: ShortText
    options: Annotated[tuple[Option, ...], Field(min_length=3, max_length=4)]
    correct_option_id: Identifier

    @model_validator(mode="after")
    def check_options(self) -> Self:
        ids = [option.id for option in self.options]
        if len(set(ids)) != len(ids) or self.correct_option_id not in ids:
            raise ValueError("Options need unique IDs and an existing correct_option_id")
        if len({option.text.casefold() for option in self.options}) != len(ids):
            raise ValueError("Option texts must be distinct")
        return self


class Topic(Definition):
    id: Literal["code-review", "meetings", "messages", "interview"]
    title: ShortText
    description: ShortText
    exercises: Annotated[tuple[Exercise, ...], Field(min_length=3, max_length=3)]


class TrainerContent(Definition):
    schema_version: Literal[1]
    version: Identifier
    topics: Annotated[tuple[Topic, ...], Field(min_length=4, max_length=4)]

    @model_validator(mode="after")
    def check_ids(self) -> Self:
        if len({topic.id for topic in self.topics}) != len(self.topics):
            raise ValueError("Topic IDs must be unique")
        ids = [exercise.id for topic in self.topics for exercise in topic.exercises]
        if len(set(ids)) != len(ids):
            raise ValueError("Exercise IDs must be globally unique")
        return self

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
