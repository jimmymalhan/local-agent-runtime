"""
CacheMiddleware for FastAPI: LRU in-memory cache for GET responses.
Supports per-route TTL via @cache(ttl=seconds) decorator.
Includes /cache/stats endpoint.
"""

import asyncio
import hashlib
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Optional

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp


# ---------------------------------------------------------------------------
# LRU Cache Store
# ---------------------------------------------------------------------------

class LRUCacheStore:
    """Thread-safe (asyncio-safe) in-memory LRU cache with per-entry TTL."""

    def __init__(self, max_size: int = 1024):
        self.max_size = max_size
        self._store: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = asyncio.Lock()
        # stats
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    async def get(self, key: str) -> Optional[dict[str, Any]]:
        async with self._lock:
            if key not in self._store:
                self.misses += 1
                return None

            entry = self._store[key]
            if entry["expires_at"] < time.time():
                del self._store[key]
                self.misses += 1
                return None

            # Move to end (most-recently used)
            self._store.move_to_end(key)
            self.hits += 1
            return entry

    async def set(self, key: str, value: dict[str, Any]) -> None:
        async with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = value
                return

            if len(self._store) >= self.max_size:
                self._store.popitem(last=False)
                self.evictions += 1

            self._store[key] = value

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0
            self.evictions = 0

    @property
    def size(self) -> int:
        return len(self._store)

    def stats(self) -> dict[str, Any]:
        total = self.hits + self.misses
        return {
            "size": self.size,
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
            "total_requests": total,
        }


# ---------------------------------------------------------------------------
# Route-level TTL registry (populated by @cache decorator)
# ---------------------------------------------------------------------------

_route_ttl_registry: dict[str, int] = {}


def cache(ttl: int = 60) -> Callable:
    """Decorator that registers a per-route TTL for the cache middleware.

    Usage:
        @app.get("/items")
        @cache(ttl=120)
        async def list_items():
            ...
    """

    def decorator(func: Callable) -> Callable:
        # Store TTL keyed by the qualified function name; the middleware
        # resolves the matched route's endpoint to look this up.
        _route_ttl_registry[func.__qualname__] = ttl

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)

        # Preserve the qualname so the middleware can find the TTL
        wrapper.__qualname__ = func.__qualname__
        wrapper._cache_ttl = ttl
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Cache key builder
# ---------------------------------------------------------------------------

def _build_cache_key(request: Request) -> str:
    """Deterministic cache key from method + path + sorted query params."""
    url = str(request.url.path)
    query = str(sorted(request.query_params.multi_items()))
    raw = f"{request.method}:{url}:{query}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class CacheMiddleware(BaseHTTPMiddleware):
    """Caches GET responses by URL + query parameters.

    Args:
        app: The ASGI application.
        store: An ``LRUCacheStore`` instance (shared across the app).
        default_ttl: Fallback TTL in seconds when a route has no @cache decorator.
    """

    def __init__(self, app: ASGIApp, store: LRUCacheStore, default_ttl: int = 60):
        super().__init__(app)
        self.store = store
        self.default_ttl = default_ttl

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Only cache GET requests
        if request.method != "GET":
            return await call_next(request)

        # Skip the stats endpoint itself
        if request.url.path == "/cache/stats":
            return await call_next(request)

        cache_key = _build_cache_key(request)

        # Check cache
        cached = await self.store.get(cache_key)
        if cached is not None:
            return Response(
                content=cached["body"],
                status_code=cached["status_code"],
                headers=cached["headers"],
                media_type=cached.get("media_type"),
            )

        # Forward to the actual endpoint
        response = await call_next(request)

        # Only cache successful responses
        if 200 <= response.status_code < 300:
            body = b""
            async for chunk in response.body_iterator:
                if isinstance(chunk, str):
                    body += chunk.encode("utf-8")
                else:
                    body += chunk

            ttl = self._resolve_ttl(request)

            # Store headers as string pairs (not raw bytes)
            headers = {k: v for k, v in response.headers.items() if k != "content-length"}

            await self.store.set(cache_key, {
                "body": body,
                "status_code": response.status_code,
                "headers": headers,
                "media_type": response.media_type,
                "expires_at": time.time() + ttl,
            })

            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response

    def _resolve_ttl(self, request: Request) -> int:
        """Look up per-route TTL from the @cache decorator registry."""
        route = request.scope.get("route")
        if route is not None:
            endpoint = getattr(route, "endpoint", None)
            if endpoint is not None:
                # Check for _cache_ttl attribute set by the @cache decorator
                ttl = getattr(endpoint, "_cache_ttl", None)
                if ttl is not None:
                    return ttl
                # Fallback: check the registry by qualname
                qualname = getattr(endpoint, "__qualname__", "")
                if qualname in _route_ttl_registry:
                    return _route_ttl_registry[qualname]
        return self.default_ttl


