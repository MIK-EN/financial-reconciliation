"""Strict publication boundary for the supported content/policy versions."""

import hashlib
import json
import re
from typing import cast

from english_for_developers.content.normalization import normalize_word, split_text
from english_for_developers.content.schema import (
    ContentBundle,
    DisplaySegment,
    Explanation,
    Recommendation,
    TextDefinition,
    WordDefinition,
)
from english_for_developers.onboarding.types import ROUTING_V1, Level, Route, TextId, Transition

_TEXT_IDS = frozenset(route.text_id for route in ROUTING_V1)
_LEVELS = frozenset(("foundations", "basic_docs", "confident_reading", "complex_texts"))
_REASONS = frozenset(
    t.reason_code
    for route in ROUTING_V1
    for t in (route.accessible, route.difficult)
    if t.reason_code is not None
)


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("Invalid object fields")
    return cast(dict[str, object], value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected an array")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected a non-empty string")
    return value


def _text_id(value: object) -> TextId:
    text_id = _string(value)
    if text_id not in _TEXT_IDS:
        raise ValueError("Unknown text_id")
    return text_id


def _level(value: object) -> Level:
    level = _string(value)
    if level not in _LEVELS:
        raise ValueError("Unknown level")
    return cast(Level, level)


def _text(value: object) -> TextDefinition:
    raw = _object(value, {"id", "segments", "words"})
    words: list[WordDefinition] = []
    word_lookup: dict[str, str] = {}
    ids: set[str] = set()
    for value in _list(raw["words"]):
        word = _object(value, {"id", "normalized"})
        word_id, normalized = _string(word["id"]), _string(word["normalized"])
        if normalize_word(normalized) != normalized:
            raise ValueError("Word must already be normalized")
        if word_id in ids or normalized in word_lookup:
            raise ValueError("Duplicate word_id or normalized word")
        ids.add(word_id)
        word_lookup[normalized] = word_id
        words.append(WordDefinition(word_id, normalized))
    segments: list[DisplaySegment] = []
    used: set[str] = set()
    for value in _list(raw["segments"]):
        segment = _object(value, {"kind", "value"})
        source = segment["value"]
        if not isinstance(source, str) or not source:
            raise ValueError("Expected non-empty source segment")
        if segment["kind"] == "excluded":
            segments.append(DisplaySegment(source, None))
        elif segment["kind"] == "text":
            for display, normalized_token in split_text(source):
                if normalized_token is None:
                    segments.append(DisplaySegment(display, None))
                else:
                    if normalized_token not in word_lookup:
                        raise ValueError("Missing word definition")
                    used.add(normalized_token)
                    segments.append(DisplaySegment(display, word_lookup[normalized_token]))
        else:
            raise ValueError("Unsupported segment kind")
    if not used or used != set(word_lookup):
        raise ValueError("Text has no countable words or unused word definitions")
    return TextDefinition(_text_id(raw["id"]), tuple(words), tuple(segments))


def _transition(value: object) -> Transition:
    if isinstance(value, dict) and "next_text_id" in value:
        raw = _object(value, {"next_text_id"})
        return Transition(next_text_id=_text_id(raw["next_text_id"]))
    raw = _object(value, {"level", "reason_code"})
    reason = _string(raw["reason_code"])
    if reason not in _REASONS:
        raise ValueError("Unknown reason_code")
    return Transition(level=_level(raw["level"]), reason_code=reason)


def _validate_routes(routes: tuple[Route, ...]) -> None:
    by_id = {route.text_id: route for route in routes}
    if len(by_id) != len(routes) or set(by_id) != _TEXT_IDS:
        raise ValueError("Missing or repeated route")
    seen: set[TextId] = set()
    reached_levels: set[Level] = set()
    reached_reasons: set[str] = set()

    def visit(text_id: TextId, path: tuple[TextId, ...]) -> None:
        if text_id in path or len(path) >= 4:
            raise ValueError("Cyclic or excessively long route")
        seen.add(text_id)
        path = (*path, text_id)
        route = by_id[text_id]
        for transition in (route.accessible, route.difficult):
            if transition.next_text_id is not None:
                visit(transition.next_text_id, path)
            else:
                if len(path) < 2 or transition.level is None or transition.reason_code is None:
                    raise ValueError("Invalid terminal route")
                reached_levels.add(transition.level)
                reached_reasons.add(transition.reason_code)

    visit("start", ())
    if seen != _TEXT_IDS or reached_levels != _LEVELS or reached_reasons != _REASONS:
        raise ValueError("Unreachable content or result")
    if by_id != {route.text_id: route for route in ROUTING_V1}:
        raise ValueError("Routes do not match routing-v1")


def validate_bundle(raw: object) -> ContentBundle:
    root = _object(
        raw,
        {
            "bundle_version",
            "normalization_version",
            "policy_version",
            "texts",
            "routes",
            "recommendations",
            "explanations",
        },
    )
    version = _string(root["bundle_version"])
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", version):
        raise ValueError("Invalid bundle version")
    if root["normalization_version"] != "surface-v1" or root["policy_version"] != "routing-v1":
        raise ValueError("Unsupported normalization or routing version")
    texts = tuple(_text(value) for value in _list(root["texts"]))
    if len(texts) != len(_TEXT_IDS) or {text.id for text in texts} != _TEXT_IDS:
        raise ValueError("Missing or repeated text")
    routes_list = []
    for value in _list(root["routes"]):
        route = _object(value, {"text_id", "accessible", "difficult"})
        routes_list.append(
            Route(
                _text_id(route["text_id"]),
                _transition(route["accessible"]),
                _transition(route["difficult"]),
            )
        )
    routes = tuple(routes_list)
    _validate_routes(routes)
    recommendations = []
    for value in _list(root["recommendations"]):
        recommendation = _object(value, {"id", "title", "description"})
        recommendations.append(
            Recommendation(
                _level(recommendation["id"]),
                _string(recommendation["title"]),
                _string(recommendation["description"]),
            )
        )
    if len(recommendations) != 4 or {r.id for r in recommendations} != _LEVELS:
        raise ValueError("Missing or repeated recommendation")
    explanations = []
    for value in _list(root["explanations"]):
        explanation = _object(value, {"reason_code", "text"})
        explanations.append(
            Explanation(_string(explanation["reason_code"]), _string(explanation["text"]))
        )
    if len(explanations) != len(_REASONS) or {e.reason_code for e in explanations} != _REASONS:
        raise ValueError("Missing or repeated explanation")
    canonical_json = json.dumps(
        raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return ContentBundle(
        version,
        "surface-v1",
        "routing-v1",
        hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
        canonical_json,
        texts,
        routes,
        tuple(recommendations),
        tuple(explanations),
    )
