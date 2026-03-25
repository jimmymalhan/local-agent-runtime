"""TDD tests for CircuitBreaker(failure_threshold, reset_timeout)."""

import time
import unittest


class CircuitBreakerOpenError(Exception):
    """Raised when a call is attempted while the circuit is open."""
    pass


class CircuitBreaker:
    """Circuit breaker with three states: closed, open, half-open."""

    def __init__(self, failure_threshold: int, reset_timeout: float):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = "closed"
        self.failure_count = 0
        self._opened_at: float | None = None

    def call(self, func, *args, **kwargs):
        if self.state == "open":
            if time.monotonic() - self._opened_at >= self.reset_timeout:
                self.state = "half-open"
            else:
                raise CircuitBreakerOpenError("Circuit is open")

        try:
            result = func(*args, **kwargs)
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()
            return result

    def _record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            self._opened_at = time.monotonic()

    def _record_success(self):
        if self.state == "half-open":
            self.state = "closed"
        self.failure_count = 0


class TestCircuitBreakerStates(unittest.TestCase):
    """Test initial states and basic properties."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        assert cb.state == "closed"

    def test_initial_failure_count_is_zero(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        assert cb.failure_count == 0

    def test_successful_call_keeps_closed(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        result = cb.call(lambda: 42)
        assert result == 42
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_successful_call_passes_args(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        result = cb.call(lambda x, y: x + y, 3, 7)
        assert result == 10

    def test_successful_call_passes_kwargs(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        result = cb.call(lambda x, y=0: x + y, 5, y=10)
        assert result == 15


class TestCircuitBreakerFailures(unittest.TestCase):
    """Test failure counting and transition to open."""

    def _failing_func(self):
        raise RuntimeError("boom")

    def test_single_failure_increments_count(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        with self.assertRaises(RuntimeError):
            cb.call(self._failing_func)
        assert cb.failure_count == 1
        assert cb.state == "closed"

    def test_failures_below_threshold_stay_closed(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                cb.call(self._failing_func)
        assert cb.failure_count == 2
        assert cb.state == "closed"

    def test_reaching_threshold_opens_circuit(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        for _ in range(3):
            with self.assertRaises(RuntimeError):
                cb.call(self._failing_func)
        assert cb.state == "open"
        assert cb.failure_count == 3

    def test_exceeding_threshold_stays_open(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=5.0)
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                cb.call(self._failing_func)
        assert cb.state == "open"
        with self.assertRaises(CircuitBreakerOpenError):
            cb.call(lambda: 1)

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        with self.assertRaises(RuntimeError):
            cb.call(self._failing_func)
        assert cb.failure_count == 1
        cb.call(lambda: "ok")
        assert cb.failure_count == 0
        assert cb.state == "closed"


class TestCircuitBreakerOpen(unittest.TestCase):
    """Test open state behavior."""

    def _open_circuit(self, cb):
        for _ in range(cb.failure_threshold):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
            except RuntimeError:
                pass

    def test_open_circuit_rejects_calls(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=5.0)
        self._open_circuit(cb)
        assert cb.state == "open"
        with self.assertRaises(CircuitBreakerOpenError):
            cb.call(lambda: "should not run")

    def test_open_circuit_rejects_multiple_calls(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=5.0)
        self._open_circuit(cb)
        for _ in range(5):
            with self.assertRaises(CircuitBreakerOpenError):
                cb.call(lambda: "nope")
        assert cb.state == "open"

    def test_open_error_message(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=5.0)
        self._open_circuit(cb)
        try:
            cb.call(lambda: None)
            assert False, "Should have raised"
        except CircuitBreakerOpenError as e:
            assert "open" in str(e).lower()


class TestCircuitBreakerHalfOpen(unittest.TestCase):
    """Test half-open state transitions."""

    def _open_circuit(self, cb):
        for _ in range(cb.failure_threshold):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
            except RuntimeError:
                pass

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.1)
        self._open_circuit(cb)
        assert cb.state == "open"
        time.sleep(0.15)
        # Next call attempt should transition to half-open
        result = cb.call(lambda: "recovered")
        assert result == "recovered"
        assert cb.state == "closed"

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.1)
        self._open_circuit(cb)
        time.sleep(0.15)
        cb.call(lambda: "ok")
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_half_open_failure_reopens_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.1)
        self._open_circuit(cb)
        time.sleep(0.15)
        # This call will transition to half-open, then fail, reopening
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail again")))
        assert cb.state == "open"

    def test_stays_open_before_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=5.0)
        self._open_circuit(cb)
        with self.assertRaises(CircuitBreakerOpenError):
            cb.call(lambda: "too soon")
        assert cb.state == "open"


class TestCircuitBreakerFullCycle(unittest.TestCase):
    """Test complete lifecycle: closed -> open -> half-open -> closed."""

    def test_full_recovery_cycle(self):
        cb = CircuitBreaker(failure_threshold=2, reset_timeout=0.1)

        # Phase 1: closed, working
        assert cb.call(lambda: "a") == "a"
        assert cb.state == "closed"

        # Phase 2: failures trip the breaker
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("err")))
            except RuntimeError:
                pass
        assert cb.state == "open"

        # Phase 3: open, calls rejected
        with self.assertRaises(CircuitBreakerOpenError):
            cb.call(lambda: "blocked")

        # Phase 4: wait for timeout, half-open -> success -> closed
        time.sleep(0.15)
        assert cb.call(lambda: "back") == "back"
        assert cb.state == "closed"
        assert cb.failure_count == 0

        # Phase 5: normal operation resumes
        assert cb.call(lambda: "normal") == "normal"

    def test_repeated_open_close_cycles(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.05)

        for cycle in range(3):
            # Trip the breaker
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError(f"cycle {cycle}")))
            except RuntimeError:
                pass
            assert cb.state == "open", f"Cycle {cycle}: should be open"

            # Wait and recover
            time.sleep(0.08)
            cb.call(lambda: "ok")
            assert cb.state == "closed", f"Cycle {cycle}: should be closed"

    def test_partial_failures_then_success_resets(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)

        # 2 failures (below threshold)
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("err")))
            except RuntimeError:
                pass
        assert cb.failure_count == 2
        assert cb.state == "closed"

        # Success resets count
        cb.call(lambda: "ok")
        assert cb.failure_count == 0

        # Need 3 fresh failures to trip
        for _ in range(2):
            try:
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("err")))
            except RuntimeError:
                pass
        assert cb.state == "closed"  # Still closed, only 2 failures


class TestCircuitBreakerEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def test_threshold_of_one(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.1)
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("one")))
        assert cb.state == "open"

    def test_original_exception_propagates(self):
        cb = CircuitBreaker(failure_threshold=5, reset_timeout=1.0)

        with self.assertRaises(ValueError) as ctx:
            cb.call(lambda: (_ for _ in ()).throw(ValueError("specific")))
        assert "specific" in str(ctx.exception)

        with self.assertRaises(TypeError) as ctx:
            cb.call(lambda: (_ for _ in ()).throw(TypeError("type err")))
        assert "type err" in str(ctx.exception)

    def test_different_exception_types_all_count(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        exceptions = [RuntimeError("a"), ValueError("b"), TypeError("c")]
        for exc in exceptions:
            try:
                cb.call(lambda e=exc: (_ for _ in ()).throw(e))
            except Exception:
                pass
        assert cb.state == "open"
        assert cb.failure_count == 3

    def test_zero_timeout_immediately_half_opens(self):
        cb = CircuitBreaker(failure_threshold=1, reset_timeout=0)
        with self.assertRaises(RuntimeError):
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("trip")))
        assert cb.state == "open"
        # With 0 timeout, next call should transition to half-open immediately
        result = cb.call(lambda: "instant recovery")
        assert result == "instant recovery"
        assert cb.state == "closed"

    def test_call_with_stateful_function(self):
        cb = CircuitBreaker(failure_threshold=3, reset_timeout=1.0)
        counter = {"n": 0}

        def increment():
            counter["n"] += 1
            return counter["n"]

        assert cb.call(increment) == 1
        assert cb.call(increment) == 2
        assert cb.call(increment) == 3


if __name__ == "__main__":
    # Run with assertions via unittest
    unittest.main(verbosity=2)
