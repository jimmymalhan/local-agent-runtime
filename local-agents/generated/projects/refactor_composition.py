"""
Refactor: Replace a 4-level inheritance hierarchy with composition
using Protocol types and dependency injection.

BEFORE (inheritance):
    BaseLogger -> FileLogger -> TimestampedFileLogger -> EncryptedTimestampedFileLogger

AFTER (composition):
    Separate concerns into Protocol-based components:
    - Formatter (adds timestamps, prefixes, etc.)
    - Encryptor (encrypts content)
    - Writer (writes to destination: file, memory, etc.)
    - Logger composes them via dependency injection
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# BEFORE: 4-level inheritance hierarchy
# ---------------------------------------------------------------------------

class BaseLogger:
    """Level 1: basic in-memory log."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    def log(self, message: str) -> None:
        self.entries.append(message)

    def get_entries(self) -> list[str]:
        return list(self.entries)


class FileLogger(BaseLogger):
    """Level 2: writes to a 'file' (simulated with a list)."""

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path = file_path
        self.file_contents: list[str] = []

    def log(self, message: str) -> None:
        super().log(message)
        self.file_contents.append(f"[{self.file_path}] {message}")


class TimestampedFileLogger(FileLogger):
    """Level 3: prepends a timestamp to every message."""

    def __init__(self, file_path: str, clock: callable | None = None) -> None:
        super().__init__(file_path)
        self._clock = clock or datetime.utcnow

    def log(self, message: str) -> None:
        ts = self._clock().isoformat()
        super().log(f"{ts} | {message}")


class EncryptedTimestampedFileLogger(TimestampedFileLogger):
    """Level 4: hashes (simulated encryption) the final stored content."""

    def __init__(self, file_path: str, secret: str, clock: callable | None = None) -> None:
        super().__init__(file_path, clock)
        self.secret = secret

    def log(self, message: str) -> None:
        super().log(message)
        # "encrypt" the last file entry in-place
        raw = self.file_contents[-1]
        hashed = hashlib.sha256((raw + self.secret).encode()).hexdigest()
        self.file_contents[-1] = f"ENC:{hashed}"


# ---------------------------------------------------------------------------
# AFTER: Composition with Protocols and dependency injection
# ---------------------------------------------------------------------------

@runtime_checkable
class Formatter(Protocol):
    """Transforms a message before it is written."""

    def format(self, message: str) -> str: ...


@runtime_checkable
class Encryptor(Protocol):
    """Encrypts content before storage."""

    def encrypt(self, content: str) -> str: ...


@runtime_checkable
class Writer(Protocol):
    """Writes formatted content to a destination."""

    def write(self, content: str) -> None: ...

    def replace_last(self, content: str) -> None: ...

    def read_all(self) -> list[str]: ...


# --- Concrete implementations ---

class IdentityFormatter:
    """No-op formatter: returns the message unchanged."""

    def format(self, message: str) -> str:
        return message


class TimestampFormatter:
    """Prepends an ISO timestamp to every message."""

    def __init__(self, clock: callable | None = None) -> None:
        self._clock = clock or datetime.utcnow

    def format(self, message: str) -> str:
        ts = self._clock().isoformat()
        return f"{ts} | {message}"


class PrefixFormatter:
    """Adds an arbitrary prefix to messages."""

    def __init__(self, prefix: str) -> None:
        self._prefix = prefix

    def format(self, message: str) -> str:
        return f"{self._prefix}{message}"


class NoEncryptor:
    """No-op encryptor: returns content unchanged."""

    def encrypt(self, content: str) -> str:
        return content


