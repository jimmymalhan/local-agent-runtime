#!/usr/bin/env python3
"""
tasks/task_suite.py — 100 Hard Task Benchmark Suite
=====================================================
Reusable across any project. Zero hardcoded paths. Pure capability testing.

Covers:
  - HumanEval-style coding problems (25 tasks)
  - LeetCode Hard algorithms (20 tasks)
  - Full project spin-up from 1 line (15 tasks)
  - Multi-file refactor with breaking changes (15 tasks)
  - Autonomous debugging of broken codebases (10 tasks)
  - Test generation with coverage (10 tasks)
  - System architecture design (5 tasks)

Usage:
  from tasks.task_suite import build_task_suite
  tasks = build_task_suite()          # all 100
  tasks = build_task_suite(n=10)      # first 10
  tasks = build_task_suite(category="code_gen")  # filter by category
"""

def build_task_suite(n: int = 0, category: str = "") -> list:
    tasks = []
    _id = [1]

    def add(title, desc, cat, difficulty="hard"):
        tasks.append({
            "id": _id[0],
            "title": title,
            "description": desc,
            "category": cat,
            "difficulty": difficulty,
        })
        _id[0] += 1

    # ── HumanEval-style Code Gen (25 tasks) ────────────────────────────────
    add("Implement LRU Cache",
        "Write a Python class LRUCache(capacity) with get(key) and put(key, value). "
        "get returns -1 if key not found. O(1) for both operations. "
        "Include full test suite with at least 8 assertions.",
        "code_gen")
    add("Balanced parentheses checker",
        "Write is_valid(s: str) -> bool that returns True if brackets are balanced. "
        "Handles (), [], {}. Write assertions for empty string, nested, mismatched.",
        "code_gen")
    add("Serialize / deserialize binary tree",
        "Write serialize(root) and deserialize(data) for a binary tree. "
        "Use a BFS approach. Include TreeNode class. "
        "Test with a 7-node tree and verify round-trip.",
        "code_gen")
    add("Implement Trie with prefix search",
        "Write Trie class with insert(word), search(word), startsWith(prefix). "
        "All O(m) where m = word length. Include 10+ assertions.",
        "code_gen")
    add("Flatten nested dictionary",
        "Write flatten(d: dict, sep: str = '.') -> dict that flattens nested dicts "
        "using sep as separator for nested keys. Handle empty dicts and None values.",
        "code_gen")
    add("Rate limiter with sliding window",
        "Implement RateLimiter(max_calls: int, period_s: float) class with "
        "allow() -> bool method using sliding window algorithm. Thread-safe.",
        "code_gen")
    add("Implement merge sort with comparison counter",
        "Write merge_sort(arr, counter=[]) that sorts and counts comparisons. "
        "Return (sorted_arr, comparison_count). Test with 10+ cases.",
        "code_gen")
    add("Fibonacci with memoization and big number support",
        "Write fib(n: int) -> int that handles n up to 10000. "
        "Use iterative approach (not recursion) with O(n) time and O(1) space. "
        "Verify fib(100) = 354224848179261915075.",
        "code_gen")
    add("CSV parser with type inference",
        "Write parse_csv(text: str) -> list[dict] that parses CSV text. "
        "Infer types: int, float, bool, str. Handle quoted fields with commas.",
        "code_gen")
    add("Async HTTP client with retry and backoff",
        "Write async fetch(url, max_retries=3) using aiohttp or httpx. "
        "Exponential backoff: 1s, 2s, 4s. Handle timeouts and 5xx errors.",
        "code_gen")
    add("Implement a pub/sub event bus",
        "Write EventBus class with subscribe(event, callback), publish(event, data), "
        "unsubscribe(event, callback). Thread-safe. Test with multiple subscribers.",
        "code_gen")
    add("Parse and evaluate mathematical expressions",
        "Write evaluate(expr: str) -> float that evaluates expressions like "
        "'3 + 4 * 2 / (1 - 5)^2'. Handles +, -, *, /, ^ and parentheses. "
        "No eval() allowed.",
        "code_gen")
    add("Implement circular buffer",
        "Write CircularBuffer(size) with push(item), pop() -> item, is_full() -> bool. "
        "FIFO. Raises BufferError if empty or full. Fully tested.",
        "code_gen")
    add("URL parser and builder",
        "Write parse_url(url: str) -> dict and build_url(parts: dict) -> str. "
        "Handle scheme, host, port, path, query params, fragment. Round-trip tests.",
        "code_gen")
    add("Dijkstra shortest path",
        "Write dijkstra(graph: dict, start: str, end: str) -> tuple[int, list]. "
        "Returns (distance, path). Graph: {node: {neighbor: weight}}. "
        "Test on a 6-node graph.",
        "code_gen")
    add("Implement thread-safe counter with atomic increment",
        "Write AtomicCounter with increment(), decrement(), get() -> int, reset(). "
        "Thread-safe. Test with 100 threads each incrementing 1000 times.",
        "code_gen")
    add("JSON schema validator",
        "Write validate(data, schema) -> tuple[bool, list[str]]. "
        "Support type, required, properties, minLength, minimum, maximum. "
        "Return (is_valid, list_of_errors).",
        "code_gen")
    add("Implement a simple tokenizer",
        "Write tokenize(code: str) -> list[Token] for Python-like syntax. "
        "Token types: NUMBER, STRING, IDENTIFIER, OPERATOR, PUNCTUATION, WHITESPACE. "
        "Dataclass Token(type, value, line, col).",
        "code_gen")
    add("Implement binary search with rotated array support",
        "Write search(nums: list, target: int) -> int that works on both normal "
        "and rotated sorted arrays. O(log n). Returns index or -1.",
        "code_gen")
    add("Bloom filter implementation",
        "Write BloomFilter(capacity, error_rate) with add(item), might_contain(item). "
        "Use MurmurHash-inspired bit operations. Show false positive rate test.",
        "code_gen")
    add("Retry decorator with exponential backoff",
        "Write @retry(max_attempts=3, backoff=2.0, exceptions=(Exception,)) decorator. "
        "Doubles wait time each retry. Logs each attempt. Test with a flaky function.",
        "code_gen")
    add("Implement observer pattern",
        "Write Observable with subscribe(event_type, handler), emit(event_type, data), "
        "unsubscribe(event_type, handler). Support wildcard '*' event type.",
        "code_gen")
    add("Graph cycle detection (directed and undirected)",
        "Write has_cycle_directed(graph) and has_cycle_undirected(graph) using DFS. "
        "Graph as adjacency list. Test with 5 graphs including edge cases.",
        "code_gen")
    add("Implement priority queue with update-priority support",
        "Write PriorityQueue with push(item, priority), pop() -> item, "
        "update_priority(item, new_priority). Min-heap. O(log n) operations.",
        "code_gen")
    add("Write a coroutine-based pipeline",
        "Write pipeline(*transforms) that chains coroutine functions. "
        "Each transform is async def f(item) -> item. Test with 3 transforms "
        "and 100 items processed concurrently.",
        "code_gen")

    # ── LeetCode Hard Algorithms (20 tasks) ────────────────────────────────
    add("Median of two sorted arrays",
        "Write find_median_sorted_arrays(nums1, nums2) -> float. O(log(m+n)). "
        "No merging allowed. Test with: [1,3],[2] → 2.0; [1,2],[3,4] → 2.5",
        "bug_fix")
    add("Trapping rain water",
        "Write trap(height: list) -> int using O(1) space (two pointer). "
        "Test: [0,1,0,2,1,0,1,3,2,1,2,1] → 6",
        "bug_fix")
    add("Wildcard pattern matching",
        "Write is_match(s: str, p: str) -> bool where p has '?' (any char) "
        "and '*' (any sequence). DP solution. Test 8 cases.",
        "bug_fix")
    add("Minimum window substring",
        "Write min_window(s, t) -> str. Find smallest window in s containing "
        "all chars of t. Empty string if none. Sliding window O(n).",
        "bug_fix")
    add("Word ladder II — all shortest paths",
        "Write find_ladders(begin, end, word_list) -> list[list[str]]. "
        "BFS + backtrack. 'hit' → 'hot' → 'dot' → 'dog' → 'cog'",
        "bug_fix")
    add("Largest rectangle in histogram",
        "Write largest_rectangle(heights: list) -> int using a stack. "
        "O(n). Test: [2,1,5,6,2,3] → 10",
        "bug_fix")
    add("N-Queens II — count solutions",
        "Write total_n_queens(n: int) -> int. Count all valid placements. "
        "n=8 → 92. Bitmasking approach.",
        "bug_fix")
    add("Serialize expression tree and evaluate",
        "Write ExprTree with parse(expr: str), evaluate() -> float, to_infix() -> str. "
        "Handles +,-,*,/,^ and parentheses.",
        "bug_fix")
    add("Regular expression matching",
        "Write is_match(s, p) with '.' and '*'. DP table approach. "
        "Test: ('aa','a*') → True, ('ab','.*') → True, ('aab','c*a*b') → True",
        "bug_fix")
    add("Bus routes — minimum transfers",
        "Write num_buses_to_destination(routes, source, target) -> int. "
        "BFS over routes not stops. Test provided example.",
        "bug_fix")
    add("Edit distance with path reconstruction",
        "Write edit_distance(s1, s2) -> tuple[int, list[str]]. "
        "Returns (min_ops, list_of_operations). Each op: 'insert c at i', etc.",
        "bug_fix")
    add("Maximum flow — Ford-Fulkerson",
        "Write max_flow(graph, source, sink) -> int. Adjacency matrix. "
        "Test on 6-node network with expected result 23.",
        "bug_fix")
    add("Skyline problem",
        "Write get_skyline(buildings) -> list[list[int]]. "
        "buildings = [[L,R,H]]. Output: [[x,h]] key points.",
        "bug_fix")
    add("All palindrome partitions with min cuts",
        "Write min_cut(s: str) -> int and all_palindrome_partitions(s) -> list[list]. "
        "DP for min_cut O(n^2). Backtrack for all partitions.",
        "bug_fix")
    add("Count of smaller numbers after self",
        "Write count_smaller(nums: list) -> list[int] using merge sort + counting. "
        "O(n log n). Test: [5,2,6,1] → [2,1,1,0]",
        "bug_fix")
    add("Alien dictionary — topological sort",
        "Write alien_order(words: list[str]) -> str. "
        "Returns character order or '' if invalid. Use Kahn's algorithm.",
        "bug_fix")
    add("Burst balloons DP",
        "Write max_coins(nums: list) -> int. DP interval problem. "
        "Test: [3,1,5,8] → 167",
        "bug_fix")
    add("Sliding window maximum",
        "Write max_sliding_window(nums, k) -> list using deque. O(n). "
        "Test: [1,3,-1,-3,5,3,6,7], k=3 → [3,3,5,5,6,7]",
        "bug_fix")
    add("Largest number in array after k swaps",
        "Write largest_number(arr: list, k: int) -> str. "
        "Greedy approach. Test: arr=[1,2,3,4,5], k=2 → '54321'? Verify.",
        "bug_fix")
    add("Stone game optimal strategy DP",
        "Write stone_game(piles: list) -> bool. Returns True if first player always wins. "
        "And optimal_score(piles) -> tuple[int,int] returning both players' scores.",
        "bug_fix")

    # ── Full Project Spin-Up (15 tasks) ────────────────────────────────────
    add("Build FastAPI TODO API with SQLite",
        "Scaffold a complete FastAPI application with SQLite backend. "
        "Endpoints: POST /todos, GET /todos, GET /todos/{id}, PATCH /todos/{id}, DELETE /todos/{id}. "
        "Use SQLAlchemy ORM. Include Pydantic schemas, proper HTTP status codes, "
        "and a working main.py. All in a single directory.",
        "scaffold")
    add("Build a Python CLI tool with Click",
        "Build a CLI tool called 'filebot' using Click. Commands: "
        "filebot search --pattern GLOB, filebot rename --from PATTERN --to PATTERN, "
        "filebot stats PATH. Include help text and error handling.",
        "scaffold")
    add("Build a Redis-like in-memory store",
        "Build RedisLite: in-memory key-value store with: SET/GET/DEL, "
        "EXPIRE/TTL, LPUSH/LPOP/LRANGE, HSET/HGET/HGETALL. "
        "Thread-safe. Full test suite.",
        "scaffold")
    add("Build a webhook dispatcher service",
        "Build a WebhookDispatcher: accepts events via POST /events, "
        "dispatches to registered webhooks with retry logic (3 retries, backoff). "
        "Register webhooks via POST /webhooks. FastAPI + asyncio.",
        "scaffold")
    add("Build a markdown to HTML static site generator",
        "Build SiteGen CLI: reads *.md files from input/, converts to HTML with "
        "template, outputs to output/. Supports frontmatter (title, date, tags). "
        "Generates index.html with list of posts.",
        "scaffold")
    add("Build a Python package with proper structure",
        "Scaffold a pip-installable Python package 'datatools' with: "
        "pyproject.toml, src/datatools/__init__.py, 3 utility modules, "
        "tests/ with pytest, README.md, GitHub Actions CI yaml.",
        "scaffold")
    add("Build a task queue with worker pool",
        "Build TaskQueue with enqueue(func, *args), start_workers(n), "
        "stop(), get_results() -> list. Uses threading. Handles exceptions. "
        "Test with 50 tasks and 4 workers.",
        "scaffold")
    add("Build a configuration management system",
        "Build ConfigManager that loads from YAML/JSON/env vars with priority: "
        "env > file > defaults. Supports nested keys, type coercion, "
        "hot-reload on file change, validation.",
        "scaffold")
    add("Build a simple ORM with metaclass magic",
        "Build MiniORM: Model base class using metaclasses. "
        "Supports Field(type, required, default), save(), delete(), "
        "find(**kwargs) -> list, SQLite backend. Test with User and Post models.",
        "scaffold")
    add("Build a dependency injection container",
        "Build DIContainer with register(name, factory), resolve(name), "
        "singleton support, circular dependency detection. "
        "Test with a 3-layer service architecture.",
        "scaffold")
    add("Build a caching middleware for FastAPI",
        "Build CacheMiddleware for FastAPI: caches GET responses by URL + query params. "
        "TTL per route via decorator @cache(ttl=60). In-memory LRU store. "
        "Include cache stats endpoint.",
        "scaffold")
    add("Build a log aggregator with tail and search",
        "Build LogAggregator: tail -f style watcher on multiple log files. "
        "Search by regex, time range, log level. Output to terminal or file. "
        "Async file watchers.",
        "scaffold")
    add("Build a feature flag system",
        "Build FeatureFlags: enable/disable features per user/environment. "
        "Store in JSON file. Decorator @feature_required('flag_name'). "
        "Percentage rollout support. REST API to toggle flags.",
        "scaffold")
    add("Build a schema migration tool",
        "Build DBMigrate: reads migration files from migrations/*.sql, "
        "tracks applied migrations in _migrations table, apply(), rollback(n=1), "
        "status() shows applied/pending. SQLite.",
        "scaffold")
    add("Build a plugin system with dynamic loading",
        "Build PluginManager: discovers plugins in plugins/ directory, "
        "loads them dynamically, validates plugin interface, registers hooks. "
        "Plugin protocol: name, version, hooks: dict[str, callable].",
        "scaffold")

    # ── TDD Red/Green (15 tasks) ────────────────────────────────────────────
    add("TDD: Write tests first for a bank account",
        "Write the failing tests first for BankAccount class. Then implement "
        "to make them pass. Must have: deposit, withdraw, transfer, get_balance. "
        "Tests must cover: overdraft, negative amounts, concurrent transfers.",
        "tdd")
    add("TDD: Tests for a password validator",
        "Write failing tests for validate_password(pwd) -> tuple[bool, list[str]]. "
        "Rules: min 8 chars, uppercase, lowercase, digit, special char. "
        "Return (is_valid, list_of_violations). Implement after tests.",
        "tdd")
    add("TDD: Tests for a shopping cart",
        "Write tests for ShoppingCart: add_item, remove_item, apply_coupon, "
        "get_total (with tax), checkout -> Receipt. Coupon types: percent, fixed.",
        "tdd")
    add("TDD: Tests for a file system mock",
        "Write tests for MockFS: create_file, read_file, write_file, delete_file, "
        "list_dir, mkdir. Raise FileNotFoundError / IsADirectoryError correctly.",
        "tdd")
    add("TDD: Tests for a state machine",
        "Write tests for StateMachine(states, transitions, initial). "
        "transition(event) raises InvalidTransition if not allowed. "
        "Test a traffic light and a door lock.",
        "tdd")
    add("TDD: Tests for a CSV report generator",
        "Write tests for ReportGenerator: add_row, set_headers, filter_rows, "
        "sort_by(col), export_csv() -> str, export_json() -> str.",
        "tdd")
    add("TDD: Tests for an in-memory search engine",
        "Write tests for SearchEngine: index(doc_id, text), search(query) -> list[str], "
        "delete(doc_id). Case insensitive. Support AND/OR operators.",
        "tdd")
    add("TDD: Tests for a graph path finder",
        "Write tests for PathFinder: bfs_path, dfs_path, all_paths, shortest_path. "
        "Directed weighted graph. Test disconnected, cyclic, large graphs.",
        "tdd")
    add("TDD: Tests for a token bucket rate limiter",
        "Write tests for TokenBucket(rate, capacity). consume(tokens) -> bool. "
        "refill happens automatically. Thread-safety tests with concurrent callers.",
        "tdd")
    add("TDD: Tests for a date/time parser",
        "Write tests for parse_datetime(s) -> datetime. Handles: ISO 8601, "
        "Unix timestamps, relative ('2 days ago'), natural language ('next Monday').",
        "tdd")
    add("TDD: Tests for a diff algorithm",
        "Write tests for diff(a: list, b: list) -> list[Change]. "
        "Change has type (add/remove/keep), index, value. Myers diff algorithm.",
        "tdd")
    add("TDD: Tests for a circuit breaker",
        "Write tests for CircuitBreaker(failure_threshold, reset_timeout). "
        "States: closed, open, half-open. call(func) wraps function. "
        "Test state transitions under failure/recovery scenarios.",
        "tdd")
    add("TDD: Tests for a JSON patch applier",
        "Write tests for apply_patch(obj, patch) implementing RFC 6902 JSON Patch. "
        "Operations: add, remove, replace, move, copy, test.",
        "tdd")
    add("TDD: Tests for a permissions system",
        "Write tests for Permissions(roles, resources). "
        "check(user, action, resource) -> bool. RBAC model. "
        "Test: read/write/delete actions with admin/editor/viewer roles.",
        "tdd")
    add("TDD: Tests for an event sourcing store",
        "Write tests for EventStore: append(event), get_events(aggregate_id), "
        "replay(aggregate_id) -> AggregateState, snapshot_at(version).",
        "tdd")

    # ── Architecture Design (5 tasks) ──────────────────────────────────────
    add("Design a distributed task queue",
        "Design and implement a simplified distributed task queue. "
        "Components: Producer, Broker (in-memory), Consumer pool, DeadLetterQueue. "
        "Worker heartbeat, task retry on timeout, poison pill handling.",
        "arch")
    add("Design a CQRS event-sourced system",
        "Design Command/Query Responsibility Segregation with event sourcing. "
        "CommandBus, QueryBus, EventStore, Projector. "
        "Implement for a simple order management domain.",
        "arch")
    add("Design a multi-tenant SaaS data layer",
        "Design data isolation strategy for multi-tenant app. "
        "Options: shared table (tenant_id), separate schema, separate DB. "
        "Implement shared table approach with Row Level Security simulation.",
        "arch")
    add("Design a plugin architecture for a text editor",
        "Design extensible plugin system: PluginHost, Plugin interface, "
        "HookRegistry, PluginLoader. Plugins can: intercept keystrokes, "
        "modify buffer, add commands, register file type handlers.",
        "arch")
    add("Design a real-time collaborative editing engine",
        "Design Operational Transformation engine for collaborative text editing. "
        "Operations: insert(pos, char), delete(pos). transform(op1, op2) for conflicts. "
        "Implement two-client convergence proof.",
        "arch")

    # ── Refactoring (10 tasks) ──────────────────────────────────────────────
    add("Refactor: spaghetti code into clean architecture",
        "Given a 100-line Python function that does everything (parse, validate, "
        "transform, store), refactor it into separate classes following SRP. "
        "Write the messy code first, then refactor it, keeping all tests green.",
        "refactor")
    add("Refactor: extract strategy pattern",
        "Refactor a sorting function with 5 if/elif branches (bubble, merge, quick, "
        "heap, radix) into a Strategy pattern. Demonstrate OCP.",
        "refactor")
    add("Refactor: replace magic numbers and strings",
        "Take code with 20+ magic numbers and strings, extract them to named "
        "constants, Enum classes, and config. Show before/after with same behavior.",
        "refactor")
    add("Refactor: eliminate deep nesting",
        "Take a function with 5 levels of nesting (if/for/try). Refactor using "
        "early returns, guard clauses, extracted helper functions. "
        "Max nesting depth after refactor: 2.",
        "refactor")
    add("Refactor: convert callback hell to async/await",
        "Convert nested callback-based code (5 levels deep) to clean async/await. "
        "Handle errors properly. Show that behavior is preserved.",
        "refactor")
    add("Refactor: extract configuration from code",
        "Take a class hardcoded with 15 configuration values. Extract to "
        "dataclass Config, YAML file, and environment variable support. "
        "Priority: env > yaml > defaults.",
        "refactor")
    add("Refactor: replace inheritance with composition",
        "Take a 4-level inheritance hierarchy. Refactor to composition using "
        "Protocol types and dependency injection. Show all tests still pass.",
        "refactor")
    add("Refactor: optimize hot path with profiling",
        "Take a slow function with obvious inefficiencies (O(n²) lookup, repeated "
        "computation, unnecessary copies). Profile it with cProfile, identify "
        "top 3 bottlenecks, fix them, show 10x improvement.",
        "refactor")
    add("Refactor: add type annotations to untyped code",
        "Take 200 lines of Python with no type annotations. Add full mypy-compatible "
        "type hints. Use TypeVar, Generic, Protocol where appropriate. Run mypy.",
        "refactor")
    add("Refactor: split monolith into modules",
        "Take a 500-line single-file Python script. Identify cohesive modules. "
        "Split into properly organized package with __init__.py, no circular imports, "
        "clean public API.",
        "refactor")

    # ── TDD extras (5 tasks to reach 100) ──────────────────────────────────
    add("TDD: Tests for a regex engine",
        "Write tests for RegexMatcher(pattern).match(text) -> Match|None. "
        "Support: . * + ? ^ $ [] groups. Then implement to pass all tests.",
        "tdd")
    add("TDD: Tests for a simple query language",
        "Write tests for QueryParser(table_data).query(sql_like: str) -> list. "
        "Support: SELECT col, FROM, WHERE col=val AND/OR col>val, ORDER BY, LIMIT.",
        "tdd")
    add("TDD: Tests for a webhook signature verifier",
        "Write tests for verify_signature(payload, signature, secret) -> bool. "
        "HMAC-SHA256 based. Test timing-safe comparison, tampered payload rejection.",
        "tdd")
    add("TDD: Tests for an object pool",
        "Write tests for ObjectPool(factory, max_size). acquire() -> obj, release(obj). "
        "Blocks if pool empty. Timeout raises PoolExhausted. Thread-safe.",
        "tdd")
    add("TDD: Tests for a simple interpreter",
        "Write tests for Interpreter that executes: variable assignment, "
        "arithmetic, if/else, while loops, print. Each test: program string → expected output.",
        "tdd")

    # ── E2E Pipelines (5 tasks) ─────────────────────────────────────────────
    add("Build full ETL pipeline with error recovery",
        "Build ETL pipeline: extract from CSV, transform (clean, validate, normalize), "
        "load to SQLite. Error recovery: log bad rows, continue. "
        "Report: rows processed, errors, time.",
        "e2e")
    add("Build a code review automation pipeline",
        "Build pipeline: read Python file → AST analysis → complexity metrics → "
        "style check (PEP8) → security scan (hardcoded secrets, SQL injection) → "
        "report. All checks run in parallel.",
        "e2e")
    add("Build a data validation and normalization pipeline",
        "Build pipeline for user data: validate schema → normalize phone/email/names → "
        "deduplicate → enrich (add country from phone prefix) → export. "
        "Process 1000 rows, show stats.",
        "e2e")
    add("Build a log analysis pipeline",
        "Parse nginx access logs → extract: top 10 URLs, error rate, p50/p95/p99 "
        "latency, requests per minute trend → write HTML report. "
        "Use generator pipeline for memory efficiency.",
        "e2e")
    add("Build a dependency graph analyzer",
        "Analyze Python project imports: build dependency graph, "
        "detect circular imports, find unused imports, rank by fan-in/fan-out, "
        "generate ASCII graph and JSON report.",
        "e2e")

    # Filter if requested
    all_tasks = tasks
    if category:
        all_tasks = [t for t in tasks if t["category"] == category]
    if n:
        all_tasks = all_tasks[:n]

    return all_tasks


if __name__ == "__main__":
    suite = build_task_suite()
    from collections import Counter
    cats = Counter(t["category"] for t in suite)
    print(f"Total tasks: {len(suite)}")
    for cat, count in sorted(cats.items()):
        print(f"  {cat:12}: {count}")
