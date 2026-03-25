"""
LogAggregator: tail -f style watcher on multiple log files.
Search by regex, time range, log level. Output to terminal or file. Async file watchers.
"""

import asyncio
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import IO, Callable, Dict, List, Optional, Pattern, Set


class LogLevel(Enum):
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

    @classmethod
    def from_string(cls, s: str) -> "LogLevel":
        mapping = {
            "DEBUG": cls.DEBUG,
            "INFO": cls.INFO,
            "WARNING": cls.WARNING,
            "WARN": cls.WARNING,
            "ERROR": cls.ERROR,
            "CRITICAL": cls.CRITICAL,
            "FATAL": cls.CRITICAL,
        }
        return mapping.get(s.upper(), cls.INFO)


LOG_LEVEL_PATTERN = re.compile(
    r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\b", re.IGNORECASE
)

TIMESTAMP_PATTERNS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"), "%Y-%m-%dT%H:%M:%S"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"), "%Y-%m-%d %H:%M:%S"),
    (re.compile(r"\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}"), "%d/%b/%Y:%H:%M:%S"),
]


@dataclass
class LogEntry:
    source: str
    line: str
    line_number: int
    timestamp: Optional[datetime] = None
    level: Optional[LogLevel] = None
    raw: str = ""

    def matches_level(self, min_level: LogLevel) -> bool:
        if self.level is None:
            return True
        return self.level.value >= min_level.value

    def matches_time_range(
        self, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> bool:
        if self.timestamp is None:
            return True
        if start and self.timestamp < start:
            return False
        if end and self.timestamp > end:
            return False
        return True

    def matches_regex(self, pattern: "re.Pattern[str]") -> bool:
        return bool(pattern.search(self.line))


def parse_timestamp(line: str) -> Optional[datetime]:
    for pat, fmt in TIMESTAMP_PATTERNS:
        m = pat.search(line)
        if m:
            try:
                return datetime.strptime(m.group(), fmt)
            except ValueError:
                continue
    return None


def parse_level(line: str) -> Optional[LogLevel]:
    m = LOG_LEVEL_PATTERN.search(line)
    if m:
        return LogLevel.from_string(m.group())
    return None


def parse_line(source: str, line: str, line_number: int) -> LogEntry:
    return LogEntry(
        source=source,
        line=line.rstrip("\n"),
        line_number=line_number,
        timestamp=parse_timestamp(line),
        level=parse_level(line),
        raw=line,
    )


@dataclass
class SearchFilter:
    regex: Optional["re.Pattern[str]"] = None
    min_level: Optional[LogLevel] = None
    time_start: Optional[datetime] = None
    time_end: Optional[datetime] = None

    def matches(self, entry: LogEntry) -> bool:
        if self.min_level and not entry.matches_level(self.min_level):
            return False
        if not entry.matches_time_range(self.time_start, self.time_end):
            return False
        if self.regex and not entry.matches_regex(self.regex):
            return False
        return True


class OutputWriter:
    def __init__(self, file_path: Optional[str] = None):
        self._file_path = file_path
        self._fh: Optional[IO[str]] = None

    def open(self) -> None:
        if self._file_path:
            self._fh = open(self._file_path, "a", encoding="utf-8")

    def write(self, entry: LogEntry) -> None:
        formatted = f"[{entry.source}:{entry.line_number}] {entry.line}"
        if self._fh:
            self._fh.write(formatted + "\n")
            self._fh.flush()
        else:
            print(formatted)

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


class LogAggregator:
    def __init__(
        self,
        files: List[str],
        search_filter: Optional[SearchFilter] = None,
        output_file: Optional[str] = None,
        poll_interval: float = 0.2,
        on_entry: Optional[Callable[[LogEntry], None]] = None,
    ):
        self._files = [str(Path(f).resolve()) for f in files]
        self._filter = search_filter or SearchFilter()
        self._writer = OutputWriter(output_file)
        self._poll_interval = poll_interval
        self._on_entry = on_entry
        self._running = False
        self._entries: List[LogEntry] = []
        self._positions: Dict[str, int] = {}
        self._line_counts: Dict[str, int] = {}

    @property
    def entries(self) -> List[LogEntry]:
        return list(self._entries)

    def search(self, search_filter: Optional[SearchFilter] = None) -> List[LogEntry]:
        sf = search_filter or self._filter
        return [e for e in self._entries if sf.matches(e)]

    def _read_new_lines(self, filepath: str) -> List[LogEntry]:
        results: List[LogEntry] = []
        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._positions.get(filepath, 0))
                line_num = self._line_counts.get(filepath, 0)
                for line in fh:
                    line_num += 1
                    entry = parse_line(
                        source=os.path.basename(filepath),
                        line=line,
                        line_number=line_num,
                    )
                    results.append(entry)
                self._positions[filepath] = fh.tell()
                self._line_counts[filepath] = line_num
        except FileNotFoundError:
            pass
        return results

    def read_existing(self) -> None:
        """Read all existing content from watched files."""
        for filepath in self._files:
            new_entries = self._read_new_lines(filepath)
            for entry in new_entries:
                self._entries.append(entry)
                if self._filter.matches(entry):
                    self._writer.write(entry)
                    if self._on_entry:
                        self._on_entry(entry)

    async def _watch_file(self, filepath: str, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            new_entries = self._read_new_lines(filepath)
            for entry in new_entries:
                self._entries.append(entry)
                if self._filter.matches(entry):
                    self._writer.write(entry)
                    if self._on_entry:
                        self._on_entry(entry)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._poll_interval
                )
            except asyncio.TimeoutError:
                pass

    async def tail(self, duration: Optional[float] = None) -> None:
        """Tail all files asynchronously. Runs until stop() or duration expires."""
        self._running = True
        self._writer.open()
        stop_event = asyncio.Event()

        tasks = [
            asyncio.create_task(self._watch_file(f, stop_event))
            for f in self._files
        ]

        if duration is not None:
            await asyncio.sleep(duration)
            stop_event.set()
        else:
            try:
                while self._running:
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                pass
            stop_event.set()

        await asyncio.gather(*tasks)
        self._writer.close()

    def stop(self) -> None:
        self._running = False


