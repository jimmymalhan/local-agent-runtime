#!/usr/bin/env python3
"""
Autonomous agent runner V4 — iterative tool-use loop.
Called by agent-loop.sh / Business OS API to give agents Claude-like autonomy.

Flow per task:
  1. Triage    — discover relevant files from title+description
  2. Context   — preload those files + directory listing
  3. Iterate   — up to MAX_ITERATIONS rounds: LLM → parse directives → execute → feedback
  4. Verify    — confirm output files exist and are non-empty
  5. Report    — log outcome, update task status via API

Supported directives (parsed from LLM output):
  WRITE_FILE: <path>\n```\n<content>\n```
  READ_FILE: <path>
  PATCH_FILE: <path> — <find_str> → <replace_str>
  LIST_DIR: <path>
  SEARCH_CODE: <pattern>
  RUN: <shell command>
  DONE: <message>
  FAILED: <reason>
"""
import os, sys, json, re, subprocess, time, textwrap, traceback, urllib.request
from pathlib import Path
from datetime import datetime

# ── Config ─────────────────────────────────────────────────────────────────
API            = f"http://127.0.0.1:{os.environ.get('PORT_API','8000')}"
def _resolve_bos() -> str:
    p = os.environ.get('BOS_HOME', os.path.expanduser('~/local-agents-work'))
    # Resolve symlinks; if broken symlink, fall back to default
    try:
        resolved = os.path.realpath(p)
        if os.path.islink(p) and not os.path.exists(resolved):
            p = os.path.expanduser('~/local-agents-work')
        os.makedirs(p, exist_ok=True)
        return p
    except Exception:
        fallback = os.path.expanduser('~/local-agents-work')
        os.makedirs(fallback, exist_ok=True)
        return fallback
BOS            = _resolve_bos()
NEXUS_API      = os.environ.get('NEXUS_API', '')
LOCAL_MODEL    = os.environ.get('LOCAL_MODEL', 'nexus-local')
MAX_FILE_CHARS = 12_000
MAX_CTX        = 12288
MAX_ITERATIONS = 12
SCRATCH_DIR    = '/tmp'

# ── Complexity tiers ────────────────────────────────────────────────────────
_SIMPLE_PATTERNS = {
    'hello world', 'fibonacci', 'factorial', 'binary search', 'bubble sort',
    'insertion sort', 'selection sort', 'reverse string', 'palindrome',
    'fizzbuzz', 'two sum', 'sum of', 'count words', 'flatten list',
    'merge sort', 'quicksort', 'group by', 'memoize', 'decorator',
    'stack', 'queue', 'linked list', 'thread-safe counter', 'retry decorator',
    'context manager', 'csv parser', 'has_cycle', 'lru cache',
}
_ULTRA_KEYWORDS = {
    'distributed', 'consensus', 'raft', 'paxos', 'vector clock',
    'actor model', 'event sourcing', 'cqrs', 'saga pattern',
    'service mesh', 'circuit breaker full', 'chaos engineering',
    'benchmark harness', 'jit compiler', 'virtual machine', 'bytecode',
}


def classify_task(title: str, description: str) -> dict:
    combined = (title + ' ' + description).lower()
    is_ultra = any(kw in combined for kw in _ULTRA_KEYWORDS)
    wc = len(description.split())
    is_simple = (not is_ultra and wc < 80 and
                 any(p in combined for p in _SIMPLE_PATTERNS))
    if is_ultra:
        return {"tier": "ultra", "max_iters": 16, "num_ctx": 16384, "timeout": 480}
    if is_simple:
        return {"tier": "simple", "max_iters": 5, "num_ctx": 4096, "timeout": 120}
    if wc > 200 or any(kw in combined for kw in ['multi-file', 'fastapi', 'pipeline', 'e2e']):
        return {"tier": "hard", "max_iters": 14, "num_ctx": 12288, "timeout": 360}
    return {"tier": "medium", "max_iters": 10, "num_ctx": 8192, "timeout": 240}


# ── API helpers ─────────────────────────────────────────────────────────────

