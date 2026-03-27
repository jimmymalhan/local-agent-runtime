"""
Refactor: Optimize Hot Path with Profiling

Demonstrates profiling a slow function with cProfile, identifying the top 3
bottlenecks, and applying targeted fixes for a 10x+ improvement.

Scenario: A data pipeline that processes sensor readings — deduplicates them,
enriches each with a category lookup, and computes rolling statistics.
"""

import cProfile
import io
import pstats
import random
import time
from collections import defaultdict
from functools import lru_cache


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

NUM_READINGS = 8_000
NUM_CATEGORIES = 200
WINDOW_SIZE = 50

random.seed(42)

CATEGORIES = {f"sensor_{i}": f"category_{i % 20}" for i in range(NUM_CATEGORIES)}
READINGS = [
    {
        "sensor_id": f"sensor_{random.randint(0, NUM_CATEGORIES - 1)}",
        "value": round(random.uniform(0, 100), 2),
        "timestamp": 1_700_000_000 + i,
    }
    for i in range(NUM_READINGS)
]
# Inject ~30% duplicates by timestamp
for i in range(0, NUM_READINGS, 3):
    READINGS.append({**READINGS[i]})
random.shuffle(READINGS)


# ===================================================================
# SLOW VERSION — three deliberate bottlenecks
# ===================================================================

def slow_deduplicate(readings: list[dict]) -> list[dict]:
    """Bottleneck 1: O(n^2) duplicate check via list scan."""
    seen: list[int] = []
    result: list[dict] = []
    for r in readings:
        ts = r["timestamp"]
        if ts not in seen:          # O(n) membership test on list
            seen.append(ts)
            result.append(r)
    return result


def slow_enrich(readings: list[dict]) -> list[dict]:
    """Bottleneck 2: Repeated deep-copy + linear category lookup per item."""
    enriched: list[dict] = []
    for r in readings:
        # Unnecessary full-dict copy every iteration
        copy = {k: v for k, v in r.items()}
        # Linear scan through all categories instead of direct lookup
        for sensor_id, cat in CATEGORIES.items():
            if sensor_id == copy["sensor_id"]:
                copy["category"] = cat
                break
        enriched.append(copy)
    return enriched


def slow_rolling_stats(readings: list[dict], window: int) -> list[dict]:
    """Bottleneck 3: Recomputes full window sum from scratch each step."""
    results: list[dict] = []
    for i in range(len(readings)):
        start = max(0, i - window + 1)
        window_vals = [readings[j]["value"] for j in range(start, i + 1)]
        avg = sum(window_vals) / len(window_vals)
        mx = max(window_vals)
        mn = min(window_vals)
        results.append({
            **readings[i],
            "rolling_avg": round(avg, 4),
            "rolling_max": mx,
            "rolling_min": mn,
        })
    return results


def slow_pipeline(readings: list[dict]) -> list[dict]:
    deduped = slow_deduplicate(readings)
    enriched = slow_enrich(deduped)
    return slow_rolling_stats(enriched, WINDOW_SIZE)


# ===================================================================
# FAST VERSION — targeted fixes for each bottleneck
# ===================================================================

def fast_deduplicate(readings: list[dict]) -> list[dict]:
    """Fix 1: O(1) membership test with a set."""
    seen: set[int] = set()
    result: list[dict] = []
    for r in readings:
        ts = r["timestamp"]
        if ts not in seen:
            seen.add(ts)
            result.append(r)
    return result


def fast_enrich(readings: list[dict]) -> list[dict]:
    """Fix 2: Direct dict lookup (O(1)), mutate in-place instead of copying."""
    for r in readings:
        r["category"] = CATEGORIES.get(r["sensor_id"], "unknown")
    return readings


def fast_rolling_stats(readings: list[dict], window: int) -> list[dict]:
    """Fix 3: Incremental sliding-window with a deque-style approach."""
    from collections import deque

    results: list[dict] = []
    win: deque[float] = deque()
    running_sum = 0.0
    # For O(1) min/max we maintain sorted auxiliary structures;
    # here we use simple deques that track monotonic extremes.
    max_deque: deque[tuple[int, float]] = deque()  # (index, value) decreasing
    min_deque: deque[tuple[int, float]] = deque()  # (index, value) increasing

    for i, r in enumerate(readings):
        v = r["value"]
        win.append(v)
        running_sum += v

        # Maintain monotonic deques for O(1) max/min
        while max_deque and max_deque[-1][1] <= v:
            max_deque.pop()
        max_deque.append((i, v))

        while min_deque and min_deque[-1][1] >= v:
            min_deque.pop()
        min_deque.append((i, v))

        # Evict elements outside window
        if len(win) > window:
            old = win.popleft()
            running_sum -= old
            if max_deque[0][0] <= i - window:
                max_deque.popleft()
            if min_deque[0][0] <= i - window:
                min_deque.popleft()

        avg = running_sum / len(win)
        r["rolling_avg"] = round(avg, 4)
        r["rolling_max"] = max_deque[0][1]
        r["rolling_min"] = min_deque[0][1]
        results.append(r)

    return results