# ──────────────────────────────────────────────
# Tests / assertions in __main__
# ──────────────────────────────────────────────

if __name__ == "__main__":

    # --- Test 1: Parsing ---
    line1 = "2024-06-15 10:30:45 ERROR Something broke badly"
    entry1 = parse_line("app.log", line1, 1)
    assert entry1.level == LogLevel.ERROR, f"Expected ERROR, got {entry1.level}"
    assert entry1.timestamp == datetime(2024, 6, 15, 10, 30, 45), (
        f"Wrong timestamp: {entry1.timestamp}"
    )
    assert entry1.source == "app.log"
    assert entry1.line_number == 1

    line2 = "Just a plain line with no level or time"
    entry2 = parse_line("sys.log", line2, 42)
    assert entry2.level is None
    assert entry2.timestamp is None
    assert entry2.line_number == 42

    line3 = "2024-01-01T00:00:00 DEBUG Starting up"
    entry3 = parse_line("boot.log", line3, 1)
    assert entry3.level == LogLevel.DEBUG
    assert entry3.timestamp is not None

    print("[PASS] Test 1: Parsing")

    # --- Test 2: LogLevel ordering ---
    assert LogLevel.DEBUG.value < LogLevel.INFO.value
    assert LogLevel.INFO.value < LogLevel.WARNING.value
    assert LogLevel.WARNING.value < LogLevel.ERROR.value
    assert LogLevel.ERROR.value < LogLevel.CRITICAL.value
    assert LogLevel.from_string("WARN") == LogLevel.WARNING
    assert LogLevel.from_string("FATAL") == LogLevel.CRITICAL
    print("[PASS] Test 2: LogLevel ordering")

    # --- Test 3: SearchFilter ---
    sf = SearchFilter(
        regex=re.compile(r"broke"),
        min_level=LogLevel.WARNING,
    )
    assert sf.matches(entry1) is True   # ERROR + "broke" in line
    assert sf.matches(entry2) is False  # no "broke" match
    assert sf.matches(entry3) is False  # DEBUG < WARNING

    sf_time = SearchFilter(
        time_start=datetime(2024, 6, 1),
        time_end=datetime(2024, 6, 30),
    )
    assert sf_time.matches(entry1) is True
    assert sf_time.matches(entry3) is False  # Jan 2024 outside range

    print("[PASS] Test 3: SearchFilter")

    # --- Test 4: Read existing files ---
    with tempfile.TemporaryDirectory() as tmpdir:
        log1 = os.path.join(tmpdir, "app.log")
        log2 = os.path.join(tmpdir, "error.log")

        with open(log1, "w") as f:
            f.write("2024-06-15 10:00:00 INFO Starting application\n")
            f.write("2024-06-15 10:00:01 DEBUG Loading config\n")
            f.write("2024-06-15 10:00:02 ERROR Failed to connect to DB\n")

        with open(log2, "w") as f:
            f.write("2024-06-15 10:00:03 WARNING Disk usage high\n")
            f.write("2024-06-15 10:00:04 CRITICAL Out of memory\n")

        agg = LogAggregator(files=[log1, log2])
        agg.read_existing()

        assert len(agg.entries) == 5, f"Expected 5 entries, got {len(agg.entries)}"

        errors = agg.search(SearchFilter(min_level=LogLevel.ERROR))
        assert len(errors) == 2, f"Expected 2 ERROR+ entries, got {len(errors)}"

        db_hits = agg.search(SearchFilter(regex=re.compile(r"DB|memory", re.IGNORECASE)))
        assert len(db_hits) == 2, f"Expected 2 DB/memory hits, got {len(db_hits)}"

        print("[PASS] Test 4: Read existing files")

    # --- Test 5: Output to file ---
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "test.log")
        out_path = os.path.join(tmpdir, "output.txt")

        with open(log_path, "w") as f:
            f.write("2024-06-15 12:00:00 ERROR Kaboom\n")
            f.write("2024-06-15 12:00:01 INFO All good\n")

        agg = LogAggregator(
            files=[log_path],
            search_filter=SearchFilter(min_level=LogLevel.ERROR),
            output_file=out_path,
        )
        agg._writer.open()
        agg.read_existing()
        agg._writer.close()

        with open(out_path) as f:
            lines = f.readlines()
        assert len(lines) == 1, f"Expected 1 filtered output line, got {len(lines)}"
        assert "Kaboom" in lines[0]

        print("[PASS] Test 5: Output to file")

    # --- Test 6: Async tail -f (simulate appending) ---
    async def test_tail() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "live.log")
            with open(log_path, "w") as f:
                f.write("2024-06-15 13:00:00 INFO Initial line\n")

            collected: List[LogEntry] = []

            agg = LogAggregator(
                files=[log_path],
                on_entry=lambda e: collected.append(e),
                poll_interval=0.05,
            )

            async def append_lines() -> None:
                await asyncio.sleep(0.15)
                with open(log_path, "a") as f:
                    f.write("2024-06-15 13:00:01 WARNING Late warning\n")
                    f.write("2024-06-15 13:00:02 ERROR Late error\n")

            asyncio.ensure_future(append_lines())
            await agg.tail(duration=0.5)

            assert len(collected) == 3, (
                f"Expected 3 entries from tail, got {len(collected)}"
            )
            levels = [e.level for e in collected]
            assert LogLevel.INFO in levels
            assert LogLevel.WARNING in levels
            assert LogLevel.ERROR in levels

            print("[PASS] Test 6: Async tail -f")

    asyncio.run(test_tail())

    # --- Test 7: Tail with filter (only ERROR+) ---
    async def test_tail_filtered() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "filtered.log")
            with open(log_path, "w") as f:
                f.write("2024-06-15 14:00:00 DEBUG noisy debug\n")

            collected: List[LogEntry] = []

            agg = LogAggregator(
                files=[log_path],
                search_filter=SearchFilter(min_level=LogLevel.ERROR),
                on_entry=lambda e: collected.append(e),
                poll_interval=0.05,
            )

            async def append_lines() -> None:
                await asyncio.sleep(0.1)
                with open(log_path, "a") as f:
                    f.write("2024-06-15 14:00:01 INFO skip me\n")
                    f.write("2024-06-15 14:00:02 ERROR catch me\n")
                    f.write("2024-06-15 14:00:03 CRITICAL catch me too\n")

            asyncio.ensure_future(append_lines())
            await agg.tail(duration=0.5)

            assert len(collected) == 2, (
                f"Expected 2 filtered entries, got {len(collected)}"
            )
            assert all(
                e.level is not None and e.level.value >= LogLevel.ERROR.value
                for e in collected
            )

            print("[PASS] Test 7: Tail with filter")

    asyncio.run(test_tail_filtered())

    # --- Test 8: Multiple files watched concurrently ---
    async def test_multi_file() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_a = os.path.join(tmpdir, "a.log")
            log_b = os.path.join(tmpdir, "b.log")
            for p in [log_a, log_b]:
                with open(p, "w") as f:
                    f.write("")

            collected: List[LogEntry] = []

            agg = LogAggregator(
                files=[log_a, log_b],
                on_entry=lambda e: collected.append(e),
                poll_interval=0.05,
            )

            async def append_to_both() -> None:
                await asyncio.sleep(0.1)
                with open(log_a, "a") as f:
                    f.write("2024-06-15 15:00:00 INFO from A\n")
                with open(log_b, "a") as f:
                    f.write("2024-06-15 15:00:01 ERROR from B\n")

            asyncio.ensure_future(append_to_both())
            await agg.tail(duration=0.4)

            sources = {e.source for e in collected}
            assert "a.log" in sources, f"Missing a.log, got {sources}"
            assert "b.log" in sources, f"Missing b.log, got {sources}"
            assert len(collected) == 2

            print("[PASS] Test 8: Multiple files watched concurrently")

    asyncio.run(test_multi_file())

    # --- Test 9: Search after tail ---
    async def test_search_after_tail() -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "search.log")
            with open(log_path, "w") as f:
                f.write("2024-06-15 16:00:00 INFO user logged in\n")
                f.write("2024-06-15 16:00:01 ERROR timeout on request\n")
                f.write("2024-06-15 16:00:02 INFO request completed\n")
                f.write("2024-06-15 16:00:03 ERROR null pointer exception\n")

            agg = LogAggregator(files=[log_path], poll_interval=0.05)
            await agg.tail(duration=0.2)

            all_entries = agg.entries
            assert len(all_entries) == 4

            error_search = agg.search(SearchFilter(min_level=LogLevel.ERROR))
            assert len(error_search) == 2

            regex_search = agg.search(
                SearchFilter(regex=re.compile(r"request"))
            )
            assert len(regex_search) == 2

            combined = agg.search(
                SearchFilter(
                    min_level=LogLevel.ERROR,
                    regex=re.compile(r"timeout"),
                )
            )
            assert len(combined) == 1
            assert "timeout" in combined[0].line

            time_search = agg.search(
                SearchFilter(
                    time_start=datetime(2024, 6, 15, 16, 0, 1),
                    time_end=datetime(2024, 6, 15, 16, 0, 2),
                )
            )
            assert len(time_search) == 2

            print("[PASS] Test 9: Search after tail")

    asyncio.run(test_search_after_tail())

    print("\n=== All 9 tests passed ===")
