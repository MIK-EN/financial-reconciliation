"""Username validation and Argon2 password hashing."""

import re

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

_PASSWORD_HASH = PasswordHash.recommended()


def normalize_username(value: str) -> str:
    username = value.strip().lower()
    if re.fullmatch(r"[a-z0-9_]{3,32}", username) is None:
        raise ValueError("username must contain 3–32 ASCII letters, digits or underscores")
    return username


def hash_password(password: str) -> str:
    if not 15 <= len(password) <= 128:
        raise ValueError("password must contain 15–128 characters")
    return _PASSWORD_HASH.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash.isascii():
        return False
    try:
        return _PASSWORD_HASH.verify(password, password_hash)
    except UnknownHashError:
        return False
