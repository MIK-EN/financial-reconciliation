import pytest

from reconciliation.content.normalization import normalize_word


@pytest.mark.parametrize(
    ("value", "expected"), [("File", "file"), ("DON’T", "don't"), ("request", "request")]
)
def test_normalize_surface_form(value, expected):
    assert normalize_word(value) == expected


@pytest.mark.parametrize("value", ["", "two words", "file2", "файл", "-file", "file_", "'file'"])
def test_reject_non_word(value):
    with pytest.raises(ValueError):
        normalize_word(value)


def test_grammatical_forms_remain_distinct():
    assert normalize_word("request") != normalize_word("requests")
