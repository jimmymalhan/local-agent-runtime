"""Data transformation utilities."""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Hashable


def flatten(nested: Iterable[Any], *, depth: int = -1) -> list[Any]:
    """Recursively flatten an iterable.

    Args:
        nested: The iterable to flatten.
        depth: Maximum depth to flatten (-1 for unlimited).

    Returns:
        A flat list of elements.
    """
    result: list[Any] = []
    _flatten(nested, result, depth)
    return result


def _flatten(items: Any, out: list[Any], depth: int) -> None:
    for item in items:
        if isinstance(item, (list, tuple)) and depth != 0:
            _flatten(item, out, depth - 1)
        else:
            out.append(item)


def chunk(seq: list[Any], size: int) -> list[list[Any]]:
    """Split a list into fixed-size chunks.

    Args:
        seq: The list to split.
        size: Maximum number of elements per chunk.

    Returns:
        A list of sub-lists.

    Raises:
        ValueError: If size is less than 1.
    """
    if size < 1:
        raise ValueError(f"chunk size must be >= 1, got {size}")
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def deduplicate(seq: list[Any], *, key: Any = None) -> list[Any]:
    """Remove duplicates while preserving order.

    Args:
        seq: The list to deduplicate.
        key: Optional callable to compute a comparison key per element.

    Returns:
        A new list with duplicates removed.
    """
    seen: set[Hashable] = set()
    result: list[Any] = []
    for item in seq:
        k = key(item) if key else item
        if k not in seen:
            seen.add(k)
            result.append(item)
    return result


if __name__ == "__main__":
    assert flatten([1, [2, [3, [4]]]]) == [1, 2, 3, 4]
    assert flatten([1, [2, [3]]], depth=1) == [1, 2, [3]]
    assert flatten([]) == []

    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
    assert chunk([], 3) == []
    try:
        chunk([1], 0)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass

    assert deduplicate([1, 2, 2, 3, 1]) == [1, 2, 3]
    assert deduplicate(["a", "A", "b"], key=str.lower) == ["a", "b"]

    print("transform: all assertions passed")
