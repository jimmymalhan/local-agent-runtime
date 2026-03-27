#!/usr/bin/env python3
"""
input_validator.py — Comprehensive Input Validation & Sanitization
==================================================================
Schema validation, type checking, SQL injection prevention, XSS protection.
Used at system boundaries before data enters the pipeline.
"""
import re
import html
import json
import unicodedata
from typing import Any, Dict, List, Optional, Union, Callable


# ---------------------------------------------------------------------------
# SQL Injection Prevention
# ---------------------------------------------------------------------------

# Patterns that indicate SQL injection attempts
SQL_INJECTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|EXEC|EXECUTE|UNION)\b\s)", re.IGNORECASE),
    re.compile(r"(--|#|/\*|\*/)", re.IGNORECASE),
    re.compile(r"(\b(OR|AND)\b\s+\d+\s*=\s*\d+)", re.IGNORECASE),
    re.compile(r"(\b(OR|AND)\b\s+['\"]?\w+['\"]?\s*=\s*['\"]?\w+['\"]?)", re.IGNORECASE),
    re.compile(r"(;\s*(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE))", re.IGNORECASE),
    re.compile(r"(CHAR\s*\(\s*\d+\s*\))", re.IGNORECASE),
    re.compile(r"(0x[0-9a-fA-F]+)"),
    re.compile(r"(\bSLEEP\s*\()", re.IGNORECASE),
    re.compile(r"(\bBENCHMARK\s*\()", re.IGNORECASE),
    re.compile(r"(\bWAITFOR\b)", re.IGNORECASE),
    re.compile(r"(\bLOAD_FILE\s*\()", re.IGNORECASE),
    re.compile(r"(\bINTO\s+(OUT|DUMP)FILE\b)", re.IGNORECASE),
    re.compile(r"(\bINFORMATION_SCHEMA\b)", re.IGNORECASE),
    re.compile(r"('\s*(OR|AND)\s+')", re.IGNORECASE),
]

# ---------------------------------------------------------------------------
# XSS Prevention
# ---------------------------------------------------------------------------

XSS_PATTERNS: List[re.Pattern] = [
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"<\s*/\s*script", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"vbscript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),  # onclick=, onerror=, etc.
    re.compile(r"<\s*iframe", re.IGNORECASE),
    re.compile(r"<\s*object", re.IGNORECASE),
    re.compile(r"<\s*embed", re.IGNORECASE),
    re.compile(r"<\s*img\b[^>]*\bon\w+\s*=", re.IGNORECASE),
    re.compile(r"<\s*svg\b[^>]*\bon\w+\s*=", re.IGNORECASE),
    re.compile(r"expression\s*\(", re.IGNORECASE),
    re.compile(r"url\s*\(\s*['\"]?\s*javascript:", re.IGNORECASE),
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
    re.compile(r"<\s*meta\b[^>]*\bhttp-equiv", re.IGNORECASE),
    re.compile(r"<\s*link\b[^>]*\brel\s*=\s*['\"]?import", re.IGNORECASE),
]

# Characters that should never appear in typical text input
DANGEROUS_CHARS = set("\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f"
                      "\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f")


# ---------------------------------------------------------------------------
# Validation Result
# ---------------------------------------------------------------------------

class ValidationResult:
    """Immutable result of a validation check."""

    __slots__ = ("valid", "value", "errors")

    def __init__(self, valid: bool, value: Any = None, errors: Optional[List[str]] = None):
        object.__setattr__(self, "valid", valid)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "errors", errors or [])

    def __setattr__(self, _name: str, _value: Any):
        raise AttributeError("ValidationResult is immutable")

    def __repr__(self):
        return f"ValidationResult(valid={self.valid}, errors={self.errors})"


# ---------------------------------------------------------------------------
# Core Sanitizers
# ---------------------------------------------------------------------------

def strip_null_bytes(text: str) -> str:
    """Remove null bytes and control characters."""
    return "".join(ch for ch in text if ch not in DANGEROUS_CHARS)


def normalize_unicode(text: str) -> str:
    """Normalize unicode to NFC form to prevent homoglyph attacks."""
    return unicodedata.normalize("NFC", text)


