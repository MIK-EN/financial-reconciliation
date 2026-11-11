import copy
import json
from dataclasses import FrozenInstanceError

import pytest

from reconciliation.content.validation import validate_bundle

EXPECTED = {
    "simplified": ("Open the file. Read the text. Save your changes.", 8, 9),
    "start": ("You can create a new file, save your work, and open the file again later.", 14, 15),
    "installation": (
        "Before you install the application, check the system requirements. You may "
        "need to update your operating system or free up some disk space.",
        20,
        23,
    ),
    "parameters": (
        "The function returns a list of matching items. If you omit the optional limit "
        "parameter, it returns all available results. An empty list means that no "
        "matches were found.",
        26,
        29,
    ),
    "constraints": (
        "When a request fails, the client retries it automatically unless retries "
        "have been disabled. Repeated requests may cause duplicate operations, so "
        "this behavior should only be enabled when the server can safely handle "
        "them.",
        31,
        34,
    ),
}


def test_exact_v1_texts_and_word_counts(bundle):
    assert bundle.bundle_version == "onboarding-v1"
    assert bundle.normalization_version == "surface-v1"
    assert bundle.policy_version == "routing-v1"
    assert len(bundle.texts) == 5
    assert len(bundle.recommendations) == 4
    for text_id, (expected, unique, occurrences) in EXPECTED.items():
        text = bundle.get_text(text_id)
        assert "".join(s.text for s in text.segments) == expected
        assert len(text.words) == unique
        assert sum(s.word_id is not None for s in text.segments) == occurrences
    start = bundle.get_text("start")
    file_ids = [s.word_id for s in start.segments if s.text.lower() == "file"]
    assert len(file_ids) == 2 and len(set(file_ids)) == 1


def test_canonical_hash_and_immutable_snapshot(raw_bundle):
    bundle = validate_bundle(raw_bundle)
    reordered = json.loads(json.dumps(raw_bundle, sort_keys=True, indent=4))
    assert validate_bundle(reordered).content_hash == bundle.content_hash
    assert len(bundle.content_hash) == 64
    raw_bundle["texts"][0]["segments"][0]["value"] = "Changed."
    assert "".join(s.text for s in bundle.texts[0].segments) != "Changed."
    with pytest.raises(FrozenInstanceError):
        bundle.bundle_version = "changed"


def test_supported_punctuation_and_excluded_fragments(raw_bundle):
    raw_bundle["texts"][0]["segments"] = [
        {"kind": "text", "value": "“File” file; don’t don't. Well-known "},
        {"kind": "excluded", "value": "open_file(x2) https://example.com 123"},
    ]
    raw_bundle["texts"][0]["words"] = [
        {"id": "w1", "normalized": "file"},
        {"id": "w2", "normalized": "don't"},
        {"id": "w3", "normalized": "well"},
        {"id": "w4", "normalized": "known"},
    ]
    text = validate_bundle(raw_bundle).texts[0]
    assert len(text.words) == 4
    assert "".join(s.text for s in text.segments) == (
        "“File” file; don’t don't. Well-known open_file(x2) https://example.com 123"
    )
    assert text.segments[-1].word_id is None
    assert [s.word_id for s in text.segments if s.text.lower() == "file"] == ["w1", "w1"]
    assert [s.word_id for s in text.segments if s.text in ["don’t", "don't"]] == ["w2", "w2"]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "... ",
        "file2",
        "https://example.com",
        "open_file",
        "open()",
        "файл",
        "file 😀",
        "<b>file</b>",
        "`file`",
        "file + text",
    ],
)
def test_unmarked_unsupported_content_rejected(raw_bundle, value):
    raw_bundle["texts"][0]["segments"] = [{"kind": "text", "value": value}]
    with pytest.raises(ValueError):
        validate_bundle(raw_bundle)


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_word_id",
        "duplicate_normalized",
        "missing_word",
        "extra_word",
        "wrong_segment",
        "missing_text",
        "duplicate_text",
        "extra_field",
        "wrong_version",
        "cycle",
        "missing_branch",
        "bad_reason",
        "unknown_level",
        "unreachable_text",
        "invalid_type",
    ],
)
def test_invalid_bundle_rejected(raw_bundle, mutation):
    text = raw_bundle["texts"][0]
    if mutation == "duplicate_word_id":
        text["words"][1]["id"] = text["words"][0]["id"]
    elif mutation == "duplicate_normalized":
        text["words"][1]["normalized"] = text["words"][0]["normalized"]
    elif mutation == "missing_word":
        text["words"].pop()
    elif mutation == "extra_word":
        text["words"].append({"id": "unused", "normalized": "unused"})
    elif mutation == "wrong_segment":
        text["segments"][0]["kind"] = "code"
    elif mutation == "missing_text":
        raw_bundle["texts"].pop()
    elif mutation == "duplicate_text":
        raw_bundle["texts"].append(copy.deepcopy(text))
    elif mutation == "extra_field":
        raw_bundle["future_answers"] = []
    elif mutation == "wrong_version":
        raw_bundle["normalization_version"] = "unknown"
    elif mutation == "cycle":
        raw_bundle["routes"][0]["accessible"] = {"next_text_id": "start"}
    elif mutation == "missing_branch":
        del raw_bundle["routes"][0]["difficult"]
    elif mutation == "bad_reason":
        raw_bundle["routes"][1]["accessible"]["reason_code"] = "missing"
    elif mutation == "unknown_level":
        raw_bundle["routes"][1]["accessible"]["level"] = "missing"
    elif mutation == "unreachable_text":
        raw_bundle["routes"][0]["difficult"] = {"next_text_id": "installation"}
    elif mutation == "invalid_type":
        raw_bundle["texts"] = "not a list"
    with pytest.raises(ValueError):
        validate_bundle(raw_bundle)


