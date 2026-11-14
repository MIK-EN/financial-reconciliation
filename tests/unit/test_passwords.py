import pytest

from english_for_developers.accounts.passwords import (
    hash_password,
    normalize_username,
    verify_password,
)


@pytest.mark.parametrize("username", ["abc", "a" * 32, "dev_123"])
def test_username_accepts_ascii_characters_and_length_boundaries(username: str) -> None:
    assert normalize_username(username) == username


def test_username_strips_outer_whitespace_and_lowercases() -> None:
    assert normalize_username(" \tDev_123\n") == "dev_123"


@pytest.mark.parametrize(
    "username", ["", "ab", "a" * 33, "a b", "développeur", "разработчик", "dev-name"]
)
def test_username_rejects_invalid_length_or_characters(username: str) -> None:
    with pytest.raises(ValueError):
        normalize_username(username)


@pytest.mark.parametrize("password", ["a" * 14, "a" * 129])
def test_hash_password_rejects_invalid_length(password: str) -> None:
    with pytest.raises(ValueError):
        hash_password(password)


@pytest.mark.parametrize("password", ["a" * 15, "a" * 128])
def test_password_length_boundaries_hash_and_verify(password: str) -> None:
    password_hash = hash_password(password)

    assert password_hash.startswith("$argon2id$")
    assert password_hash != password
    assert verify_password(password, password_hash) is True
    assert verify_password("a different password", password_hash) is False


@pytest.mark.parametrize(
    ("password", "changed_password"),
    [
        ("  Mixed Case Password  ", "Mixed Case Password"),
        ("Mixed Case Password", "mixed case password"),
        ("пароль разработчика", "пароль разработчикa"),
        ("a" * 14 + "é", "a" * 14 + "e\u0301"),
    ],
)
def test_password_preserves_spaces_case_and_unicode(password: str, changed_password: str) -> None:
    password_hash = hash_password(password)

    assert verify_password(password, password_hash) is True
    assert verify_password(changed_password, password_hash) is False


@pytest.mark.parametrize(
    "password_hash",
    [
        "",
        "not a password hash",
        "$2b$12$unsupportedbcrypt",
        "$argon2id$broken",
        "$argon2id$v=19$m=invalid,t=3,p=4$c2FsdA$aGFzaA",
        "$argon2id$v=999$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaA",
    ],
)
def test_verify_password_rejects_malformed_or_incompatible_hash(password_hash: str) -> None:
    assert verify_password("a valid password", password_hash) is False


@pytest.mark.parametrize(
    "password_hash",
    [
        "$argon2id$v=19$m=65536,t=3,p=4$éééééééé$aGFzaA",
        "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$éééééééé",
        "$argon2id$v=19$m=６５５３６,t=3,p=4$c2FsdHNhbHQ$aGFzaA",
    ],
    ids=["unicode-salt", "unicode-digest", "unicode-parameter"],
)
def test_verify_password_rejects_non_ascii_stored_hash(password_hash: str) -> None:
    assert verify_password("a valid password", password_hash) is False