def api_call(method: str, path: str, data=None, timeout: int = 15):
    url = f"{API}{path}"
    body = json.dumps(data).encode() if data else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def update_task_status(task_id: int, status: str, note: str = ""):
    payload = {"status": status}
    if note:
        payload["notes"] = note[:2000]
    api_call("PATCH", f"/tasks/{task_id}", payload)


def add_task_log(task_id: int, message: str, level: str = "info"):
    api_call("POST", f"/tasks/{task_id}/logs", {
        "level": level,
        "message": message[:1000],
    })


# ── Nexus engine LLM call ───────────────────────────────────────────────────

def llm_call(messages: list, num_ctx: int = MAX_CTX, model: str = None) -> str:
    """Call Nexus engine chat API. Returns assistant message content."""
    model = model or LOCAL_MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "num_ctx": num_ctx,
            "temperature": 0.1,
            "top_p": 0.9,
        },
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{NEXUS_API}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
            return resp.get("message", {}).get("content", "")
    except Exception as e:
        return f"[LLM_ERROR] {e}"


# ── Path normalization ──────────────────────────────────────────────────────

def normalize_path(p: str) -> str:
    """Normalize /local-agents-os/ shorthand to actual BOS path."""
    if p.startswith('/local-agents-os/') or p == '/local-agents-os':
        p = BOS + p[len('/local-agents-os'):]
    if p.startswith('~/'):
        p = os.path.expanduser(p)
    return p


# ── Directive parsers ───────────────────────────────────────────────────────

def parse_write_file(text: str) -> list:
    """Extract WRITE_FILE directives. Falls back to markdown code blocks with path hints."""
    writes = []
    # Primary: explicit WRITE_FILE: directive
    pattern = re.compile(
        r'WRITE_FILE:\s*(.+?)\n(?:```(?:\w+)?\n)?(.*?)(?:```|(?=\nWRITE_FILE:|\nDONE:|\nFAILED:|\Z))',
        re.DOTALL
    )
    for m in pattern.finditer(text):
        path = normalize_path(m.group(1).strip())
        content = m.group(2).strip()
        if path and content:
            writes.append({"path": path, "content": content})
    if writes:
        return writes

    # Fallback: detect "File path: /abs/path.py" + subsequent code block
    path_hints = re.findall(
        r'(?:[Ff]ile\s+[Pp]ath|[Ff]ile\s+[Nn]ame|[Ff]ilename|[Pp]ath)[:`\s]+[`"\']?(/[^\s\n`\'"]+\.py)[`"\']?',
        text
    )
    # Also check for first-line path comment inside code block: # /abs/path/file.py
    code_blocks = re.findall(r'```(?:python)?\n(.*?)```', text, re.DOTALL)
    for block in code_blocks:
        first_line = block.strip().splitlines()[0] if block.strip() else ""
        m = re.match(r'#\s*(/[^\s]+\.py)', first_line)
        if m:
            path_hints.insert(0, m.group(1))

    if path_hints and code_blocks:
        detected_path = normalize_path(path_hints[0].strip())
        # Pick the largest Python-looking code block
        py_blocks = [b for b in code_blocks if re.search(r'\bdef \b|\bclass \b|import ', b)]
        content = max(py_blocks or code_blocks, key=len).strip()
        # Strip leading path comment if present
        lines = content.splitlines()
        if lines and re.match(r'#\s*/[^\s]+\.py', lines[0]):
            content = "\n".join(lines[1:]).strip()
        if content:
            writes.append({"path": detected_path, "content": content})
        return writes

    # Last resort: any code block with def/class → write to BOS/solution.py
    for block in code_blocks:
        if re.search(r'\bdef \b|\bclass \b', block):
            writes.append({"path": os.path.join(BOS, "solution.py"), "content": block.strip()})
            return writes

    return writes


