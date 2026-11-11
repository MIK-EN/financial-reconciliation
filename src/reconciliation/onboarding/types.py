"""Immutable values shared by content validation and onboarding rules."""

from dataclasses import dataclass
from typing import Literal

TextId = Literal["start", "simplified", "installation", "parameters", "constraints"]
Level = Literal["foundations", "basic_docs", "confident_reading", "complex_texts"]
AnswerMode = Literal["all_known", "unknown_words"]


@dataclass(frozen=True)
class Transition:
    next_text_id: TextId | None = None
    level: Level | None = None
    reason_code: str | None = None


@dataclass(frozen=True)
class Route:
    text_id: TextId
    accessible: Transition
    difficult: Transition


@dataclass(frozen=True)
class AnswerEvaluation:
    mode: AnswerMode
    word_ids: tuple[str, ...]
    unknown_count: int
    total_count: int
    accessible: bool


ROUTING_V1: tuple[Route, ...] = (
    Route("start", Transition(next_text_id="installation"), Transition(next_text_id="simplified")),
    Route(
        "simplified",
        Transition(level="foundations", reason_code="simplified_accessible"),
        Transition(level="foundations", reason_code="simplified_difficult"),
    ),
    Route(
        "installation",
        Transition(next_text_id="parameters"),
        Transition(level="foundations", reason_code="start_accessible"),
    ),
    Route(
        "parameters",
        Transition(next_text_id="constraints"),
        Transition(level="basic_docs", reason_code="installation_accessible"),
    ),
    Route(
        "constraints",
        Transition(level="complex_texts", reason_code="constraints_accessible"),
        Transition(level="confident_reading", reason_code="parameters_accessible"),
    ),
)
