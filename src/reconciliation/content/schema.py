"""Validated content snapshots; no mutable input objects escape publication."""

from dataclasses import dataclass

from reconciliation.onboarding.types import Level, Route, TextId


@dataclass(frozen=True)
class WordDefinition:
    id: str
    normalized: str


@dataclass(frozen=True)
class DisplaySegment:
    text: str
    word_id: str | None


@dataclass(frozen=True)
class TextDefinition:
    id: TextId
    words: tuple[WordDefinition, ...]
    segments: tuple[DisplaySegment, ...]


@dataclass(frozen=True)
class Recommendation:
    id: Level
    title: str
    description: str


@dataclass(frozen=True)
class Explanation:
    reason_code: str
    text: str


@dataclass(frozen=True)
class ContentBundle:
    bundle_version: str
    normalization_version: str
    policy_version: str
    content_hash: str
    texts: tuple[TextDefinition, ...]
    routes: tuple[Route, ...]
    recommendations: tuple[Recommendation, ...]
    explanations: tuple[Explanation, ...]

    def get_text(self, text_id: str) -> TextDefinition:
        for text in self.texts:
            if text.id == text_id:
                return text
        raise ValueError("Unknown text_id")