def parse_run_commands(text: str) -> list:
    """Extract RUN: commands. Falls back to ```sh blocks."""
    cmds = []
    # Primary: explicit RUN: directive
    for m in re.finditer(r'^RUN:\s*(.+)$', text, re.MULTILINE):
        cmd = m.group(1).strip()
        cmd = re.sub(r'(?<![/\w])/local-agents-os(/[^\s\'"]*)?',
                     lambda m2: BOS + (m2.group(1) or ''), cmd)
        cmds.append(cmd)
    if cmds:
        return cmds
    # Fallback: extract python3 commands from ```sh / ```bash / ```shell blocks
    for m in re.finditer(r'```(?:sh|bash|shell|console)\n(.*?)```', text, re.DOTALL):
        for line in m.group(1).splitlines():
            line = line.strip()
            if line and not line.startswith('#') and re.search(r'\bpython3?\b', line):
                line = re.sub(r'(?<![/\w])/local-agents-os(/[^\s\'"]*)?',
                              lambda m2: BOS + (m2.group(1) or ''), line)
                cmds.append(line)
    return cmds


def parse_patch_file(text: str) -> list:
    """Extract PATCH_FILE directives."""
    patches = []
    for m in re.finditer(r'PATCH_FILE:\s*(.+?)\s*—\s*(.+?)\s*→\s*(.+)$', text, re.MULTILINE):
        patches.append({
            "path": normalize_path(m.group(1).strip()),
            "find": m.group(2).strip(),
            "replace": m.group(3).strip(),
        })
    return patches


def parse_read_file(text: str) -> list:
    """Extract READ_FILE paths."""
    paths = []
    for m in re.finditer(r'^READ_FILE:\s*(.+)$', text, re.MULTILINE):
        paths.append(normalize_path(m.group(1).strip()))
    return paths


def parse_list_dir(text: str) -> list:
    """Extract LIST_DIR paths."""
    paths = []
    for m in re.finditer(r'^LIST_DIR:\s*(.+)$', text, re.MULTILINE):
        paths.append(normalize_path(m.group(1).strip()))
    return paths


def parse_search_code(text: str) -> list:
    """Extract SEARCH_CODE patterns."""
    patterns = []
    for m in re.finditer(r'^SEARCH_CODE:\s*(.+)$', text, re.MULTILINE):
        patterns.append(m.group(1).strip())
    return patterns


def is_done(text: str) -> bool:
    return bool(re.search(r'(?:^DONE:|^\*\*DONE[:\*]|^DONE\s*—)', text, re.MULTILINE))


def is_failed(text: str) -> str:
    m = re.search(r'^FAILED:\s*(.+)$', text, re.MULTILINE)
    return m.group(1).strip() if m else ""


# ── Directive executors ─────────────────────────────────────────────────────

def exec_write_file(path: str, content: str) -> str:
    # Ensure all writes stay inside BOS — never leak to project root or /
    abs_path = os.path.abspath(path)
    if not abs_path.startswith(BOS):
        # Relative path or wrong prefix → redirect to BOS/basename
        filename = os.path.basename(abs_path) or "solution.py"
        path = os.path.join(BOS, filename)
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            f.write(content)
        size = len(content)
        lines = content.count('\n') + 1
        return f"[WRITE_FILE] OK: {path} ({lines} lines, {size} chars)"
    except Exception as e:
        return f"[WRITE_FILE] ERROR: {path}: {e}"


def exec_run(cmd: str, timeout: int = 30) -> str:
    # Normalize: model often emits `python` but macOS only has `python3`
    import re as _re
    cmd = _re.sub(r'\bpython\b(?!3)', 'python3', cmd)
    # Skip unfilled placeholder paths
    if '/path/to/' in cmd or '/absolute/path/' in cmd:
        return "[RUN] SKIP: placeholder path not replaced by agent"
    # Skip bare relative filenames like `python3 file.py` or `python3 solution.py`
    if _re.search(r'python3?\s+(?![-/])\w+\.py\b', cmd) and not cmd.strip().startswith('/') and '/' not in cmd.split()[-1]:
        return "[RUN] SKIP: relative filename — agent must use absolute path"
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        rc = result.returncode
        combined = []
        if out:
            combined.append(out[:2000])
        if err:
            combined.append(f"STDERR: {err[:500]}")
        combined.append(f"returncode={rc}")
        return "[RUN] " + "\n".join(combined)
    except subprocess.TimeoutExpired:
        return f"[RUN] TIMEOUT after {timeout}s: {cmd}"
    except Exception as e:
        return f"[RUN] ERROR: {e}"


