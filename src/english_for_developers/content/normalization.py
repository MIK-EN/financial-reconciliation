"""surface-v1: ASCII English surface forms with internal apostrophes."""

import re

_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
_PUNCTUATION = frozenset(" \t\r\n.,;:!?-—–()\"“”‘’'")


def normalize_word(value: str) -> str:
    if not _WORD.fullmatch(value):
        raise ValueError("Expected one supported English word")
    return value.replace("’", "'").lower()


def split_text(value: str) -> tuple[tuple[str, str | None], ...]:
    """Preserve display exactly; fail rather than count parts of code or identifiers."""
    if re.search(r"[A-Za-z]\s*\(", value):
        raise ValueError("Function calls must be explicitly excluded")
    if re.search(r"[A-Za-z]\.[A-Za-z]", value):
        raise ValueError("Domain-like fragments must be explicitly excluded")
    parts: list[tuple[str, str | None]] = []
    position = 0
    for match in _WORD.finditer(value):
        gap = value[position : match.start()]
        if not set(gap) <= _PUNCTUATION:
            raise ValueError("Unsupported fragment must be explicitly excluded")
        if gap:
            parts.append((gap, None))
        word = match.group()
        parts.append((word, normalize_word(word)))
        position = match.end()
    gap = value[position:]
    if not set(gap) <= _PUNCTUATION:
        raise ValueError("Unsupported fragment must be explicitly excluded")
    if gap:
        parts.append((gap, None))
    return tuple(parts)
