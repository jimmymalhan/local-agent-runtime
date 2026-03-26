"""TDD tests for Myers diff algorithm."""

from dataclasses import dataclass
from enum import Enum
from typing import List, Any


class ChangeType(Enum):
    ADD = "add"
    REMOVE = "remove"
    KEEP = "keep"


@dataclass
class Change:
    type: ChangeType
    index: int
    value: Any


def diff(a: list, b: list) -> List[Change]:
    """Myers diff algorithm."""
    n, m = len(a), len(b)
    if n == 0 and m == 0:
        return []

    max_d = n + m
    v = {0: 0}
    trace = []

    for d in range(max_d + 1):
        trace.append(dict(v))
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and v.get(k - 1, 0) < v.get(k + 1, 0)):
                x = v.get(k + 1, 0)
            else:
                x = v.get(k - 1, 0) + 1
            y = x - k
            while x < n and y < m and a[x] == b[y]:
                x += 1
                y += 1
            v[k] = x
            if x >= n and y >= m:
                changes = []
                cx, cy = n, m
                for dd in range(d, -1, -1):
                    t = trace[dd]
                    kk = cx - cy
                    if kk == -dd or (kk != dd and t.get(kk - 1, 0) < t.get(kk + 1, 0)):
                        prev_k = kk + 1
                    else:
                        prev_k = kk - 1
                    prev_x = t.get(prev_k, 0)
                    prev_y = prev_x - prev_k
                    while cx > prev_x and cy > prev_y:
                        cx -= 1
                        cy -= 1
                        changes.append(Change(ChangeType.KEEP, cx, a[cx]))
                    if dd > 0:
                        if prev_k == kk + 1:
                            changes.append(Change(ChangeType.ADD, prev_y, b[prev_y]))
                            cy -= 1
                        else:
                            changes.append(Change(ChangeType.REMOVE, prev_x, a[prev_x]))
                            cx -= 1
                changes.reverse()
                return changes
    return []


def apply_diff(a: list, changes: List[Change]) -> list:
    """Apply a diff to list a to produce list b."""
    result = []
    for c in changes:
        if c.type == ChangeType.KEEP:
            result.append(c.value)
        elif c.type == ChangeType.ADD:
            result.append(c.value)
        # REMOVE: skip
    return result


def count_types(changes: List[Change]):
    adds = sum(1 for c in changes if c.type == ChangeType.ADD)
    removes = sum(1 for c in changes if c.type == ChangeType.REMOVE)
    keeps = sum(1 for c in changes if c.type == ChangeType.KEEP)
    return adds, removes, keeps


