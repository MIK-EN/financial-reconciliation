import pytest

from english_for_developers.content.schema import TextDefinition, WordDefinition
from english_for_developers.onboarding.rules import evaluate_answer, next_transition

COUNTS = {"simplified": 8, "start": 14, "installation": 20, "parameters": 26, "constraints": 31}


@pytest.fixture
def texts():
    """Synthetic texts isolate answer rules from the publication parser and content file."""
    return {
        text_id: TextDefinition(
            text_id,
            tuple(WordDefinition(f"w{i}", f"word{i}") for i in range(1, total + 1)),
            (),
        )
        for text_id, total in COUNTS.items()
    }


@pytest.mark.parametrize(
    ("text_id", "count"), [(text_id, u) for text_id, n in COUNTS.items() for u in range(n + 1)]
)
def test_every_unknown_count(texts, text_id, count):
    text = texts[text_id]
    ids = [word.id for word in text.words][:count]
    result = evaluate_answer(text, "unknown_words" if count else "all_known", ids, 20)
    assert result.unknown_count == count
    assert result.total_count == COUNTS[text_id]
    assert result.accessible is (100 * count <= 20 * COUNTS[text_id])
    assert result.word_ids == tuple(sorted(ids))


@pytest.mark.parametrize(
    ("outcomes", "expected_texts", "level", "reason"),
    [
        ([False, False], ["start", "simplified"], "foundations", "simplified_difficult"),
        ([False, True], ["start", "simplified"], "foundations", "simplified_accessible"),
        ([True, False], ["start", "installation"], "foundations", "start_accessible"),
        (
            [True, True, False],
            ["start", "installation", "parameters"],
            "basic_docs",
            "installation_accessible",
        ),
        (
            [True, True, True, False],
            ["start", "installation", "parameters", "constraints"],
            "confident_reading",
            "parameters_accessible",
        ),
        (
            [True, True, True, True],
            ["start", "installation", "parameters", "constraints"],
            "complex_texts",
            "constraints_accessible",
        ),
    ],
)
def test_six_complete_routes(outcomes, expected_texts, level, reason):
    current = "start"
    seen = []
    for accessible in outcomes:
        seen.append(current)
        transition = next_transition(current, accessible)
        current = transition.next_text_id
    assert seen == expected_texts
    assert current is None
    assert transition.level == level
    assert transition.reason_code == reason
    assert 2 <= len(seen) <= 4


@pytest.mark.parametrize(
    ("mode", "ids"),
    [
        ("all_known", ["w1"]),
        ("unknown_words", []),
        ("other", []),
        ("unknown_words", ["w1", "w1"]),
        ("unknown_words", ["foreign"]),
    ],
)
def test_invalid_answer(texts, mode, ids):
    with pytest.raises(ValueError):
        evaluate_answer(texts["start"], mode, ids, 20)


@pytest.mark.parametrize("threshold", [-1, 101, True, 20.0])
def test_invalid_threshold(texts, threshold):
    with pytest.raises(ValueError):
        evaluate_answer(texts["start"], "all_known", [], threshold)


def test_input_order_is_not_part_of_answer(texts):
    text = texts["start"]
    ids = [word.id for word in text.words][:2]
    assert evaluate_answer(text, "unknown_words", ids, 20) == evaluate_answer(
        text, "unknown_words", list(reversed(ids)), 20
    )


def test_threshold_is_a_parameter(texts):
    text = texts["installation"]
    ids = [word.id for word in text.words][:4]
    assert evaluate_answer(text, "unknown_words", ids, 20).accessible
    assert not evaluate_answer(text, "unknown_words", ids, 19).accessible
    assert evaluate_answer(text, "unknown_words", [w.id for w in text.words], 100).accessible
    assert evaluate_answer(text, "all_known", [], 0).accessible


def test_unknown_text_rejected():
    with pytest.raises(ValueError):
        next_transition("foreign", True)


def test_empty_text_cannot_be_evaluated():
    with pytest.raises(ValueError):
        evaluate_answer(TextDefinition("start", (), ()), "all_known", [], 20)