def sanitize_for_sql(text: str) -> str:
    """Escape characters dangerous in SQL contexts."""
    replacements = {
        "'": "''",
        "\\": "\\\\",
        "\x00": "",
        "\n": "\\n",
        "\r": "\\r",
        "\x1a": "\\Z",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def sanitize_for_html(text: str) -> str:
    """HTML-escape to prevent XSS in rendered output."""
    return html.escape(text, quote=True)


def sanitize_string(text: str) -> str:
    """Full sanitization pipeline for untrusted string input."""
    text = strip_null_bytes(text)
    text = normalize_unicode(text)
    text = text.strip()
    return text


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------

def detect_sql_injection(text: str) -> List[str]:
    """Return list of SQL injection patterns found in text."""
    findings = []
    for pattern in SQL_INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(f"SQL injection pattern: {match.group()!r}")
    return findings


def detect_xss(text: str) -> List[str]:
    """Return list of XSS patterns found in text."""
    findings = []
    for pattern in XSS_PATTERNS:
        match = pattern.search(text)
        if match:
            findings.append(f"XSS pattern: {match.group()!r}")
    return findings


# ---------------------------------------------------------------------------
# Type Checking & Schema Validation
# ---------------------------------------------------------------------------

TYPE_MAP = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "number": (int, float),
    "bool": bool,
    "boolean": bool,
    "list": list,
    "array": list,
    "dict": dict,
    "object": dict,
    "none": type(None),
    "null": type(None),
}


def check_type(value: Any, expected: str) -> bool:
    """Check if value matches the expected type string."""
    py_type = TYPE_MAP.get(expected.lower())
    if py_type is None:
        return False
    return isinstance(value, py_type)


def validate_schema(data: Any, schema: Dict[str, Any]) -> ValidationResult:
    """
    Validate data against a schema definition.

    Schema format:
    {
        "type": "object",
        "required": ["field1", "field2"],
        "properties": {
            "field1": {"type": "string", "min_length": 1, "max_length": 200},
            "field2": {"type": "integer", "min": 0, "max": 100},
            "field3": {"type": "array", "items": {"type": "string"}, "max_items": 50},
            "field4": {"type": "string", "pattern": "^[a-z]+$"},
            "field5": {"type": "string", "enum": ["a", "b", "c"]},
        }
    }
    """
    errors: List[str] = []

    # Top-level type check
    schema_type = schema.get("type", "object")
    if not check_type(data, schema_type):
        errors.append(f"Expected type '{schema_type}', got '{type(data).__name__}'")
        return ValidationResult(False, data, errors)

    # For non-object types, do value-level checks
    if schema_type in ("string", "str"):
        errors.extend(_validate_string_field("value", data, schema))
        sanitized = sanitize_string(data) if not errors else data
        return ValidationResult(len(errors) == 0, sanitized, errors)

    if schema_type in ("integer", "int", "float", "number"):
        errors.extend(_validate_number_field("value", data, schema))
        return ValidationResult(len(errors) == 0, data, errors)

    if schema_type in ("array", "list"):
        errors.extend(_validate_array_field("value", data, schema))
        return ValidationResult(len(errors) == 0, data, errors)

    # Object validation
    if schema_type in ("object", "dict"):
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        # Check required fields
        if isinstance(data, dict):
            for field_name in required:
                if field_name not in data:
                    errors.append(f"Missing required field: '{field_name}'")

            # Validate each property
            sanitized_data = {}
            for field_name, field_schema in properties.items():
                if field_name not in data:
                    if "default" in field_schema:
                        sanitized_data[field_name] = field_schema["default"]
                    continue

                field_value = data[field_name]
                field_type = field_schema.get("type", "string")

                # Type check
                if not check_type(field_value, field_type):
                    errors.append(f"Field '{field_name}': expected type '{field_type}', got '{type(field_value).__name__}'")
                    sanitized_data[field_name] = field_value
                    continue

                # String-specific validation
                if field_type in ("string", "str") and isinstance(field_value, str):
                    field_errors = _validate_string_field(field_name, field_value, field_schema)
                    errors.extend(field_errors)
                    sanitized_data[field_name] = sanitize_string(field_value) if not field_errors else field_value

                # Number-specific validation
                elif field_type in ("integer", "int", "float", "number"):
                    errors.extend(_validate_number_field(field_name, field_value, field_schema))
                    sanitized_data[field_name] = field_value

                # Array-specific validation
                elif field_type in ("array", "list"):
                    errors.extend(_validate_array_field(field_name, field_value, field_schema))
                    sanitized_data[field_name] = field_value

                # Nested object
                elif field_type in ("object", "dict") and isinstance(field_value, dict):
                    nested_result = validate_schema(field_value, field_schema)
                    errors.extend([f"Field '{field_name}'.{e}" for e in nested_result.errors])
                    sanitized_data[field_name] = nested_result.value

                else:
                    sanitized_data[field_name] = field_value

            # Preserve unvalidated fields (pass-through)
            for key in data:
                if key not in sanitized_data:
                    sanitized_data[key] = data[key]

            return ValidationResult(len(errors) == 0, sanitized_data, errors)

    return ValidationResult(len(errors) == 0, data, errors)


