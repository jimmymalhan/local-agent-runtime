#!/usr/bin/env python3
"""
rate_limiter.py — Rate Limiting & DDoS Protection
===================================================
Per-IP, per-user, per-endpoint rate limits with sliding windows,
token buckets, and circuit breakers for downstream protection.
"""
import time
import threading
from collections import defaultdict
import hashlib
import functools
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum


# ---------------------------------------------------------------------------
# Rate Limit Result
# ---------------------------------------------------------------------------

class RateLimitResult:
    """Result of a rate limit check."""

    __slots__ = ("allowed", "remaining", "reset_at", "retry_after", "reason")

    def __init__(
        self,
        allowed: bool,
        remaining: int = 0,
        reset_at: float = 0.0,
        retry_after: float = 0.0,
        reason: str = "",
    ):
        self.allowed = allowed
        self.remaining = remaining
        self.reset_at = reset_at
        self.retry_after = retry_after
        self.reason = reason

    def __repr__(self):
        return (
            f"RateLimitResult(allowed={self.allowed}, remaining={self.remaining}, "
            f"retry_after={self.retry_after:.1f}s, reason={self.reason!r})"
        )

    def to_headers(self) -> Dict[str, str]:
        """Generate standard rate limit HTTP headers."""
        headers = {
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(int(self.reset_at)),
        }
        if not self.allowed:
            headers["Retry-After"] = str(int(self.retry_after) + 1)
        return headers


# ---------------------------------------------------------------------------
# Sliding Window Rate Limiter
# ---------------------------------------------------------------------------

class SlidingWindowLimiter:
    """
    Sliding window log rate limiter.
    Tracks exact timestamps of requests within the window for accurate limiting.
    """

    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str, now: Optional[float] = None) -> RateLimitResult:
        """Check if a request is allowed without consuming a slot."""
        now = now or time.monotonic()
        with self._lock:
            self._prune(key, now)
            count = len(self._requests[key])
            remaining = max(0, self.max_requests - count)
            reset_at = now + self.window_seconds
            if count >= self.max_requests:
                oldest = self._requests[key][0]
                retry_after = oldest + self.window_seconds - now
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=reset_at,
                    retry_after=max(0, retry_after),
                    reason=f"Rate limit exceeded: {count}/{self.max_requests} in {self.window_seconds}s window",
                )
            return RateLimitResult(allowed=True, remaining=remaining, reset_at=reset_at)

    def acquire(self, key: str, now: Optional[float] = None) -> RateLimitResult:
        """Try to acquire a slot. Returns result with allowed=True if granted."""
        now = now or time.monotonic()
        with self._lock:
            self._prune(key, now)
            count = len(self._requests[key])
            reset_at = now + self.window_seconds
            if count >= self.max_requests:
                oldest = self._requests[key][0]
                retry_after = oldest + self.window_seconds - now
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=reset_at,
                    retry_after=max(0, retry_after),
                    reason=f"Rate limit exceeded: {count}/{self.max_requests} in {self.window_seconds}s window",
                )
            self._requests[key].append(now)
            remaining = self.max_requests - count - 1
            return RateLimitResult(allowed=True, remaining=remaining, reset_at=reset_at)

    def _prune(self, key: str, now: float):
        """Remove timestamps outside the current window."""
        cutoff = now - self.window_seconds
        entries = self._requests[key]
        # Binary-style prune: find first entry within window
        idx = 0
        for i, ts in enumerate(entries):
            if ts > cutoff:
                idx = i
                break
        else:
            idx = len(entries)
        if idx > 0:
            self._requests[key] = entries[idx:]

    def reset(self, key: str):
        """Reset limits for a key."""
        with self._lock:
            self._requests.pop(key, None)

    def reset_all(self):
        """Reset all tracked keys."""
        with self._lock:
            self._requests.clear()


# ---------------------------------------------------------------------------
# Token Bucket Rate Limiter
# ---------------------------------------------------------------------------

class TokenBucket:
    """
    Token bucket algorithm for burst-tolerant rate limiting.
    Allows short bursts up to bucket capacity while enforcing sustained rate.
    """

    def __init__(self, capacity: int, refill_rate: float):
        """
        Args:
            capacity: Maximum tokens (burst size).
            refill_rate: Tokens added per second.
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens: Dict[str, float] = {}
        self._last_refill: Dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str, tokens: int = 1, now: Optional[float] = None) -> RateLimitResult:
        """Try to consume tokens from the bucket."""
        now = now or time.monotonic()
        with self._lock:
            self._refill(key, now)
            current = self._tokens.get(key, self.capacity)
            if current >= tokens:
                self._tokens[key] = current - tokens
                remaining = int(self._tokens[key])
                return RateLimitResult(
                    allowed=True,
                    remaining=remaining,
                    reset_at=now + (self.capacity - remaining) / max(self.refill_rate, 0.001),
                )
            else:
                deficit = tokens - current
                retry_after = deficit / max(self.refill_rate, 0.001)
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    reset_at=now + retry_after,
                    retry_after=retry_after,
                    reason=f"Token bucket empty: {current:.1f}/{self.capacity} tokens available, need {tokens}",
                )

    def _refill(self, key: str, now: float):
        """Add tokens based on elapsed time."""
        last = self._last_refill.get(key)
        if last is None:
            self._tokens[key] = self.capacity
            self._last_refill[key] = now
            return
        elapsed = now - last
        if elapsed <= 0:
            return
        current = self._tokens.get(key, self.capacity)
        new_tokens = elapsed * self.refill_rate
        self._tokens[key] = min(self.capacity, current + new_tokens)
        self._last_refill[key] = now

    def reset(self, key: str):
        """Reset bucket for a key."""
        with self._lock:
            self._tokens.pop(key, None)
            self._last_refill.pop(key, None)

    def reset_all(self):
        """Reset all buckets."""
        with self._lock:
            self._tokens.clear()
            self._last_refill.clear()


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation, requests flow through
    OPEN = "open"            # Failures exceeded threshold, requests blocked
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker pattern for downstream service protection.

    CLOSED  -> (failures >= threshold)  -> OPEN
    OPEN    -> (timeout elapsed)        -> HALF_OPEN
    HALF_OPEN -> (success)              -> CLOSED
    HALF_OPEN -> (failure)              -> OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
        success_threshold: int = 1,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Current state (may transition from OPEN -> HALF_OPEN on read)."""
        with self._lock:
            if self._state == CircuitState.OPEN:
                now = time.monotonic()
                if now - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    self._success_count = 0
            return self._state

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        state = self.state  # Triggers potential state transition
        with self._lock:
            if state == CircuitState.CLOSED:
                return True
            elif state == CircuitState.OPEN:
                return False
            else:  # HALF_OPEN
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

    def record_success(self):
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                # Decay failures on success
                self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self):
        """Record a failed call."""
        now = time.monotonic()
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = now
            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._half_open_calls = 0
                self._success_count = 0
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN

    def reset(self):
        """Force reset to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = 0.0

    def get_stats(self) -> Dict[str, Any]:
        """Return circuit breaker stats."""
        return {
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


# ---------------------------------------------------------------------------
# Per-Endpoint Circuit Breaker Registry
# ---------------------------------------------------------------------------

class CircuitBreakerRegistry:
    """Manages circuit breakers per endpoint/service."""

    def __init__(self, default_config: Optional[Dict[str, Any]] = None):
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._configs: Dict[str, Dict[str, Any]] = {}
        self._default_config = default_config or {
            "failure_threshold": 5,
            "recovery_timeout": 30.0,
            "half_open_max_calls": 1,
            "success_threshold": 1,
        }
        self._lock = threading.Lock()

    def configure(self, endpoint: str, **kwargs):
        """Set custom config for an endpoint."""
        with self._lock:
            self._configs[endpoint] = kwargs
            # Recreate breaker if it exists
            if endpoint in self._breakers:
                self._breakers[endpoint] = CircuitBreaker(**kwargs)

    def get(self, endpoint: str) -> CircuitBreaker:
        """Get or create circuit breaker for endpoint."""
        with self._lock:
            if endpoint not in self._breakers:
                config = self._configs.get(endpoint, self._default_config)
                self._breakers[endpoint] = CircuitBreaker(**config)
            return self._breakers[endpoint]

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats for all circuit breakers."""
        with self._lock:
            return {ep: cb.get_stats() for ep, cb in self._breakers.items()}


