"""Tests for datatools.stats."""

import math

import pytest

from datatools.stats import mean, median, stdev


class TestMean:
    def test_basic(self):
        assert mean([1, 2, 3]) == 2.0

    def test_single(self):
        assert mean([42]) == 42.0

    def test_floats(self):
        assert abs(mean([1.5, 2.5]) - 2.0) < 1e-9

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            mean([])


class TestMedian:
    def test_odd_count(self):
        assert median([3, 1, 2]) == 2

    def test_even_count(self):
        assert median([1, 2, 3, 4]) == 2.5

    def test_single(self):
        assert median([7]) == 7

    def test_already_sorted(self):
        assert median([10, 20, 30]) == 20

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="at least one"):
            median([])


class TestStdev:
    def test_sample_stdev(self):
        values = [2, 4, 4, 4, 5, 5, 7, 9]
        assert abs(stdev(values) - 2.138089935299395) < 1e-9

    def test_population_stdev(self):
        values = [2, 4, 4, 4, 5, 5, 7, 9]
        assert abs(stdev(values, population=True) - 2.0) < 1e-9

    def test_identical_values(self):
        assert stdev([5, 5, 5], population=True) == 0.0

    def test_two_values(self):
        result = stdev([0, 10])
        expected = math.sqrt(50)
        assert abs(result - expected) < 1e-9

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            stdev([])

    def test_single_sample_raises(self):
        with pytest.raises(ValueError, match="at least two"):
            stdev([1])

    def test_single_population_ok(self):
        assert stdev([5], population=True) == 0.0
