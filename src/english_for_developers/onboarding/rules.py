"""Pure answer evaluation; HTTP and persistence are deliberately outside this module."""

from english_for_developers.content.schema import TextDefinition
from english_for_developers.onboarding.types import (
    ROUTING_V1,
    AnswerEvaluation,
    AnswerMode,
    Route,
    TextId,
    Transition,
)


def evaluate_answer(
    text: TextDefinition,
    mode: AnswerMode,
    word_ids: list[str],
    threshold_percent: int,
) -> AnswerEvaluation:
    if type(threshold_percent) is not int or not 0 <= threshold_percent <= 100:
        raise ValueError("Threshold must be an integer from 0 to 100")
    total = len(text.words)
    if total == 0:
        raise ValueError("Text must have countable words")
    if mode not in ("all_known", "unknown_words"):
        raise ValueError("Unknown answer mode")
    if (mode == "all_known" and word_ids) or (mode == "unknown_words" and not word_ids):
        raise ValueError("Mode and word_ids disagree")
    known_ids = {word.id for word in text.words}
    # Reject duplicates BEFORE converting to a canonical set/order.
    if len(word_ids) > total or len(set(word_ids)) != len(word_ids):
        raise ValueError("Repeated or excessive word_ids")
    if not set(word_ids) <= known_ids:
        raise ValueError("Unknown word_id")
    unknown = len(word_ids)
    return AnswerEvaluation(
        mode, tuple(sorted(word_ids)), unknown, total, 100 * unknown <= threshold_percent * total
    )


def next_transition(
    text_id: TextId,
    accessible: bool,
    *,
    policy: tuple[Route, ...] = ROUTING_V1,
) -> Transition:
    for route in policy:
        if route.text_id == text_id:
            return route.accessible if accessible else route.difficult
    raise ValueError("Unknown text_id")
