"""Tests for datatools.validate."""

import pytest

from datatools.validate import is_email, is_url, check_schema


class TestIsEmail:
    def test_valid(self):
        assert is_email("user@example.com") is True

    def test_with_dots_and_plus(self):
        assert is_email("first.last+tag@sub.example.co.uk") is True

    def test_missing_at(self):
        assert is_email("userexample.com") is False

    def test_double_at(self):
        assert is_email("user@@example.com") is False

    def test_empty(self):
        assert is_email("") is False

    def test_no_domain(self):
        assert is_email("user@") is False


class TestIsUrl:
    def test_https(self):
        assert is_url("https://example.com") is True

    def test_http_with_port(self):
        assert is_url("http://localhost:8080/api") is True

    def test_with_path(self):
        assert is_url("https://example.com/path/to/resource") is True

    def test_ftp_rejected(self):
        assert is_url("ftp://files.example.com") is False

    def test_no_scheme(self):
        assert is_url("example.com") is False

    def test_empty(self):
        assert is_url("") is False


class TestCheckSchema:
    def test_valid_data(self):
        schema = {"name": str, "age": int}
        assert check_schema({"name": "Alice", "age": 30}, schema) == []

    def test_missing_field(self):
        schema = {"name": str, "age": int}
        errors = check_schema({"name": "Alice"}, schema)
        assert errors == ["missing field: age"]

    def test_wrong_type(self):
        schema = {"name": str}
        errors = check_schema({"name": 123}, schema)
        assert len(errors) == 1
        assert "expected" in errors[0]

    def test_multiple_errors(self):
        schema = {"a": int, "b": str, "c": float}
        errors = check_schema({}, schema)
        assert len(errors) == 3

    def test_extra_fields_ignored(self):
        schema = {"name": str}
        assert check_schema({"name": "ok", "extra": 42}, schema) == []

    def test_tuple_of_types(self):
        schema = {"value": (int, float)}
        assert check_schema({"value": 3.14}, schema) == []
        assert check_schema({"value": 7}, schema) == []