def _validate_string_field(name: str, value: str, schema: Dict) -> List[str]:
    """Validate constraints on a string field."""
    errors = []
    min_len = schema.get("min_length")
    max_len = schema.get("max_length")
    pattern = schema.get("pattern")
    enum = schema.get("enum")
    no_sql = schema.get("no_sql_injection", True)
    no_xss = schema.get("no_xss", True)

    if min_len is not None and len(value) < min_len:
        errors.append(f"Field '{name}': length {len(value)} < minimum {min_len}")
    if max_len is not None and len(value) > max_len:
        errors.append(f"Field '{name}': length {len(value)} > maximum {max_len}")
    if pattern is not None and not re.match(pattern, value):
        errors.append(f"Field '{name}': does not match pattern '{pattern}'")
    if enum is not None and value not in enum:
        errors.append(f"Field '{name}': '{value}' not in allowed values {enum}")
    if no_sql:
        sql_findings = detect_sql_injection(value)
        for finding in sql_findings:
            errors.append(f"Field '{name}': {finding}")
    if no_xss:
        xss_findings = detect_xss(value)
        for finding in xss_findings:
            errors.append(f"Field '{name}': {finding}")

    return errors


def _validate_number_field(name: str, value: Union[int, float], schema: Dict) -> List[str]:
    """Validate constraints on a numeric field."""
    errors = []
    min_val = schema.get("min")
    max_val = schema.get("max")

    if min_val is not None and value < min_val:
        errors.append(f"Field '{name}': {value} < minimum {min_val}")
    if max_val is not None and value > max_val:
        errors.append(f"Field '{name}': {value} > maximum {max_val}")

    return errors


def _validate_array_field(name: str, value: list, schema: Dict) -> List[str]:
    """Validate constraints on an array field."""
    errors = []
    min_items = schema.get("min_items")
    max_items = schema.get("max_items")
    items_schema = schema.get("items")

    if min_items is not None and len(value) < min_items:
        errors.append(f"Field '{name}': {len(value)} items < minimum {min_items}")
    if max_items is not None and len(value) > max_items:
        errors.append(f"Field '{name}': {len(value)} items > maximum {max_items}")

    if items_schema:
        item_type = items_schema.get("type", "string")
        for i, item in enumerate(value):
            if not check_type(item, item_type):
                errors.append(f"Field '{name}[{i}]': expected type '{item_type}', got '{type(item).__name__}'")
            elif item_type in ("string", "str") and isinstance(item, str):
                item_errors = _validate_string_field(f"{name}[{i}]", item, items_schema)
                errors.extend(item_errors)

    return errors


# ---------------------------------------------------------------------------
# High-Level Validators for Common Inputs
# ---------------------------------------------------------------------------

# Task input schema
TASK_SCHEMA = {
    "type": "object",
    "required": ["id", "title"],
    "properties": {
        "id": {"type": "string", "pattern": r"^t-[a-f0-9]{8}$", "no_sql_injection": True, "no_xss": True},
        "title": {"type": "string", "min_length": 3, "max_length": 500},
        "description": {"type": "string", "max_length": 5000},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "failed", "blocked"]},
        "priority": {"type": "integer", "min": 0, "max": 10},
        "agent": {"type": "string", "max_length": 100},
        "tags": {"type": "array", "max_items": 20, "items": {"type": "string", "max_length": 50}},
    }
}

