#!/usr/bin/env python3
"""
opus_benchmark.py — 100-Task Ultra Benchmark Suite (Single Source)
====================================================================
build_task_suite() returns all 100 tasks used by bench_compare.py.

Categories (100 tasks total):
  code_gen  : 25   bug_fix  : 20   scaffold : 15
  tdd       : 15   arch     : 10   refactor : 10   e2e : 5

Each task has:
  id, category, title, description (with WRITE_FILE/RUN/PATCH_FILE directives)

Used by: bench_compare.py (single import point)
DO NOT create tasks directly here — use bench_compare.py.
"""
import os
from pathlib import Path

BOS = os.path.expanduser("~/local-agents-os")


def build_task_suite() -> list:
    """Return all 100 benchmark tasks. Called once by bench_compare.py."""
    tasks = []

    # ── Category 1: Code Generation (25 tasks) ────────────────────────────
    code_gen_specs = [
        ("Implement a stack with push/pop/peek/is_empty",
         "class Stack:\n    def push(self, x): ...\n    def pop(self): ...\n    def peek(self): ...\n    def is_empty(self) -> bool: ..."),
        ("Implement a queue using two stacks",
         "class Queue:\n    def enqueue(self, x): ...\n    def dequeue(self): ..."),
        ("Write binary search (iterative, returns index or -1)",
         "def binary_search(arr: list, target: int) -> int: ..."),
        ("Write merge sort",
         "def merge_sort(arr: list) -> list: ..."),
        ("Implement LRU Cache with get/put in O(1)",
         "class LRUCache:\n    def __init__(self, capacity: int): ...\n    def get(self, key: int) -> int: ...\n    def put(self, key: int, val: int): ..."),
        ("Write a retry decorator (N times, configurable exceptions)",
         "def retry(times=3, exceptions=(Exception,)):\n    def decorator(fn): ...\n    return decorator"),
        ("Implement a pub/sub EventEmitter",
         "class EventEmitter:\n    def on(self, event, fn): ...\n    def emit(self, event, *args): ...\n    def off(self, event, fn): ..."),
        ("Write a Timer context manager that prints elapsed time",
         "class Timer:\n    def __enter__(self): ...\n    def __exit__(self, *args): ..."),
        ("Implement flatten(nested_list) recursively",
         "def flatten(lst): ...  # [[1,[2]],[3]] → [1,2,3]"),
        ("Write a memoize decorator using functools.wraps",
         "def memoize(fn): ..."),
        ("Implement a CSV parser (no stdlib csv module)",
         "def parse_csv(text: str) -> list: ..."),
        ("Write group_by(lst, key_fn) → dict",
         "def group_by(lst, key_fn): ..."),
        ("Implement a thread-safe counter using threading.Lock",
         "class Counter:\n    def increment(self): ...\n    def value(self) -> int: ..."),
        ("Write has_cycle(head) — Floyd's tortoise and hare",
         "def has_cycle(head) -> bool: ..."),
        ("Implement a Trie with insert/search/starts_with",
         "class Trie:\n    def insert(self, word): ...\n    def search(self, word) -> bool: ...\n    def starts_with(self, prefix) -> bool: ..."),
        ("Write a topological sort dependency resolver",
         "def resolve(deps: dict) -> list: ...  # {'b':['a'],'c':['b']} → ['a','b','c']"),
        ("Implement rolling_average(data, window) as a generator",
         "def rolling_average(data, window): ..."),
        ("Write chunk(lst, n) — yields sublists of size n",
         "def chunk(lst, n): ..."),
        ("Implement deep_equal(a, b) for nested dicts/lists",
         "def deep_equal(a, b) -> bool: ..."),
        ("Write all permutations of a string",
         "def permutations(s: str) -> list: ..."),
        ("Implement a tokenizer: split on whitespace + punctuation",
         "def tokenize(text: str) -> list: ..."),
        ("Write Caesar cipher encode/decode",
         "def caesar(text: str, shift: int, decode=False) -> str: ..."),
        ("Implement a URL slug generator",
         "def slugify(text: str) -> str: ...  # 'Hello World!' → 'hello-world'"),
        ("Write a simple math expression evaluator (no eval)",
         "def calc(expr: str) -> float: ...  # '3 + 4 * 2' → 11.0"),
        ("Implement a Bloom filter",
         "class BloomFilter:\n    def add(self, item): ...\n    def might_contain(self, item) -> bool: ..."),
    ]
    for i, (title, hint) in enumerate(code_gen_specs):
        tasks.append({
            "id": f"codegen_{i+1:02d}",
            "category": "code_gen",
            "title": f"CODE-{i+1:02d}: {title}",
            "description": (
                f"WRITE_FILE: {BOS}/bench_code_{i+1:02d}.py\n"
                f"```python\n# {title}\n{hint}\n```\n"
                f"Include a __main__ block with at least 3 assertions.\n"
                f"RUN: python3 {BOS}/bench_code_{i+1:02d}.py\n"
                f"DONE: file written, all assertions pass."
            ),
            "weight": 1,
        })

    # ── Category 2: Bug Fixing (20 tasks) ─────────────────────────────────
    bug_specs = [
        ("off-by-one in binary search",
         "def search(arr,t):\n    l,r=0,len(arr)\n    while l<r:\n        m=(l+r)//2\n        if arr[m]==t: return m\n        elif arr[m]<t: l=m  # BUG: should be l=m+1\n        else: r=m\n    return -1"),
        ("infinite loop in linked list reverse",
         "def reverse(head):\n    prev=None; curr=head\n    while curr:\n        curr.next=prev  # BUG: lost next pointer\n        prev=curr; curr=curr.next\n    return prev"),
        ("integer overflow in fibonacci",
         "def fib(n):\n    a,b=0,1\n    for _ in range(n): a,b=b,a+b\n    return a  # BUG: returns a, should return b for fib(n)"),
        ("wrong base case in factorial",
         "def factorial(n):\n    if n==1: return 1  # BUG: misses n==0\n    return n*factorial(n-1)"),
        ("stack overflow in quicksort (no base case)",
         "def quicksort(arr):\n    pivot=arr[0]  # BUG: no base case check\n    left=[x for x in arr if x<pivot]\n    right=[x for x in arr if x>pivot]\n    return quicksort(left)+[pivot]+quicksort(right)"),
        ("wrong comparison in max_subarray (Kadane's)",
         "def max_sub(arr):\n    best=curr=arr[0]\n    for x in arr[1:]:\n        curr=max(x, curr+x)\n        best=max(best,curr)\n    return best  # BUG: should initialize from arr[0] not loop from 1"),
        ("race condition in thread-safe counter (missing lock)",
         "class Counter:\n    def __init__(self): self.n=0\n    def inc(self): self.n+=1  # BUG: not thread-safe\n    def val(self): return self.n"),
        ("memory leak — list grows unbounded",
         "cache=[]\ndef add(x):\n    cache.append(x)  # BUG: no eviction policy"),
        ("wrong slice in rotate array",
         "def rotate(arr, k):\n    k=k%len(arr)\n    return arr[k:]+arr[:k]  # BUG: should be arr[-k:]+arr[:-k]"),
        ("broken merge in merge sort",
         "def merge(a,b):\n    out=[]\n    while a and b:\n        if a[0]<b[0]: out.append(a.pop())  # BUG: pop() removes from end\n        else: out.append(b.pop(0))\n    return out+a+b"),
        ("wrong dict update in group_by",
         "def group_by(lst,fn):\n    d={}\n    for x in lst:\n        k=fn(x)\n        d[k]=x  # BUG: overwrites, should append"),
        ("CSV parser fails on quoted fields",
         'def parse_csv(line):\n    return line.split(",")  # BUG: breaks on "a,b","c"'),
        ("tokenizer drops last token",
         "def tokenize(s):\n    tokens=[]; cur=''\n    for c in s:\n        if c.isalnum(): cur+=c\n        elif cur: tokens.append(cur)  # BUG: misses final token\n    return tokens"),
        ("bloom filter false negative (wrong hash)",
         "class BF:\n    def __init__(self): self.bits=set()\n    def add(self,x): self.bits.add(hash(x))\n    def check(self,x): return hash(x)+1 in self.bits  # BUG: +1"),
        ("LRU get doesn't update recency",
         "class LRU:\n    def __init__(self,cap): self.cap=cap; self.cache={}\n    def get(self,k): return self.cache.get(k,-1)  # BUG: no recency update"),
        ("EventEmitter doesn't support multiple listeners",
         "class EE:\n    def __init__(self): self.h={}\n    def on(self,e,fn): self.h[e]=fn  # BUG: overwrites, not appends"),
        ("retry decorator swallows non-retryable errors",
         "def retry(fn):\n    def w(*a):\n        for _ in range(3):\n            try: return fn(*a)\n            except: pass  # BUG: catches ALL exceptions\n    return w"),
        ("context manager doesn't restore state on exception",
         "class CM:\n    def __enter__(self): self.old=os.getcwd(); os.chdir('/tmp')\n    def __exit__(self,*a): pass  # BUG: never restores"),
        ("dependency resolver has no cycle detection",
         "def resolve(deps):\n    order=[]\n    def visit(n):\n        for dep in deps.get(n,[]): visit(dep)  # BUG: infinite loop on cycles\n        if n not in order: order.append(n)\n    for n in deps: visit(n)\n    return order"),
        ("Caesar cipher wraps incorrectly for negative shift",
         "def caesar(text,shift):\n    return ''.join(chr(ord(c)+shift) for c in text)  # BUG: no modulo wrap"),
    ]
    for i, (title, buggy_code) in enumerate(bug_specs):
        tasks.append({
            "id": f"bugfix_{i+1:02d}",
            "category": "bug_fix",
            "title": f"BUG-{i+1:02d}: Fix {title}",
            "description": (
                f"Buggy code:\n```python\n{buggy_code}\n```\n"
                f"WRITE_FILE: {BOS}/bench_bug_{i+1:02d}.py  (write the FIXED version)\n"
                f"Include 3+ assertions that would have caught the bug.\n"
                f"RUN: python3 {BOS}/bench_bug_{i+1:02d}.py\n"
                f"DONE: bug fixed, all assertions pass."
            ),
            "weight": 1,
        })

    # ── Category 3: Project Scaffold (15 tasks) ────────────────────────────
    scaffold_specs = [
        ("CLI TODO app", "bench_todo_app", "FastAPI + SQLite CRUD"),
        ("Python package template", "bench_package", "setup.py + __init__.py + tests/"),
        ("Flask REST API", "bench_flask", "GET/POST/PUT/DELETE + error handlers"),
        ("SQLite CRUD module", "bench_sqlite_crud", "create/read/update/delete + migrations"),
        ("HTTP API client", "bench_api_client", "requests wrapper with retry + auth"),
        ("Log parser CLI", "bench_log_parser", "parse nginx/app logs, filter by level"),
        ("Task queue (in-memory)", "bench_task_queue", "producer/consumer with threading"),
        ("Config loader", "bench_config_loader", "YAML/JSON/ENV with type validation"),
        ("Markdown to HTML converter", "bench_md_to_html", "headings, bold, code blocks"),
        ("CSV pipeline", "bench_csv_pipeline", "read → transform → write with type coercion"),
        ("File watcher", "bench_file_watcher", "inotify/polling + callback on change"),
        ("KV store with TTL", "bench_kv_store", "dict + expiry, thread-safe"),
        ("Plugin loader", "bench_plugin_loader", "importlib + entry points pattern"),
        ("Circuit breaker", "bench_circuit_breaker", "closed/open/half-open states"),
        ("Scheduler (cron-style)", "bench_scheduler", "run tasks at intervals, thread-safe"),
    ]
    for i, (name, dirname, hint) in enumerate(scaffold_specs):
        tasks.append({
            "id": f"scaffold_{i+1:02d}",
            "category": "scaffold",
            "title": f"SCAFFOLD-{i+1:02d}: Build {name}",
            "description": (
                f"Build a complete {name} project.\n"
                f"Hint: {hint}\n"
                f"Target directory: {BOS}/{dirname}/\n"
                f"Required files: __init__.py, main.py, test_{dirname.replace('bench_','')}.py\n"
                f"WRITE_FILE: {BOS}/{dirname}/main.py\n"
                f"WRITE_FILE: {BOS}/{dirname}/test_{dirname.replace('bench_','')}.py\n"
                f"RUN: python3 -m py_compile {BOS}/{dirname}/main.py\n"
                f"RUN: python3 -m pytest {BOS}/{dirname}/ -q 2>&1 | head -15\n"
                f"DONE: project written, at least 2 tests pass."
            ),
            "weight": 2,
        })

    # ── Category 4: TDD Red/Green (15 tasks) ──────────────────────────────
    tdd_specs = [
        ("string_utils", "reverse, palindrome, count_vowels, slugify"),
        ("math_utils", "is_prime, gcd, lcm, power_mod"),
        ("list_utils", "flatten, chunk, group_by, zip_with"),
        ("cache", "LRUCache: get/put/capacity/eviction"),
        ("tokenizer", "split, tokenize, count_words, stem"),
        ("validator", "email, url, phone, credit card formats"),
        ("date_utils", "parse_date, days_between, next_weekday, format_relative"),
        ("tree_ops", "bst_insert, bst_search, inorder, height"),
        ("graph_ops", "bfs, dfs, has_cycle, topological_sort"),
        ("rate_limiter", "token bucket: allow, refill, is_allowed"),
        ("event_bus", "subscribe, publish, unsubscribe, wildcard"),
        ("json_diff", "diff two JSON objects, return added/removed/changed"),
        ("text_search", "exact, prefix, fuzzy (Levenshtein distance ≤2)"),
        ("concurrency", "thread-safe queue: put, get, empty, size"),
        ("serializer", "to_json, from_json, to_csv, from_csv"),
    ]
    for i, (module, features) in enumerate(tdd_specs):
        test_file = f"test_{module}.py"
        impl_file = f"{module}.py"
        tasks.append({
            "id": f"tdd_{i+1:02d}",
            "category": "tdd",
            "title": f"TDD-{i+1:02d}: {module} ({features.split(',')[0]}...)",
            "description": (
                f"TDD Red/Green cycle for: {module}\nFeatures: {features}\n\n"
                f"Step 1 (RED): Write failing tests\n"
                f"  WRITE_FILE: {BOS}/{test_file}\n"
                f"  RUN: python3 -m pytest {BOS}/{test_file} 2>&1 | head -5  # must show FAILED\n\n"
                f"Step 2 (GREEN): Implement to pass all tests\n"
                f"  WRITE_FILE: {BOS}/{impl_file}\n"
                f"  RUN: python3 -m pytest {BOS}/{test_file} -v 2>&1 | head -20\n\n"
                f"DONE: all tests pass, implementation complete."
            ),
            "weight": 2,
        })

    # ── Category 5: Architecture / Design (10 tasks) ──────────────────────
    arch_specs = [
        ("Observer pattern", "Subject/Observer with add/remove/notify"),
        ("Command pattern", "Command/Invoker/History with undo/redo"),
        ("Strategy pattern", "sorting strategy: bubble/merge/quick interchangeable"),
        ("Pipeline pattern", "data pipeline: source → transform → sink composable"),
        ("Repository pattern", "abstract repo + in-memory impl + SQLite impl"),
        ("Circuit breaker", "full state machine: closed/open/half-open with metrics"),
        ("Event sourcing", "EventStore: append_event, get_history, rebuild_state"),
        ("CQRS stub", "separate Command and Query handlers, in-memory"),
        ("Service locator", "register, resolve, singleton vs transient"),
        ("Actor model stub", "Actor: send_message, receive, mailbox queue"),
    ]
    for i, (pattern, desc) in enumerate(arch_specs):
        tasks.append({
            "id": f"arch_{i+1:02d}",
            "category": "arch",
            "title": f"ARCH-{i+1:02d}: Implement {pattern}",
            "description": (
                f"Design and implement: {pattern}\n"
                f"Requirements: {desc}\n"
                f"WRITE_FILE: {BOS}/bench_arch_{i+1:02d}.py\n"
                f"Include a runnable demo in __main__ that shows all features.\n"
                f"RUN: python3 {BOS}/bench_arch_{i+1:02d}.py\n"
                f"DONE: pattern implemented, demo runs without errors."
            ),
            "weight": 2,
        })

    # ── Category 6: Refactoring (10 tasks) ────────────────────────────────
    refactor_specs = [
        ("Extract method: 80-line function with 5 responsibilities",
         "def process(data):\n    # 80 lines of mixed validation + transform + save + log + notify\n    pass"),
        ("Remove duplication: 3 nearly-identical report generators",
         "# report_daily(), report_weekly(), report_monthly() share 90% code"),
        ("Replace magic numbers with named constants",
         "if status == 3: ...\nif retries > 7: ...\nif timeout < 30: ..."),
        ("Convert procedural to OOP: script with 15 globals",
         "# 200-line script, 15 module globals, 8 functions with side effects"),
        ("Add error handling to brittle code",
         "# Code that crashes on: missing key, None input, empty list, network error"),
        ("Break god class: class with 25 methods, 3 concerns",
         "class App:  # handles config + db + HTTP + logging + formatting"),
        ("Replace switch/elif chain with polymorphism",
         "if type=='circle': ...\nelif type=='square': ...\nelif type=='triangle': ..."),
        ("Introduce null object pattern",
         "# 12 places check 'if result is None: ...' before using result"),
        ("Replace temp variable with query method",
         "total = price * qty\ntax = total * 0.08\nfinal = total + tax  # repeated 20 times"),
        ("Extract configuration from hardcoded values",
         "# URLs, timeouts, limits, thresholds all hardcoded in 8 different files"),
    ]
    for i, (title, code_smell) in enumerate(refactor_specs):
        tasks.append({
            "id": f"refactor_{i+1:02d}",
            "category": "refactor",
            "title": f"REFACTOR-{i+1:02d}: {title}",
            "description": (
                f"Original smell:\n```python\n{code_smell}\n```\n"
                f"WRITE_FILE: {BOS}/bench_refactor_{i+1:02d}.py\n"
                f"Write the REFACTORED version (clean, maintainable, same behavior).\n"
                f"Include a simple test that proves behavior is preserved.\n"
                f"RUN: python3 -m py_compile {BOS}/bench_refactor_{i+1:02d}.py\n"
                f"RUN: python3 {BOS}/bench_refactor_{i+1:02d}.py\n"
                f"DONE: refactored, clean, tests pass."
            ),
            "weight": 2,
        })

    # ── Category 7: E2E Pipeline (5 tasks) ────────────────────────────────
    e2e_specs = [
        ("Data ingestion pipeline", "CSV → validate → transform → SQLite → summary report"),
        ("API + CLI dual interface", "FastAPI backend + Click CLI that calls same business logic"),
        ("Event-driven workflow", "EventBus → handlers → side effects → audit log"),
        ("Multi-stage data processor", "5 stages: load → clean → enrich → aggregate → export"),
        ("Async task executor", "asyncio task pool, rate limiting, retry, progress tracking"),
    ]
    for i, (title, components) in enumerate(e2e_specs):
        tasks.append({
            "id": f"e2e_{i+1:02d}",
            "category": "e2e",
            "title": f"E2E-{i+1:02d}: {title}",
            "description": (
                f"Build end-to-end: {title}\n"
                f"Components: {components}\n"
                f"Target: {BOS}/bench_e2e_{i+1:02d}/\n"
                f"WRITE_FILE: {BOS}/bench_e2e_{i+1:02d}/main.py\n"
                f"WRITE_FILE: {BOS}/bench_e2e_{i+1:02d}/test_main.py\n"
                f"RUN: python3 -m py_compile {BOS}/bench_e2e_{i+1:02d}/main.py\n"
                f"RUN: python3 -m pytest {BOS}/bench_e2e_{i+1:02d}/ -q 2>&1 | head -15\n"
                f"SCAN_TODOS: {BOS}/bench_e2e_{i+1:02d}/\n"
                f"DONE: pipeline complete, all tests pass."
            ),
            "weight": 3,
        })

    assert len(tasks) == 100, f"Expected 100 tasks, got {len(tasks)}"
    return tasks


if __name__ == "__main__":
    tasks = build_task_suite()
    from collections import Counter
    cats = Counter(t["category"] for t in tasks)
    print(f"Total tasks: {len(tasks)}")
    for cat, n in sorted(cats.items()):
        print(f"  {cat}: {n}")