# ---------------------------------------------------------------------------
# DDoS Detection — Burst & Pattern Analyzer
# ---------------------------------------------------------------------------

class DDoSDetector:
    """
    Detects DDoS patterns by analyzing request rates and burst behavior.
    Uses multiple signal layers:
    1. Global rate spike detection
    2. Per-IP burst detection
    3. Repeated identical request fingerprint detection
    """

    def __init__(
        self,
        global_rps_limit: int = 1000,
        per_ip_burst_limit: int = 50,
        per_ip_burst_window: float = 10.0,
        fingerprint_threshold: int = 20,
        fingerprint_window: float = 60.0,
        ban_duration: float = 300.0,
    ):
        self.global_rps_limit = global_rps_limit
        self.per_ip_burst_limit = per_ip_burst_limit
        self.per_ip_burst_window = per_ip_burst_window
        self.fingerprint_threshold = fingerprint_threshold
        self.fingerprint_window = fingerprint_window
        self.ban_duration = ban_duration

        self._global_limiter = SlidingWindowLimiter(global_rps_limit, 1.0)
        self._ip_burst_limiter = SlidingWindowLimiter(per_ip_burst_limit, per_ip_burst_window)
        self._fingerprint_limiter = SlidingWindowLimiter(fingerprint_threshold, fingerprint_window)
        self._banned: Dict[str, float] = {}  # ip -> ban_expires_at (monotonic)
        self._lock = threading.Lock()

    def check_request(
        self,
        ip: str,
        endpoint: str = "",
        fingerprint: str = "",
        now: Optional[float] = None,
    ) -> RateLimitResult:
        """
        Analyze a request for DDoS indicators.
        Returns allowed=False if any DDoS signal triggers.
        """
        now = now or time.monotonic()

        # Check ban list first
        with self._lock:
            ban_expires = self._banned.get(ip)
            if ban_expires is not None:
                if now < ban_expires:
                    return RateLimitResult(
                        allowed=False,
                        remaining=0,
                        retry_after=ban_expires - now,
                        reason=f"IP {ip} is banned for DDoS behavior",
                    )
                else:
                    del self._banned[ip]

        # Layer 1: Global rate
        global_result = self._global_limiter.acquire("__global__", now)
        if not global_result.allowed:
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after=global_result.retry_after,
                reason="Global rate limit exceeded (possible DDoS)",
            )

        # Layer 2: Per-IP burst
        ip_result = self._ip_burst_limiter.acquire(ip, now)
        if not ip_result.allowed:
            self._ban_ip(ip, now)
            return RateLimitResult(
                allowed=False,
                remaining=0,
                retry_after=self.ban_duration,
                reason=f"IP {ip} burst limit exceeded, banned for {self.ban_duration}s",
            )

        # Layer 3: Request fingerprint (detect replayed/automated requests)
        if fingerprint:
            fp_key = f"{ip}:{fingerprint}"
            fp_result = self._fingerprint_limiter.acquire(fp_key, now)
            if not fp_result.allowed:
                self._ban_ip(ip, now)
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after=self.ban_duration,
                    reason=f"Repeated request pattern detected from {ip}",
                )

        return RateLimitResult(
            allowed=True,
            remaining=ip_result.remaining,
        )

    def _ban_ip(self, ip: str, now: float):
        """Add IP to ban list."""
        with self._lock:
            self._banned[ip] = now + self.ban_duration

    def unban_ip(self, ip: str):
        """Remove IP from ban list."""
        with self._lock:
            self._banned.pop(ip, None)

    def get_banned_ips(self) -> Dict[str, float]:
        """Return currently banned IPs and their expiry times."""
        now = time.monotonic()
        with self._lock:
            # Prune expired bans
            expired = [ip for ip, exp in self._banned.items() if now >= exp]
            for ip in expired:
                del self._banned[ip]
            return dict(self._banned)

    def reset(self):
        """Reset all DDoS state."""
        self._global_limiter.reset_all()
        self._ip_burst_limiter.reset_all()
        self._fingerprint_limiter.reset_all()
        with self._lock:
            self._banned.clear()


# ---------------------------------------------------------------------------
# Composite Rate Limiter — Unified per-IP, per-user, per-endpoint
# ---------------------------------------------------------------------------

class RateLimitConfig:
    """Configuration for a single rate limit tier."""

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        burst_capacity: Optional[int] = None,
        burst_refill_rate: Optional[float] = None,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.burst_capacity = burst_capacity
        self.burst_refill_rate = burst_refill_rate


# Default rate limit configurations
DEFAULT_RATE_LIMITS: Dict[str, RateLimitConfig] = {
    "ip": RateLimitConfig(max_requests=100, window_seconds=60.0),
    "user": RateLimitConfig(max_requests=200, window_seconds=60.0),
    "endpoint:/api/diagnose": RateLimitConfig(
        max_requests=20,
        window_seconds=60.0,
        burst_capacity=5,
        burst_refill_rate=0.33,
    ),
    "endpoint:/api/batch-diagnose": RateLimitConfig(
        max_requests=5,
        window_seconds=60.0,
        burst_capacity=2,
        burst_refill_rate=0.08,
    ),
    "endpoint:default": RateLimitConfig(max_requests=60, window_seconds=60.0),
}


