"""
TDD tests for parse_datetime(s) -> datetime
Handles: ISO 8601, Unix timestamps, relative ('2 days ago'), natural language ('next Monday').
"""

import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch


# Stub: replace with real implementation
def parse_datetime(s: str) -> datetime:
    raise NotImplementedError("parse_datetime not yet implemented")


class TestISO8601(unittest.TestCase):
    """ISO 8601 format parsing."""

    def test_basic_date(self):
        result = parse_datetime("2024-03-15")
        assert result.year == 2024
        assert result.month == 3
        assert result.day == 15

    def test_date_with_time(self):
        result = parse_datetime("2024-03-15T10:30:00")
        assert result == datetime(2024, 3, 15, 10, 30, 0)

    def test_date_with_time_and_seconds(self):
        result = parse_datetime("2024-03-15T10:30:45")
        assert result == datetime(2024, 3, 15, 10, 30, 45)

    def test_utc_zulu_suffix(self):
        result = parse_datetime("2024-03-15T10:30:00Z")
        assert result.tzinfo is not None
        assert result == datetime(2024, 3, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_positive_offset(self):
        result = parse_datetime("2024-03-15T10:30:00+05:30")
        expected_tz = timezone(timedelta(hours=5, minutes=30))
        assert result == datetime(2024, 3, 15, 10, 30, 0, tzinfo=expected_tz)

    def test_negative_offset(self):
        result = parse_datetime("2024-03-15T10:30:00-04:00")
        expected_tz = timezone(timedelta(hours=-4))
        assert result == datetime(2024, 3, 15, 10, 30, 0, tzinfo=expected_tz)

    def test_with_microseconds(self):
        result = parse_datetime("2024-03-15T10:30:00.123456")
        assert result.microsecond == 123456

    def test_compact_format(self):
        result = parse_datetime("20240315T103000")
        assert result == datetime(2024, 3, 15, 10, 30, 0)

    def test_date_only_no_time(self):
        result = parse_datetime("2024-01-01")
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0


class TestUnixTimestamps(unittest.TestCase):
    """Unix timestamp parsing (seconds and milliseconds)."""

    def test_unix_seconds(self):
        result = parse_datetime("1710505800")
        expected = datetime(2024, 3, 15, 14, 30, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_unix_zero(self):
        result = parse_datetime("0")
        assert result == datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_unix_milliseconds(self):
        result = parse_datetime("1710505800000")
        expected = datetime(2024, 3, 15, 14, 30, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_negative_unix_timestamp(self):
        result = parse_datetime("-86400")
        expected = datetime(1969, 12, 31, 0, 0, 0, tzinfo=timezone.utc)
        assert result == expected

    def test_float_unix_timestamp(self):
        result = parse_datetime("1710505800.5")
        assert result.microsecond == 500000


class TestRelativeDates(unittest.TestCase):
    """Relative date expressions like '2 days ago', 'in 3 hours'."""

    def _fixed_now(self):
        return datetime(2024, 3, 15, 12, 0, 0)

    @patch("test_datetime_parser.datetime", wraps=datetime)
    def _parse_with_frozen_now(self, s, mock_dt):
        mock_dt.now.return_value = self._fixed_now()
        return parse_datetime(s)

    def test_days_ago(self):
        result = self._parse_with_frozen_now("2 days ago")
        expected = self._fixed_now() - timedelta(days=2)
        assert result == expected

    def test_hours_ago(self):
        result = self._parse_with_frozen_now("5 hours ago")
        expected = self._fixed_now() - timedelta(hours=5)
        assert result == expected

    def test_minutes_ago(self):
        result = self._parse_with_frozen_now("30 minutes ago")
        expected = self._fixed_now() - timedelta(minutes=30)
        assert result == expected

    def test_seconds_ago(self):
        result = self._parse_with_frozen_now("10 seconds ago")
        expected = self._fixed_now() - timedelta(seconds=10)
        assert result == expected

    def test_weeks_ago(self):
        result = self._parse_with_frozen_now("3 weeks ago")
        expected = self._fixed_now() - timedelta(weeks=3)
        assert result == expected

    def test_one_day_ago(self):
        result = self._parse_with_frozen_now("1 day ago")
        expected = self._fixed_now() - timedelta(days=1)
        assert result == expected

    def test_in_future_hours(self):
        result = self._parse_with_frozen_now("in 3 hours")
        expected = self._fixed_now() + timedelta(hours=3)
        assert result == expected

    def test_in_future_days(self):
        result = self._parse_with_frozen_now("in 5 days")
        expected = self._fixed_now() + timedelta(days=5)
        assert result == expected

    def test_yesterday(self):
        result = self._parse_with_frozen_now("yesterday")
        expected = self._fixed_now() - timedelta(days=1)
        assert result.date() == expected.date()

    def test_tomorrow(self):
        result = self._parse_with_frozen_now("tomorrow")
        expected = self._fixed_now() + timedelta(days=1)
        assert result.date() == expected.date()

    def test_now(self):
        result = self._parse_with_frozen_now("now")
        assert result == self._fixed_now()

    def test_today(self):
        result = self._parse_with_frozen_now("today")
        assert result.date() == self._fixed_now().date()


class TestNaturalLanguage(unittest.TestCase):
    """Natural language expressions like 'next Monday', 'last Friday'."""

    def _fixed_now(self):
        # Friday, March 15, 2024
        return datetime(2024, 3, 15, 12, 0, 0)

    @patch("test_datetime_parser.datetime", wraps=datetime)
    def _parse_with_frozen_now(self, s, mock_dt):
        mock_dt.now.return_value = self._fixed_now()
        return parse_datetime(s)

    def test_next_monday(self):
        result = self._parse_with_frozen_now("next Monday")
        # March 15 is Friday; next Monday is March 18
        assert result.date() == datetime(2024, 3, 18).date()
        assert result.weekday() == 0  # Monday

    def test_next_friday(self):
        result = self._parse_with_frozen_now("next Friday")
        # March 15 is Friday; next Friday is March 22
        assert result.date() == datetime(2024, 3, 22).date()
        assert result.weekday() == 4  # Friday

    def test_next_sunday(self):
        result = self._parse_with_frozen_now("next Sunday")
        assert result.weekday() == 6

    def test_last_monday(self):
        result = self._parse_with_frozen_now("last Monday")
        # March 15 is Friday; last Monday is March 11
        assert result.date() == datetime(2024, 3, 11).date()
        assert result.weekday() == 0

    def test_last_wednesday(self):
        result = self._parse_with_frozen_now("last Wednesday")
        assert result.date() == datetime(2024, 3, 13).date()
        assert result.weekday() == 2

    def test_next_returns_future_date(self):
        result = self._parse_with_frozen_now("next Tuesday")
        assert result > self._fixed_now()

    def test_last_returns_past_date(self):
        result = self._parse_with_frozen_now("last Tuesday")
        assert result < self._fixed_now()

    def test_case_insensitive(self):
        result = self._parse_with_frozen_now("next monday")
        assert result.weekday() == 0

    def test_next_saturday(self):
        result = self._parse_with_frozen_now("Next Saturday")
        assert result.date() == datetime(2024, 3, 16).date()
        assert result.weekday() == 5


class TestEdgeCases(unittest.TestCase):
    """Edge cases and error handling."""

    def test_empty_string_raises(self):
        with self.assertRaises((ValueError, TypeError)):
            parse_datetime("")

    def test_none_raises(self):
        with self.assertRaises((ValueError, TypeError)):
            parse_datetime(None)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            parse_datetime("not a date at all xyz")

    def test_whitespace_stripped(self):
        result = parse_datetime("  2024-03-15T10:30:00  ")
        assert result == datetime(2024, 3, 15, 10, 30, 0)

    def test_returns_datetime_type(self):
        result = parse_datetime("2024-03-15")
        assert isinstance(result, datetime)

    def test_leap_year_feb_29(self):
        result = parse_datetime("2024-02-29")
        assert result.month == 2
        assert result.day == 29

    def test_non_leap_year_feb_29_raises(self):
        with self.assertRaises(ValueError):
            parse_datetime("2023-02-29")

    def test_end_of_year(self):
        result = parse_datetime("2024-12-31T23:59:59")
        assert result == datetime(2024, 12, 31, 23, 59, 59)

    def test_beginning_of_year(self):
        result = parse_datetime("2024-01-01T00:00:00")
        assert result == datetime(2024, 1, 1, 0, 0, 0)


class TestReturnTypes(unittest.TestCase):
    """Ensure consistent return types across all formats."""

    def test_iso_returns_datetime(self):
        assert isinstance(parse_datetime("2024-03-15"), datetime)

    def test_timestamp_returns_datetime(self):
        assert isinstance(parse_datetime("1710505800"), datetime)

    @patch("test_datetime_parser.datetime", wraps=datetime)
    def test_relative_returns_datetime(self, mock_dt):
        mock_dt.now.return_value = datetime(2024, 3, 15, 12, 0, 0)
        assert isinstance(parse_datetime("2 days ago"), datetime)

    @patch("test_datetime_parser.datetime", wraps=datetime)
    def test_natural_returns_datetime(self, mock_dt):
        mock_dt.now.return_value = datetime(2024, 3, 15, 12, 0, 0)
        assert isinstance(parse_datetime("next Monday"), datetime)


if __name__ == "__main__":
    # Quick smoke test with assertions before full suite
    print("Running smoke tests...")

    # ISO 8601
    try:
        r = parse_datetime("2024-03-15T10:30:00")
        assert r == datetime(2024, 3, 15, 10, 30, 0), f"ISO basic failed: {r}"
        print("  ISO 8601 basic: PASS")
    except NotImplementedError:
        print("  ISO 8601 basic: SKIP (not implemented)")

    # Unix timestamp
    try:
        r = parse_datetime("0")
        assert r == datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc), f"Unix epoch failed: {r}"
        print("  Unix timestamp: PASS")
    except NotImplementedError:
        print("  Unix timestamp: SKIP (not implemented)")

    # Relative
    try:
        r = parse_datetime("now")
        assert isinstance(r, datetime), f"Relative 'now' failed: {r}"
        print("  Relative (now): PASS")
    except NotImplementedError:
        print("  Relative (now): SKIP (not implemented)")

    # Natural language
    try:
        r = parse_datetime("next Monday")
        assert isinstance(r, datetime), f"Natural language failed: {r}"
        assert r.weekday() == 0, f"next Monday weekday wrong: {r.weekday()}"
        print("  Natural language: PASS")
    except NotImplementedError:
        print("  Natural language: SKIP (not implemented)")

    # Error cases
    try:
        parse_datetime("")
        print("  Empty string: FAIL (should have raised)")
    except (ValueError, TypeError):
        print("  Empty string raises: PASS")
    except NotImplementedError:
        print("  Empty string: SKIP (not implemented)")

    print("\nRunning full test suite...")
    unittest.main(verbosity=2)