def exec_patch_file(path: str, find: str, replace: str) -> str:
    try:
        with open(path) as f:
            content = f.read()
        if find not in content:
            return f"[PATCH_FILE] Pattern not found in {path}: {find[:50]}"
        new_content = content.replace(find, replace, 1)
        with open(path, 'w') as f:
            f.write(new_content)
        return f"[PATCH_FILE] OK: {path}"
    except Exception as e:
        return f"[PATCH_FILE] ERROR: {e}"


def exec_read_file(path: str) -> str:
    try:
        with open(path) as f:
            content = f.read(MAX_FILE_CHARS)
        lines = content.count('\n') + 1
        return f"[READ_FILE] {path} ({lines} lines):\n{content}"
    except Exception as e:
        return f"[READ_FILE] ERROR: {path}: {e}"


def exec_list_dir(path: str) -> str:
    try:
        entries = sorted(os.listdir(path))
        return f"[LIST_DIR] {path}:\n" + "\n".join(f"  {e}" for e in entries[:100])
    except Exception as e:
        return f"[LIST_DIR] ERROR: {path}: {e}"


def exec_search_code(pattern: str, search_path: str = None) -> str:
    search_path = search_path or BOS
    try:
        result = subprocess.run(
            ["grep", "-r", "--include=*.py", "-n", pattern, search_path],
            capture_output=True, text=True, timeout=15
        )
        out = (result.stdout or "").strip()[:3000]
        return f"[SEARCH_CODE] '{pattern}' in {search_path}:\n{out or '(no matches)'}"
    except Exception as e:
        return f"[SEARCH_CODE] ERROR: {e}"


# ── System prompt builder ───────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are an elite autonomous software engineer. You complete every coding task with production-level quality.

## Chain-of-Thought Protocol (MANDATORY — follow in order)

### Step 1: Understand
Restate the task in one sentence. List exact deliverables (files to create, functions to implement).
Identify what is NOT needed (scope boundary).

### Step 2: Plan
For each file you will write: name the file path, list the functions/classes inside it, note dependencies.
Use REAL absolute paths like {BOS}/filename.py — NEVER write /path/to/file.py.

### Step 3: Implement
Write the COMPLETE code. No placeholders. No "# TODO". No "...".
Every function must be fully implemented. Every import must be real.
Include a __main__ block with at least 3 assertions that prove correctness.

### Step 4: Verify
After writing each file:
  RUN: python3 -m py_compile /absolute/path/to/file.py
  RUN: python3 /absolute/path/to/file.py
Both must pass before DONE.

### Step 5: Self-Audit (before DONE)
1. All file paths are real absolute paths ✓
2. All imports reference real stdlib or installed packages ✓
3. All functions are fully implemented (no stubs) ✓
4. RUN commands passed ✓
5. __main__ assertions cover happy path + edge cases ✓

## Directives

WRITE_FILE: {BOS}/solution.py
```python
# COMPLETE file content — all imports, all code, no placeholders
```

READ_FILE: {BOS}/solution.py
LIST_DIR: {BOS}
SEARCH_CODE: pattern
PATCH_FILE: {BOS}/solution.py — <find> → <replace>
RUN: python3 -m py_compile {BOS}/solution.py
RUN: python3 {BOS}/solution.py
DONE: one-line summary of what was built and tested
FAILED: exact reason (missing dep, permission error — not "can't figure it out")

