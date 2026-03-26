"""Data validation utilities."""

from __future__ import annotations

import re
from typing import Any


_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

_URL_RE = re.compile(
    r"^https?://"
    r"[a-zA-Z0-9.-]+"
    r"(?:\:[0-9]+)?"
    r"(?:/[^\s]*)?$"
)


def is_email(value: str) -> bool:
    """Return True if *value* looks like a valid email address."""
    return bool(_EMAIL_RE.match(value))


def is_url(value: str) -> bool:
    """Return True if *value* looks like a valid HTTP(S) URL."""
    return bool(_URL_RE.match(value))


def check_schema(
    data: dict[str, Any],
    schema: dict[str, type | tuple[type, ...]],
) -> list[str]:
    """Validate *data* against a simple type schema.

    Args:
        data: The dictionary to validate.
        schema: Mapping of field name to expected type(s).

    Returns:
        A list of human-readable error strings (empty means valid).
    """
    errors: list[str] = []
    for field, expected in schema.items():
        if field not in data:
            errors.append(f"missing field: {field}")
        elif not isinstance(data[field], expected):
            errors.append(
                f"field '{field}': expected {expected}, got {type(data[field]).__name__}"
            )
    return errors


if __name__ == "__main__":
    assert is_email("user@example.com") is True
    assert is_email("bad@@example") is False
    assert is_email("") is False

    assert is_url("https://example.com") is True
    assert is_url("http://localhost:8080/path") is True
    assert is_url("ftp://nope") is False
    assert is_url("not-a-url") is False

    schema = {"name": str, "age": int}
    assert check_schema({"name": "Alice", "age": 30}, schema) == []
    assert check_schema({"name": "Alice"}, schema) == ["missing field: age"]
    errs = check_schema({"name": 123, "age": 30}, schema)
    assert len(errs) == 1 and "expected" in errs[0]

    print("validate: all assertions passed")