# Incident input schema (for diagnosis endpoint)
INCIDENT_SCHEMA = {
    "type": "object",
    "required": ["incident"],
    "properties": {
        "incident": {"type": "string", "min_length": 10, "max_length": 2000},
        "context": {"type": "string", "max_length": 5000},
        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
    }
}

# Agent output schema
AGENT_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["quality_score"],
    "properties": {
        "quality_score": {"type": "number", "min": 0, "max": 100},
        "quality": {"type": "number", "min": 0, "max": 100},
        "model": {"type": "string", "max_length": 100},
        "output": {"type": "string", "max_length": 50000},
        "errors": {"type": "array", "max_items": 100, "items": {"type": "string"}},
    }
}


def validate_task_input(data: Any) -> ValidationResult:
    """Validate task data against task schema."""
    return validate_schema(data, TASK_SCHEMA)


def validate_incident_input(data: Any) -> ValidationResult:
    """Validate incident diagnosis input."""
    return validate_schema(data, INCIDENT_SCHEMA)


def validate_agent_output(data: Any) -> ValidationResult:
    """Validate agent output data."""
    return validate_schema(data, AGENT_OUTPUT_SCHEMA)


def validate_json_string(raw: str, max_size: int = 1_000_000) -> ValidationResult:
    """Validate and parse a JSON string, rejecting oversized or malformed input."""
    errors = []
    if len(raw) > max_size:
        errors.append(f"JSON input too large: {len(raw)} bytes > {max_size} limit")
        return ValidationResult(False, None, errors)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        errors.append(f"Invalid JSON: {exc}")
        return ValidationResult(False, None, errors)

    return ValidationResult(True, data, errors)


# ---------------------------------------------------------------------------
# Path Traversal Prevention
# ---------------------------------------------------------------------------

PATH_TRAVERSAL_PATTERNS = [
    re.compile(r"\.\.[\\/]"),
    re.compile(r"[\\/]\.\."),
    re.compile(r"^~"),
    re.compile(r"%2e%2e", re.IGNORECASE),
    re.compile(r"%252e%252e", re.IGNORECASE),
    re.compile(r"\x00"),
]


def detect_path_traversal(path: str) -> List[str]:
    """Detect path traversal attempts."""
    findings = []
    for pattern in PATH_TRAVERSAL_PATTERNS:
        match = pattern.search(path)
        if match:
            findings.append(f"Path traversal pattern: {match.group()!r}")
    return findings


def validate_file_path(path: str, allowed_dirs: Optional[List[str]] = None) -> ValidationResult:
    """Validate a file path is safe."""
    errors = []
    traversal = detect_path_traversal(path)
    if traversal:
        errors.extend(traversal)
    if allowed_dirs:
        if not any(path.startswith(d) for d in allowed_dirs):
            errors.append(f"Path '{path}' not in allowed directories")
    return ValidationResult(len(errors) == 0, path, errors)


