"""Descriptive statistics utilities."""

from __future__ import annotations

import math
from typing import Sequence


def mean(values: Sequence[float]) -> float:
    """Return the arithmetic mean.

    Raises:
        ValueError: If the sequence is empty.
    """
    if not values:
        raise ValueError("mean requires at least one value")
    return sum(values) / len(values)


def median(values: Sequence[float]) -> float:
    """Return the median value.

    Raises:
        ValueError: If the sequence is empty.
    """
    if not values:
        raise ValueError("median requires at least one value")
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def stdev(values: Sequence[float], *, population: bool = False) -> float:
    """Return the standard deviation.

    Args:
        values: Numeric sequence.
        population: If True, compute population stdev; otherwise sample stdev.

    Raises:
        ValueError: If values has fewer elements than required.
    """
    n = len(values)
    if n == 0:
        raise ValueError("stdev requires at least one value")
    if not population and n < 2:
        raise ValueError("sample stdev requires at least two values")
    m = mean(values)
    ss = sum((x - m) ** 2 for x in values)
    divisor = n if population else (n - 1)
    return math.sqrt(ss / divisor)


if __name__ == "__main__":
    assert mean([1, 2, 3]) == 2.0
    assert mean([10]) == 10.0

    assert median([3, 1, 2]) == 2
    assert median([1, 2, 3, 4]) == 2.5

    assert abs(stdev([2, 4, 4, 4, 5, 5, 7, 9]) - 2.138089935299395) < 1e-9
    assert abs(stdev([2, 4, 4, 4, 5, 5, 7, 9], population=True) - 2.0) < 1e-9

    try:
        mean([])
    except ValueError:
        pass

    try:
        stdev([1])
    except ValueError:
        pass

    print("stats: all assertions passed")