## Hard Rules
- File paths MUST start with {BOS}/ — use {BOS}/taskname.py as your default
- NEVER use /path/to/ or /absolute/path/ or file.py alone — always {BOS}/filename.py
- NEVER write local-agents-os in any path — use {BOS}/ only
- NEVER truncate code — write every single line
- NEVER leave stubs — every function must be fully implemented
- Use python3 not python in all RUN commands
- After WRITE_FILE: RUN py_compile, then RUN the file, then DONE
- Quality = files written + RUN OK + __main__ assertions pass
"""


# ── Main agent loop ─────────────────────────────────────────────────────────

def run_task(task: dict) -> dict:
    """
    Main entry: run a single task through the iterative agent loop.
    Returns: {status, iters, files_written, quality_score}
    """
    task_id = task.get("id")
    title = task.get("title", "")
    description = task.get("description", title)
    codebase_path = task.get("codebase_path", BOS)

    complexity = classify_task(title, description)
    max_iters = complexity["max_iters"]
    num_ctx = complexity["num_ctx"]

    print(f"[AGENT] Task #{task_id}: {title[:60]} [{complexity['tier']}]")
    if task_id:
        update_task_status(task_id, "in_progress", f"Agent started [{complexity['tier']}]")

    # Build initial context
    context_parts = [f"Task: {title}\n\n{description}"]
    try:
        entries = sorted(os.listdir(codebase_path))[:30]
        context_parts.append(f"Codebase at {codebase_path}:\n" +
                              "\n".join(f"  {e}" for e in entries))
    except Exception:
        pass

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(context_parts)},
    ]

    files_written = []
    tool_results = []
    productive_iters = 0
    start = time.time()

    for iteration in range(max_iters):
        # Feed tool results from previous iteration
        if tool_results:
            messages.append({
                "role": "user",
                "content": "Tool results:\n" + "\n".join(tool_results[-8:])
            })
            tool_results = []

        # LLM call
        response = llm_call(messages, num_ctx=num_ctx)
        if response.startswith("[LLM_ERROR]"):
            print(f"[AGENT] LLM error at iter {iteration}: {response}")
            break

        messages.append({"role": "assistant", "content": response})
        if task_id:
            add_task_log(task_id, f"iter {iteration+1}: {response[:200]}")

        # Parse and execute directives
        iter_productive = False

        # WRITE_FILE
        for w in parse_write_file(response):
            result = exec_write_file(w["path"], w["content"])
            tool_results.append(result)
            if "OK:" in result:
                files_written.append(w["path"])
                iter_productive = True
                print(f"  [WRITE] {w['path']}")

        # PATCH_FILE
        for p in parse_patch_file(response):
            result = exec_patch_file(p["path"], p["find"], p["replace"])
            tool_results.append(result)
            if "OK:" in result:
                iter_productive = True

        # READ_FILE
        for path in parse_read_file(response):
            result = exec_read_file(path)
            tool_results.append(result[:3000])

        # LIST_DIR
        for path in parse_list_dir(response):
            result = exec_list_dir(path)
            tool_results.append(result)

        # SEARCH_CODE
        for pattern in parse_search_code(response):
            result = exec_search_code(pattern, codebase_path)
            tool_results.append(result[:2000])

        # RUN
        for cmd in parse_run_commands(response):
            result = exec_run(cmd)
            tool_results.append(result)
            if "returncode=0" in result:
                iter_productive = True
                print(f"  [RUN] OK: {cmd[:60]}")
            else:
                print(f"  [RUN] FAIL: {cmd[:60]}")

        if iter_productive:
            productive_iters += 1

        # Check terminal conditions
        fail_reason = is_failed(response)
        if fail_reason:
            print(f"[AGENT] FAILED: {fail_reason}")
            if task_id:
                update_task_status(task_id, "blocked", f"FAILED: {fail_reason}")
            return {"status": "failed", "iters": iteration+1,
                    "files_written": files_written, "quality_score": 0}

        if is_done(response):
            elapsed = time.time() - start
            quality = _compute_quality(files_written, tool_results)
            print(f"[AGENT] DONE in {elapsed:.1f}s | iters={iteration+1} | "
                  f"files={len(files_written)} | quality={quality}/100")
            if task_id:
                update_task_status(task_id, "done",
                                   f"Done in {elapsed:.1f}s, quality={quality}/100")
                api_call("PATCH", f"/tasks/{task_id}", {"eval_score": quality})
            return {"status": "done", "iters": iteration+1,
                    "files_written": files_written, "quality_score": quality}

    # Exhausted iterations
    elapsed = time.time() - start
    print(f"[AGENT] Max iterations ({max_iters}) reached in {elapsed:.1f}s")
    quality = _compute_quality(files_written, tool_results) if files_written else 0

    if files_written and quality >= 40:
        # Partial success
        if task_id:
            update_task_status(task_id, "done",
                               f"Partial: {len(files_written)} files, quality={quality}/100")
            api_call("PATCH", f"/tasks/{task_id}", {"eval_score": quality})
        return {"status": "partial", "iters": max_iters,
                "files_written": files_written, "quality_score": quality}

    if task_id:
        update_task_status(task_id, "blocked",
                           f"Max iterations reached, {len(files_written)} files written")
    return {"status": "blocked", "iters": max_iters,
            "files_written": files_written, "quality_score": quality}


def _compute_quality(files_written: list, tool_results: list) -> int:
    """Score 0-100 based on files written and run results."""
    score = 0
    if files_written:
        score += min(40, len(files_written) * 15)
    results_text = " ".join(str(r) for r in tool_results).lower()
    if "returncode=0" in results_text:
        score += 25
    if "error" not in results_text and "failed" not in results_text:
        score += 15
    if "assert" in results_text or "pass" in results_text:
        score += 10
    if "syntax" in results_text:
        score -= 10
    return max(0, min(100, score))


# ── Task poller (standalone mode) ──────────────────────────────────────────

def poll_and_run(poll_interval: int = 5, model: str = None):
    """
    Continuously poll the task board for 'todo' tasks assigned to 'local-agent'
    and process them one at a time. Runs as a daemon process.
    """
    global LOCAL_MODEL
    if model:
        LOCAL_MODEL = model
    print(f"[POLLER] Starting task poller (model={LOCAL_MODEL})")
    while True:
        try:
            tasks = api_call("GET", "/tasks?status=todo&assignee=local-agent&limit=5") or []
            if not tasks:
                tasks = api_call("GET", "/tasks?status=todo&limit=5") or []
                tasks = [t for t in tasks if t.get("assignee") == "local-agent"]

            if tasks:
                task = tasks[0]
                print(f"\n[POLLER] Picked up task #{task['id']}: {task.get('title','')[:60]}")
                run_task(task)
            else:
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("[POLLER] Stopped")
            break
        except Exception as e:
            print(f"[POLLER] Error: {e}")
            time.sleep(poll_interval)


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Autonomous agent runner V4")
    ap.add_argument("--task-id", type=int, help="Run a specific task by ID")
    ap.add_argument("--poll", action="store_true", help="Poll board and run tasks")
    ap.add_argument("--model", default=LOCAL_MODEL, help="Nexus engine model to use")
    ap.add_argument("--test", action="store_true", help="Run self-test")
    args = ap.parse_args()

    if args.test:
        test_task = {
            "id": None,
            "title": "Write hello_world.py",
            "description": (
                f"WRITE_FILE: {BOS}/hello_world.py\n"
                "```python\ndef hello(name='World'):\n    return f'Hello, {name}!'\n\n"
                "if __name__ == '__main__':\n    assert hello() == 'Hello, World!'\n"
                "    assert hello('Test') == 'Hello, Test!'\n    print('OK')\n```\n"
                f"RUN: python3 {BOS}/hello_world.py\nDONE: hello_world.py written."
            ),
        }
        result = run_task(test_task)
        print(json.dumps(result, indent=2))
    elif args.task_id:
        task = api_call("GET", f"/tasks/{args.task_id}")
        if task:
            result = run_task(task)
            print(json.dumps(result, indent=2))
        else:
            print(f"Task {args.task_id} not found")
    elif args.poll:
        poll_and_run(model=args.model)
    else:
        ap.print_help()