# ---------------------------------------------------------------------------
# __main__ — Assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # -----------------------------------------------------------------------
    # 1. SQL Injection Detection
    # -----------------------------------------------------------------------
    sql_attacks = [
        "'; DROP TABLE users; --",
        "1 OR 1=1",
        "admin' OR '1'='1",
        "1; DELETE FROM tasks",
        "UNION SELECT * FROM information_schema.tables",
        "1; WAITFOR DELAY '0:0:5'",
        "BENCHMARK(10000000,SHA1('test'))",
        "LOAD_FILE('/etc/passwd')",
        "SELECT CHAR(65)",
    ]
    for attack in sql_attacks:
        findings = detect_sql_injection(attack)
        assert len(findings) > 0, f"Failed to detect SQL injection: {attack!r}"

    safe_strings = [
        "Database query takes 45 seconds",
        "The server crashed at 3am",
        "Memory usage is high",
        "Task completed successfully",
    ]
    for safe in safe_strings:
        findings = detect_sql_injection(safe)
        assert len(findings) == 0, f"False positive SQL detection on: {safe!r} -> {findings}"

    print("[PASS] SQL injection detection")

    # -----------------------------------------------------------------------
    # 2. XSS Detection
    # -----------------------------------------------------------------------
    xss_attacks = [
        '<script>alert("xss")</script>',
        '<img src=x onerror=alert(1)>',
        "javascript:alert(1)",
        '<iframe src="evil.com">',
        '<svg onload=alert(1)>',
        '<div onclick=alert(1)>',
        "expression(alert(1))",
        "data:text/html,<script>alert(1)</script>",
        '<object data="evil.swf">',
        '<embed src="evil.swf">',
    ]
    for attack in xss_attacks:
        findings = detect_xss(attack)
        assert len(findings) > 0, f"Failed to detect XSS: {attack!r}"

    safe_html = [
        "The page loaded slowly",
        "User clicked the button",
        "Image failed to load",
        "Timeout after 30 seconds",
    ]
    for safe in safe_html:
        findings = detect_xss(safe)
        assert len(findings) == 0, f"False positive XSS detection on: {safe!r} -> {findings}"

    print("[PASS] XSS detection")

    # -----------------------------------------------------------------------
    # 3. String Sanitization
    # -----------------------------------------------------------------------
    assert strip_null_bytes("hello\x00world") == "helloworld"
    assert strip_null_bytes("clean") == "clean"
    assert strip_null_bytes("\x01\x02\x03abc") == "abc"

    assert sanitize_for_html('<script>alert("x")</script>') == '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;'
    assert sanitize_for_html("safe text") == "safe text"
    assert sanitize_for_html('a="b"&c') == 'a=&quot;b&quot;&amp;c'

    assert sanitize_for_sql("it's a test") == "it''s a test"
    assert sanitize_for_sql("normal") == "normal"

    assert sanitize_string("  hello\x00world  ") == "helloworld"
    print("[PASS] String sanitization")

    # -----------------------------------------------------------------------
    # 4. Type Checking
    # -----------------------------------------------------------------------
    assert check_type("hello", "string") is True
    assert check_type("hello", "str") is True
    assert check_type(42, "integer") is True
    assert check_type(42, "int") is True
    assert check_type(3.14, "float") is True
    assert check_type(42, "number") is True
    assert check_type(3.14, "number") is True
    assert check_type(True, "boolean") is True
    assert check_type(True, "bool") is True
    assert check_type([1, 2], "array") is True
    assert check_type([1, 2], "list") is True
    assert check_type({"a": 1}, "object") is True
    assert check_type({"a": 1}, "dict") is True
    assert check_type(None, "null") is True
    assert check_type(None, "none") is True

    assert check_type(42, "string") is False
    assert check_type("hello", "integer") is False
    assert check_type([], "object") is False
    assert check_type({}, "array") is False
    print("[PASS] Type checking")

    # -----------------------------------------------------------------------
    # 5. Schema Validation — Valid Input
    # -----------------------------------------------------------------------
    valid_task = {
        "id": "t-abcdef01",
        "title": "Fix the login bug",
        "status": "pending",
        "priority": 5,
        "agent": "executor",
        "tags": ["bugfix", "auth"],
    }
    result = validate_task_input(valid_task)
    assert result.valid, f"Valid task rejected: {result.errors}"
    assert result.value["id"] == "t-abcdef01"
    assert result.value["title"] == "Fix the login bug"
    print("[PASS] Schema validation — valid task")

    # -----------------------------------------------------------------------
    # 6. Schema Validation — Missing Required Fields
    # -----------------------------------------------------------------------
    result = validate_task_input({"title": "No ID"})
    assert not result.valid
    assert any("id" in e for e in result.errors)

    result = validate_task_input({"id": "t-00000000"})
    assert not result.valid
    assert any("title" in e for e in result.errors)
    print("[PASS] Schema validation — missing fields")

    # -----------------------------------------------------------------------
    # 7. Schema Validation — Type Mismatch
    # -----------------------------------------------------------------------
    result = validate_task_input({"id": "t-abcdef01", "title": "Ok", "priority": "high"})
    assert not result.valid
    assert any("priority" in e and "type" in e for e in result.errors)
    print("[PASS] Schema validation — type mismatch")

    # -----------------------------------------------------------------------
    # 8. Schema Validation — SQL Injection in Fields
    # -----------------------------------------------------------------------
    result = validate_task_input({
        "id": "t-abcdef01",
        "title": "'; DROP TABLE tasks; --",
    })
    assert not result.valid
    assert any("SQL injection" in e for e in result.errors)
    print("[PASS] Schema validation — SQL injection blocked")

    # -----------------------------------------------------------------------
    # 9. Schema Validation — XSS in Fields
    # -----------------------------------------------------------------------
    result = validate_task_input({
        "id": "t-abcdef01",
        "title": '<script>alert("pwned")</script>',
    })
    assert not result.valid
    assert any("XSS" in e for e in result.errors)
    print("[PASS] Schema validation — XSS blocked")

    # -----------------------------------------------------------------------
    # 10. Schema Validation — String Length Constraints
    # -----------------------------------------------------------------------
    result = validate_task_input({"id": "t-abcdef01", "title": "ab"})
    assert not result.valid
    assert any("min_length" in e or "minimum" in e for e in result.errors)

    result = validate_task_input({"id": "t-abcdef01", "title": "x" * 501})
    assert not result.valid
    assert any("max_length" in e or "maximum" in e for e in result.errors)
    print("[PASS] Schema validation — length constraints")

    # -----------------------------------------------------------------------
    # 11. Schema Validation — Enum Constraints
    # -----------------------------------------------------------------------
    result = validate_task_input({
        "id": "t-abcdef01",
        "title": "Valid title here",
        "status": "unknown_status",
    })
    assert not result.valid
    assert any("not in allowed" in e for e in result.errors)
    print("[PASS] Schema validation — enum constraints")

    # -----------------------------------------------------------------------
    # 12. Schema Validation — Number Range
    # -----------------------------------------------------------------------
    result = validate_task_input({
        "id": "t-abcdef01",
        "title": "Valid title here",
        "priority": 99,
    })
    assert not result.valid
    assert any("maximum" in e for e in result.errors)

    result = validate_task_input({
        "id": "t-abcdef01",
        "title": "Valid title here",
        "priority": -1,
    })
    assert not result.valid
    assert any("minimum" in e for e in result.errors)
    print("[PASS] Schema validation — number range")

    # -----------------------------------------------------------------------
    # 13. Schema Validation — Array Constraints
    # -----------------------------------------------------------------------
    result = validate_task_input({
        "id": "t-abcdef01",
        "title": "Valid title here",
        "tags": ["a" * 51],
    })
    assert not result.valid
    assert any("maximum" in e for e in result.errors)

    result = validate_task_input({
        "id": "t-abcdef01",
        "title": "Valid title here",
        "tags": [123],
    })
    assert not result.valid
    assert any("type" in e for e in result.errors)
    print("[PASS] Schema validation — array constraints")

    # -----------------------------------------------------------------------
    # 14. Schema Validation — Pattern Matching
    # -----------------------------------------------------------------------
    result = validate_task_input({
        "id": "invalid-id-format",
        "title": "Valid title here",
    })
    assert not result.valid
    assert any("pattern" in e for e in result.errors)

    result = validate_task_input({
        "id": "t-abcdef01",
        "title": "Valid title here",
    })
    assert result.valid
    print("[PASS] Schema validation — pattern matching")

    # -----------------------------------------------------------------------
    # 15. Incident Schema Validation
    # -----------------------------------------------------------------------
    result = validate_incident_input({"incident": "Database query takes 45 seconds and times out"})
    assert result.valid, f"Valid incident rejected: {result.errors}"

    result = validate_incident_input({"incident": "short"})
    assert not result.valid
    assert any("minimum" in e for e in result.errors)

    result = validate_incident_input({})
    assert not result.valid
    assert any("incident" in e for e in result.errors)
    print("[PASS] Incident schema validation")

    # -----------------------------------------------------------------------
    # 16. Agent Output Validation
    # -----------------------------------------------------------------------
    result = validate_agent_output({"quality_score": 85.5, "quality": 85.5, "model": "local-v1"})
    assert result.valid, f"Valid agent output rejected: {result.errors}"

    result = validate_agent_output({"quality_score": 150})
    assert not result.valid
    assert any("maximum" in e for e in result.errors)

    result = validate_agent_output({})
    assert not result.valid
    assert any("quality_score" in e for e in result.errors)
    print("[PASS] Agent output validation")

    # -----------------------------------------------------------------------
    # 17. JSON String Validation
    # -----------------------------------------------------------------------
    result = validate_json_string('{"key": "value"}')
    assert result.valid
    assert result.value == {"key": "value"}

    result = validate_json_string("{invalid json}")
    assert not result.valid
    assert any("Invalid JSON" in e for e in result.errors)

    result = validate_json_string("x" * 2_000_000)
    assert not result.valid
    assert any("too large" in e for e in result.errors)
    print("[PASS] JSON string validation")

    # -----------------------------------------------------------------------
    # 18. Path Traversal Detection
    # -----------------------------------------------------------------------
    traversal_attacks = [
        "../../../etc/passwd",
        "..\\windows\\system32",
        "foo/%2e%2e/bar",
        "~/.ssh/id_rsa",
    ]
    for attack in traversal_attacks:
        findings = detect_path_traversal(attack)
        assert len(findings) > 0, f"Failed to detect path traversal: {attack!r}"

    safe_paths = [
        "reports/output.json",
        "state/agent_stats.json",
        "dashboard/state.json",
    ]
    for safe in safe_paths:
        findings = detect_path_traversal(safe)
        assert len(findings) == 0, f"False positive path traversal on: {safe!r}"
    print("[PASS] Path traversal detection")

    # -----------------------------------------------------------------------
    # 19. File Path Validation with Allowed Dirs
    # -----------------------------------------------------------------------
    result = validate_file_path("reports/out.json", allowed_dirs=["reports/", "state/"])
    assert result.valid

    result = validate_file_path("/etc/passwd", allowed_dirs=["reports/", "state/"])
    assert not result.valid
    assert any("not in allowed" in e for e in result.errors)

    result = validate_file_path("../../etc/passwd")
    assert not result.valid
    assert any("Path traversal" in e for e in result.errors)
    print("[PASS] File path validation")

    # -----------------------------------------------------------------------
    # 20. Nested Object Validation
    # -----------------------------------------------------------------------
    nested_schema = {
        "type": "object",
        "required": ["name", "config"],
        "properties": {
            "name": {"type": "string", "min_length": 1, "max_length": 100},
            "config": {
                "type": "object",
                "required": ["timeout"],
                "properties": {
                    "timeout": {"type": "integer", "min": 1, "max": 300},
                    "retries": {"type": "integer", "min": 0, "max": 10},
                }
            }
        }
    }

    result = validate_schema({"name": "test", "config": {"timeout": 30, "retries": 3}}, nested_schema)
    assert result.valid, f"Valid nested object rejected: {result.errors}"

    result = validate_schema({"name": "test", "config": {"timeout": 999}}, nested_schema)
    assert not result.valid
    assert any("maximum" in e for e in result.errors)

    result = validate_schema({"name": "test", "config": {}}, nested_schema)
    assert not result.valid
    assert any("timeout" in e for e in result.errors)
    print("[PASS] Nested object validation")

    # -----------------------------------------------------------------------
    # 21. ValidationResult Immutability
    # -----------------------------------------------------------------------
    vr = ValidationResult(True, "data", [])
    try:
        vr.valid = False
        assert False, "Should have raised AttributeError"
    except AttributeError:
        pass
    print("[PASS] ValidationResult immutability")

    # -----------------------------------------------------------------------
    # 22. Unicode Normalization
    # -----------------------------------------------------------------------
    # NFC normalization combines combining characters
    composed = "\u00e9"         # é (precomposed)
    decomposed = "e\u0301"     # e + combining acute accent
    assert normalize_unicode(decomposed) == composed
    print("[PASS] Unicode normalization")

    # -----------------------------------------------------------------------
    # Done
    # -----------------------------------------------------------------------
    print("\n=== ALL 22 TESTS PASSED ===")