def test_content_change_changes_hash(raw_bundle):
    original = validate_bundle(raw_bundle)
    raw_bundle["recommendations"][0]["description"] += " Дополнение."
    assert validate_bundle(raw_bundle).content_hash != original.content_hash


@pytest.mark.parametrize("raw", [None, [], 42, "bundle"])
def test_non_object_bundle_rejected(raw):
    with pytest.raises(ValueError):
        validate_bundle(raw)


def test_reject_unmarked_domain_with_valid_word_map(raw_bundle):
    raw_bundle["texts"][0]["segments"] = [{"kind": "text", "value": "Visit www.example.com"}]
    raw_bundle["texts"][0]["words"] = [
        {"id": f"w{i}", "normalized": word}
        for i, word in enumerate(["visit", "www", "example", "com"])
    ]
    with pytest.raises(ValueError):
        validate_bundle(raw_bundle)


def test_reject_unmarked_function_with_space(raw_bundle):
    raw_bundle["texts"][0]["segments"] = [{"kind": "text", "value": "open ()"}]
    raw_bundle["texts"][0]["words"] = [{"id": "w1", "normalized": "open"}]
    with pytest.raises(ValueError):
        validate_bundle(raw_bundle)


def test_preserve_whitespace_only_author_segments(raw_bundle):
    raw_bundle["texts"][0]["segments"] += [{"kind": "text", "value": " \n"}]
    text = validate_bundle(raw_bundle).texts[0]
    assert "".join(s.text for s in text.segments).endswith(" \n")


@pytest.mark.parametrize(
    "mutation",
    [
        "empty_words",
        "duplicate_level",
        "duplicate_explanation",
        "extra_nested_field",
        "excluded_only",
    ],
)
def test_invalid_publication_details(raw_bundle, mutation):
    if mutation == "empty_words":
        raw_bundle["texts"][0]["words"] = []
    elif mutation == "duplicate_level":
        raw_bundle["recommendations"][1]["id"] = raw_bundle["recommendations"][0]["id"]
    elif mutation == "duplicate_explanation":
        raw_bundle["explanations"][1]["reason_code"] = raw_bundle["explanations"][0]["reason_code"]
    elif mutation == "extra_nested_field":
        raw_bundle["texts"][0]["segments"][0]["unexpected"] = True
    elif mutation == "excluded_only":
        raw_bundle["texts"][0]["segments"] = [{"kind": "excluded", "value": "foo()"}]
        raw_bundle["texts"][0]["words"] = []
    with pytest.raises(ValueError):
        validate_bundle(raw_bundle)