def fast_pipeline(readings: list[dict]) -> list[dict]:
    deduped = fast_deduplicate(readings)
    enriched = fast_enrich(deduped)
    return fast_rolling_stats(enriched, WINDOW_SIZE)


# ===================================================================
# Profiling helpers
# ===================================================================

def profile_function(func, *args, **kwargs):
    """Run func under cProfile, return (result, stats_string, elapsed)."""
    pr = cProfile.Profile()
    t0 = time.perf_counter()
    pr.enable()
    result = func(*args, **kwargs)
    pr.disable()
    elapsed = time.perf_counter() - t0

    stream = io.StringIO()
    ps = pstats.Stats(pr, stream=stream)
    ps.sort_stats("cumulative")
    ps.print_stats(15)
    return result, stream.getvalue(), elapsed


def top_bottlenecks(stats_text: str, n: int = 3) -> list[str]:
    """Extract top-n function names from cProfile output."""
    lines = stats_text.strip().splitlines()
    funcs: list[str] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("ncalls") or line.startswith("Ordered"):
            continue
        parts = line.rsplit(None, 1)
        if len(parts) == 2 and ("(" in parts[-1] or "<" in parts[-1]):
            funcs.append(parts[-1])
        if len(funcs) == n:
            break
    return funcs


# ===================================================================
# Main: profile, compare, assert improvement
# ===================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("PROFILING SLOW PIPELINE")
    print("=" * 70)

    slow_data = [dict(r) for r in READINGS]  # fresh copy
    slow_result, slow_stats, slow_time = profile_function(slow_pipeline, slow_data)
    print(slow_stats)
    print(f"Slow pipeline: {slow_time:.4f}s  ({len(slow_result)} records)\n")

    bottlenecks = top_bottlenecks(slow_stats)
    print("Top bottlenecks identified:")
    for i, b in enumerate(bottlenecks, 1):
        print(f"  {i}. {b}")

    print("\n" + "=" * 70)
    print("PROFILING FAST PIPELINE")
    print("=" * 70)

    fast_data = [dict(r) for r in READINGS]  # fresh copy
    fast_result, fast_stats, fast_time = profile_function(fast_pipeline, fast_data)
    print(fast_stats)
    print(f"Fast pipeline: {fast_time:.4f}s  ({len(fast_result)} records)\n")

    # ------------------------------------------------------------------
    # Correctness assertions
    # ------------------------------------------------------------------
    assert len(slow_result) == len(fast_result), (
        f"Length mismatch: slow={len(slow_result)} fast={len(fast_result)}"
    )

    for i, (s, f) in enumerate(zip(slow_result, fast_result)):
        assert s["sensor_id"] == f["sensor_id"], f"sensor_id mismatch at {i}"
        assert s["value"] == f["value"], f"value mismatch at {i}"
        assert s["timestamp"] == f["timestamp"], f"timestamp mismatch at {i}"
        assert s["category"] == f["category"], f"category mismatch at {i}"
        assert abs(s["rolling_avg"] - f["rolling_avg"]) < 1e-3, (
            f"rolling_avg mismatch at {i}: {s['rolling_avg']} vs {f['rolling_avg']}"
        )
        assert s["rolling_max"] == f["rolling_max"], f"rolling_max mismatch at {i}"
        assert s["rolling_min"] == f["rolling_min"], f"rolling_min mismatch at {i}"

    print("All correctness assertions passed.\n")

    # ------------------------------------------------------------------
    # Speedup assertion
    # ------------------------------------------------------------------
    speedup = slow_time / fast_time
    print(f"Speedup: {speedup:.1f}x  (slow={slow_time:.4f}s, fast={fast_time:.4f}s)")

    assert speedup >= 10, (
        f"Expected >=10x speedup, got {speedup:.1f}x. "
        f"slow={slow_time:.4f}s fast={fast_time:.4f}s"
    )
    print(f"10x improvement target met ({speedup:.1f}x).")

    # ------------------------------------------------------------------
    # Summary of fixes
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("BOTTLENECK ANALYSIS & FIXES")
    print("=" * 70)
    print("""
Bottleneck 1 — slow_deduplicate (O(n^2) list membership)
  Problem : `if ts not in seen` on a plain list is O(n) per check.
  Fix     : Replace list with set for O(1) membership.

Bottleneck 2 — slow_enrich (unnecessary copies + linear category scan)
  Problem : Dict comprehension copy per reading + linear scan of
            CATEGORIES dict items instead of direct key lookup.
  Fix     : Direct dict.get() lookup (O(1)), mutate in-place.

Bottleneck 3 — slow_rolling_stats (recompute full window each step)
  Problem : Rebuilds window list and recomputes sum/max/min from
            scratch at every index — O(n * window).
  Fix     : Incremental running sum + monotonic deques for O(1)
            amortized max/min per step.
""")
