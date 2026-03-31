#!/usr/bin/env python3
"""
tasks/task_suite.py — 100 Production-Grade Real-World Task Benchmark Suite
===========================================================================
Reusable across any project. Zero hardcoded paths. Pure capability testing.

Philosophy:
  Every task here is something a senior engineer at a FAANG-level company
  would be proud to ship. No toy problems. No LeetCode puzzles.
  Each task produces a real, runnable deliverable.

Categories:
  - scaffold  (20): Full project spin-up from 1 description — FastAPI, React, CLI, etc.
  - refactor  (20): Real codebase transformations — callback hell, auth migration, etc.
  - code_gen  (20): Production utility code — rate limiters, queues, caches, pipelines
  - tdd       (15): Write tests for existing real codebases + fix failures
  - arch      (10): System design with code — distributed systems, microservices
  - debug     (10): Fix intentionally broken production code (real failure patterns)
  - research  (5):  Web research + structured deliverable

Usage:
  from tasks.task_suite import build_task_suite
  tasks = build_task_suite()                       # all 100
  tasks = build_task_suite(n=10)                   # first 10
  tasks = build_task_suite(category="scaffold")    # filter by category
  tasks = build_task_suite(difficulty="hard")      # filter by difficulty
"""


def build_task_suite(n: int = 0, category: str = "", difficulty: str = "") -> list:
    tasks = []
    _id = [1]

    def add(title, desc, cat, diff="hard"):
        if category and cat != category:
            return
        if difficulty and diff != difficulty:
            return
        tasks.append({
            "id": _id[0],
            "title": title,
            "description": desc,
            "category": cat,
            "difficulty": diff,
        })
        _id[0] += 1

    # ── SCAFFOLD (20): Full project spin-ups from 1-line descriptions ─────────
    add("Build a production FastAPI REST API with JWT auth",
        "Scaffold a FastAPI application with: POST /auth/register, POST /auth/login "
        "(returns JWT), GET /users/me (protected). Use Pydantic models, bcrypt password "
        "hashing, JWT with 24h expiry. SQLite via SQLAlchemy. Include Alembic migration. "
        "Run with uvicorn. Write 5 integration tests using httpx. Runnable in < 60s.",
        "scaffold")

    add("Build a CLI deployment tool with subcommands",
        "Write a Python CLI using Click or Typer with commands: "
        "deploy <env> (blue-green deploy to staging/prod), "
        "rollback <version>, status (show running services), "
        "logs <service> --tail N. "
        "Read config from deploy.yaml. Show colored output. "
        "Mock subprocess calls in tests. 100% coverage on happy paths.",
        "scaffold")

    add("Build a real-time WebSocket chat server",
        "Build a Python WebSocket server using websockets or FastAPI WebSockets. "
        "Supports: join <room>, send <message>, list rooms. "
        "Broadcasts to all users in a room. Handles disconnect gracefully. "
        "Includes a simple HTML test client. "
        "Write asyncio tests simulating 3 concurrent users in 1 room.",
        "scaffold")

    add("Build a data pipeline with ETL + validation",
        "Write an ETL pipeline: Extract from CSV (provided schema: id,name,email,amount,date), "
        "Transform (normalize emails, parse dates, validate amounts > 0), "
        "Load to SQLite. Use dataclasses for schema. "
        "Handle malformed rows: log error, skip, continue. "
        "Write 10 unit tests covering valid rows, missing fields, bad dates.",
        "scaffold")

    add("Build a Markdown blog static site generator",
        "Write a Python SSG: reads *.md files from posts/, renders to HTML using "
        "a Jinja2 template with title/date/tags from frontmatter, "
        "generates index.html with post list sorted by date, "
        "copies static/ assets, writes to dist/. "
        "CLI: `ssg build`, `ssg serve` (local preview). "
        "Include 8 tests verifying output HTML content.",
        "scaffold")

    add("Build a GitHub Actions CI pipeline for a Python project",
        "Write .github/workflows/ci.yml that: runs on push to main + PRs, "
        "sets up Python 3.11, installs deps from requirements.txt, "
        "runs pytest with coverage (fail if < 80%), runs ruff linter, "
        "builds Docker image (if Dockerfile exists), "
        "publishes coverage badge to PR comment. "
        "Include a sample Python project to validate against.",
        "scaffold")

    add("Build a multi-tenant SaaS API with RBAC",
        "Write a FastAPI app with: tenant isolation (X-Tenant-ID header), "
        "3 roles: admin, editor, viewer with permission checks, "
        "CRUD endpoints for /projects and /tasks, "
        "rate limiting per tenant (100 req/min), "
        "audit log on all writes (who, what, when). "
        "SQLite backend. Write 12 integration tests covering RBAC boundaries.",
        "scaffold")

    add("Build a distributed task queue with workers",
        "Implement a task queue: TaskQueue class with enqueue(task_fn, *args), "
        "Worker(queue, concurrency=4) that processes tasks with asyncio, "
        "retry logic (3x exponential backoff on exception), "
        "priority queue (1-10 scale), "
        "dead letter queue for tasks that fail all retries. "
        "Write tests simulating 50 tasks with 2 intentional failures.",
        "scaffold")

    add("Build a feature flag service",
        "Write a feature flag service: FlagStore (Redis-backed or SQLite), "
        "Flag(name, enabled, rollout_pct, user_whitelist), "
        "is_enabled(flag_name, user_id) → bool (consistent hash for rollout), "
        "REST API: GET /flags, POST /flags, PATCH /flags/:name. "
        "Include SDK: from flags import is_enabled. "
        "Write 10 tests covering rollout percentages and whitelist.",
        "scaffold")

    add("Build a metrics collection and alerting system",
        "Write a metrics system: Metrics.counter(name), Metrics.gauge(name, val), "
        "Metrics.histogram(name, val), export to Prometheus format (/metrics endpoint), "
        "AlertRule(metric, condition, threshold, notify_fn), "
        "AlertManager runs checks every 30s, "
        "StatsDClient for sending metrics remotely. "
        "Include 10 unit tests.",
        "scaffold")

    add("Build a document search engine with TF-IDF",
        "Write a search engine: index_documents(docs: list[dict]), "
        "search(query: str, top_k=10) → ranked results using TF-IDF scoring, "
        "supports phrase queries ('exact phrase'), "
        "highlight matching terms in snippets, "
        "persist index to disk (pickle or JSON). "
        "REST API: POST /index, GET /search?q=. "
        "Write 8 tests with a 20-doc corpus.",
        "scaffold")

    add("Build a GraphQL API with subscriptions",
        "Write a GraphQL API using Strawberry or Ariadne: "
        "types: User, Post, Comment with relationships, "
        "queries: user(id), posts(userId), "
        "mutations: createPost, createComment, "
        "subscription: postAdded (WebSocket). "
        "SQLite backend. N+1 query protection with DataLoader. "
        "Include 8 integration tests.",
        "scaffold")

    add("Build a gRPC microservice for user management",
        "Write a gRPC service: define user.proto (CreateUser, GetUser, ListUsers, DeleteUser), "
        "implement Python server with grpcio, "
        "SQLite persistence, "
        "interceptor for logging all RPC calls with latency, "
        "Python client with retry on UNAVAILABLE. "
        "Include 6 integration tests.",
        "scaffold")

    add("Build a cron job scheduler",
        "Write a cron scheduler: Schedule.add(cron_expr, fn, name), "
        "parse standard 5-field cron expressions, "
        "run jobs in threads (max_workers=4), "
        "track job history (start_time, duration, status, output), "
        "REST API: GET /jobs, POST /jobs/run/:name, GET /jobs/:name/history. "
        "Write 10 tests including cron parsing edge cases.",
        "scaffold")

    add("Build a file upload service with processing pipeline",
        "Write a FastAPI file upload service: "
        "POST /upload (accepts CSV, JSON, Parquet), "
        "validate schema on upload, "
        "async processing pipeline: parse → validate → store → notify, "
        "GET /uploads/:id/status, "
        "GET /uploads/:id/results. "
        "Use asyncio queues for pipeline. "
        "Write 8 tests covering each file type.",
        "scaffold")

    add("Build a config management system",
        "Write a hierarchical config system: "
        "read from YAML files (base.yaml, env/prod.yaml, env/dev.yaml), "
        "merge with precedence (env > env-specific > base), "
        "support env var overrides (prefix: APP_), "
        "type coercion (str, int, bool, list), "
        "validate required keys, "
        "hot-reload on SIGHUP. "
        "CLI: `config get KEY`, `config set KEY VAL`. "
        "Write 12 tests.",
        "scaffold")

    add("Build an OAuth2 provider with PKCE",
        "Implement OAuth2 authorization code flow with PKCE: "
        "GET /authorize (redirect with code), "
        "POST /token (exchange code for access+refresh tokens), "
        "POST /token/refresh, "
        "GET /userinfo (protected), "
        "token introspection endpoint. "
        "In-memory store. Write 10 tests covering the full flow.",
        "scaffold")

    add("Build a streaming data processor",
        "Write a streaming processor: "
        "Stream(source_fn) → produces records lazily, "
        "chain: .filter(pred), .map(fn), .batch(size), .window(seconds), "
        ".aggregate(fn), .sink(output_fn), "
        "backpressure: pause source if buffer > 1000 items, "
        "error handling: skip bad records, log, continue. "
        "Write 10 tests including windowed aggregation.",
        "scaffold")

    add("Build a zero-downtime database migration tool",
        "Write a DB migration tool: "
        "migrations/ directory with up/down SQL files, "
        "MigrationRunner: run(db_url) applies pending migrations in order, "
        "lock table to prevent concurrent runs, "
        "rollback on failure, "
        "migrate status shows applied/pending, "
        "generate new migration: `migrate create <name>`. "
        "Write 8 tests with a real SQLite DB.",
        "scaffold")

    add("Build a request tracing and observability system",
        "Write distributed tracing: "
        "TraceContext(trace_id, span_id, parent_span_id), "
        "propagate via X-Trace-ID header through HTTP calls, "
        "Span(name, context) as context manager, "
        "SpanExporter → writes to traces/trace_{id}.json, "
        "sampling: 10% of requests traced by default, "
        "FastAPI middleware that instruments all endpoints. "
        "Write 8 tests.",
        "scaffold")

    # ── REFACTOR (20): Real codebase transformations ──────────────────────────
    add("Refactor callback hell to async/await",
        "Given a file with 5 nested callback functions (provided), "
        "refactor to use async/await with proper error handling. "
        "Maintain identical behavior. Add type hints. "
        "Write before/after tests proving behavioral equivalence. "
        "No global state. No monkey-patching.",
        "refactor")

    add("Extract magic numbers and inline strings to constants",
        "Given a 200-line file with magic numbers and hardcoded strings (provided), "
        "extract to a Config dataclass at the top. "
        "No behavior change. "
        "Every constant must have a clear name that a new engineer can understand. "
        "Write tests that use Config values directly.",
        "refactor")

    add("Refactor God class into focused modules",
        "Given a 400-line UserManager class (provided) that handles: "
        "auth, email sending, billing, and session management, "
        "split into 4 focused classes with clear interfaces. "
        "Preserve all public methods. "
        "Add integration test proving the refactored system behaves identically.",
        "refactor")

    add("Migrate from raw SQL to SQLAlchemy ORM",
        "Given a Python module with 10 raw sqlite3 queries (provided), "
        "migrate to SQLAlchemy ORM with declarative models. "
        "Keep the same public function signatures. "
        "Add migrations using Alembic. "
        "Write 8 tests using an in-memory SQLite DB.",
        "refactor")

    add("Refactor synchronous I/O to async",
        "Given a Python web scraper that uses requests (provided, 150 lines), "
        "refactor to use httpx.AsyncClient with asyncio.gather for parallelism. "
        "Target: 5x faster on 20 URLs. "
        "Add semaphore to limit to 5 concurrent requests. "
        "Write tests with mocked HTTP responses.",
        "refactor")

    add("Replace if/elif chain with strategy pattern",
        "Given a file with a 30-case if/elif dispatch chain (provided), "
        "refactor to use a dict-based strategy pattern. "
        "New strategies must be addable without modifying core dispatcher. "
        "Write 10 tests. No behavior change allowed.",
        "refactor")

    add("Extract hardcoded configuration to environment-aware config",
        "Given a module with DB URLs, API keys, and service endpoints hardcoded (provided), "
        "extract to a Pydantic Settings class that reads from env vars with sensible defaults. "
        "Support .env file loading. "
        "Write tests that override individual config values.",
        "refactor")

    add("Refactor deeply nested conditionals to early returns",
        "Given a function with 6-deep nesting (provided), "
        "flatten using guard clauses / early returns. "
        "Max nesting depth after: 2. "
        "Identical behavior required. "
        "Add mypy type hints throughout. "
        "Write 8 before/after tests.",
        "refactor")

    add("Decompose monolithic function into pipeline",
        "Given a 200-line function that does: fetch, parse, validate, transform, store (provided), "
        "decompose into 5 single-responsibility functions chained as a pipeline. "
        "Each step takes input and returns output (no side effects except store). "
        "Write tests for each step independently.",
        "refactor")

    add("Add structured logging to replace print statements",
        "Given a module with 20 print() statements (provided), "
        "replace with structlog or Python logging with: "
        "log levels (DEBUG/INFO/WARNING/ERROR), "
        "structured fields (request_id, user_id, duration_ms), "
        "JSON output format, "
        "contextvar-based request context. "
        "Write tests asserting log output.",
        "refactor")

    add("Migrate from threading to asyncio",
        "Given a producer-consumer system using threading.Thread and Queue (provided, 120 lines), "
        "migrate to asyncio.Queue and async workers. "
        "Same throughput guarantee: 100 msgs/s. "
        "No locks (use asyncio primitives). "
        "Write 6 tests.",
        "refactor")

    add("Add input validation and sanitization layer",
        "Given a FastAPI app with no input validation (provided), "
        "add: Pydantic models for all request bodies, "
        "custom validators for email, phone, URL fields, "
        "sanitize HTML in text fields (strip tags), "
        "return 422 with field-level error messages. "
        "Write 10 tests covering valid + invalid inputs.",
        "refactor")

    add("Convert procedural script to testable module",
        "Given a 150-line procedural script with no functions (provided), "
        "refactor into: main() entry point, "
        "5+ pure functions with clear inputs/outputs, "
        "no global state, "
        "if __name__ == '__main__' guard. "
        "Write 8 unit tests.",
        "refactor")

    add("Add retry and circuit breaker to HTTP client",
        "Given a module making raw requests.get() calls (provided), "
        "wrap with: "
        "retry decorator (3x, exponential backoff 1s/2s/4s), "
        "circuit breaker (open after 5 failures, reset after 60s), "
        "timeout (10s per request), "
        "structured error logging. "
        "Write 10 tests with mocked failures.",
        "refactor")

    add("Migrate password storage from MD5 to bcrypt",
        "Given a user auth module using MD5 for passwords (provided), "
        "migrate to bcrypt with work factor 12. "
        "Write migration script for existing hashes (re-hash on next login). "
        "Add timing-safe compare. "
        "Write 8 security tests.",
        "refactor")

    add("Extract shared utilities into a proper package",
        "Given 5 Python files each with copy-pasted utility functions (provided), "
        "extract shared code into utils/ package with: "
        "utils/strings.py, utils/dates.py, utils/http.py, utils/validation.py. "
        "Remove all duplication. "
        "Write 15 tests covering each utility.",
        "refactor")

    add("Add caching layer to expensive operations",
        "Given a module with 4 functions that make expensive DB/API calls (provided), "
        "add: functools.lru_cache for pure functions, "
        "Redis-style TTL cache for time-sensitive data, "
        "cache invalidation on writes, "
        "cache hit/miss metrics. "
        "Write 10 tests including cache invalidation.",
        "refactor")

    add("Refactor error handling from bare except to typed exceptions",
        "Given a module with 10 bare except: pass blocks (provided), "
        "replace with: custom exception hierarchy, "
        "typed catches (ValueError, ConnectionError, etc.), "
        "proper logging in each handler, "
        "re-raise where appropriate. "
        "Write 8 tests asserting specific exceptions are raised.",
        "refactor")

    add("Add database connection pooling",
        "Given a module that creates a new DB connection per query (provided), "
        "add connection pooling: pool size 5-20, "
        "connection health check, "
        "auto-reconnect on stale connections, "
        "context manager for safe acquire/release, "
        "pool metrics (active, idle, waiting). "
        "Write 8 tests.",
        "refactor")

    add("Parallelize sequential data processing",
        "Given a script that processes 1000 records sequentially (provided, ~50ms per record), "
        "parallelize with concurrent.futures.ProcessPoolExecutor, "
        "chunk size auto-tuned to CPU count, "
        "progress bar with tqdm, "
        "partial failure handling (collect errors, continue), "
        "final summary: N processed, M failed. "
        "Write 6 tests.",
        "refactor")

    # ── CODE GEN (20): Production utility code ────────────────────────────────
    add("Implement sliding window rate limiter",
        "Write RateLimiter(max_calls, window_seconds) with allow(key) → bool. "
        "Uses sliding window (not fixed window). Thread-safe with RLock. "
        "Works per-key (user ID, IP). TTL cleanup for expired windows. "
        "Write 10 tests covering burst, steady rate, multi-key.",
        "code_gen")

    add("Build a connection pool for HTTP clients",
        "Write ConnectionPool(base_url, max_connections=10) with get(), post(), put(). "
        "Reuse connections (keep-alive). "
        "Timeout per request (configurable). "
        "Circuit breaker: open after 5 consecutive failures. "
        "Write 8 tests with mocked responses.",
        "code_gen")

    add("Write a zero-dependency JSON schema validator",
        "Write validate(data, schema) → (bool, list[str]) that validates JSON against "
        "a schema dict supporting: type (string/integer/boolean/array/object), "
        "required, properties, minLength/maxLength, minimum/maximum, enum, pattern. "
        "Return list of validation errors with JSON path. "
        "Write 12 tests.",
        "code_gen")

    add("Implement an LRU cache with TTL",
        "Write LRUCache(capacity, ttl_seconds=None) with get(key), set(key, val), "
        "delete(key), clear(). Thread-safe. TTL per-item. "
        "Evict LRU when capacity full. "
        "Write 10 tests including TTL expiry and thread safety.",
        "code_gen")

    add("Write a generic retry decorator",
        "Write @retry(max_attempts=3, exceptions=(Exception,), backoff=1.0, jitter=True) "
        "decorator. Exponential backoff with optional jitter. "
        "Works on sync and async functions. "
        "Log each retry with attempt number and exception. "
        "Write 10 tests including async usage.",
        "code_gen")

    add("Build a concurrent task executor",
        "Write TaskExecutor(max_workers=4) with submit(fn, *args), "
        "submit_many(tasks: list[tuple]) → list[Future], "
        "wait_all(), cancel_pending(), "
        "results() → list[Any] (in submission order). "
        "Write 8 tests including cancellation.",
        "code_gen")

    add("Implement pub/sub event system",
        "Write EventBus with: subscribe(event: str, handler: Callable), "
        "publish(event: str, payload: dict), "
        "unsubscribe(event, handler), "
        "publish_async(event, payload) → asyncio coroutine, "
        "middleware support (logging, auth). "
        "Thread-safe. Write 10 tests.",
        "code_gen")

    add("Write a data validation pipeline",
        "Write Pipeline(*validators) where each validator is Callable[[dict], dict | None]. "
        "None means validation failed. "
        "Pipeline.validate(data) → ValidationResult(ok, errors, data). "
        "Built-in validators: required_fields, type_check, range_check, regex_match. "
        "Write 10 tests.",
        "code_gen")

    add("Implement a token bucket for rate limiting",
        "Write TokenBucket(capacity, refill_rate) with consume(tokens=1) → bool. "
        "Refill continuously (not in fixed intervals). "
        "Thread-safe. "
        "Works across processes via Redis (optional). "
        "Write 10 tests.",
        "code_gen")

    add("Build a lightweight dependency injection container",
        "Write Container with: register(name, factory), "
        "resolve(name) → instance (singleton by default), "
        "wire(cls) → inject registered deps into class constructor, "
        "scope: singleton vs transient. "
        "Write 10 tests.",
        "code_gen")

    add("Implement HMAC request signing",
        "Write RequestSigner(secret_key) with: "
        "sign(method, url, body, timestamp) → signature string, "
        "verify(request, signature, timestamp, tolerance_s=300) → bool. "
        "Use SHA-256 HMAC. Replay attack prevention (timestamp check). "
        "Write 8 tests including replay prevention.",
        "code_gen")

    add("Write a binary heap priority queue",
        "Write PriorityQueue with: push(item, priority), "
        "pop() → item (highest priority first), "
        "peek() → item, "
        "update_priority(item, new_priority), "
        "supports custom comparators. "
        "Write 10 tests.",
        "code_gen")

    add("Implement distributed lock via file locking",
        "Write FileLock(path, timeout=10) as context manager. "
        "acquire() blocks until lock available or timeout. "
        "Works across processes. "
        "Stale lock detection (PID check). "
        "Write 8 tests including timeout and stale lock.",
        "code_gen")

    add("Build a simple key-value store with WAL",
        "Write KVStore(path) with get(key), set(key, val), delete(key), "
        "Write-Ahead Log: every write appended to wal.log before applied, "
        "compaction: merge WAL into snapshot when WAL > 1000 entries, "
        "recovery: replay WAL on startup. "
        "Write 10 tests including crash recovery simulation.",
        "code_gen")

    add("Write a typed settings system with validation",
        "Write Settings class using dataclasses + __post_init__ validation. "
        "Read from: env vars, .env file, YAML config, defaults. "
        "Precedence: env > .env > YAML > default. "
        "Type coercion for int, bool, list. "
        "Required field validation. "
        "Write 10 tests.",
        "code_gen")

    add("Implement backpressure-aware producer",
        "Write Producer(consumer_fn, max_queue=100) with: "
        "produce(item) → blocks if queue full (backpressure), "
        "produce_many(items), "
        "flush(), "
        "metrics: produced_count, dropped_count, backpressure_events. "
        "Write 8 tests.",
        "code_gen")

    add("Build a checksum and integrity verification system",
        "Write FileIntegrity with: compute(path) → {md5, sha256, size, mtime}, "
        "verify(path, expected) → (bool, list[str]), "
        "watch(dir, interval=60) → yields changed files, "
        "manifest: save/load all checksums to manifest.json. "
        "Write 8 tests.",
        "code_gen")

    add("Implement command pattern with undo/redo",
        "Write CommandHistory with: execute(cmd: Command), "
        "undo(), redo(), "
        "history() → list[Command], "
        "Command protocol: execute(), undo(), description. "
        "Example: TextEditor with Insert/Delete commands. "
        "Write 10 tests including undo/redo sequences.",
        "code_gen")

    add("Write a structured logger with context",
        "Write Logger(name) with debug/info/warning/error/critical methods. "
        "with_context(**kwargs) returns child logger with extra fields. "
        "JSON output: {timestamp, level, name, message, context, trace_id}. "
        "trace_id propagates via contextvars. "
        "Write 8 tests asserting JSON output structure.",
        "code_gen")

    add("Build a dead letter queue handler",
        "Write DLQ(max_retries=3, retry_delay=5.0) with: "
        "enqueue(task, metadata), "
        "process() → tries task, moves to dead_letters if max retries exceeded, "
        "requeue(task_id) → manually retry from dead letters, "
        "list_dead() → all failed tasks with error info. "
        "Write 10 tests.",
        "code_gen")

    # ── TDD (15): Write tests for real codebases + fix failures ──────────────
    add("Write integration tests for a FastAPI CRUD API",
        "Given a FastAPI app with /users endpoints (provided), "
        "write a full pytest test suite using httpx.AsyncClient: "
        "create, read, update, delete + edge cases (404, 422, duplicate). "
        "Use pytest fixtures with fresh DB per test. "
        "Achieve 90%+ coverage. "
        "All tests must pass.",
        "tdd")

    add("Write property-based tests with Hypothesis",
        "Given a parser module (provided), "
        "write Hypothesis-based property tests for 5 functions. "
        "Define strategies for each input type. "
        "Find and fix at least 2 edge cases the unit tests missed. "
        "Document what Hypothesis found.",
        "tdd")

    add("Write load tests with Locust",
        "Given a FastAPI API (provided), "
        "write a Locust load test: "
        "100 concurrent users, 5-minute ramp-up, "
        "mix of GET (80%) and POST (20%) requests, "
        "assert: p95 latency < 500ms, error rate < 1%, "
        "generate HTML report. "
        "Include a Locustfile.py with realistic user behavior.",
        "tdd")

    add("Write contract tests for a REST API",
        "Given an API spec (OpenAPI YAML provided), "
        "write Schemathesis or custom contract tests that: "
        "hit every endpoint with valid inputs → verify response schema, "
        "hit every endpoint with invalid inputs → verify 4xx responses, "
        "verify Content-Type headers. "
        "Fix any contract violations found.",
        "tdd")

    add("Write mutation tests to find weak test coverage",
        "Given a module with 80% line coverage (provided), "
        "run mutmut or manual mutations on 5 functions. "
        "Find mutations that survive (weak tests). "
        "Write new tests that kill each surviving mutation. "
        "Report: before mutation score vs after.",
        "tdd")

    add("Write async tests for a WebSocket service",
        "Given a WebSocket server (provided), "
        "write pytest-asyncio tests: "
        "connect, send message, receive broadcast, "
        "disconnect handling, "
        "10 concurrent clients, "
        "invalid message handling. "
        "Use asyncio.gather for concurrent test.",
        "tdd")

    add("Write tests for error recovery paths",
        "Given a service with retry logic (provided), "
        "write tests that simulate: "
        "network timeout → retry → success, "
        "5xx response → exponential backoff → success, "
        "all retries exhausted → failure with correct error, "
        "circuit breaker open → fail fast. "
        "Use unittest.mock for all network calls.",
        "tdd")

    add("Write parametrized tests for a data processor",
        "Given a data transformation module (provided), "
        "write pytest parametrized tests covering 20+ input/output pairs: "
        "happy path, null values, unicode, very large numbers, empty lists, "
        "deeply nested dicts. "
        "Use pytest.mark.parametrize. "
        "Achieve 95% branch coverage.",
        "tdd")

    add("Write security tests for an auth module",
        "Given a JWT auth module (provided), "
        "write security tests: "
        "expired token rejection, "
        "invalid signature rejection, "
        "algorithm confusion attack (RS256 → HS256), "
        "missing claims rejection, "
        "timing-safe comparison. "
        "All tests must pass after fixes.",
        "tdd")

    add("Write end-to-end tests for a CLI tool",
        "Given a CLI tool (provided), "
        "write e2e tests using subprocess.run: "
        "test all subcommands with valid args, "
        "test all subcommands with invalid args → correct exit codes, "
        "test --help output format, "
        "test stdin/stdout piping. "
        "Use pytest fixtures for temp directories.",
        "tdd")

    add("Write performance benchmarks with pytest-benchmark",
        "Given a module with 4 algorithmic functions (provided), "
        "write pytest-benchmark tests: "
        "baseline each function with 1000-item input, "
        "compare optimized vs naive implementation, "
        "assert optimized is 2x faster. "
        "Generate benchmark report.",
        "tdd")

    add("Write tests for a state machine",
        "Given a state machine class (provided), "
        "write tests covering: "
        "all valid transitions, "
        "all invalid transitions (assert StateError raised), "
        "concurrent transition attempts (thread safety), "
        "state persistence (serialize/deserialize), "
        "history tracking. "
        "15+ test cases.",
        "tdd")

    add("Write database integration tests",
        "Given a repository class (provided), "
        "write integration tests using real SQLite: "
        "CRUD operations, "
        "transaction rollback on error, "
        "concurrent writes (5 threads), "
        "pagination (offset/limit), "
        "search with filters. "
        "Use pytest fixtures to reset DB between tests.",
        "tdd")

    add("Write tests for a caching layer",
        "Given a cache module (provided), "
        "write tests: "
        "cache hit returns value without calling source, "
        "cache miss calls source and stores result, "
        "TTL expiry forces fresh fetch, "
        "invalidation works correctly, "
        "concurrent access is safe. "
        "10+ tests.",
        "tdd")

    add("Add type coverage with mypy",
        "Given a 200-line module with no type hints (provided), "
        "add type annotations until mypy --strict passes. "
        "Use TypeVar, Protocol, overload where appropriate. "
        "Write 5 tests that exercise the typed interfaces. "
        "No 'type: ignore' allowed.",
        "tdd")

    # ── ARCHITECTURE (10): System design with runnable code ───────────────────
    add("Design and implement a CQRS system",
        "Implement CQRS pattern: "
        "Command side: CreateOrder, CancelOrder commands → CommandBus → handlers, "
        "Query side: GetOrder, ListOrders → read models (denormalized), "
        "Event store: append-only events in SQLite, "
        "Projections: rebuild read models from events. "
        "Include 8 integration tests proving command → query consistency.",
        "arch")

    add("Design a multi-region data sync system",
        "Design and implement a data sync protocol: "
        "2 'regions' (in-memory dicts), "
        "vector clocks for conflict detection, "
        "last-write-wins conflict resolution (with pluggable resolver), "
        "sync protocol: send diff since last_seen_version, "
        "handle network partition: queue writes, replay on reconnect. "
        "Write 10 tests including conflict scenarios.",
        "arch")

    add("Implement a plugin architecture",
        "Design a plugin system: "
        "PluginManager.discover(path) loads all .py files in plugins/, "
        "each plugin registers via @plugin(name, version), "
        "plugins declare dependencies (loaded in order), "
        "PluginManager.enable(name), disable(name), "
        "lifecycle hooks: on_load, on_unload. "
        "Write 8 tests.",
        "arch")

    add("Build a saga-based distributed transaction",
        "Implement saga pattern for a checkout flow: "
        "steps: reserve_inventory → charge_payment → send_confirmation, "
        "compensating transactions: release_inventory, refund_payment, "
        "SagaCoordinator: orchestrate steps with rollback on failure, "
        "persist saga state to DB, "
        "retry failed steps up to 3x. "
        "Write 10 tests including partial failure scenarios.",
        "arch")

    add("Design a hierarchical cache with L1/L2",
        "Implement 2-tier cache: "
        "L1: in-process LRU (fast, limited size 100 items), "
        "L2: disk-based (slow, 10000 items), "
        "policy: L1 hit → return, L1 miss → check L2 → fill L1 → return, "
        "invalidation: propagate to both tiers, "
        "eviction: LRU in L1, LFU in L2. "
        "Write 10 tests.",
        "arch")

    add("Implement event sourcing for user accounts",
        "Build event-sourced UserAccount: "
        "events: UserCreated, EmailChanged, PasswordChanged, AccountDeactivated, "
        "aggregate: apply events to rebuild state, "
        "EventStore: append_event(aggregate_id, event), load_events(aggregate_id), "
        "snapshot every 10 events for performance, "
        "projection: UserSummaryView (current state). "
        "Write 10 tests.",
        "arch")

    add("Build a circuit breaker with half-open state",
        "Implement CircuitBreaker(failure_threshold=5, recovery_timeout=60): "
        "CLOSED → OPEN (after threshold failures), "
        "OPEN → HALF-OPEN (after timeout), "
        "HALF-OPEN → CLOSED (after 3 successful probes), "
        "HALF-OPEN → OPEN (on failure), "
        "metrics: state transitions, failure rate. "
        "Write 12 tests.",
        "arch")

    add("Design a batch processing system with checkpointing",
        "Build BatchProcessor(input_fn, process_fn, output_fn, batch_size=100): "
        "process records in batches, "
        "checkpoint progress every batch (offset to file), "
        "resume from checkpoint on restart, "
        "dead letter queue for failed records, "
        "metrics: throughput, error rate. "
        "Write 10 tests including resume-from-checkpoint.",
        "arch")

    add("Implement a consistent hashing ring",
        "Write ConsistentHashRing with: "
        "add_node(node_id, virtual_nodes=100), "
        "remove_node(node_id), "
        "get_node(key) → node_id (consistent mapping), "
        "rebalancing: minimal data movement when nodes change, "
        "list_nodes() → all physical nodes. "
        "Write 10 tests.",
        "arch")

    add("Build an actor model concurrency system",
        "Implement actor model: "
        "Actor(name, handler_fn) with mailbox (asyncio.Queue), "
        "send(actor_ref, message), "
        "ActorSystem.spawn(cls) → ActorRef, "
        "supervision: restart crashed actors, "
        "poison pill for graceful shutdown. "
        "Write 10 tests including supervision.",
        "arch")

    # ── DEBUG (10): Fix broken production code ────────────────────────────────
    add("Fix a race condition in a producer-consumer system",
        "Given a producer-consumer with intermittent data corruption (provided), "
        "diagnose the race condition using code inspection (not running). "
        "Fix using appropriate synchronization primitives. "
        "Write 5 tests that would have caught the bug. "
        "Explain why the bug occurred in a 3-sentence comment.",
        "debug")

    add("Fix memory leak in a long-running service",
        "Given a service with steadily growing memory (provided, code includes the leak), "
        "identify the leak source (hint: look at caches, listeners, and global state). "
        "Fix it. "
        "Add a test that would detect the leak (check object counts before/after). "
        "Add monitoring: log memory usage every 60s.",
        "debug")

    add("Fix N+1 query problem in ORM code",
        "Given an API endpoint that loads users and their posts (provided), "
        "identify the N+1 query pattern. "
        "Fix using eager loading or DataLoader. "
        "Add query count assertion (max 2 queries for any N users). "
        "Write 5 tests.",
        "debug")

    add("Fix a deadlock in concurrent code",
        "Given a banking system that deadlocks when transferring between accounts (provided), "
        "identify the lock acquisition order causing the deadlock. "
        "Fix using consistent lock ordering or tryLock with timeout. "
        "Write a test that proves the deadlock no longer occurs under concurrent load.",
        "debug")

    add("Fix silent data corruption in a serialization module",
        "Given a module that serializes/deserializes Python objects (provided), "
        "find the 3 bugs causing silent corruption (floats, None values, nested dicts). "
        "Fix all 3. "
        "Write 8 round-trip tests that catch each bug.",
        "debug")

    add("Fix an auth bypass vulnerability",
        "Given an authentication middleware (provided), "
        "find the 2 security vulnerabilities: "
        "1) token validation has a logic error, "
        "2) timing attack is possible. "
        "Fix both. Write security tests proving the fixes work.",
        "debug")

    add("Fix a pagination off-by-one error causing duplicate/missing records",
        "Given a paginated list endpoint (provided), "
        "find and fix the off-by-one error in cursor-based pagination. "
        "Write tests with 11 items across 3 pages verifying no duplicates and no missing items.",
        "debug")

    add("Fix incorrect error handling that swallows exceptions",
        "Given a module with broad try/except blocks that silently discard errors (provided), "
        "identify 4 places where exceptions are swallowed. "
        "Fix each: reraise, log, or return error Result. "
        "Write 8 tests that verify errors propagate correctly.",
        "debug")

    add("Fix a configuration injection that causes test pollution",
        "Given a module using global mutable config (provided), "
        "find where test pollution occurs (tests affecting each other). "
        "Fix using dependency injection or test fixtures that reset state. "
        "Write 5 independent tests that can run in any order.",
        "debug")

    add("Fix incorrect async/await usage causing unhandled promises",
        "Given an async Python module with 5 missing awaits (provided), "
        "find all missing awaits (they cause coroutines to never execute). "
        "Fix each. "
        "Add asyncio.run() assertions to verify execution. "
        "Write 8 tests.",
        "debug")

    # ── RESEARCH (5): Web research + structured deliverable ──────────────────
    add("Research top Python async frameworks for production APIs in 2025",
        "Search for: best Python async web frameworks 2025, "
        "FastAPI vs Litestar vs Starlette benchmarks, "
        "real-world production usage reports. "
        "Deliver: comparison table (throughput, ecosystem, DX, production readiness), "
        "top 3 recommendations with rationale, "
        "list of companies using each in production. "
        "Minimum 5 sources cited.",
        "research")

    add("Research real-world failures of distributed systems in 2024-2025",
        "Search r/devops, Hacker News, engineering blogs for: "
        "production incidents caused by distributed system failures, "
        "most common root causes (split-brain, clock skew, network partition), "
        "how top companies (AWS, Cloudflare, Stripe) handle these. "
        "Deliver: top 10 failure patterns with prevention strategies.",
        "research")

    add("Research local LLM performance on coding tasks vs GPT-4 2025",
        "Search HuggingFace, Papers With Code, r/LocalLLaMA for: "
        "best local models for code generation (SWE-bench scores), "
        "nexus-local vs open-source coder models benchmarks, "
        "hardware requirements for each. "
        "Deliver: leaderboard table with SWE-bench scores, "
        "recommendation for this system (running on Mac M-series).",
        "research")

    add("Research best practices for agent self-improvement",
        "Search academic papers (ArXiv), GitHub, and tech blogs for: "
        "self-improving AI agent architectures, "
        "prompt optimization methods (APE, OPRO, DSPy), "
        "agent benchmark suites better than HumanEval. "
        "Deliver: 5 techniques applicable to this system, "
        "ranked by implementation effort vs quality gain.",
        "research")

    add("Research production observability stack for Python microservices 2025",
        "Search for: best observability setup for Python services in production, "
        "OpenTelemetry Python SDK adoption, "
        "Prometheus vs Datadog vs Grafana Cloud tradeoffs, "
        "structured logging best practices (structlog vs loguru). "
        "Deliver: recommended stack with setup instructions (< 1 hour to implement), "
        "cost comparison for 10M events/day.",
        "research")

    if n:
        tasks = tasks[:n]
    return tasks


if __name__ == "__main__":
    suite = build_task_suite()
    cats = {}
    for t in suite:
        cats[t["category"]] = cats.get(t["category"], 0) + 1
    print(f"Total tasks: {len(suite)}")
    for cat, count in sorted(cats.items()):
        print(f"  {cat:12}: {count}")