class CompositeRateLimiter:
    """
    Unified rate limiter combining per-IP, per-user, and per-endpoint limits.
    Also integrates DDoS detection and circuit breakers.
    """

    def __init__(
        self,
        rate_limits: Optional[Dict[str, RateLimitConfig]] = None,
        ddos_detector: Optional[DDoSDetector] = None,
        circuit_breakers: Optional[CircuitBreakerRegistry] = None,
    ):
        self._configs = rate_limits or DEFAULT_RATE_LIMITS
        self._window_limiters: Dict[str, SlidingWindowLimiter] = {}
        self._bucket_limiters: Dict[str, TokenBucket] = {}
        self._ddos = ddos_detector or DDoSDetector()
        self._circuits = circuit_breakers or CircuitBreakerRegistry()
        self._lock = threading.Lock()

        # Initialize limiters from configs
        for name, config in self._configs.items():
            self._window_limiters[name] = SlidingWindowLimiter(
                config.max_requests, config.window_seconds
            )
            if config.burst_capacity and config.burst_refill_rate:
                self._bucket_limiters[name] = TokenBucket(
                    config.burst_capacity, config.burst_refill_rate
                )

    def check_request(
        self,
        ip: str,
        user_id: Optional[str] = None,
        endpoint: str = "",
        fingerprint: str = "",
        now: Optional[float] = None,
    ) -> RateLimitResult:
        """
        Check all rate limit layers for a request.
        Order: DDoS -> IP -> User -> Endpoint -> Circuit Breaker.
        Returns first denial or overall allowed.
        """
        now = now or time.monotonic()

        # Layer 0: DDoS detection
        ddos_result = self._ddos.check_request(ip, endpoint, fingerprint, now)
        if not ddos_result.allowed:
            return ddos_result

        # Layer 1: Per-IP rate limit
        ip_limiter = self._window_limiters.get("ip")
        if ip_limiter:
            ip_result = ip_limiter.acquire(f"ip:{ip}", now)
            if not ip_result.allowed:
                return RateLimitResult(
                    allowed=False,
                    remaining=ip_result.remaining,
                    reset_at=ip_result.reset_at,
                    retry_after=ip_result.retry_after,
                    reason=f"Per-IP rate limit exceeded for {ip}",
                )

        # Layer 2: Per-user rate limit
        if user_id:
            user_limiter = self._window_limiters.get("user")
            if user_limiter:
                user_result = user_limiter.acquire(f"user:{user_id}", now)
                if not user_result.allowed:
                    return RateLimitResult(
                        allowed=False,
                        remaining=user_result.remaining,
                        reset_at=user_result.reset_at,
                        retry_after=user_result.retry_after,
                        reason=f"Per-user rate limit exceeded for user {user_id}",
                    )

        # Layer 3: Per-endpoint rate limit
        if endpoint:
            ep_key = f"endpoint:{endpoint}"
            ep_limiter = self._window_limiters.get(ep_key)
            if ep_limiter is None:
                ep_key = "endpoint:default"
                ep_limiter = self._window_limiters.get(ep_key)

            if ep_limiter:
                ep_result = ep_limiter.acquire(f"{ep_key}:{ip}:{user_id or 'anon'}", now)
                if not ep_result.allowed:
                    return RateLimitResult(
                        allowed=False,
                        remaining=ep_result.remaining,
                        reset_at=ep_result.reset_at,
                        retry_after=ep_result.retry_after,
                        reason=f"Per-endpoint rate limit exceeded for {endpoint}",
                    )

            # Endpoint burst check (token bucket)
            ep_bucket = self._bucket_limiters.get(ep_key)
            if ep_bucket is None and f"endpoint:{endpoint}" in self._bucket_limiters:
                ep_bucket = self._bucket_limiters[f"endpoint:{endpoint}"]
            if ep_bucket:
                burst_result = ep_bucket.acquire(f"{ep_key}:{ip}:{user_id or 'anon'}", now=now)
                if not burst_result.allowed:
                    return RateLimitResult(
                        allowed=False,
                        remaining=burst_result.remaining,
                        reset_at=burst_result.reset_at,
                        retry_after=burst_result.retry_after,
                        reason=f"Burst limit exceeded for {endpoint}",
                    )

        # Layer 4: Circuit breaker
        if endpoint:
            cb = self._circuits.get(endpoint)
            if not cb.allow_request():
                stats = cb.get_stats()
                return RateLimitResult(
                    allowed=False,
                    remaining=0,
                    retry_after=cb.recovery_timeout,
                    reason=f"Circuit breaker OPEN for {endpoint} ({stats['failure_count']} failures)",
                )

        return RateLimitResult(allowed=True, remaining=-1)

    def record_endpoint_success(self, endpoint: str):
        """Record successful response for circuit breaker."""
        if endpoint:
            self._circuits.get(endpoint).record_success()

    def record_endpoint_failure(self, endpoint: str):
        """Record failed response for circuit breaker."""
        if endpoint:
            self._circuits.get(endpoint).record_failure()

    def configure_endpoint(self, endpoint: str, config: RateLimitConfig):
        """Add or update rate limit config for an endpoint."""
        key = f"endpoint:{endpoint}"
        self._configs[key] = config
        self._window_limiters[key] = SlidingWindowLimiter(
            config.max_requests, config.window_seconds
        )
        if config.burst_capacity and config.burst_refill_rate:
            self._bucket_limiters[key] = TokenBucket(
                config.burst_capacity, config.burst_refill_rate
            )

    def configure_circuit_breaker(self, endpoint: str, **kwargs):
        """Configure circuit breaker for an endpoint."""
        self._circuits.configure(endpoint, **kwargs)

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive stats."""
        return {
            "circuit_breakers": self._circuits.get_all_stats(),
            "banned_ips": self._ddos.get_banned_ips(),
        }

    def reset(self):
        """Reset all limiters."""
        for limiter in self._window_limiters.values():
            limiter.reset_all()
        for bucket in self._bucket_limiters.values():
            bucket.reset_all()
        self._ddos.reset()


# ---------------------------------------------------------------------------
# IP Whitelist / Blacklist
# ---------------------------------------------------------------------------

class IPAccessList:
    """
    Maintain whitelist and blacklist of IPs/CIDRs.
    Whitelist bypasses all rate limits; blacklist blocks immediately.
    Supports exact IPs and /24, /16, /8 CIDR prefixes.
    """

    def __init__(
        self,
        whitelist: Optional[List[str]] = None,
        blacklist: Optional[List[str]] = None,
    ):
        self._whitelist: set = set(whitelist or [])
        self._blacklist: set = set(blacklist or [])
        self._lock = threading.Lock()

    def _match(self, ip: str, entries: set) -> bool:
        """Check if IP matches any entry (exact or CIDR prefix)."""
        if ip in entries:
            return True
        parts = ip.split(".")
        if len(parts) == 4:
            # Check /24, /16, /8 prefixes
            prefixes = [
                f"{parts[0]}.{parts[1]}.{parts[2]}.0/24",
                f"{parts[0]}.{parts[1]}.0.0/16",
                f"{parts[0]}.0.0.0/8",
            ]
            for prefix in prefixes:
                if prefix in entries:
                    return True
        return False

    def is_whitelisted(self, ip: str) -> bool:
        with self._lock:
            return self._match(ip, self._whitelist)

    def is_blacklisted(self, ip: str) -> bool:
        with self._lock:
            return self._match(ip, self._blacklist)

    def add_whitelist(self, ip: str):
        with self._lock:
            self._whitelist.add(ip)

    def add_blacklist(self, ip: str):
        with self._lock:
            self._blacklist.add(ip)

    def remove_whitelist(self, ip: str):
        with self._lock:
            self._whitelist.discard(ip)

    def remove_blacklist(self, ip: str):
        with self._lock:
            self._blacklist.discard(ip)

    def check(self, ip: str) -> Optional[RateLimitResult]:
        """
        Returns RateLimitResult(allowed=True) for whitelist,
        RateLimitResult(allowed=False) for blacklist,
        None if IP is in neither list.
        """
        if self.is_whitelisted(ip):
            return RateLimitResult(allowed=True, remaining=-1, reason="IP whitelisted")
        if self.is_blacklisted(ip):
            return RateLimitResult(
                allowed=False, remaining=0, retry_after=0,
                reason=f"IP {ip} is blacklisted",
            )
        return None


# ---------------------------------------------------------------------------
# Adaptive Penalty Escalation
# ---------------------------------------------------------------------------

class AdaptivePenalty:
    """
    Escalates ban duration for repeat offenders.
    Each violation doubles the penalty up to max_penalty.
    Violation history decays after decay_period of good behavior.
    """

    def __init__(
        self,
        base_penalty: float = 60.0,
        max_penalty: float = 3600.0,
        multiplier: float = 2.0,
        decay_period: float = 900.0,
    ):
        self.base_penalty = base_penalty
        self.max_penalty = max_penalty
        self.multiplier = multiplier
        self.decay_period = decay_period
        self._violations: Dict[str, List[float]] = defaultdict(list)  # key -> [timestamps]
        self._lock = threading.Lock()

    def record_violation(self, key: str, now: Optional[float] = None) -> float:
        """Record a violation and return the escalated penalty duration."""
        now = now or time.monotonic()
        with self._lock:
            self._prune(key, now)
            self._violations[key].append(now)
            count = len(self._violations[key])
            penalty = min(
                self.base_penalty * (self.multiplier ** (count - 1)),
                self.max_penalty,
            )
            return penalty

    def get_violation_count(self, key: str, now: Optional[float] = None) -> int:
        now = now or time.monotonic()
        with self._lock:
            self._prune(key, now)
            return len(self._violations[key])

    def _prune(self, key: str, now: float):
        """Remove violations older than decay_period."""
        cutoff = now - self.decay_period
        self._violations[key] = [t for t in self._violations[key] if t > cutoff]
        if not self._violations[key]:
            del self._violations[key]

    def reset(self, key: Optional[str] = None):
        with self._lock:
            if key:
                self._violations.pop(key, None)
            else:
                self._violations.clear()


# ---------------------------------------------------------------------------
# Request Guard — High-Level Protection Wrapper
# ---------------------------------------------------------------------------

class RequestGuard:
    """
    All-in-one request protection combining:
    - IP whitelist/blacklist
    - Composite rate limiting (per-IP, per-user, per-endpoint)
    - DDoS detection
    - Circuit breakers
    - Adaptive penalty escalation

    Designed as the single entry point for request validation.
    """

    def __init__(
        self,
        rate_limiter: Optional[CompositeRateLimiter] = None,
        ip_access_list: Optional[IPAccessList] = None,
        penalty: Optional[AdaptivePenalty] = None,
    ):
        self._limiter = rate_limiter or CompositeRateLimiter()
        self._acl = ip_access_list or IPAccessList()
        self._penalty = penalty or AdaptivePenalty()
        self._lock = threading.Lock()

    def check(
        self,
        ip: str,
        user_id: Optional[str] = None,
        endpoint: str = "",
        fingerprint: str = "",
        now: Optional[float] = None,
    ) -> RateLimitResult:
        """
        Full request check through all protection layers.
        Returns RateLimitResult indicating whether the request should proceed.
        """
        now = now or time.monotonic()

        # Layer 0: ACL check
        acl_result = self._acl.check(ip)
        if acl_result is not None:
            return acl_result

        # Layer 1-4: Composite rate limiter
        result = self._limiter.check_request(
            ip=ip, user_id=user_id, endpoint=endpoint,
            fingerprint=fingerprint, now=now,
        )

        if not result.allowed:
            # Escalate penalty for repeat offenders
            penalty_key = f"ip:{ip}"
            escalated = self._penalty.record_violation(penalty_key, now)
            effective = max(escalated, result.retry_after)
            result = RateLimitResult(
                allowed=False,
                remaining=0,
                reset_at=now + effective,
                retry_after=effective,
                reason=f"{result.reason} (escalated penalty: {escalated:.0f}s)",
            )

        return result

    def record_success(self, endpoint: str):
        self._limiter.record_endpoint_success(endpoint)

    def record_failure(self, endpoint: str):
        self._limiter.record_endpoint_failure(endpoint)

    @property
    def acl(self) -> IPAccessList:
        return self._acl

    @property
    def limiter(self) -> CompositeRateLimiter:
        return self._limiter

    @property
    def penalty(self) -> AdaptivePenalty:
        return self._penalty

    def get_stats(self) -> Dict[str, Any]:
        return self._limiter.get_stats()

    def reset(self):
        self._limiter.reset()
        self._penalty.reset()


def request_fingerprint(*args: str) -> str:
    """Generate a fingerprint hash from request components (method, path, body, etc.)."""
    combined = "|".join(args)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]


def rate_limited(
    guard: RequestGuard,
    ip_extractor: Optional[Callable] = None,
    user_extractor: Optional[Callable] = None,
    endpoint_name: str = "",
):
    """
    Decorator that applies rate limiting to a function.
    On denial, raises RateLimitExceeded with the result details.

    Usage:
        guard = RequestGuard()

        @rate_limited(guard, endpoint_name="/api/diagnose")
        def handle_diagnose(request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            ip = ip_extractor(args, kwargs) if ip_extractor else kwargs.get("ip", "unknown")
            user = user_extractor(args, kwargs) if user_extractor else kwargs.get("user_id")
            ep = endpoint_name or func.__name__
            fp = request_fingerprint(ip, ep, str(kwargs.get("body", "")))

            result = guard.check(ip=ip, user_id=user, endpoint=ep, fingerprint=fp)
            if not result.allowed:
                raise RateLimitExceeded(result)
            return func(*args, **kwargs)
        return wrapper
    return decorator


class RateLimitExceeded(Exception):
    """Raised when a rate-limited function is called beyond its limit."""

    def __init__(self, result: RateLimitResult):
        self.result = result
        super().__init__(f"Rate limit exceeded: {result.reason}")


# ---------------------------------------------------------------------------
# __main__ — Assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # -----------------------------------------------------------------------
    # 1. SlidingWindowLimiter — Basic Allow/Deny
    # -----------------------------------------------------------------------
    limiter = SlidingWindowLimiter(max_requests=3, window_seconds=10.0)
    t = 1000.0

    r1 = limiter.acquire("client-a", now=t)
    assert r1.allowed, "First request should be allowed"
    assert r1.remaining == 2

    r2 = limiter.acquire("client-a", now=t + 0.1)
    assert r2.allowed
    assert r2.remaining == 1

    r3 = limiter.acquire("client-a", now=t + 0.2)
    assert r3.allowed
    assert r3.remaining == 0

    r4 = limiter.acquire("client-a", now=t + 0.3)
    assert not r4.allowed, "4th request should be denied"
    assert r4.retry_after > 0
    assert "Rate limit exceeded" in r4.reason
    print("[PASS] SlidingWindowLimiter — basic allow/deny")

    # -----------------------------------------------------------------------
    # 2. SlidingWindowLimiter — Window Expiry
    # -----------------------------------------------------------------------
    r5 = limiter.acquire("client-a", now=t + 11.0)
    assert r5.allowed, "Request should be allowed after window expires"
    assert r5.remaining == 2
    print("[PASS] SlidingWindowLimiter — window expiry")

    # -----------------------------------------------------------------------
    # 3. SlidingWindowLimiter — Key Isolation
    # -----------------------------------------------------------------------
    limiter2 = SlidingWindowLimiter(max_requests=1, window_seconds=10.0)
    ra = limiter2.acquire("key-a", now=t)
    assert ra.allowed
    rb = limiter2.acquire("key-b", now=t)
    assert rb.allowed, "Different keys should have independent limits"
    ra2 = limiter2.acquire("key-a", now=t + 0.1)
    assert not ra2.allowed
    print("[PASS] SlidingWindowLimiter — key isolation")

    # -----------------------------------------------------------------------
    # 4. SlidingWindowLimiter — Check vs Acquire
    # -----------------------------------------------------------------------
    limiter3 = SlidingWindowLimiter(max_requests=2, window_seconds=10.0)
    check = limiter3.check("check-key", now=t)
    assert check.allowed
    assert check.remaining == 2  # check doesn't consume

    acq = limiter3.acquire("check-key", now=t)
    assert acq.allowed
    assert acq.remaining == 1  # acquire consumes

    check2 = limiter3.check("check-key", now=t + 0.1)
    assert check2.allowed
    assert check2.remaining == 1  # still 1 (check doesn't consume)
    print("[PASS] SlidingWindowLimiter — check vs acquire")

    # -----------------------------------------------------------------------
    # 5. SlidingWindowLimiter — Reset
    # -----------------------------------------------------------------------
    limiter4 = SlidingWindowLimiter(max_requests=1, window_seconds=60.0)
    limiter4.acquire("reset-key", now=t)
    denied = limiter4.acquire("reset-key", now=t + 0.1)
    assert not denied.allowed
    limiter4.reset("reset-key")
    allowed = limiter4.acquire("reset-key", now=t + 0.2)
    assert allowed.allowed, "Should be allowed after reset"
    print("[PASS] SlidingWindowLimiter — reset")

    # -----------------------------------------------------------------------
    # 6. TokenBucket — Basic Operation
    # -----------------------------------------------------------------------
    bucket = TokenBucket(capacity=5, refill_rate=1.0)
    t = 2000.0

    for i in range(5):
        r = bucket.acquire("tb-client", now=t + i * 0.01)
        assert r.allowed, f"Token {i+1} should be available"
    assert r.remaining == 0

    denied = bucket.acquire("tb-client", now=t + 0.1)
    assert not denied.allowed, "Should be denied when bucket empty"
    assert denied.retry_after > 0
    assert "Token bucket empty" in denied.reason
    print("[PASS] TokenBucket — basic operation")

    # -----------------------------------------------------------------------
    # 7. TokenBucket — Refill
    # -----------------------------------------------------------------------
    r = bucket.acquire("tb-client", now=t + 3.0)
    assert r.allowed, "Tokens should have refilled after 3 seconds"
    print("[PASS] TokenBucket — refill")

    # -----------------------------------------------------------------------
    # 8. TokenBucket — Multi-token Acquire
    # -----------------------------------------------------------------------
    bucket2 = TokenBucket(capacity=10, refill_rate=2.0)
    r = bucket2.acquire("multi", tokens=5, now=t)
    assert r.allowed
    assert r.remaining == 5
    r = bucket2.acquire("multi", tokens=6, now=t + 0.01)
    assert not r.allowed, "Not enough tokens for 6"
    r = bucket2.acquire("multi", tokens=5, now=t + 0.02)
    assert r.allowed
    print("[PASS] TokenBucket — multi-token acquire")

    # -----------------------------------------------------------------------
    # 9. CircuitBreaker — Closed State
    # -----------------------------------------------------------------------
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request()
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    print("[PASS] CircuitBreaker — closed state")

    # -----------------------------------------------------------------------
    # 10. CircuitBreaker — Opens After Threshold Failures
    # -----------------------------------------------------------------------
    cb2 = CircuitBreaker(failure_threshold=3, recovery_timeout=5.0)
    cb2.record_failure()
    cb2.record_failure()
    assert cb2.state == CircuitState.CLOSED, "Still closed after 2 failures"
    cb2.record_failure()
    assert cb2.state == CircuitState.OPEN, "Should open after 3 failures"
    assert not cb2.allow_request(), "Requests should be blocked when open"
    print("[PASS] CircuitBreaker — opens after threshold")

    # -----------------------------------------------------------------------
    # 11. CircuitBreaker — Half-Open After Timeout
    # -----------------------------------------------------------------------
    cb3 = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0, half_open_max_calls=1)
    cb3.record_failure()
    cb3.record_failure()
    assert cb3.state == CircuitState.OPEN

    # Simulate time passing by manipulating internal state
    cb3._last_failure_time = time.monotonic() - 2.0
    assert cb3.state == CircuitState.HALF_OPEN, "Should transition to half-open after timeout"
    assert cb3.allow_request(), "First half-open call should be allowed"
    assert not cb3.allow_request(), "Second half-open call should be blocked"
    print("[PASS] CircuitBreaker — half-open transition")

    # -----------------------------------------------------------------------
    # 12. CircuitBreaker — Half-Open Success -> Closed
    # -----------------------------------------------------------------------
    cb4 = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0, success_threshold=1)
    cb4.record_failure()
    cb4.record_failure()
    cb4._last_failure_time = time.monotonic() - 2.0
    assert cb4.state == CircuitState.HALF_OPEN
    cb4.allow_request()  # consume half-open slot
    cb4.record_success()
    assert cb4.state == CircuitState.CLOSED, "Should close after success in half-open"
    print("[PASS] CircuitBreaker — half-open recovery")

    # -----------------------------------------------------------------------
    # 13. CircuitBreaker — Half-Open Failure -> Open
    # -----------------------------------------------------------------------
    cb5 = CircuitBreaker(failure_threshold=2, recovery_timeout=1.0)
    cb5.record_failure()
    cb5.record_failure()
    cb5._last_failure_time = time.monotonic() - 2.0
    assert cb5.state == CircuitState.HALF_OPEN
    cb5.allow_request()
    cb5.record_failure()
    assert cb5.state == CircuitState.OPEN, "Should re-open after failure in half-open"
    print("[PASS] CircuitBreaker — half-open failure")

    # -----------------------------------------------------------------------
    # 14. CircuitBreaker — Reset
    # -----------------------------------------------------------------------
    cb6 = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
    cb6.record_failure()
    cb6.record_failure()
    assert cb6.state == CircuitState.OPEN
    cb6.reset()
    assert cb6.state == CircuitState.CLOSED
    assert cb6.allow_request()
    print("[PASS] CircuitBreaker — reset")

    # -----------------------------------------------------------------------
    # 15. CircuitBreaker — Stats
    # -----------------------------------------------------------------------
    cb7 = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    cb7.record_failure()
    cb7.record_failure()
    stats = cb7.get_stats()
    assert stats["state"] == "closed"
    assert stats["failure_count"] == 2
    assert stats["failure_threshold"] == 5
    print("[PASS] CircuitBreaker — stats")

    # -----------------------------------------------------------------------
    # 16. CircuitBreakerRegistry
    # -----------------------------------------------------------------------
    registry = CircuitBreakerRegistry()
    cb_a = registry.get("/api/diagnose")
    cb_b = registry.get("/api/batch")
    assert cb_a is not cb_b, "Different endpoints get different breakers"
    assert registry.get("/api/diagnose") is cb_a, "Same endpoint returns same breaker"

    registry.configure("/api/critical", failure_threshold=2, recovery_timeout=10.0)
    cb_c = registry.get("/api/critical")
    assert cb_c.failure_threshold == 2
    print("[PASS] CircuitBreakerRegistry")

    # -----------------------------------------------------------------------
    # 17. DDoSDetector — Normal Traffic Allowed
    # -----------------------------------------------------------------------
    ddos = DDoSDetector(
        global_rps_limit=100,
        per_ip_burst_limit=10,
        per_ip_burst_window=5.0,
        fingerprint_threshold=5,
        fingerprint_window=10.0,
        ban_duration=60.0,
    )
    t = 5000.0
    r = ddos.check_request("192.168.1.1", "/api/test", now=t)
    assert r.allowed, "Normal traffic should be allowed"
    print("[PASS] DDoSDetector — normal traffic")

    # -----------------------------------------------------------------------
    # 18. DDoSDetector — IP Burst Ban
    # -----------------------------------------------------------------------
    ddos2 = DDoSDetector(
        global_rps_limit=1000,
        per_ip_burst_limit=5,
        per_ip_burst_window=10.0,
        ban_duration=30.0,
    )
    t = 6000.0
    for i in range(5):
        r = ddos2.check_request("10.0.0.1", "/api/test", now=t + i * 0.01)
        assert r.allowed, f"Request {i+1} should be allowed"

    r = ddos2.check_request("10.0.0.1", "/api/test", now=t + 0.1)
    assert not r.allowed, "Should be banned after burst"
    assert "banned" in r.reason.lower() or "burst" in r.reason.lower()

    # Different IP should still work
    r = ddos2.check_request("10.0.0.2", "/api/test", now=t + 0.2)
    assert r.allowed, "Other IPs should not be affected"
    print("[PASS] DDoSDetector — IP burst ban")

    # -----------------------------------------------------------------------
    # 19. DDoSDetector — Fingerprint Detection
    # -----------------------------------------------------------------------
    ddos3 = DDoSDetector(
        global_rps_limit=1000,
        per_ip_burst_limit=100,
        per_ip_burst_window=10.0,
        fingerprint_threshold=3,
        fingerprint_window=10.0,
        ban_duration=30.0,
    )
    t = 7000.0
    for i in range(3):
        r = ddos3.check_request("172.16.0.1", "/api/test", fingerprint="same-payload-hash", now=t + i * 0.01)
        assert r.allowed

    r = ddos3.check_request("172.16.0.1", "/api/test", fingerprint="same-payload-hash", now=t + 0.05)
    assert not r.allowed, "Should detect repeated fingerprint"
    assert "pattern" in r.reason.lower()
    print("[PASS] DDoSDetector — fingerprint detection")

    # -----------------------------------------------------------------------
    # 20. DDoSDetector — Ban Expiry
    # -----------------------------------------------------------------------
    ddos4 = DDoSDetector(
        global_rps_limit=1000,
        per_ip_burst_limit=2,
        per_ip_burst_window=10.0,
        ban_duration=5.0,
    )
    t = 8000.0
    ddos4.check_request("ban-ip", now=t)
    ddos4.check_request("ban-ip", now=t + 0.01)
    r = ddos4.check_request("ban-ip", now=t + 0.02)
    assert not r.allowed

    banned = ddos4.get_banned_ips()
    assert "ban-ip" in banned

    # After ban expires
    r = ddos4.check_request("ban-ip", now=t + 100.0)
    assert r.allowed, "Should be allowed after ban expires"
    print("[PASS] DDoSDetector — ban expiry")

    # -----------------------------------------------------------------------
    # 21. DDoSDetector — Unban
    # -----------------------------------------------------------------------
    ddos5 = DDoSDetector(per_ip_burst_limit=1, per_ip_burst_window=10.0, ban_duration=600.0)
    t = 9000.0
    ddos5.check_request("unban-ip", now=t)
    ddos5.check_request("unban-ip", now=t + 0.01)
    r = ddos5.check_request("unban-ip", now=t + 0.02)
    assert not r.allowed

    ddos5.unban_ip("unban-ip")
    # Still need burst limiter to expire or use new window
    ddos5._ip_burst_limiter.reset("unban-ip")
    r = ddos5.check_request("unban-ip", now=t + 0.03)
    assert r.allowed, "Should be allowed after manual unban"
    print("[PASS] DDoSDetector — manual unban")

    # -----------------------------------------------------------------------
    # 22. CompositeRateLimiter — Normal Request
    # -----------------------------------------------------------------------
    rl = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=10, window_seconds=60.0),
            "user": RateLimitConfig(max_requests=20, window_seconds=60.0),
            "endpoint:/api/test": RateLimitConfig(max_requests=5, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=30, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(
            global_rps_limit=1000,
            per_ip_burst_limit=100,
            per_ip_burst_window=10.0,
        ),
    )
    t = 10000.0

    r = rl.check_request(ip="192.168.1.10", user_id="user-1", endpoint="/api/test", now=t)
    assert r.allowed, "Normal request should pass all layers"
    print("[PASS] CompositeRateLimiter — normal request")

    # -----------------------------------------------------------------------
    # 23. CompositeRateLimiter — Per-IP Limit
    # -----------------------------------------------------------------------
    rl2 = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=3, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=100, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
    )
    t = 11000.0
    for i in range(3):
        r = rl2.check_request(ip="1.2.3.4", now=t + i * 0.01)
        assert r.allowed
    r = rl2.check_request(ip="1.2.3.4", now=t + 0.05)
    assert not r.allowed
    assert "Per-IP" in r.reason
    print("[PASS] CompositeRateLimiter — per-IP limit")

    # -----------------------------------------------------------------------
    # 24. CompositeRateLimiter — Per-User Limit
    # -----------------------------------------------------------------------
    rl3 = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=1000, window_seconds=60.0),
            "user": RateLimitConfig(max_requests=2, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=1000, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
    )
    t = 12000.0
    for i in range(2):
        r = rl3.check_request(ip=f"10.0.{i}.1", user_id="user-42", now=t + i * 0.01)
        assert r.allowed
    r = rl3.check_request(ip="10.0.99.1", user_id="user-42", now=t + 0.05)
    assert not r.allowed
    assert "Per-user" in r.reason
    print("[PASS] CompositeRateLimiter — per-user limit")

    # -----------------------------------------------------------------------
    # 25. CompositeRateLimiter — Per-Endpoint Limit
    # -----------------------------------------------------------------------
    rl4 = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=1000, window_seconds=60.0),
            "endpoint:/api/expensive": RateLimitConfig(max_requests=2, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=1000, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
    )
    t = 13000.0
    for i in range(2):
        r = rl4.check_request(ip="5.5.5.5", endpoint="/api/expensive", now=t + i * 0.01)
        assert r.allowed
    r = rl4.check_request(ip="5.5.5.5", endpoint="/api/expensive", now=t + 0.05)
    assert not r.allowed
    assert "Per-endpoint" in r.reason
    print("[PASS] CompositeRateLimiter — per-endpoint limit")

    # -----------------------------------------------------------------------
    # 26. CompositeRateLimiter — Circuit Breaker Integration
    # -----------------------------------------------------------------------
    rl5 = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=1000, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=1000, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
    )
    rl5.configure_circuit_breaker("/api/flaky", failure_threshold=3, recovery_timeout=60.0)
    t = 14000.0

    # Record failures to trip the breaker
    for _ in range(3):
        rl5.record_endpoint_failure("/api/flaky")

    r = rl5.check_request(ip="9.9.9.9", endpoint="/api/flaky", now=t)
    assert not r.allowed
    assert "Circuit breaker" in r.reason
    print("[PASS] CompositeRateLimiter — circuit breaker integration")

    # -----------------------------------------------------------------------
    # 27. CompositeRateLimiter — Circuit Breaker Recovery
    # -----------------------------------------------------------------------
    rl6 = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=1000, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=1000, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
    )
    rl6.configure_circuit_breaker("/api/recover", failure_threshold=2, recovery_timeout=1.0, success_threshold=1)
    t = 15000.0

    rl6.record_endpoint_failure("/api/recover")
    rl6.record_endpoint_failure("/api/recover")
    cb_r = rl6._circuits.get("/api/recover")
    assert cb_r.state == CircuitState.OPEN

    # Simulate timeout
    cb_r._last_failure_time = time.monotonic() - 2.0
    assert cb_r.state == CircuitState.HALF_OPEN

    r = rl6.check_request(ip="8.8.8.8", endpoint="/api/recover", now=t)
    assert r.allowed, "Half-open should allow one request"
    rl6.record_endpoint_success("/api/recover")
    assert cb_r.state == CircuitState.CLOSED
    print("[PASS] CompositeRateLimiter — circuit breaker recovery")

    # -----------------------------------------------------------------------
    # 28. RateLimitResult — Headers
    # -----------------------------------------------------------------------
    result = RateLimitResult(allowed=False, remaining=0, reset_at=1700000000, retry_after=30.5)
    headers = result.to_headers()
    assert headers["X-RateLimit-Remaining"] == "0"
    assert headers["X-RateLimit-Reset"] == "1700000000"
    assert headers["Retry-After"] == "31"

    result2 = RateLimitResult(allowed=True, remaining=5, reset_at=1700000060)
    headers2 = result2.to_headers()
    assert "Retry-After" not in headers2
    assert headers2["X-RateLimit-Remaining"] == "5"
    print("[PASS] RateLimitResult — headers")

    # -----------------------------------------------------------------------
    # 29. CompositeRateLimiter — Configure Endpoint
    # -----------------------------------------------------------------------
    rl7 = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=1000, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=1000, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
    )
    rl7.configure_endpoint("/api/new", RateLimitConfig(max_requests=1, window_seconds=60.0))
    t = 16000.0

    r = rl7.check_request(ip="7.7.7.7", endpoint="/api/new", now=t)
    assert r.allowed
    r = rl7.check_request(ip="7.7.7.7", endpoint="/api/new", now=t + 0.01)
    assert not r.allowed
    print("[PASS] CompositeRateLimiter — dynamic endpoint config")

    # -----------------------------------------------------------------------
    # 30. CompositeRateLimiter — Stats
    # -----------------------------------------------------------------------
    stats = rl5.get_stats()
    assert "circuit_breakers" in stats
    assert "banned_ips" in stats
    assert "/api/flaky" in stats["circuit_breakers"]
    print("[PASS] CompositeRateLimiter — stats")

    # -----------------------------------------------------------------------
    # 31. CompositeRateLimiter — Reset
    # -----------------------------------------------------------------------
    rl8 = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=1, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=100, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
    )
    t = 17000.0
    rl8.check_request(ip="6.6.6.6", now=t)
    r = rl8.check_request(ip="6.6.6.6", now=t + 0.01)
    assert not r.allowed
    rl8.reset()
    r = rl8.check_request(ip="6.6.6.6", now=t + 0.02)
    assert r.allowed, "Should be allowed after full reset"
    print("[PASS] CompositeRateLimiter — reset")

    # -----------------------------------------------------------------------
    # 32. Thread Safety Smoke Test
    # -----------------------------------------------------------------------
    import concurrent.futures

    shared_limiter = SlidingWindowLimiter(max_requests=100, window_seconds=5.0)
    results = []

    def hit_limiter(i):
        return shared_limiter.acquire(f"thread-key", now=20000.0 + i * 0.001)

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(hit_limiter, i) for i in range(150)]
        results = [f.result() for f in futures]

    allowed_count = sum(1 for r in results if r.allowed)
    denied_count = sum(1 for r in results if not r.allowed)
    assert allowed_count == 100, f"Expected 100 allowed, got {allowed_count}"
    assert denied_count == 50, f"Expected 50 denied, got {denied_count}"
    print("[PASS] Thread safety smoke test")

    # -----------------------------------------------------------------------
    # 33. TokenBucket — Key Isolation
    # -----------------------------------------------------------------------
    bucket3 = TokenBucket(capacity=2, refill_rate=0.5)
    t = 21000.0
    r_a = bucket3.acquire("bucket-a", now=t)
    r_b = bucket3.acquire("bucket-b", now=t)
    assert r_a.allowed and r_b.allowed
    bucket3.acquire("bucket-a", now=t + 0.01)
    denied_a = bucket3.acquire("bucket-a", now=t + 0.02)
    assert not denied_a.allowed
    allowed_b = bucket3.acquire("bucket-b", now=t + 0.02)
    assert allowed_b.allowed, "Key B should be independent of Key A"
    print("[PASS] TokenBucket — key isolation")

    # -----------------------------------------------------------------------
    # 34. CircuitBreaker — Success Decays Failure Count
    # -----------------------------------------------------------------------
    cb8 = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)
    cb8.record_failure()
    cb8.record_failure()
    cb8.record_failure()
    assert cb8._failure_count == 3
    cb8.record_success()
    assert cb8._failure_count == 2, "Success should decay failure count"
    cb8.record_success()
    cb8.record_success()
    assert cb8._failure_count == 0, "Failure count should not go below 0"
    print("[PASS] CircuitBreaker — success decays failures")

    # -----------------------------------------------------------------------
    # 35. CompositeRateLimiter — Anonymous User (no user_id)
    # -----------------------------------------------------------------------
    rl9 = CompositeRateLimiter(
        rate_limits={
            "ip": RateLimitConfig(max_requests=100, window_seconds=60.0),
            "user": RateLimitConfig(max_requests=5, window_seconds=60.0),
            "endpoint:default": RateLimitConfig(max_requests=100, window_seconds=60.0),
        },
        ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
    )
    t = 22000.0
    for i in range(10):
        r = rl9.check_request(ip="3.3.3.3", now=t + i * 0.01)
        assert r.allowed, f"Anonymous request {i+1} should pass (no user limit applied)"
    print("[PASS] CompositeRateLimiter — anonymous user bypass")

    # -----------------------------------------------------------------------
    # 36. IPAccessList — Whitelist
    # -----------------------------------------------------------------------
    acl = IPAccessList(whitelist=["10.0.0.1", "192.168.0.0/24"], blacklist=["1.2.3.4"])
    assert acl.is_whitelisted("10.0.0.1")
    assert not acl.is_whitelisted("10.0.0.2")
    assert acl.is_whitelisted("192.168.0.55")  # /24 match
    assert not acl.is_whitelisted("192.168.1.55")

    r = acl.check("10.0.0.1")
    assert r is not None and r.allowed
    assert "whitelisted" in r.reason
    print("[PASS] IPAccessList — whitelist")

    # -----------------------------------------------------------------------
    # 37. IPAccessList — Blacklist
    # -----------------------------------------------------------------------
    assert acl.is_blacklisted("1.2.3.4")
    assert not acl.is_blacklisted("1.2.3.5")

    r = acl.check("1.2.3.4")
    assert r is not None and not r.allowed
    assert "blacklisted" in r.reason

    r = acl.check("99.99.99.99")
    assert r is None, "Unknown IP should return None"
    print("[PASS] IPAccessList — blacklist")

    # -----------------------------------------------------------------------
    # 38. IPAccessList — CIDR /16 and /8
    # -----------------------------------------------------------------------
    acl2 = IPAccessList(whitelist=["172.16.0.0/16"], blacklist=["10.0.0.0/8"])
    assert acl2.is_whitelisted("172.16.5.100")
    assert acl2.is_whitelisted("172.16.255.1")
    assert not acl2.is_whitelisted("172.17.0.1")

    assert acl2.is_blacklisted("10.1.2.3")
    assert acl2.is_blacklisted("10.255.255.255")
    assert not acl2.is_blacklisted("11.0.0.1")
    print("[PASS] IPAccessList — CIDR /16 and /8")

    # -----------------------------------------------------------------------
    # 39. IPAccessList — Add/Remove
    # -----------------------------------------------------------------------
    acl3 = IPAccessList()
    assert not acl3.is_whitelisted("5.5.5.5")
    acl3.add_whitelist("5.5.5.5")
    assert acl3.is_whitelisted("5.5.5.5")
    acl3.remove_whitelist("5.5.5.5")
    assert not acl3.is_whitelisted("5.5.5.5")

    acl3.add_blacklist("6.6.6.6")
    assert acl3.is_blacklisted("6.6.6.6")
    acl3.remove_blacklist("6.6.6.6")
    assert not acl3.is_blacklisted("6.6.6.6")
    print("[PASS] IPAccessList — add/remove")

    # -----------------------------------------------------------------------
    # 40. AdaptivePenalty — Escalation
    # -----------------------------------------------------------------------
    penalty = AdaptivePenalty(base_penalty=10.0, max_penalty=160.0, multiplier=2.0, decay_period=100.0)
    t = 30000.0

    p1 = penalty.record_violation("offender-1", now=t)
    assert p1 == 10.0, f"First violation: expected 10.0, got {p1}"

    p2 = penalty.record_violation("offender-1", now=t + 1)
    assert p2 == 20.0, f"Second violation: expected 20.0, got {p2}"

    p3 = penalty.record_violation("offender-1", now=t + 2)
    assert p3 == 40.0, f"Third violation: expected 40.0, got {p3}"

    p4 = penalty.record_violation("offender-1", now=t + 3)
    assert p4 == 80.0, f"Fourth violation: expected 80.0, got {p4}"

    p5 = penalty.record_violation("offender-1", now=t + 4)
    assert p5 == 160.0, f"Fifth violation: expected 160.0, got {p5}"

    # Should cap at max
    p6 = penalty.record_violation("offender-1", now=t + 5)
    assert p6 == 160.0, f"Sixth violation: should cap at 160.0, got {p6}"
    print("[PASS] AdaptivePenalty — escalation")

    # -----------------------------------------------------------------------
    # 41. AdaptivePenalty — Decay
    # -----------------------------------------------------------------------
    penalty2 = AdaptivePenalty(base_penalty=10.0, max_penalty=1000.0, multiplier=2.0, decay_period=50.0)
    t = 31000.0
    penalty2.record_violation("decayer", now=t)
    penalty2.record_violation("decayer", now=t + 1)
    assert penalty2.get_violation_count("decayer", now=t + 2) == 2

    # After decay_period, violations should be pruned
    assert penalty2.get_violation_count("decayer", now=t + 60) == 0
    p = penalty2.record_violation("decayer", now=t + 60)
    assert p == 10.0, "After decay, penalty should reset to base"
    print("[PASS] AdaptivePenalty — decay")

    # -----------------------------------------------------------------------
    # 42. AdaptivePenalty — Key Isolation
    # -----------------------------------------------------------------------
    penalty3 = AdaptivePenalty(base_penalty=5.0, multiplier=3.0)
    t = 32000.0
    penalty3.record_violation("key-x", now=t)
    penalty3.record_violation("key-x", now=t + 0.1)
    penalty3.record_violation("key-y", now=t)
    assert penalty3.get_violation_count("key-x", now=t + 0.2) == 2
    assert penalty3.get_violation_count("key-y", now=t + 0.2) == 1
    print("[PASS] AdaptivePenalty — key isolation")

    # -----------------------------------------------------------------------
    # 43. AdaptivePenalty — Reset
    # -----------------------------------------------------------------------
    penalty4 = AdaptivePenalty()
    penalty4.record_violation("reset-key")
    assert penalty4.get_violation_count("reset-key") >= 1
    penalty4.reset("reset-key")
    assert penalty4.get_violation_count("reset-key") == 0
    penalty4.record_violation("a")
    penalty4.record_violation("b")
    penalty4.reset()
    assert penalty4.get_violation_count("a") == 0
    assert penalty4.get_violation_count("b") == 0
    print("[PASS] AdaptivePenalty — reset")

    # -----------------------------------------------------------------------
    # 44. RequestGuard — Whitelist Bypass
    # -----------------------------------------------------------------------
    guard = RequestGuard(
        rate_limiter=CompositeRateLimiter(
            rate_limits={
                "ip": RateLimitConfig(max_requests=1, window_seconds=60.0),
                "endpoint:default": RateLimitConfig(max_requests=1, window_seconds=60.0),
            },
            ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
        ),
        ip_access_list=IPAccessList(whitelist=["127.0.0.1"]),
    )
    t = 33000.0
    # Whitelisted IP bypasses all limits
    for i in range(10):
        r = guard.check(ip="127.0.0.1", endpoint="/api/test", now=t + i * 0.01)
        assert r.allowed, f"Whitelisted IP request {i+1} should always pass"
    print("[PASS] RequestGuard — whitelist bypass")

    # -----------------------------------------------------------------------
    # 45. RequestGuard — Blacklist Block
    # -----------------------------------------------------------------------
    guard2 = RequestGuard(
        ip_access_list=IPAccessList(blacklist=["evil.ip"]),
    )
    r = guard2.check(ip="evil.ip", endpoint="/api/test")
    assert not r.allowed
    assert "blacklisted" in r.reason
    print("[PASS] RequestGuard — blacklist block")

    # -----------------------------------------------------------------------
    # 46. RequestGuard — Adaptive Penalty Escalation
    # -----------------------------------------------------------------------
    guard3 = RequestGuard(
        rate_limiter=CompositeRateLimiter(
            rate_limits={
                "ip": RateLimitConfig(max_requests=1, window_seconds=60.0),
                "endpoint:default": RateLimitConfig(max_requests=100, window_seconds=60.0),
            },
            ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
        ),
        penalty=AdaptivePenalty(base_penalty=30.0, multiplier=2.0, max_penalty=600.0),
    )
    t = 34000.0

    # First request passes
    r = guard3.check(ip="repeat-offender", now=t)
    assert r.allowed

    # Second request denied (1 req/min limit)
    r = guard3.check(ip="repeat-offender", now=t + 0.01)
    assert not r.allowed
    assert "escalated" in r.reason

    # Third attempt — penalty should escalate further
    r = guard3.check(ip="repeat-offender", now=t + 0.02)
    assert not r.allowed
    assert "escalated" in r.reason
    print("[PASS] RequestGuard — adaptive penalty escalation")

    # -----------------------------------------------------------------------
    # 47. RequestGuard — Get Stats & Reset
    # -----------------------------------------------------------------------
    stats = guard3.get_stats()
    assert "circuit_breakers" in stats
    assert "banned_ips" in stats
    guard3.reset()
    # After reset, should be allowed again
    r = guard3.check(ip="repeat-offender", now=t + 1.0)
    assert r.allowed
    print("[PASS] RequestGuard — stats & reset")

    # -----------------------------------------------------------------------
    # 48. request_fingerprint — Deterministic Hash
    # -----------------------------------------------------------------------
    fp1 = request_fingerprint("GET", "/api/test", "body1")
    fp2 = request_fingerprint("GET", "/api/test", "body1")
    fp3 = request_fingerprint("POST", "/api/test", "body1")
    assert fp1 == fp2, "Same inputs should produce same fingerprint"
    assert fp1 != fp3, "Different inputs should produce different fingerprint"
    assert len(fp1) == 16, "Fingerprint should be 16 hex chars"
    print("[PASS] request_fingerprint — deterministic hash")

    # -----------------------------------------------------------------------
    # 49. rate_limited Decorator — Allowed
    # -----------------------------------------------------------------------
    test_guard = RequestGuard(
        rate_limiter=CompositeRateLimiter(
            rate_limits={
                "ip": RateLimitConfig(max_requests=5, window_seconds=60.0),
                "endpoint:default": RateLimitConfig(max_requests=100, window_seconds=60.0),
            },
            ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
        ),
    )

    @rate_limited(test_guard, endpoint_name="/api/test")
    def my_handler(ip="0.0.0.0", body=""):
        return "ok"

    assert my_handler(ip="10.10.10.10") == "ok"
    assert my_handler(ip="10.10.10.10") == "ok"
    print("[PASS] rate_limited decorator — allowed")

    # -----------------------------------------------------------------------
    # 50. rate_limited Decorator — Denied
    # -----------------------------------------------------------------------
    deny_guard = RequestGuard(
        rate_limiter=CompositeRateLimiter(
            rate_limits={
                "ip": RateLimitConfig(max_requests=1, window_seconds=60.0),
                "endpoint:default": RateLimitConfig(max_requests=100, window_seconds=60.0),
            },
            ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
        ),
    )

    @rate_limited(deny_guard, endpoint_name="/api/limited")
    def limited_handler(ip="0.0.0.0"):
        return "ok"

    assert limited_handler(ip="denied.ip") == "ok"  # first call ok
    try:
        limited_handler(ip="denied.ip")
        assert False, "Should have raised RateLimitExceeded"
    except RateLimitExceeded as e:
        assert e.result is not None
        assert not e.result.allowed
    print("[PASS] rate_limited decorator — denied")

    # -----------------------------------------------------------------------
    # 51. RequestGuard — Record Success/Failure (Circuit Breaker)
    # -----------------------------------------------------------------------
    cb_guard = RequestGuard(
        rate_limiter=CompositeRateLimiter(
            rate_limits={
                "ip": RateLimitConfig(max_requests=1000, window_seconds=60.0),
                "endpoint:default": RateLimitConfig(max_requests=1000, window_seconds=60.0),
            },
            ddos_detector=DDoSDetector(global_rps_limit=10000, per_ip_burst_limit=10000, per_ip_burst_window=1.0),
        ),
    )
    cb_guard.limiter.configure_circuit_breaker("/api/fragile", failure_threshold=2, recovery_timeout=60.0)

    cb_guard.record_failure("/api/fragile")
    cb_guard.record_failure("/api/fragile")
    r = cb_guard.check(ip="1.1.1.1", endpoint="/api/fragile")
    assert not r.allowed
    assert "Circuit breaker" in r.reason
    print("[PASS] RequestGuard — circuit breaker via record_failure")

    # -----------------------------------------------------------------------
    # Done
    # -----------------------------------------------------------------------
    print(f"\n=== ALL 51 TESTS PASSED ===")
