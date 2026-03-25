"""TDD tests for a token bucket rate limiter."""

import threading
import time
import unittest


class TokenBucket:
    """Token bucket rate limiter with automatic refill."""

    def __init__(self, rate: float, capacity: int):
        """
        Args:
            rate: Tokens added per second.
            capacity: Maximum number of tokens the bucket can hold.
        """
        if rate <= 0:
            raise ValueError("rate must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.rate = rate
        self.capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self.rate
        self._tokens = min(self.capacity, self._tokens + new_tokens)
        self._last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful, False otherwise."""
        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


class TestTokenBucketInit(unittest.TestCase):
    """Tests for bucket initialization."""

    def test_initial_tokens_equal_capacity(self):
        bucket = TokenBucket(rate=10, capacity=5)
        assert bucket.available == 5

    def test_rate_stored(self):
        bucket = TokenBucket(rate=7.5, capacity=10)
        assert bucket.rate == 7.5

    def test_capacity_stored(self):
        bucket = TokenBucket(rate=1, capacity=100)
        assert bucket.capacity == 100

    def test_zero_rate_raises(self):
        with self.assertRaises(ValueError):
            TokenBucket(rate=0, capacity=10)

    def test_negative_rate_raises(self):
        with self.assertRaises(ValueError):
            TokenBucket(rate=-1, capacity=10)

    def test_zero_capacity_raises(self):
        with self.assertRaises(ValueError):
            TokenBucket(rate=1, capacity=0)

    def test_negative_capacity_raises(self):
        with self.assertRaises(ValueError):
            TokenBucket(rate=1, capacity=-5)


class TestTokenBucketConsume(unittest.TestCase):
    """Tests for basic consume behavior."""

    def test_consume_single_token(self):
        bucket = TokenBucket(rate=1, capacity=10)
        assert bucket.consume(1) is True

    def test_consume_reduces_available(self):
        bucket = TokenBucket(rate=1, capacity=10)
        bucket.consume(3)
        assert bucket.available <= 7.0 + 0.1  # small tolerance for refill

    def test_consume_all_tokens(self):
        bucket = TokenBucket(rate=1, capacity=5)
        assert bucket.consume(5) is True

    def test_consume_more_than_available_fails(self):
        bucket = TokenBucket(rate=1, capacity=5)
        assert bucket.consume(6) is False

    def test_consume_exact_capacity(self):
        bucket = TokenBucket(rate=1, capacity=10)
        assert bucket.consume(10) is True
        # Next consume should fail (no time to refill)
        assert bucket.consume(1) is False

    def test_consume_zero_tokens_succeeds(self):
        bucket = TokenBucket(rate=1, capacity=5)
        assert bucket.consume(0) is True

    def test_consume_negative_tokens_raises(self):
        bucket = TokenBucket(rate=1, capacity=5)
        with self.assertRaises(ValueError):
            bucket.consume(-1)

    def test_sequential_consumes_drain_bucket(self):
        bucket = TokenBucket(rate=1, capacity=3)
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True
        assert bucket.consume(1) is False

    def test_default_consume_one(self):
        bucket = TokenBucket(rate=1, capacity=2)
        assert bucket.consume() is True
        assert bucket.consume() is True
        assert bucket.consume() is False


class TestTokenBucketRefill(unittest.TestCase):
    """Tests for automatic refill behavior."""

    def test_refill_after_wait(self):
        bucket = TokenBucket(rate=100, capacity=10)
        bucket.consume(10)
        assert bucket.consume(1) is False
        time.sleep(0.05)  # 100 tokens/sec * 0.05s = 5 tokens
        assert bucket.consume(1) is True

    def test_refill_does_not_exceed_capacity(self):
        bucket = TokenBucket(rate=1000, capacity=5)
        time.sleep(0.1)  # Would add 100 tokens, but capped at 5
        assert bucket.available <= 5.0

    def test_partial_refill(self):
        bucket = TokenBucket(rate=100, capacity=100)
        bucket.consume(100)
        time.sleep(0.05)  # ~5 tokens refilled
        available = bucket.available
        assert 3 <= available <= 8  # tolerance for timing

    def test_refill_rate_accuracy(self):
        bucket = TokenBucket(rate=200, capacity=200)
        bucket.consume(200)
        time.sleep(0.1)  # expect ~20 tokens
        available = bucket.available
        assert 15 <= available <= 25  # timing tolerance

    def test_multiple_refill_cycles(self):
        bucket = TokenBucket(rate=100, capacity=5)
        bucket.consume(5)
        time.sleep(0.05)
        assert bucket.consume(3) is True
        bucket.consume(bucket.capacity)  # drain
        time.sleep(0.05)
        assert bucket.consume(1) is True


class TestTokenBucketThreadSafety(unittest.TestCase):
    """Thread-safety tests with concurrent callers."""

    def test_concurrent_consume_no_overdraft(self):
        """Many threads consuming should never overdraft the bucket."""
        capacity = 100
        bucket = TokenBucket(rate=0.001, capacity=capacity)  # near-zero refill
        successes = []
        barrier = threading.Barrier(20)

        def worker():
            barrier.wait()
            result = bucket.consume(1)
            successes.append(result)

        threads = [threading.Thread(target=worker) for _ in range(200)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        success_count = sum(1 for s in successes if s)
        # Cannot have consumed more than capacity (plus tiny refill)
        assert success_count <= capacity + 2  # small tolerance

    def test_concurrent_consume_total_tokens_bounded(self):
        """Total consumed tokens across threads must not exceed capacity + refilled."""
        capacity = 50
        bucket = TokenBucket(rate=0.001, capacity=capacity)
        consumed = []
        lock = threading.Lock()

        def worker():
            for _ in range(10):
                if bucket.consume(1):
                    with lock:
                        consumed.append(1)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = sum(consumed)
        assert total <= capacity + 2

    def test_concurrent_mixed_consume_sizes(self):
        """Threads consuming different amounts should still be safe."""
        bucket = TokenBucket(rate=0.001, capacity=100)
        results = {"total": 0}
        lock = threading.Lock()

        def small_consumer():
            for _ in range(20):
                if bucket.consume(1):
                    with lock:
                        results["total"] += 1

        def large_consumer():
            for _ in range(5):
                if bucket.consume(10):
                    with lock:
                        results["total"] += 10

        threads = []
        for _ in range(10):
            threads.append(threading.Thread(target=small_consumer))
            threads.append(threading.Thread(target=large_consumer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["total"] <= 102

    def test_no_race_condition_on_refill(self):
        """Concurrent access during refill should not corrupt token count."""
        bucket = TokenBucket(rate=1000, capacity=1000)
        bucket.consume(1000)
        errors = []

        def consumer():
            for _ in range(100):
                try:
                    bucket.consume(1)
                except Exception as e:
                    errors.append(e)
                time.sleep(0.001)

        threads = [threading.Thread(target=consumer) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert bucket.available >= 0

    def test_concurrent_available_reads(self):
        """Reading available tokens concurrently with consumes should not crash."""
        bucket = TokenBucket(rate=100, capacity=50)
        errors = []

        def reader():
            for _ in range(200):
                try:
                    val = bucket.available
                    assert val >= 0
                except Exception as e:
                    errors.append(e)

        def consumer():
            for _ in range(200):
                bucket.consume(1)
                time.sleep(0.001)

        threads = []
        for _ in range(5):
            threads.append(threading.Thread(target=reader))
            threads.append(threading.Thread(target=consumer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestTokenBucketEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def test_fractional_rate(self):
        bucket = TokenBucket(rate=0.5, capacity=10)
        bucket.consume(10)
        time.sleep(1.0)  # 0.5 tokens/sec * 1s = 0.5 token
        assert bucket.available < 1.0

    def test_large_capacity(self):
        bucket = TokenBucket(rate=1, capacity=1_000_000)
        assert bucket.consume(999_999) is True
        assert bucket.consume(2) is False

    def test_high_rate(self):
        bucket = TokenBucket(rate=1_000_000, capacity=100)
        bucket.consume(100)
        time.sleep(0.01)
        assert bucket.available > 0

    def test_consume_more_than_capacity_always_fails(self):
        bucket = TokenBucket(rate=1000, capacity=5)
        assert bucket.consume(6) is False
        time.sleep(0.1)
        assert bucket.consume(6) is False  # still fails, capacity is 5

    def test_burst_then_steady(self):
        """Bucket allows burst up to capacity, then limits to rate."""
        bucket = TokenBucket(rate=10, capacity=5)
        # Burst: consume all 5 at once
        assert bucket.consume(5) is True
        # Immediately after, should fail
        assert bucket.consume(1) is False
        # Wait for refill
        time.sleep(0.15)  # ~1.5 tokens
        assert bucket.consume(1) is True


if __name__ == "__main__":
    # Run with assertions first for quick smoke test
    print("Running smoke tests...")

    # Basic init
    b = TokenBucket(rate=10, capacity=5)
    assert b.available == 5
    assert b.rate == 10
    assert b.capacity == 5

    # Basic consume
    assert b.consume(3) is True
    assert b.consume(3) is False
    assert b.consume(2) is True
    assert b.consume(1) is False

    # Refill
    b2 = TokenBucket(rate=200, capacity=10)
    b2.consume(10)
    time.sleep(0.05)
    assert b2.consume(5) is True

    # Capacity cap
    b3 = TokenBucket(rate=10000, capacity=3)
    time.sleep(0.1)
    assert b3.available <= 3.0

    # Thread safety smoke test
    b4 = TokenBucket(rate=0.001, capacity=50)
    results = []
    def _worker():
        results.append(b4.consume(1))
    threads = [threading.Thread(target=_worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for r in results if r) <= 52

    print("All smoke tests passed.")
    print()

    # Run full unittest suite
    unittest.main(verbosity=2)
