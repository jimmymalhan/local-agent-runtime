"""
Refactor: Extract Strategy Pattern from sorting function.

Before (violates OCP):
    def sort_data(data, algorithm):
        if algorithm == "bubble": ...
        elif algorithm == "merge": ...
        elif algorithm == "quick": ...
        elif algorithm == "heap": ...
        elif algorithm == "radix": ...

After (OCP-compliant):
    Register new strategies without modifying existing code.
"""

from abc import ABC, abstractmethod
from typing import List


# ---------- Strategy interface ----------

class SortStrategy(ABC):
    @abstractmethod
    def sort(self, data: List[int]) -> List[int]:
        ...


# ---------- Concrete strategies ----------

class BubbleSort(SortStrategy):
    def sort(self, data: List[int]) -> List[int]:
        a = data[:]
        n = len(a)
        for i in range(n):
            for j in range(0, n - i - 1):
                if a[j] > a[j + 1]:
                    a[j], a[j + 1] = a[j + 1], a[j]
        return a


class MergeSort(SortStrategy):
    def sort(self, data: List[int]) -> List[int]:
        if len(data) <= 1:
            return data[:]
        mid = len(data) // 2
        left = self.sort(data[:mid])
        right = self.sort(data[mid:])
        return self._merge(left, right)

    @staticmethod
    def _merge(left: List[int], right: List[int]) -> List[int]:
        result = []
        i = j = 0
        while i < len(left) and j < len(right):
            if left[i] <= right[j]:
                result.append(left[i])
                i += 1
            else:
                result.append(right[j])
                j += 1
        result.extend(left[i:])
        result.extend(right[j:])
        return result


class QuickSort(SortStrategy):
    def sort(self, data: List[int]) -> List[int]:
        a = data[:]
        self._quicksort(a, 0, len(a) - 1)
        return a

    def _quicksort(self, a: List[int], low: int, high: int) -> None:
        if low < high:
            pi = self._partition(a, low, high)
            self._quicksort(a, low, pi - 1)
            self._quicksort(a, pi + 1, high)

    @staticmethod
    def _partition(a: List[int], low: int, high: int) -> int:
        pivot = a[high]
        i = low - 1
        for j in range(low, high):
            if a[j] <= pivot:
                i += 1
                a[i], a[j] = a[j], a[i]
        a[i + 1], a[high] = a[high], a[i + 1]
        return i + 1


class HeapSort(SortStrategy):
    def sort(self, data: List[int]) -> List[int]:
        a = data[:]
        n = len(a)
        for i in range(n // 2 - 1, -1, -1):
            self._heapify(a, n, i)
        for i in range(n - 1, 0, -1):
            a[0], a[i] = a[i], a[0]
            self._heapify(a, i, 0)
        return a

    @staticmethod
    def _heapify(a: List[int], n: int, i: int) -> None:
        largest = i
        left = 2 * i + 1
        right = 2 * i + 2
        if left < n and a[left] > a[largest]:
            largest = left
        if right < n and a[right] > a[largest]:
            largest = right
        if largest != i:
            a[i], a[largest] = a[largest], a[i]
            HeapSort._heapify(a, n, largest)


class RadixSort(SortStrategy):
    def sort(self, data: List[int]) -> List[int]:
        a = data[:]
        if not a:
            return a
        max_val = max(a)
        exp = 1
        while max_val // exp > 0:
            self._counting_sort(a, exp)
            exp *= 10
        return a

    @staticmethod
    def _counting_sort(a: List[int], exp: int) -> None:
        n = len(a)
        output = [0] * n
        count = [0] * 10
        for i in range(n):
            index = (a[i] // exp) % 10
            count[index] += 1
        for i in range(1, 10):
            count[i] += count[i - 1]
        for i in range(n - 1, -1, -1):
            index = (a[i] // exp) % 10
            output[count[index] - 1] = a[i]
            count[index] -= 1
        for i in range(n):
            a[i] = output[i]


# ---------- Strategy registry (OCP: add strategies without modifying Sorter) ----------

class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[str, SortStrategy] = {}

    def register(self, name: str, strategy: SortStrategy) -> None:
        self._strategies[name] = strategy

    def get(self, name: str) -> SortStrategy:
        if name not in self._strategies:
            available = ", ".join(sorted(self._strategies))
            raise ValueError(
                f"Unknown sort strategy '{name}'. Available: {available}"
            )
        return self._strategies[name]

    @property
    def available(self) -> list[str]:
        return sorted(self._strategies)


# ---------- Context ----------

class Sorter:
    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry

    def sort(self, data: List[int], algorithm: str) -> List[int]:
        strategy = self._registry.get(algorithm)
        return strategy.sort(data)


# ---------- Factory with defaults ----------

def create_default_sorter() -> Sorter:
    registry = StrategyRegistry()
    registry.register("bubble", BubbleSort())
    registry.register("merge", MergeSort())
    registry.register("quick", QuickSort())
    registry.register("heap", HeapSort())
    registry.register("radix", RadixSort())
    return Sorter(registry)


# ---------- Original function (before refactor, for comparison) ----------

def sort_data_before(data: List[int], algorithm: str) -> List[int]:
    """The old approach: violates OCP — adding a new algorithm means editing this function."""
    if algorithm == "bubble":
        a = data[:]
        n = len(a)
        for i in range(n):
            for j in range(0, n - i - 1):
                if a[j] > a[j + 1]:
                    a[j], a[j + 1] = a[j + 1], a[j]
        return a
    elif algorithm == "merge":
        return MergeSort().sort(data)
    elif algorithm == "quick":
        return QuickSort().sort(data)
    elif algorithm == "heap":
        return HeapSort().sort(data)
    elif algorithm == "radix":
        return RadixSort().sort(data)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}")


# ---------- Demonstrate OCP: add a new strategy without touching Sorter ----------

class TimSort(SortStrategy):
    """Wraps Python's built-in sorted() — added without modifying any existing class."""
    def sort(self, data: List[int]) -> List[int]:
        return sorted(data)


# ---------- main ----------

if __name__ == "__main__":
    test_cases = [
        [64, 34, 25, 12, 22, 11, 90],
        [5, 1, 4, 2, 8],
        [1],
        [3, 3, 3],
        [10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
        [1, 2, 3, 4, 5],
    ]

    sorter = create_default_sorter()

    # Verify all 5 original strategies produce correct results
    for algorithm in ["bubble", "merge", "quick", "heap", "radix"]:
        for data in test_cases:
            result = sorter.sort(data, algorithm)
            expected = sorted(data)
            assert result == expected, (
                f"{algorithm} failed on {data}: got {result}, expected {expected}"
            )
    print("All 5 strategies pass on all test cases.")

    # Demonstrate OCP: register a new strategy without modifying Sorter or StrategyRegistry
    sorter._registry.register("timsort", TimSort())
    for data in test_cases:
        result = sorter.sort(data, "timsort")
        assert result == sorted(data), f"timsort failed on {data}"
    print("OCP demonstrated: TimSort added without modifying existing code.")

    # Verify unknown strategy raises ValueError
    try:
        sorter.sort([1, 2, 3], "bogus")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown sort strategy" in str(e)
    print("Unknown strategy error handling works.")

    # Verify original data is not mutated
    original = [5, 3, 1, 4, 2]
    copy = original[:]
    for algorithm in ["bubble", "merge", "quick", "heap", "radix", "timsort"]:
        sorter.sort(original, algorithm)
        assert original == copy, f"{algorithm} mutated the input list"
    print("No strategy mutates the input list.")

    print("\nAll assertions passed.")