if __name__ == "__main__":
    # --- Test 1: Both empty ---
    result = diff([], [])
    assert result == [], f"Expected empty, got {result}"

    # --- Test 2: Empty to non-empty (all adds) ---
    result = diff([], ["a", "b", "c"])
    assert len(result) == 3
    assert all(c.type == ChangeType.ADD for c in result)
    assert [c.value for c in result] == ["a", "b", "c"]
    assert apply_diff([], result) == ["a", "b", "c"]

    # --- Test 3: Non-empty to empty (all removes) ---
    result = diff(["a", "b", "c"], [])
    assert len(result) == 3
    assert all(c.type == ChangeType.REMOVE for c in result)
    assert [c.value for c in result] == ["a", "b", "c"]
    assert apply_diff(["a", "b", "c"], result) == []

    # --- Test 4: Identical lists (all keeps) ---
    result = diff(["a", "b", "c"], ["a", "b", "c"])
    assert len(result) == 3
    assert all(c.type == ChangeType.KEEP for c in result)
    assert [c.value for c in result] == ["a", "b", "c"]
    assert apply_diff(["a", "b", "c"], result) == ["a", "b", "c"]

    # --- Test 5: Single element add ---
    result = diff(["a"], ["a", "b"])
    adds, removes, keeps = count_types(result)
    assert keeps == 1
    assert adds == 1
    assert removes == 0
    assert apply_diff(["a"], result) == ["a", "b"]

    # --- Test 6: Single element remove ---
    result = diff(["a", "b"], ["a"])
    adds, removes, keeps = count_types(result)
    assert keeps == 1
    assert removes == 1
    assert adds == 0
    assert apply_diff(["a", "b"], result) == ["a"]

    # --- Test 7: Single element replacement ---
    result = diff(["a"], ["b"])
    adds, removes, keeps = count_types(result)
    assert adds == 1
    assert removes == 1
    assert keeps == 0
    assert apply_diff(["a"], result) == ["b"]

    # --- Test 8: Classic diff example (ABCABBA -> CBABAC) ---
    a = list("ABCABBA")
    b = list("CBABAC")
    result = diff(a, b)
    assert apply_diff(a, result) == b

    # --- Test 9: Insertion in the middle ---
    result = diff(["a", "c"], ["a", "b", "c"])
    assert apply_diff(["a", "c"], result) == ["a", "b", "c"]
    adds, removes, keeps = count_types(result)
    assert keeps == 2
    assert adds == 1
    assert removes == 0

    # --- Test 10: Removal from the middle ---
    result = diff(["a", "b", "c"], ["a", "c"])
    assert apply_diff(["a", "b", "c"], result) == ["a", "c"]
    adds, removes, keeps = count_types(result)
    assert keeps == 2
    assert removes == 1
    assert adds == 0

    # --- Test 11: Completely different lists ---
    result = diff(["a", "b", "c"], ["x", "y", "z"])
    assert apply_diff(["a", "b", "c"], result) == ["x", "y", "z"]
    adds, removes, keeps = count_types(result)
    assert adds == 3
    assert removes == 3
    assert keeps == 0

    # --- Test 12: Duplicates in lists ---
    result = diff(["a", "a", "a"], ["a", "a"])
    assert apply_diff(["a", "a", "a"], result) == ["a", "a"]
    adds, removes, keeps = count_types(result)
    assert keeps == 2
    assert removes == 1

    # --- Test 13: Integer values ---
    result = diff([1, 2, 3], [1, 3, 4])
    assert apply_diff([1, 2, 3], result) == [1, 3, 4]
    adds, removes, keeps = count_types(result)
    assert keeps == 2  # 1 and 3
    assert removes == 1  # 2
    assert adds == 1  # 4

    # --- Test 14: Change objects have correct fields ---
    result = diff(["x"], ["y"])
    assert len(result) == 2
    for c in result:
        assert isinstance(c, Change)
        assert isinstance(c.type, ChangeType)
        assert isinstance(c.index, int)
        assert c.value in ("x", "y")

    # --- Test 15: Prefix preserved ---
    result = diff(["a", "b", "c", "d"], ["a", "b", "x", "y"])
    assert apply_diff(["a", "b", "c", "d"], result) == ["a", "b", "x", "y"]
    adds, removes, keeps = count_types(result)
    assert keeps == 2  # a, b

    # --- Test 16: Suffix preserved ---
    result = diff(["x", "y", "c", "d"], ["a", "b", "c", "d"])
    assert apply_diff(["x", "y", "c", "d"], result) == ["a", "b", "c", "d"]
    adds, removes, keeps = count_types(result)
    assert keeps == 2  # c, d

    # --- Test 17: Single element identical ---
    result = diff(["a"], ["a"])
    assert len(result) == 1
    assert result[0].type == ChangeType.KEEP
    assert result[0].value == "a"

    # --- Test 18: Large lists performance ---
    big_a = list(range(500))
    big_b = list(range(500))
    big_b[250] = -1  # one change in the middle
    result = diff(big_a, big_b)
    assert apply_diff(big_a, result) == big_b
    adds, removes, keeps = count_types(result)
    assert keeps == 499
    assert adds == 1
    assert removes == 1

    # --- Test 19: Ordering of changes is consistent ---
    result = diff(["a", "b"], ["b", "c"])
    reconstructed = apply_diff(["a", "b"], result)
    assert reconstructed == ["b", "c"]

    # --- Test 20: Diff minimality (Myers produces shortest edit script) ---
    a = list("ABCDEF")
    b = list("ABEF")
    result = diff(a, b)
    assert apply_diff(a, result) == b
    adds, removes, keeps = count_types(result)
    assert adds == 0
    assert removes == 2  # C, D removed
    assert keeps == 4  # A, B, E, F kept
    # Total edits should be minimal
    assert adds + removes == 2

    print("All 20 tests passed.")