# ---------------------------------------------------------------------------
# Helper to wire everything up
# ---------------------------------------------------------------------------

def add_cache(app: FastAPI, max_size: int = 1024, default_ttl: int = 60) -> LRUCacheStore:
    """Convenience function: attach CacheMiddleware + /cache/stats to *app*.

    Returns the ``LRUCacheStore`` so callers can inspect or clear it.
    """
    store = LRUCacheStore(max_size=max_size)

    @app.get("/cache/stats")
    async def cache_stats():
        return store.stats()

    @app.post("/cache/clear")
    async def cache_clear():
        await store.clear()
        return {"status": "cleared"}

    app.add_middleware(CacheMiddleware, store=store, default_ttl=default_ttl)
    return store


# ---------------------------------------------------------------------------
# Demo app + self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    from fastapi.testclient import TestClient

    app = FastAPI()
    store = add_cache(app, max_size=4, default_ttl=30)

    call_count: dict[str, int] = {"items": 0, "users": 0, "health": 0}

    @app.get("/items")
    @cache(ttl=5)
    async def list_items(page: int = 1):
        call_count["items"] += 1
        return {"items": [f"item-{i}" for i in range(page * 3)], "page": page}

    @app.get("/users")
    @cache(ttl=120)
    async def list_users():
        call_count["users"] += 1
        return {"users": ["alice", "bob"]}

    @app.get("/health")
    async def health():
        """No @cache decorator — uses default TTL."""
        call_count["health"] += 1
        return {"status": "ok"}

    # -----------------------------------------------------------------------
    # Assertions
    # -----------------------------------------------------------------------
    client = TestClient(app)

    # --- 1. First request is a cache miss, endpoint is called ---
    r1 = client.get("/items?page=1")
    assert r1.status_code == 200
    assert r1.json()["page"] == 1
    assert call_count["items"] == 1

    # --- 2. Second identical request is a cache hit ---
    r2 = client.get("/items?page=1")
    assert r2.status_code == 200
    assert r2.json() == r1.json()
    assert call_count["items"] == 1  # endpoint NOT called again

    # --- 3. Different query params → separate cache entry ---
    r3 = client.get("/items?page=2")
    assert r3.status_code == 200
    assert r3.json()["page"] == 2
    assert call_count["items"] == 2

    # --- 4. /users caches independently ---
    r4 = client.get("/users")
    assert r4.status_code == 200
    assert call_count["users"] == 1
    r5 = client.get("/users")
    assert call_count["users"] == 1  # cached

    # --- 5. /health (no @cache) still cached with default TTL ---
    client.get("/health")
    assert call_count["health"] == 1
    client.get("/health")
    assert call_count["health"] == 1

    # --- 6. Cache stats reflect hits and misses ---
    stats = client.get("/cache/stats").json()
    assert stats["hits"] >= 3        # items(1) + users(1) + health(1)
    assert stats["misses"] >= 3      # items/page=1, items/page=2, users, health
    assert stats["size"] >= 3
    assert 0 < stats["hit_rate"] < 1

    # --- 7. POST requests are never cached ---
    @app.post("/items")
    async def create_item():
        call_count["items"] += 1
        return {"created": True}

    p1 = client.post("/items")
    count_after_post = call_count["items"]
    p2 = client.post("/items")
    assert call_count["items"] == count_after_post + 1  # called again (no caching)

    # --- 8. LRU eviction (max_size=4, already 4 entries) ---
    stats_before = client.get("/cache/stats").json()
    client.get("/items?page=99")  # new entry → evicts oldest
    stats_after = client.get("/cache/stats").json()
    assert stats_after["evictions"] >= 1

    # --- 9. Cache clear works ---
    cr = client.post("/cache/clear")
    assert cr.json()["status"] == "cleared"
    stats_cleared = client.get("/cache/stats").json()
    assert stats_cleared["size"] == 0
    assert stats_cleared["hits"] == 0

    # --- 10. After clear, endpoint is called again ---
    old_count = call_count["items"]
    client.get("/items?page=1")
    assert call_count["items"] == old_count + 1

    print("All 10 assertions passed.")