class Sha256Encryptor:
    """Hashes content with a secret (simulated encryption)."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def encrypt(self, content: str) -> str:
        hashed = hashlib.sha256((content + self._secret).encode()).hexdigest()
        return f"ENC:{hashed}"


class MemoryWriter:
    """Writes to an in-memory list (replaces both BaseLogger storage and FileLogger)."""

    def __init__(self, label: str = "") -> None:
        self._label = label
        self._contents: list[str] = []

    def write(self, content: str) -> None:
        if self._label:
            self._contents.append(f"[{self._label}] {content}")
        else:
            self._contents.append(content)

    def replace_last(self, content: str) -> None:
        if self._contents:
            self._contents[-1] = content

    def read_all(self) -> list[str]:
        return list(self._contents)


@dataclass
class ComposableLogger:
    """
    Composes formatting, encryption, and writing via injected dependencies.
    Replaces the entire 4-level hierarchy.

    Pipeline order mirrors the old inheritance call chain:
        format -> label (writer prefix) -> encrypt -> store
    To achieve this, the writer first produces the labelled string,
    then the encryptor transforms it in-place.
    """

    writer: Writer
    formatter: Formatter = field(default_factory=IdentityFormatter)
    encryptor: Encryptor = field(default_factory=NoEncryptor)
    _entries: list[str] = field(default_factory=list, init=False)

    def log(self, message: str) -> None:
        formatted = self.formatter.format(message)
        self._entries.append(formatted)
        # Write first (adds label/prefix), then encrypt the stored entry in-place.
        self.writer.write(formatted)
        stored = self.writer.read_all()
        encrypted = self.encryptor.encrypt(stored[-1])
        if encrypted != stored[-1]:
            self.writer.replace_last(encrypted)

    def get_entries(self) -> list[str]:
        """Raw formatted entries (before encryption), mirrors BaseLogger.get_entries."""
        return list(self._entries)

    def get_stored(self) -> list[str]:
        """What was actually persisted (after encryption)."""
        return self.writer.read_all()


# ---------------------------------------------------------------------------
# Chained formatter: compose multiple formatters in sequence
# ---------------------------------------------------------------------------

class ChainedFormatter:
    """Applies a sequence of formatters in order."""

    def __init__(self, *formatters: Formatter) -> None:
        self._formatters = formatters

    def format(self, message: str) -> str:
        result = message
        for f in self._formatters:
            result = f.format(result)
        return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _fixed_clock() -> datetime:
    return datetime(2026, 1, 15, 12, 0, 0)


def test_base_logger_equivalent() -> None:
    """ComposableLogger with defaults behaves like BaseLogger."""
    old = BaseLogger()
    new = ComposableLogger(writer=MemoryWriter())

    for msg in ("hello", "world"):
        old.log(msg)
        new.log(msg)

    assert old.get_entries() == new.get_entries()
    assert new.get_stored() == ["hello", "world"]


def test_file_logger_equivalent() -> None:
    """ComposableLogger with a labelled writer behaves like FileLogger."""
    path = "app.log"
    old = FileLogger(path)
    new = ComposableLogger(writer=MemoryWriter(label=path))

    for msg in ("start", "stop"):
        old.log(msg)
        new.log(msg)

    assert old.get_entries() == new.get_entries()
    assert old.file_contents == new.get_stored()


def test_timestamped_file_logger_equivalent() -> None:
    """ComposableLogger with TimestampFormatter matches TimestampedFileLogger."""
    path = "ts.log"
    old = TimestampedFileLogger(path, clock=_fixed_clock)
    new = ComposableLogger(
        writer=MemoryWriter(label=path),
        formatter=TimestampFormatter(clock=_fixed_clock),
    )

    for msg in ("event-a", "event-b"):
        old.log(msg)
        new.log(msg)

    assert old.get_entries() == new.get_entries()
    assert old.file_contents == new.get_stored()


def test_encrypted_timestamped_file_logger_equivalent() -> None:
    """ComposableLogger with encryption matches EncryptedTimestampedFileLogger."""
    path = "enc.log"
    secret = "s3cret"
    old = EncryptedTimestampedFileLogger(path, secret=secret, clock=_fixed_clock)
    new = ComposableLogger(
        writer=MemoryWriter(label=path),
        formatter=TimestampFormatter(clock=_fixed_clock),
        encryptor=Sha256Encryptor(secret=secret),
    )

    messages = ("login", "query", "logout")
    for msg in messages:
        old.log(msg)
        new.log(msg)

    # Formatted entries (pre-encryption) match
    assert old.get_entries() == new.get_entries()

    # Encrypted stored entries match
    assert old.file_contents == new.get_stored()
    assert all(e.startswith("ENC:") for e in new.get_stored())


def test_protocol_conformance() -> None:
    """All concrete types satisfy their Protocol at runtime."""
    assert isinstance(IdentityFormatter(), Formatter)
    assert isinstance(TimestampFormatter(), Formatter)
    assert isinstance(PrefixFormatter("x"), Formatter)
    assert isinstance(ChainedFormatter(), Formatter)
    assert isinstance(NoEncryptor(), Encryptor)
    assert isinstance(Sha256Encryptor("k"), Encryptor)
    assert isinstance(MemoryWriter(), Writer)


def test_chained_formatter() -> None:
    """ChainedFormatter composes multiple formatters in order."""
    fmt = ChainedFormatter(
        PrefixFormatter("[INFO] "),
        TimestampFormatter(clock=_fixed_clock),
    )
    result = fmt.format("boot")
    assert result == "2026-01-15T12:00:00 | [INFO] boot"


def test_composition_flexibility() -> None:
    """
    Composition lets us create combinations that would require
    new subclasses in the inheritance model — e.g., encrypted
    but NOT timestamped.
    """
    secret = "key"
    logger = ComposableLogger(
        writer=MemoryWriter(),
        encryptor=Sha256Encryptor(secret=secret),
    )
    logger.log("plain-msg")
    assert logger.get_entries() == ["plain-msg"]
    stored = logger.get_stored()
    assert len(stored) == 1
    assert stored[0].startswith("ENC:")
    expected_hash = hashlib.sha256(("plain-msg" + secret).encode()).hexdigest()
    assert stored[0] == f"ENC:{expected_hash}"


def test_swap_writer_at_runtime() -> None:
    """Writers can be swapped without touching any other component."""
    w1 = MemoryWriter(label="primary")
    w2 = MemoryWriter(label="backup")
    logger = ComposableLogger(writer=w1)

    logger.log("first")
    # Swap the writer for subsequent logs
    old_writer = logger.writer
    logger.writer = w2
    logger.log("second")

    assert old_writer.read_all() == ["[primary] first"]
    assert w2.read_all() == ["[backup] second"]


def test_multiple_loggers_share_writer() -> None:
    """Multiple loggers can fan-in to the same writer."""
    shared = MemoryWriter()
    app_logger = ComposableLogger(writer=shared, formatter=PrefixFormatter("[APP] "))
    db_logger = ComposableLogger(writer=shared, formatter=PrefixFormatter("[DB] "))

    app_logger.log("started")
    db_logger.log("connected")
    app_logger.log("ready")

    assert shared.read_all() == [
        "[APP] started",
        "[DB] connected",
        "[APP] ready",
    ]


if __name__ == "__main__":
    tests = [
        test_base_logger_equivalent,
        test_file_logger_equivalent,
        test_timestamped_file_logger_equivalent,
        test_encrypted_timestamped_file_logger_equivalent,
        test_protocol_conformance,
        test_chained_formatter,
        test_composition_flexibility,
        test_swap_writer_at_runtime,
        test_multiple_loggers_share_writer,
    ]
    for t in tests:
        t()
        print(f"  PASS: {t.__name__}")
    print(f"\nAll {len(tests)} tests passed.")
