"""Tests for datatools.transform."""

import pytest

from datatools.transform import flatten, chunk, deduplicate


class TestFlatten:
    def test_deeply_nested(self):
        assert flatten([1, [2, [3, [4]]]]) == [1, 2, 3, 4]

    def test_already_flat(self):
        assert flatten([1, 2, 3]) == [1, 2, 3]

    def test_empty(self):
        assert flatten([]) == []

    def test_depth_limit(self):
        assert flatten([1, [2, [3, [4]]]], depth=1) == [1, 2, [3, [4]]]

    def test_mixed_types(self):
        assert flatten(["a", ["b", [1, 2]]]) == ["a", "b", 1, 2]

    def test_tuples_flattened(self):
        assert flatten([(1, 2), [3, (4, 5)]]) == [1, 2, 3, 4, 5]


class TestChunk:
    def test_even_split(self):
        assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_uneven_split(self):
        assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    def test_single_chunk(self):
        assert chunk([1, 2], 5) == [[1, 2]]

    def test_empty(self):
        assert chunk([], 3) == []

    def test_size_one(self):
        assert chunk([1, 2, 3], 1) == [[1], [2], [3]]

    def test_invalid_size(self):
        with pytest.raises(ValueError, match="chunk size must be >= 1"):
            chunk([1], 0)


class TestDeduplicate:
    def test_basic(self):
        assert deduplicate([1, 2, 2, 3, 1]) == [1, 2, 3]

    def test_preserves_order(self):
        assert deduplicate([3, 1, 2, 1, 3]) == [3, 1, 2]

    def test_with_key(self):
        assert deduplicate(["a", "A", "b", "B"], key=str.lower) == ["a", "b"]

    def test_empty(self):
        assert deduplicate([]) == []

    def test_all_unique(self):
        assert deduplicate([1, 2, 3]) == [1, 2, 3]

    def test_all_same(self):
        assert deduplicate([5, 5, 5]) == [5]
