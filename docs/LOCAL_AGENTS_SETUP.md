# LOCAL AGENTS SETUP
Paste into Claude Code from your project directory.
Local only — no git, no GitHub, no remote anything.
Works with ANY project. All variables are derived from your current directory.

---

## CHAT WITH AGENTS RIGHT NOW (no setup needed)

```bash
ollama run llama3.1:8b        # reasoning / planning
ollama run qwen2.5-coder:7b   # code questions
```

Type message → Enter. `/bye` to exit.

---

## PROJECT CONFIG

```bash
PROJECT_SLUG=$(basename "$PWD" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr '_' '-')
PROJECT_NAME=$(basename "$PWD" | sed 's/-/ /g' | sed 's/_/ /g' | \
  awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2)}1')
CODEBASE_PATH="$PWD"
BOS="$HOME/$PROJECT_SLUG-os"
export BOS_HOME="$BOS" PROJECT_SLUG PROJECT_NAME CODEBASE_PATH

# Models (only these 2 — never pull 32b+, swaps and kills Mac)
LOCAL_LIGHT="qwen2.5-coder:7b"       # code / bug tasks
LOCAL_STANDARD="llama3.1:8b"         # ops / design / research / write tasks
export LOCAL_LIGHT LOCAL_STANDARD

# Ports
PORT_API=8000
PORT_FRONTEND=3000
export PORT_API PORT_FRONTEND

# supervisord binary (pip-installed, not brew)
SUPCTL="$HOME/Library/Python/3.9/bin/supervisorctl -c $BOS/supervisord.conf"
SUPD="$HOME/Library/Python/3.9/bin/supervisord"
OLLAMA_API_BASE="http://127.0.0.1:11434"
export OLLAMA_API_BASE

echo "========================================"
echo "  Project:  $PROJECT_NAME"
echo "  Slug:     $PROJECT_SLUG"
echo "  Path:     $CODEBASE_PATH"
echo "  BOS:      $BOS"
echo "  Models:   $LOCAL_LIGHT / $LOCAL_STANDARD"
echo "  Ports:    API=$PORT_API  UI=$PORT_FRONTEND"
echo "========================================"
```

---

## RESUME RULE

```bash
SETUP_DONE=$(sqlite3 $BOS/business.db \
  "SELECT value FROM settings WHERE key='setup_complete'" 2>/dev/null)
[ "$SETUP_DONE" = "true" ] && echo "SETUP DONE — skip to ADDING TASKS" && SKIP_SETUP=1
```

If `SKIP_SETUP=1` — skip Steps 1–8, go straight to ADDING TASKS.

---

## RESUME CHECK (run every session)

```bash
BOS=$HOME/$PROJECT_SLUG-os
export BOS_HOME=$BOS
SUPCTL="$HOME/Library/Python/3.9/bin/supervisorctl -c $BOS/supervisord.conf"

echo "=== RESUME CHECK: $PROJECT_NAME ==="

[ -f "$BOS/business.db" ]         && echo "  DB            EXISTS  SKIP" || echo "  DB            MISSING CREATE"
[ -f "$BOS/api.py" ]              && echo "  api.py        EXISTS  SKIP" || echo "  api.py        MISSING CREATE"
[ -f "$BOS/db.py" ]               && echo "  db.py         EXISTS  SKIP" || echo "  db.py         MISSING CREATE"
[ -f "$BOS/agent-loop.sh" ]       && echo "  agent-loop    EXISTS  SKIP" || echo "  agent-loop    MISSING CREATE"
[ -f "$BOS/agent_runner.py" ]     && echo "  agent_runner  EXISTS  SKIP" || echo "  agent_runner  MISSING CREATE"
[ -f "$BOS/supervisor-agent.py" ] && echo "  supervisor    EXISTS  SKIP" || echo "  supervisor    MISSING CREATE"
[ -f "$BOS/frontend/index.html" ] && echo "  frontend      EXISTS  SKIP" || echo "  frontend      MISSING CREATE"
[ -f "$BOS/status.py" ]           && echo "  status.py     EXISTS  SKIP" || echo "  status.py     MISSING CREATE"

$SUPCTL status 2>/dev/null        && echo "  supervisord   UP      SKIP" || echo "  supervisord   DOWN    START"
curl -sf localhost:$PORT_API/health >/dev/null 2>&1 && echo "  API           UP      SKIP" || echo "  API           DOWN    START"
pgrep -x ollama >/dev/null        && echo "  ollama        UP      SKIP" || echo "  ollama        DOWN    START"

for M in "$LOCAL_LIGHT" "$LOCAL_STANDARD"; do
  ollama list 2>/dev/null | grep -q "${M%%:*}" \
    && echo "  $M    PULLED  SKIP" \
    || echo "  $M    MISSING PULL"
done

if [ -f "$BOS/business.db" ]; then
  sqlite3 $BOS/business.db "
    SELECT '  Tasks: ' ||
      SUM(CASE WHEN status='todo'        THEN 1 ELSE 0 END) || ' todo  ' ||
      SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) || ' running  ' ||
      SUM(CASE WHEN status='done'        THEN 1 ELSE 0 END) || ' done  ' ||
      SUM(CASE WHEN status='blocked'     THEN 1 ELSE 0 END) || ' blocked'
    FROM tasks;
    SELECT '  Setup complete: ' || COALESCE(value,'NO')
    FROM settings WHERE key='setup_complete';
  "
fi
echo ""
```

**Hard rules:**
- File exists and non-empty → skip, never overwrite
- Service UP → skip, never restart healthy
- Model pulled → skip, never re-pull
- `status=done` → never touch again
- `status=in_progress` → agent is working, do not reassign
- Only act on: missing files, down services, missing models, `todo` tasks, `blocked` tasks

---

## STEP 1 — ENV

```bash
BOS=$HOME/$PROJECT_SLUG-os
mkdir -p $BOS $BOS/logs $BOS/frontend $BOS/uploads $BOS/openwebui_tools
grep -q "BOS_HOME" ~/.zshrc || echo "export BOS_HOME=$BOS" >> ~/.zshrc
grep -q "OLLAMA_API_BASE" ~/.zshrc || echo "export OLLAMA_API_BASE=http://127.0.0.1:11434" >> ~/.zshrc
source ~/.zshrc
echo "ENV done: $BOS"
```

---

## STEP 2 — INSTALL

```bash
# Find working Python — Mac path breaks after updates
PYTHON=$(which python3.12 2>/dev/null || which python3.11 2>/dev/null || which python3.9 2>/dev/null || which python3)
echo "Python: $PYTHON ($($PYTHON --version))"
$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet \
  fastapi uvicorn "aider-chat" sqlite-utils apscheduler croniter \
  "python-jose[cryptography]" psutil sse-starlette httpx aiosqlite \
  pydantic anyio ruff supervisor \
  playwright pytest pytest-asyncio pytest-playwright websockets
$PYTHON -m playwright install chromium --with-deps
echo "Packages installed"
```

Ollama — standalone, NOT managed by supervisord (avoids port conflicts):

```bash
which ollama 2>/dev/null || curl -fsSL https://ollama.com/install.sh | sh

# CRITICAL for Mac: set env vars via launchctl if using Ollama.app
if [ -d "/Applications/Ollama.app" ]; then
  launchctl setenv OLLAMA_MAX_LOADED_MODELS 2
  launchctl setenv OLLAMA_NUM_PARALLEL 1
  launchctl setenv OLLAMA_FLASH_ATTENTION 1
  launchctl setenv OLLAMA_KV_CACHE_TYPE q8_0
  launchctl setenv OLLAMA_KEEP_ALIVE 30m
  echo "Ollama env set via launchctl"
else
  grep -q "OLLAMA_FLASH_ATTENTION" ~/.zshrc || cat >> ~/.zshrc << 'ZEOF'
export OLLAMA_MAX_LOADED_MODELS=2
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0
export OLLAMA_KEEP_ALIVE=30m
ZEOF
  source ~/.zshrc
fi

pgrep -x ollama >/dev/null && echo "ollama already running" || {
  ollama serve &>"$BOS/logs/ollama-boot.log" &
  sleep 5
}

curl -sf localhost:11434/api/tags | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'Ollama UP: {len(d[\"models\"])} models')" \
  || { echo "Ollama not responding — check $BOS/logs/ollama-boot.log"; exit 1; }
```

Pull models:

```bash
FREE=$(python3 -c "
import subprocess
out = subprocess.check_output(['vm_stat'], text=True)
free = sum(int(l.split(':')[1].strip().rstrip('.')) * 4096
           for l in out.split('\n')
           if 'Pages free' in l or 'Pages inactive' in l)
print(free // (1024*1024))
" 2>/dev/null || echo 8000)
echo "Free RAM: ${FREE}MB"
[ "$FREE" -lt 4000 ] && echo "WARNING: only ${FREE}MB free — close Chrome and other apps first"

for MODEL in "$LOCAL_LIGHT" "$LOCAL_STANDARD"; do
  ollama list | grep -q "${MODEL%%:*}" \
    && echo "SKIP (pulled): $MODEL" \
    || { echo "Pulling $MODEL..."; ollama pull "$MODEL" && echo "OK: $MODEL"; }
done
```

Smoke-test models — HARD STOP if either fails:

```bash
for MODEL in "$LOCAL_LIGHT" "$LOCAL_STANDARD"; do
  RESP=$(curl -sf -X POST localhost:11434/api/generate \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$MODEL\",\"prompt\":\"Reply with exactly: READY\",\"stream\":false,\"options\":{\"num_ctx\":2048}}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','FAIL'))" 2>&1)
  echo "  $MODEL => $RESP"
  echo "$RESP" | grep -qi "READY" || { echo "FATAL: $MODEL failed — aborting"; exit 1; }
done
echo "All models READY"
```

Aider model metadata — silences unknown model warnings, prevents browser opening:

```bash
cat > $BOS/.aider.model.metadata.json << 'METADATA'
{
  "ollama_chat/qwen2.5-coder:7b": {
    "max_tokens": 32768, "max_input_tokens": 32000, "max_output_tokens": 4096,
    "input_cost_per_token": 0.0, "output_cost_per_token": 0.0,
    "litellm_provider": "ollama_chat", "mode": "chat"
  },
  "ollama_chat/llama3.1:8b": {
    "max_tokens": 32768, "max_input_tokens": 32000, "max_output_tokens": 4096,
    "input_cost_per_token": 0.0, "output_cost_per_token": 0.0,
    "litellm_provider": "ollama_chat", "mode": "chat"
  }
}
METADATA
echo "Model metadata written"
```

---

## STEP 3 — DB (business.db, aiosqlite, WAL)

Every connection:

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;
PRAGMA foreign_keys=ON;
PRAGMA mmap_size=268435456;
PRAGMA temp_store=MEMORY;
PRAGMA wal_autocheckpoint=1000;
```

**tasks table** (no git columns):

```
id, project_id, sprint_id, parent_task_id, title, description,
task_type(code/write/research/design/ops/bug),
status(backlog/todo/in_progress/review/done/blocked),
priority(critical/high/medium/low),
assignee(human/local-agent/unassigned),
agent_model, story_points, estimated_hours, actual_hours, eta_date,
started_at, completed_at, due_date, updated_at, created_at,
retry_count, sort_order(real), is_recurring, recurrence_cron, template_id
```

Other tables: `projects`, `sprints`, `task_logs`, `activity_log`, `comments`,
`time_entries`, `task_templates`, `agent_metrics`, `api_usage`,
`notifications`, `settings`, `users`, `task_queue`

`init_db()` — creates tables only. No seed tasks.

`resolve_model(task)`:
- `code` / `bug` → `qwen2.5-coder:7b`
- `research` / `write` / `ops` / `design` → `llama3.1:8b`

`global_eta()` — total, done, remaining, blocked, hours_left, projected_completion, percent_complete, velocity_per_day

WAL checkpoint in api.py startup — runs every 30 min:

```python
async def wal_checkpoint_loop():
    while True:
        await asyncio.sleep(1800)
        async with get_db() as db:
            await db.execute("PRAGMA wal_checkpoint(PASSIVE)")

@app.on_event("startup")
async def startup():
    await init_db()
    asyncio.create_task(wal_checkpoint_loop())
    for _ in range(2):
        asyncio.create_task(agent_worker())
```

---

## STEP 4 — API (api.py, port 8000)

CORS all origins. Pydantic v2 (`RootModel`, not `__root__`).

POST /tasks — use `Request` body directly:

```python
@app.post("/tasks", status_code=201)
async def create_task(request: Request, background: BackgroundTasks):
    payload = await request.json()
    # handle single dict or list
```

Every write pipeline: SQLite update → activity_log → WebSocket broadcast including `global_eta_update` event → BackgroundTasks notification

Required endpoints:

```
GET   /health                  → {"status":"ok","db":"ok","ollama":"ok","agents":2}
CRUD  /projects /sprints /tasks /labels /users
GET   /agent/queue             → next todo local-agent task + resolved_model
PATCH /agent/heartbeat         → {task_id, model}
GET   /agent/status            → {status, model, current_task, tasks_done_today}
GET   /metrics/global-eta      → {done, remaining, blocked, hours_left,
                                   projected_completion, percent_complete,
                                   velocity_per_day}
GET   /tasks/logs/recent       → last 50 DESC
GET   /logs/stream             → SSE, never timeout
GET   /logs/file?name=X        → last 100 lines of $BOS/logs/{X}.log
GET   /settings
PATCH /settings
POST  /notifications/webhook
WS    /ws/{board_id}
POST  /admin/wal-checkpoint    → trigger WAL checkpoint
```

Start:
```bash
cd $BOS && uvicorn api:app --host 0.0.0.0 --port $PORT_API
```

---

## STEP 5 — AGENT LOOP (agent-loop.sh)

2 workers run under supervisord. **All local. No git. No commits. No branches.**

### V3 → V10: Autonomous Agent Runner (`agent_runner.py`)

`agent-loop.sh` delegates to `agent_runner.py`. Agents work like Claude with tool use:
investigate → plan → implement → verify → self-heal, iteratively.

**Flow** (iterative loop, up to 8 rounds per task):
1. **Triage** — keyword scan finds relevant files (FILE_HINTS), loads up to 6 context files
2. **Initial prompt** — directory listing + file contents sent to LLM
3. **Iterate** — LLM outputs directives → executed → results fed back → LLM continues
4. **Terminal** — loop ends on `DONE:` or `FAILED:`, or after 8 iterations
5. **Verify** — confirm written files exist and are non-empty
6. **Self-review** (V10) — post quality summary: file sizes, line counts, syntax status
7. **Report** — logs outcome, exits 0 (done) or 1 (blocked)

#### Complete directive set

| Directive | What agent does |
|---|---|
| `READ_FILE: /path` | Read any file mid-task, content fed back next iteration |
| `LIST_DIR: /path` | List directory contents |
| `SEARCH_CODE: pattern` | grep -rn across .py/.html/.sh/.md files |
| `WRITE_FILE: /path` | Write full file (V4: atomic write + auto-backup to .bak) |
| `APPEND_FILE: /path` | Append content to file |
| `PATCH_FILE: /path` | Targeted find/replace: <<<ORIGINAL…===…>>>REPLACEMENT |
| `RUN: cmd` | Execute shell command; stdout+stderr+exit code fed back |
| `MEMO: key = value` | Save note to /tmp/stacky_memo_{id}.json (V5: persists across retries) |
| `CONFIDENCE: N` | Rate confidence 1-10; if < 5, agent investigates more before writing |
| `ROLLBACK: /path` | Restore file from its .bak backup (V4) |
| `PLAN: text` | Agent announces its approach (informational) |
| `DONE: summary` | Task complete — runner exits 0 |
| `FAILED: reason` | Task blocked — runner exits 1 |

#### Version history

| Version | Key feature |
|---|---|
| V1 | Single LLM call, bare aider delegation |
| V2 | agent_runner.py: 6-step loop, FILE_HINTS, aider replacement |
| **V3** | **Multi-turn iterative loop (8 rounds), READ_FILE, LIST_DIR, SEARCH_CODE, PATCH_FILE, RUN output fed back** |
| **V4** | **Atomic writes (write→.tmp→rename), auto-backup (.bak), ROLLBACK directive** |
| **V5** | **Task scratchpad (MEMO), persists across retries in /tmp/stacky_memo_{id}.json** |
| **V6** | **Planning V2: creates project + sprint in addition to sub-tasks** |
| **V7** | **PARALLEL_READ: read multiple files in one step; prose-loop counter (3x no-directive → force DONE)** |
| **V8** | **Auto-test loop: after writing .py, discovers test_*.py and runs pytest** |
| **V9** | **SCAN_TODOS: grep TODO/FIXME/HACK/XXX + quality score per-KLOC** |
| **V10** | **Confidence gating (CONFIDENCE:), self-review summary after DONE** |
| **V13** | **self_improve.py: reads benchmark, auto-patches SYSTEM_PROMPT (speed/quality/completion/self-heal)** |
| **V14** | **SCAFFOLD: declare multi-file project structure upfront; normalize_path() fixes /stacky-os/ root errors** |
| **V15** | **Debug+fix task type: read traceback, patch both bugs, verify exit 0** |
| **V16** | **TDD RED-GREEN: write failing tests first, then implement until all pass** |
| **V17** | **Architecture-plan-then-implement: PLAN directive before WRITE_FILE** |
| **V18** | **CONSTRAINT_CHECK: verify explicit requirements before DONE; E2E pipeline (spec→code→test→quality)** |
| **V19** | **DEDUP_CHECK: scan file for duplicate function defs / repeated blocks** |
| **V20** | **RESILIENCE_NOTE: persist recovery plan to scratchpad so restarted agents resume correctly** |
| **V21** | **External evaluator: independent LLM pass scores output after DONE (not self-eval); logs score/pass** |
| **V22** | **Sprint contract: parse testable done-criteria from task description before work starts; SPRINT_CONTRACT directive** |
| **V23** | **Checkpoint/resume: save iteration state to /tmp/ckpt_{id}.json after each iter; reload on retry/restart** |
| **V24** | **Token usage tracker: log Ollama prompt_eval_count/eval_count per call to reports/token_usage.json; compute Claude API cost equivalent** |
| **V25** | **RUN path normalization: expand /stacky-os/ in shell commands (not just WRITE paths); regex only matches bare root paths** |
| **V26** | **Protected file guard: agents cannot overwrite agent_runner.py/supervisor-agent.py/api.py with <200-byte stubs; raises PermissionError with PATCH_FILE suggestion** |
| **V27** | **PYTHONPATH injection: when task writes .py to BOS but codebase_path differs, auto-injects PYTHONPATH=BOS into RUN commands so module imports resolve** |
| **V28** | **Complexity pre-screen: detect ULTRA-hard tasks (Myers diff, B-tree, NFA, SQL parser etc.) at task start and log escalation warning — prevents burning 3×12 iterations before Claude rescue** |
| **V29** | **Fast-fail escalation: ULTRA-detected tasks get max_attempts=1 (not 2); fail immediately after 1 try so supervisor escalates to Claude faster — saves 12 wasted iterations** |
| **V30** | **Iteration efficiency monitor: count productive iters (had tool results) vs total; log ratio at DONE — e.g. "8/12 productive (67% efficiency)"; stored in memo for trend analysis** |
| **V31** | **Context compression: when message history exceeds MAX_CTX×3 chars, compress middle messages into a summary block — fixes "context rot" where agents forget earlier work on long tasks** |
| **V32** | **Stagnation detector: track consecutive iterations with no new WRITE_FILE; after 2 such iterations inject a "[V32 STAGNATION ALERT]" forcing directive — breaks read-loop patterns where agent explores indefinitely without implementing** |
| **V33** | **Smart retry context: on retry, pass specific FAILED: reason + list of failed commands (with exit codes) + files already written to the retry prompt — instead of a generic "be minimal" message; targeted retry fixes exactly what broke** |
| **V34** | **Blind-write guard: if agent writes a file without doing any READ_FILE/SEARCH_CODE first and the file already has >200 bytes of content, log a warning and inject feedback — prevents stub overwrites of existing system files (root cause of V26 corruption incident)** |
| **V35** | **Directive frequency limiter: cap investigative tool calls per response (read_file≤3, search_code≤3, list_dir≤2); excess calls skipped with a nudge to start writing — prevents agents flooding one iteration with reads instead of implementing** |
| **V36** | **Run success cache: cache stdout/stderr/rc for read-only verification commands (py_compile, pytest, python3 -c); on cache hit skip re-executing and return cached result — prevents agents re-running the same syntax check 3+ times per task** |
| **V37** | **Response length budget: truncate LLM responses >10K chars before parsing — runaway responses from llama3.1:8b that repeat content or ramble past the directives are capped; reduces noise in feedback loop and speeds up iteration** |
| **V38** | **Minimum file size gate: after writing a .py file with <10 lines, inject "V38 STUB WARNING" feedback — catches incomplete implementations and stub-writes before the agent marks DONE on a hollow file** |
| **V39** | **Sprint contract auto-verify at DONE: when agent outputs DONE, check V22 contract criteria (file_exists + command_ok); if any fail, block DONE and inject failure list — forces agent to fix before marking complete** |
| **V40** | **Performance summary CSV log: after each task (success or fail) append one line to reports/perf_log.csv with: ts, task_id, title, status, iters, productive_pct, eval_score, model, duration_s — creates persistent trend data for analysis across sessions** |
| **V41** | **Adaptive iteration limit: at task start, read perf_log.csv to compute avg successful iteration count; set max_iterations = avg+2 (data-driven cap) instead of fixed 12 — tasks that typically finish in 4 iterations no longer burn 12** |
| **V42** | **Model-based timeout scaling: instead of fixed 240s LLM timeout, use 120s for 7b/8b models and 180s for larger models — reduces wait time when Ollama is under load and fails to respond within the old 4-minute window** |
| **V43** | **Model routing by task type: override caller's model at runtime based on task_type — code/bug→qwen2.5-coder:7b (better at code), write/research/ops/design→llama3.1:8b (better at prose/reasoning); picks best available fallback** |
| **V44** | **Shared agent memo: agents write codebase facts (db path, api framework, schema) to /tmp/agent_shared_memo.json; new tasks preload up to 10 facts from prior agent runs — reduces redundant READ_FILE calls across parallel tasks** |
| **V45** | **Error categorization: when RUN fails, classify the error (SyntaxError/ImportError/AssertionError/FileNotFoundError/TypeError/IndentationError) and inject a targeted [V45 HINT] fix suggestion — agent gets actionable fix advice instead of raw stderr** |
| **V46** | **File up-to-date check: before writing, compare new content with existing file (±5% length + same first/last 100 chars); if already up-to-date, skip write and inject "V46 SKIP" feedback — prevents redundant writes on task retries** |
| **V47** | **Early DONE nudge: after a successful RUN (exit 0) with files already written, inject "[V47: Command succeeded... output DONE now]" — prevents agents from continuing to explore after task is effectively complete** |
| **V48** | **Tool result deduplication: track fingerprints of prior tool results; if same result appears again in a later iteration, collapse to "[V48 DEDUP: same as prior]" — reduces feedback size on tasks where agent keeps re-reading the same file** |
| **V49** | **Task complexity classifier: compute complexity score (0-100) from description word count + WRITE_FILE count + RUN count; map to adaptive max_iters (4/7/12); combined with V41 perf data — simple tasks capped at 4 iters, hard ones get all 12** |
| **V50** | **System health check directive: HEALTH_CHECK: directive verifies API/DB/Ollama health in one call; returns structured status ("ALL SYSTEMS OK" or "ISSUES: api=F db=F ollama=F"); added to available tools in SYSTEM_PROMPT** |
| **V51** | **Confidence-gated escalation: if V21 eval_score <50 after task success, preserve scratchpad (don't clear) and log "V51 LOW-CONFIDENCE" — supervisor can detect this pattern and route follow-up to Claude for quality improvement** |
| **V52** | **Task dependency awareness: if description contains "depends_on: #N", check task N's status via API before starting; if N not done, immediately return failure ("depends_on #N not done") — prevents wasted iterations on blocked prerequisite work** |
| **V53** | **Write intent diffing: before writing, compute set diff vs existing file content; log "+N/-M lines vs prior" — gives agent and operator visibility into write scope without blocking the write** |
| **V54** | **Cross-session shared memo persistence: write_shared_memo() also saves to BOS/reports/shared_memo_persist.json; read_shared_memo() falls back to this file if /tmp is empty (e.g. after reboot) — shared codebase facts survive system restarts** |
| **V55** | **Hard benchmark suite: 3 non-ULTRA coding tasks (binary search tree, MinStack O(1), word frequency top-N) to test local agent capability after V32-V54 quality improvements — tasks #232-234 in queue** |
| **V56** | **Mid-task efficiency warning: at iteration≥max/2, if productive_iters/iteration<40%, inject "[V56 EFFICIENCY: N/M productive]" — gives agent a progress-aware intervention instead of waiting until stagnation threshold** |
| **V57** | **PATCH_FILE smoke test: after successful patch + syntax check on .py files with __main__ block, run python3 <file> as a quick smoke test; report pass/fail to agent — catches runtime errors after targeted edits** |
| **V58** | **WRITE_FILE auto smoke test: after writing a .py with __main__ block, automatically run it (15s timeout) and inject result as feedback — agent gets pass/fail without needing a separate RUN: directive** |
| **V59** | **Implicit verification: if agent writes files but issues no RUN directive, check if task description's RUN: lines reference those files; if so, auto-run them and inject result — catches "write but forget to verify" pattern** |
| **V60** | **Performance dashboard script (perf_dashboard.py): reads reports/perf_log.csv + token_usage.json; prints formatted table of task outcomes, avg iterations, productive%, eval scores, model breakdown, token savings** |
| **V61** | **Title keyword routing (V43 extension): analyze title for coding keywords (sort/tree/hash/stack/cache/implement) → qwen2.5-coder:7b; prose keywords (document/report/analyze/summarize) → llama3.1:8b; keyword match overrides task_type routing** |
| **V62** | **Consecutive failure detector: track consecutive failed RUN commands; after 3 consecutive failures, inject "[V62: approach is broken, try a completely different method]" — prevents agents from retrying the same broken approach in a loop** |
| **V63** | **Task title normalization: strip version/bench prefixes (V55-BENCH-A:, V60-BENCH:, task #123:) from title before keyword routing and complexity analysis — ensures real content keywords (sort, implement, algorithm) are detected even when buried under version prefixes** |
| **V64** | **Auto-complete simple tasks: when complexity_score < 30, single WRITE_FILE + single RUN, V58 smoke test passes, and no sprint contract — automatically trigger DONE without requiring agent to output it; eliminates wasted iterations on trivial single-file tasks** |
| **V65** | **Pre-run existence check: before executing a python3 file RUN, verify the target .py file exists; if not, block the RUN and inject "[V65: File not found — WRITE_FILE first]" — eliminates the run-before-write failure loop that caused ~30% of task failures** |
| **V66** | **Write-intent forcing: if task requires WRITE_FILE but agent completes 2+ iterations without writing anything, inject "[V66: Your NEXT response MUST start with WRITE_FILE:]" — forces action instead of continued exploration** |
| **V67** | **Force-FAILED on phantom done: when "3x no-directives" loop-break fires, check if task required WRITE_FILE but none were written; if so, outcome = FAILED instead of DONE — eliminates phantom "done" tasks with empty outputs and inflated eval scores** |
| **V68** | **Smart context preloading: skip generic type-default files (api.py, index.html) when task targets a standalone .py file unrelated to infrastructure — reduces context window noise and LLM confusion on pure algorithmic tasks** |
| **V69** | **Lenient WRITE_FILE parser: if agent writes WRITE_FILE:/path followed by code without backtick fences (or with blank line before fence), extract content anyway; strip any captured backtick fences from content — fixes most "no directives detected" failures** |
| **V70** | **Broadened DONE/FAILED parser: match "### DONE:", "**DONE:**", "  DONE:" variants (markdown-embedded terminals) — agents embed DONE in headers/bold causing missed task completion signals; also strips trailing markdown formatting after the colon** |
| **V71** | **Productive-iter tracking fix: when V64 auto-done fires (terminal=True before V30 counter), count iteration as productive if files were written or commands succeeded — fixes 0% productive reporting on fast single-iteration tasks** |
| **V72** | **File path markdown sanitization: strip leading/trailing asterisks, backticks, underscores from file paths in normalize_path() — prevents files being written as "bench_v71.py**" when agents use bold/code formatting around paths** |
| **V73** | **System prompt format enforcement: add explicit V73 critical rules block — (1) DONE must be plain line not markdown header, (2) must RUN file before DONE, (3) WRITE_FILE path must be clean absolute path without markdown** |
| **V74** | **Contract auto-run rescue: at DONE time, V39 now auto-runs command_ok criteria and injects result as feedback; if command fails, agent gets the error output directly; if it passes, command is recorded as done — eliminates stuck tasks where RUN was skipped** |
| **V75** | **Targeted smoke test error hints: when V58 smoke test fails, extract error line number from traceback and show 5-line code excerpt around the error — gives agent precise location to fix instead of just "fix with PATCH_FILE"** |
| **V76** | **AssertionError hints: when smoke test fails with AssertionError, inject "[V76: The assert statement failed — check algorithm logic]" with full error output — agents often need to know it's a logic error not a syntax error** |
| **V77** | **(skipped — rolled into V79)** |
| **V78** | **Iteration budget awareness: inject "[N iteration(s) remaining]" into every feedback message — agents become more decisive as budget runs out; "act decisively" hint fires when ≤ 2 iterations left** |
| **V79** | **PATCH_FILE alternative format support: if <<<ORIGINAL...>>>REPLACEMENT format not found, also try BEFORE:/AFTER: format that agents sometimes use — reduces PATCH FAILED errors from format mismatch** |
| **V80** | **Assertion value debugging: when AssertionError fires in smoke test, extract the failing assertion line and execute just the function call to show what was actually returned vs expected — "coin_change() returned 6, not 4"** |
| **V81** | **Missing __main__ block warning: after writing .py when task requires RUN, check if __main__ block exists; if not, inject "[V81: add __main__ block with assertions before DONE]" — prevents files that can't be smoke-tested** |
| **V82** | **V46 skip-write override on broken files: before skipping WRITE_FILE via V46 (content-unchanged guard), run compile() on the existing .py; if SyntaxError, allow overwrite instead of silently skipping — prevents V46 blocking fixes to broken files** |
| **V83** | **Code skeleton injection on repeat V66 fires: when V66 (write-intent forcing) fires on iteration ≥ 3, extract the WRITE_FILE path + function names from description and inject a concrete WRITE_FILE skeleton — agent can no longer deflect with "I can't find the function"** |
| **V84** | **Stub-run DONE blocker: V38 now records stub-warned files in a set; at V74 contract auto-run, if a stub-warned .py exits 0 with no stdout, block DONE and inject "rewrite fully" — prevents empty files from passing contract just because `python3 empty.py` exits 0** |
| **V85** | **V65 escalation skeleton: V65 pre-run block now counts per-file; on 2nd+ block of same file, immediately inject a WRITE_FILE skeleton into tool results (don't wait for V66's end-of-iteration check) — agent sees the skeleton with budget remaining to act** |
| **V86** | **Fix V83/V85 skeleton format: removed raw backtick fences from skeleton hints (agent was writing ` ```python ` as first line of output file); skeleton now says "write a triple-backtick block" in prose without embedding actual fences** |
| **V87** | **Pre-write fence sanitization: before atomic write of .py files, if content starts with ` ``` `, strip opening and closing fence markers and log V87 FENCE STRIP — fixes double-fence corruption where agent writes ` ```python\n```python\n ` and parser captures the second fence as file content** |
| **V88** | **Prose-path guard: reject WRITE_FILE paths whose basename contains spaces, apostrophes, or no file extension — agent sometimes writes `WRITE_FILE: Let's write the function...` as path; V88 blocks write + injects corrective hint with the expected absolute path format** |
| **V89** | **Extended fence strip: V87 only stripped start/end fences; V89 strips ALL fence-only lines anywhere in .py content using `re.sub(r'^\s*```[^\n]*\n?', '', content, MULTILINE)` — fixes closing ` ``` ` left mid-file when agent includes trailing prose after the code block** |
| **V90** | **Empty-result FAILED guard: fallback `elif files_written or commands_run: success = True` now checks that at least one written file is non-empty AND/OR at least one command succeeded; empty-file-only writes → FAILED not success. Also V90b: V46 skip-override extends to empty existing files (previously V82 only checked SyntaxError, not empty)** |
| **V91** | **Abort-write-on-empty: if V89 fence-strip leaves empty content, skip the write entirely and inject "[V91 WRITE ABORTED: only fences found — write real Python code]" — prevents 0-byte files from being created that then cycle through V84/V90 guards** |
| **V92** | **Compile-truncate prose stripper: after fence-strip, if content has SyntaxError at line N>5, try truncating everything from line N onward and re-compiling; if truncated version is clean, write it and inject "[V92: removed markdown prose starting at line N]" — fixes agent appending `#### Step 3:`, `- The script should...` prose after code** |
| **V93** | **System prompt WRITE_FILE content rules: added V93 CRITICAL section prohibiting markdown/prose inside WRITE_FILE blocks, ``` fence markers in content, and prose-as-path patterns — makes the "no fences in content" rules explicit to the LLM before it even generates a response** |
| **V94** | **Premature FAILED blocker: if agent issues FAILED: before iteration 3 AND task required files but none written, block FAILED and inject "V94 PREMATURE FAILED BLOCKED: write the file first" with the target path — prevents agents giving up after 1 iteration of pure planning** |
| **V95** | **Initial action hint: for code tasks with WRITE_FILE targets, prepend "ACTION: Write X immediately — do NOT explore first" to the initial prompt — reduces exploration-only iterations where agent reads files and plans without writing anything** |
| **V96** | **Force-stub on V83 ignore: if V83 skeleton was injected but agent STILL didn't write in the following iteration (iteration > V83_fire + 1), runner directly writes a `def fn(*args): pass` skeleton to the target path — agent then has a real file to fix instead of a blank slate** |
| **V97** | **Write-resistance retry escalation: V33 retry context now detects write-resistance failures (0 files written despite requirements); on retry, injects "CRITICAL: write ZERO files — THIS RETRY MUST START WITH WRITE_FILE: path" instead of generic "fix what failed" — makes the retry directive far more forceful** |
| **V98** | **Auto-inject print statement: if agent writes .py with `__main__` block but no `print()` call, runner appends `print("filename: all assertions PASS")` — ensures stdout output for V84 stub detection, improves V21 eval scores, and confirms successful assertion runs** |
| **V99** | **Context reset on severe stagnation: if stagnant_iters ≥ 5 and 0 files written, clear all conversation history to just system prompt + a fresh "V99 CONTEXT RESET: write X NOW" message — stale plan chains in conversation history confuse the model and a clean slate produces better first responses** |
| **V100** | **Last-resort 1-shot code generation fallback: after all attempts in run_with_retry() exhaust with 0 files written, make a single bare LLM call "Write ONLY Python code (no explanation) for: <task>" with no system prompt overhead; strip fences, compile-check, write and smoke-test; if smoke test passes → success, else FAILED — final safety net before giving up** |
| **V101** | **Meaningful-file guard for V90: V90's "non-empty file" check raised from `> 0 bytes` to "≥ 50 bytes AND contains at least one `def ` or `class ` statement" for .py files — single-newline stubs (1 byte) were passing `> 0` and triggering false success despite containing no code** |
| **V102** | **V96 force-stub bug fix: V83 skeleton injection updated `_v83_fired_iter` every iteration so V96's guard `iteration > _v83_fired_iter + 1` was always False (checking `n > n+1`) — fix: track `_v83_first_fired` (immutable after first fire) and check that instead; V96 now correctly forces a stub after V83 has been ignored for 2+ consecutive iterations** |
| **V103** | **Iter-1 DONE blocker for code tasks: before V39 contract check at DONE time, if iteration==1 AND task_type==code AND 0 files written, inject "V103 ITER-1 DONE BLOCKED: write the file now" with the exact WRITE_FILE path — eliminates the most common wasted first iteration where agent plans + issues DONE immediately** |
| **V104** | **Contract file_exists meaningful-check: V39's file_exists criterion upgraded from `size > 0` to the V101 meaningful-file check (≥50B + def/class for .py) — 1-byte stub files no longer pass the contract check; error message now includes actual file size to help agent diagnose "written but empty" vs "never written"** |
| **V105** | **Repeated DONE-without-write skeleton escalation: track `_done_blocked_count` (resets on any successful write); when ≥2 consecutive DONE blocks occur with 0 files written, force-write a `def fn(*args): pass` skeleton to the target path and inject "PATCH this stub now" — catches agents that re-issue DONE on iter-2 after V103 blocks iter-1** |
| **V106** | **Wrong-path write detection: after every WRITE_FILE success, compare written path against all WRITE_FILE: targets from task description; if path doesn't match any required target, inject "[V106 WRONG PATH: you wrote X but task requires Y — write to Y]" — prevents agents from writing `trap_water.py` when task needs `bench_v105.py`** |
| **V107** | **Lead-with-action initial prompt restructure: V95's action hint was appended AFTER the description so agent entered planning mode before seeing it; V107 moves a "CRITICAL: Your FIRST line MUST be WRITE_FILE: path" block to the very top of the initial_prompt — forces action-first before model reads the description** |
| **V108** | **V21 evaluator file-content injection: previously evaluator only saw "FILE: X — EXISTS (739B)" with no code; V108 passes up to 60 lines of each written .py file as a code block — allows evaluator to assess algorithmic correctness, assertion coverage, and code quality instead of just file existence** |
| **V109** | **V21 evaluator rubric upgrade: expanded description context from 400 to 800 chars, added explicit scoring rubric (100=all tests pass+clean, 90=minor issues, 80=missing edge cases, <70=wrong/broken), added directive "does code match test cases in requirements?" — produces more accurate and consistent quality scores** |
| **V110** | **Eval improvement pass: when V21 scores 80-89 (passing but imperfect), make a single bare LLM improvement call "fix these issues: {v21_issues}" with current code context; compile-check, smoke-test the improvement, and replace the file only if the improved version also runs and produces stdout — upgrades 85→90+ without risking regression** |
| **V111** | **Better V105 skeleton: V105 forced stub used `def fn(*args): pass` — V111 extracts proper function signature with type hints from "implement fn_name(arg: type) -> type" in description, and pre-populates `__main__` block with up to 3 example assertions from description — agent now has a richer skeleton to patch** |
| **V112** | **V110 temp-file bug fix: V110 was calling `run_cmd(path + '.tmp.py')` BEFORE writing to that temp path — always resulted in FileNotFoundError; fix: write temp file FIRST then run it; this was silently preventing any V110 improvement pass from ever working** |
| **V113** | **Skip directory listing for standalone new-file tasks: for code tasks with WRITE_FILE target, no relevant context files, and target doesn't yet exist, skip `ls -la {codebase_path}` — agent saw 50+ unrelated project files creating noise; replaced with "(No existing files relevant)" to keep prompt focused on the implementation** |
| **V114** | **V106 auto-copy wrong-path writes: V106 warned about wrong filename but agent had to rewrite; V114 auto-copies the content to the required path if file is valid (≥50B + def/class) and required path doesn't exist yet — task succeeds even when agent writes to `trap_water.py` instead of `bench_v105.py`** |
| **V115** | **Fast-path V21 evaluator: for clearly successful code tasks (file is ≥50B + def/class + runs with "PASS" in stdout), skip the 5-15s Ollama LLM evaluator call and return 95/100 directly — saves significant latency for the happy path; falls through to LLM eval only for ambiguous cases** |

#### Planning mode V2 (V6 upgrade)

For `task_type=design` or `estimated_hours > 3`:
```
PROJECT_NAME: <new project name>    ← agent creates a real project
SPRINT_NAME: <sprint goal>          ← agent creates a sprint
SUB_TASK: <title> | <type> | <desc> ← repeated 2-6 times
PLAN_DONE
```
- Creates new project via POST /projects
- Creates sprint via POST /sprints
- POSTs sub-tasks with `parent_task_id`, `project_id`, `sprint_id`

#### Self-heal flow (inline, no separate retry)

```
LLM writes .py → compile() checks syntax
  ✓ OK  → SYNTAX CHECK: OK fed back to LLM
  ✗ ERR → error + line excerpt fed back → LLM patches in same iteration
ROLLBACK: /path available if fix is worse than original
```

#### V8 auto-test

After writing `foo.py`, runner checks for `test_foo.py` / `foo_test.py`:
- If found: `python3 -m pytest test_foo.py -v --tb=short`
- Pass/fail output fed back to LLM as next tool result
- LLM can fix code and re-run in the same iteration loop

**FILE_HINTS keyword table** (agent_runner.py `FILE_HINTS` dict):

| Keyword | Files loaded |
|---|---|
| api, endpoint, route, task | api.py |
| database, migration, model, table | db.py |
| schema | db.py |
| frontend, board, chat, ui | frontend/index.html |
| agent, autonomous | agent-loop.sh, agent_runner.py, supervisor-agent.py |
| runner | agent_runner.py |
| supervisor, config, daemon, process | supervisord.conf, supervisor-agent.py |
| gate, approve, review | supervisor-agent.py |
| loop | agent-loop.sh |
| heartbeat, queue, worker | agent-loop.sh, api.py |
| test, e2e, playwright | e2e_test.py |
| setup, docs, readme | local-agents-setup.md |
| export, csv | api.py |
| sprint, project, metrics | api.py, db.py |

**agent-loop.sh** (v2 — uses agent_runner.py):
```bash
#!/bin/bash
# $BOS/agent-loop.sh — LOCAL ONLY. No git. No commits. No branches. No browser.
set -euo pipefail
source ~/.zshrc 2>/dev/null || true

export BOS_HOME="${BOS_HOME:-$HOME/stacky-os}"
export OLLAMA_API_BASE="http://127.0.0.1:11434"
PORT_API="${PORT_API:-8000}"
WORKER_ID="${WORKER_ID:-1}"

while true; do
  # Gate check, fetch task, mark in_progress, send heartbeat (see full file)
  # ...

  # Write task JSON for agent_runner.py
  TASK_FILE=$(mktemp /tmp/stacky_task_XXXXXX.json)
  echo "$TASK" | python3 -c "
import sys, json
t = json.load(sys.stdin)
t['resolved_model'] = '$MODEL'
t['codebase_path']  = '$WORK_DIR'
print(json.dumps(t))" > "$TASK_FILE"

  # Execute with autonomous agent_runner.py (self-heals internally)
  python3 "$BOS_HOME/agent_runner.py" "$TASK_FILE" 2>&1 \
    | tee -a "$BOS_HOME/logs/agent.log" \
    | while IFS= read -r LINE; do
        # stream each line to task logs API
        ...
      done
  EXIT_CODE=${PIPESTATUS[0]}
  rm -f "$TASK_FILE"

  # mark review (success) or blocked (failure), send idle heartbeat
done
```

**Heartbeat** — agent-loop.sh sends `PATCH /agent/heartbeat` three times per task:
1. On task start → worker shows active on dashboard
2. Every 30s background loop → keeps worker visible during long LLM calls
3. On completion → sends `model:idle` to clear active state

Worker state persisted to `settings` table — survives API restarts.

---

## STEP 6 — SUPERVISOR AGENT (supervisor-agent.py)

Fully autonomous — fixes ALL issues automatically. No manual intervention.
Runs every 15 seconds.

| What it detects | What it does |
|---|---|
| Ollama down / model not responding | Restarts ollama, retries up to 20x |
| API down | Restarts via supervisord |
| Blocked task: `ModuleNotFoundError` | `pip install {pkg}` then re-queues |
| Blocked task: `SyntaxError` | Runs targeted aider fix on that file |
| Blocked task: test failure | Runs targeted aider fix with exact traceback |
| Blocked task: linter error | Runs `ruff --fix` automatically |
| Blocked task: timeout | Kills stuck aider process, re-queues |
| Blocked task: OOM | Pauses agent-2 for 30s to free RAM |
| Blocked task: unknown (< 3 retries) | Re-queues, resets retry_count |
| Blocked task: unknown (3+ retries) | Mac notification, escalates to Claude |
| Stale `in_progress` (no heartbeat 2h+) | Resets to `todo` |
| Duplicate tasks | Removes duplicate, keeps oldest |
| Log file > 50MB | Rotates, keeps 3 backups |
| Cloud cost > $8/day | Pauses cloud tasks |
| Infinite aider loop (> 3 min) | Kills process, marks blocked |
| WAL checkpoint needed | Runs every 30 min |
| RAM < 2GB free | Pauses agents 30s |

Start: managed by supervisord (see Step 7). Logs at `$BOS/logs/supervisor.log`.

---

## STEP 7 — SUPERVISORD (supervisord.conf)

Supervisor installed via pip. Binary at `~/Library/Python/3.9/bin/supervisord`.
**Ollama is NOT in supervisord** — runs standalone to avoid port 11434 conflicts.

```ini
; $BOS/supervisord.conf
[unix_http_server]
file=%(ENV_BOS_HOME)s/logs/supervisor.sock

[supervisord]
logfile=%(ENV_BOS_HOME)s/logs/supervisord.log
logfile_maxbytes=20MB
logfile_backups=3
pidfile=%(ENV_BOS_HOME)s/logs/supervisord.pid
nodaemon=false

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix://%(ENV_BOS_HOME)s/logs/supervisor.sock

[group:core]
programs=%(ENV_PROJECT_SLUG)s-api

[group:agents]
programs=%(ENV_PROJECT_SLUG)s-supervisor,%(ENV_PROJECT_SLUG)s-agent-1,%(ENV_PROJECT_SLUG)s-agent-2

[group:ui]
programs=%(ENV_PROJECT_SLUG)s-frontend

[program:%(ENV_PROJECT_SLUG)s-api]
command=%(ENV_PYTHON)s -m uvicorn api:app --host 0.0.0.0 --port %(ENV_PORT_API)s --loop asyncio
directory=%(ENV_BOS_HOME)s
environment=BOS_HOME="%(ENV_BOS_HOME)s",PROJECT_SLUG="%(ENV_PROJECT_SLUG)s",OLLAMA_API_BASE="http://127.0.0.1:11434"
autorestart=true
startretries=10
startsecs=3
redirect_stderr=true
stdout_logfile=%(ENV_BOS_HOME)s/logs/api.log
stdout_logfile_maxbytes=50MB
stdout_logfile_backups=3

[program:%(ENV_PROJECT_SLUG)s-supervisor]
command=%(ENV_PYTHON)s %(ENV_BOS_HOME)s/supervisor-agent.py
directory=%(ENV_BOS_HOME)s
environment=BOS_HOME="%(ENV_BOS_HOME)s",PROJECT_SLUG="%(ENV_PROJECT_SLUG)s",PROJECT_NAME="%(ENV_PROJECT_NAME)s",PORT_API="%(ENV_PORT_API)s",LOCAL_LIGHT="%(ENV_LOCAL_LIGHT)s",LOCAL_STANDARD="%(ENV_LOCAL_STANDARD)s",CODEBASE_PATH="%(ENV_CODEBASE_PATH)s"
autorestart=true
startretries=5
redirect_stderr=true
stdout_logfile=%(ENV_BOS_HOME)s/logs/supervisor.log
stdout_logfile_maxbytes=20MB
stdout_logfile_backups=3

[program:%(ENV_PROJECT_SLUG)s-agent-1]
command=/bin/bash %(ENV_BOS_HOME)s/agent-loop.sh
directory=%(ENV_BOS_HOME)s
environment=BOS_HOME="%(ENV_BOS_HOME)s",WORKER_ID=1,PORT_API="%(ENV_PORT_API)s",PROJECT_SLUG="%(ENV_PROJECT_SLUG)s",PROJECT_NAME="%(ENV_PROJECT_NAME)s",CODEBASE_PATH="%(ENV_CODEBASE_PATH)s",LOCAL_LIGHT="%(ENV_LOCAL_LIGHT)s",LOCAL_STANDARD="%(ENV_LOCAL_STANDARD)s",OLLAMA_API_BASE="http://127.0.0.1:11434"
autorestart=unexpected
startretries=3
redirect_stderr=true
stdout_logfile=%(ENV_BOS_HOME)s/logs/agent.log
stdout_logfile_maxbytes=100MB
stdout_logfile_backups=5

[program:%(ENV_PROJECT_SLUG)s-agent-2]
command=/bin/bash %(ENV_BOS_HOME)s/agent-loop.sh
directory=%(ENV_BOS_HOME)s
environment=BOS_HOME="%(ENV_BOS_HOME)s",WORKER_ID=2,PORT_API="%(ENV_PORT_API)s",PROJECT_SLUG="%(ENV_PROJECT_SLUG)s",PROJECT_NAME="%(ENV_PROJECT_NAME)s",CODEBASE_PATH="%(ENV_CODEBASE_PATH)s",LOCAL_LIGHT="%(ENV_LOCAL_LIGHT)s",LOCAL_STANDARD="%(ENV_LOCAL_STANDARD)s",OLLAMA_API_BASE="http://127.0.0.1:11434"
autorestart=unexpected
startretries=3
redirect_stderr=true
stdout_logfile=%(ENV_BOS_HOME)s/logs/agent.log
stdout_logfile_maxbytes=100MB
stdout_logfile_backups=5

[program:%(ENV_PROJECT_SLUG)s-frontend]
command=python3 -m http.server %(ENV_PORT_FRONTEND)s --directory %(ENV_BOS_HOME)s/frontend
autorestart=true
redirect_stderr=true
stdout_logfile=%(ENV_BOS_HOME)s/logs/frontend.log
```

Write config and start:

```bash
PYTHON=$(which python3.12 2>/dev/null || which python3.11 2>/dev/null || which python3.9 2>/dev/null || which python3)

# Substitute all env vars into supervisord.conf
sed -e "s|%(ENV_BOS_HOME)s|$BOS|g" \
    -e "s|%(ENV_PROJECT_SLUG)s|$PROJECT_SLUG|g" \
    -e "s|%(ENV_PROJECT_NAME)s|$PROJECT_NAME|g" \
    -e "s|%(ENV_PORT_API)s|$PORT_API|g" \
    -e "s|%(ENV_PORT_FRONTEND)s|$PORT_FRONTEND|g" \
    -e "s|%(ENV_CODEBASE_PATH)s|$CODEBASE_PATH|g" \
    -e "s|%(ENV_LOCAL_LIGHT)s|$LOCAL_LIGHT|g" \
    -e "s|%(ENV_LOCAL_STANDARD)s|$LOCAL_STANDARD|g" \
    -e "s|%(ENV_PYTHON)s|$PYTHON|g" \
    $BOS/supervisord.conf.template > $BOS/supervisord.conf

# Startup order — enforced:
# 1. Ollama (standalone)
pgrep -x ollama >/dev/null || { ollama serve &>"$BOS/logs/ollama.log" & sleep 6; }

# 2. Supervisord (manages API + agents + frontend)
$HOME/Library/Python/3.9/bin/supervisord -c $BOS/supervisord.conf

# 3. Wait for gate clearance
echo "Waiting for supervisor gate..."
for i in $(seq 1 30); do
  PASSED=$(python3 -c "
import json
try:
  d=json.load(open('$BOS/logs/gate.json'))
  print(d.get('passed',False))
except: print(False)
" 2>/dev/null)
  [ "$PASSED" = "True" ] && echo "GATE CLEARED" && break
  echo "  waiting... ($i/30)"; sleep 3
done
```

Control:

```bash
SUPCTL="$HOME/Library/Python/3.9/bin/supervisorctl -c $BOS/supervisord.conf"
$SUPCTL status
$SUPCTL restart agents:
$SUPCTL restart core:
$SUPCTL tail -f $PROJECT_SLUG-supervisor stdout
```

---

## STEP 8 — VERIFY

```bash
SUPCTL="$HOME/Library/Python/3.9/bin/supervisorctl -c $BOS/supervisord.conf"
$SUPCTL status

# Models
for M in "$LOCAL_LIGHT" "$LOCAL_STANDARD"; do
  R=$(curl -sf -X POST localhost:11434/api/generate \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$M\",\"prompt\":\"Reply: READY\",\"stream\":false,\"options\":{\"num_ctx\":2048}}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('response','FAIL'))")
  echo "  $M => $R"
done

# API
curl localhost:$PORT_API/health
# Expected: {"status":"ok","db":"ok","ollama":"ok","agents":2}

# Gate status
python3 -c "
import json
d=json.load(open('$BOS/logs/gate.json'))
print('Gate:', 'PASS' if d['passed'] else 'FAIL')
for k,v in d.get('results',{}).items(): print(f'  {k}: {v[\"passed\"]} — {v[\"msg\"]}')
"

# Board
open http://localhost:$PORT_FRONTEND

# Mark complete
curl -sX PATCH localhost:$PORT_API/settings \
  -H "Content-Type: application/json" \
  -d '{"setup_complete":"true"}'
echo "Setup complete."
```

---

## STEP 8B — FRONTEND SPEC (frontend/index.html)

Single file. React 18 + SortableJS + ninja-keys + Chart.js + diff2html — all CDN. No build step.
All API calls: `localhost:$PORT_API`. WebSocket: `ws://localhost:$PORT_API/ws/board`.

---

### DESIGN SYSTEM

```
bg=#0a0a0a  surface=#111  border=#222  text=#f0f0f0  muted=#555
Font: JetBrains Mono (Google Fonts CDN)

Status colors:
  backlog=#333  todo=#444  in_progress=#1d6ef5  review=#7c3aed  done=#16a34a  blocked=#dc2626

Priority colors:
  critical=#dc2626  high=#ea580c  medium=#2563eb  low=#555

Task type colors:
  code=#6d28d9  write=#0891b2  research=#0d9488  design=#db2777  ops=#92400e  bug=#dc2626

Agent/source colors:
  agent=#1d6ef5  system=#d97706  human=#6b7280  error=#dc2626

Assignee avatars: colored circle with initials, color derived from name hash
```

---

### CORE BEHAVIOR: STATUS TRANSITIONS TRIGGER REAL ACTIONS

This is the most critical feature. Every card drag or status change fires a real side effect:

```
TODO → IN PROGRESS:
  - PATCH /tasks/{id}/status in_progress
  - POST /tasks/{id}/time/start
  - event_queue.put(task) → agent worker picks it up immediately
  - WebSocket broadcast: {type:"agent_assigned", task_id, model, worker}
  - Card shows: spinning green dot + "Agent picking up..." for 3s
  - Card then shows: model name + elapsed timer + "Working..."
  - Sidebar agent status updates live: model + task title

IN PROGRESS → TODO (drag back):
  - PATCH /tasks/{id}/status todo
  - POST /tasks/{id}/time/stop (records partial time)
  - POST kill signal: POST /agent/stop/{task_id} → kills aider process for that task
  - POST /tasks/{id}/logs "Stopped by user — drag back to TODO"
  - WebSocket broadcast: {type:"agent_stopped", task_id}
  - Card shows: orange pulse "Stopping agent..." → then returns to normal TODO card
  - Sidebar agent slot clears

IN PROGRESS → BLOCKED (drag to blocked column):
  - PATCH status=blocked + increment retry_count
  - Triggers supervisor-agent.py fix cycle immediately (POST /supervisor/fix/{task_id})
  - Card shows: red ⚠ + last error message truncated 80 chars
  - Sidebar blocked count badge increments with red pulse

IN PROGRESS → REVIEW:
  - PATCH status=review
  - POST /tasks/{id}/time/stop
  - Notification toast: "{title} ready for review"
  - Card moves to REVIEW column with purple border flash animation

REVIEW → DONE (approve):
  - PATCH status=done, set completed_at
  - Confetti burst animation on card
  - ETA accuracy recalculated: show "X% accurate" toast
  - Velocity metric updates live
  - Card fades out over 800ms then slides out of column

REVIEW → IN PROGRESS (reject — send back):
  - PATCH status=in_progress
  - POST /tasks/{id}/logs "Rejected from review — rework needed"
  - Requires rejection reason input (modal): reason saved to task_logs

TODO → BACKLOG (de-prioritize):
  - PATCH status=backlog + clear sprint_id
  - Confirm modal: "Remove from sprint?" with sprint name shown

BACKLOG → TODO (prioritize):
  - PATCH status=todo + assign to current active sprint
  - event_queue.put if assignee=local-agent
```

---

### SIDEBAR (240px fixed left)

```
Header: PROJECT NAME in project color + version tag

PROJECT LIST:
  Each project row:
  - Color dot (clickable to change color)
  - Project name (click = switch active project)
  - WIP badge: current in_progress count / wip_limit (red if over)
  - Progress bar: % done tasks, colored by project color, 4px height
  - "X% · ETA [date]" below bar — orange if not on track, green if on track
  - Sprint name + days remaining (red if < 2 days)
  - Agent model pills: shows which models are active on this project
  - Expand arrow: shows task breakdown (code/write/research counts)

BUSINESS GOALS PANEL (collapsible, below projects):
  - List of goals from GOALS.md (loaded via GET /settings?key=goals)
  - Each goal: title + % of linked tasks done + color bar
  - Click goal → filters board to show only tasks linked to that goal
  - "Add Goal" button → inline input

AGENT STATUS PANEL:
  Worker 1:
    - Green pulse if active, grey if idle
    - Model name + version
    - Current task title (30 chars) + task type badge
    - Elapsed timer (live, updates every second)
    - Codebase path (truncated, clickable → opens in Finder)
    - Files being edited (from aider output parsing)
  Worker 2: same layout

  "View All Agent Activity" link → opens LOGS tab filtered to agent source

WHO IS DOING WHAT (presence panel):
  - Avatars of human users with their current task (from WS heartbeats)
  - Agent workers shown as robot avatars with task
  - Click avatar → filters board to show that person's tasks
  - Hover avatar → tooltip: name + task title + time on task

SERVICE HEALTH:
  - Dot per service: ollama / api / agent-1 / agent-2 / frontend
  - Green=up, red=down, yellow=starting
  - Click any red dot → shows last 10 log lines in mini popover
  - Refreshes every 10s via GET /supervisor/status

API COST TODAY:
  - "$X.XX today / $X.XX this month"
  - Click → breakdown by model

LIVE CLOCK: top right of sidebar, updates every second
```

---

### TOPBAR

```
Left:
  - Active project name (click → rename inline)
  - Codebase path chip (click → opens in Finder via window.open)
  - Sprint selector dropdown: shows all sprints, active one selected
    - Sprint dates + days left + goal summary
    - "New Sprint" option at bottom

Center tabs:
  BOARD · BACKLOG · SPRINTS · METRICS · GOALS · LOGS · CHAT
  Each tab shows count badge (tasks, blocked alerts, unread logs)

Right:
  - ETA line: "ETA [date] · X% done" — green/orange/red based on track
  - Model pills: active models shown as colored chips
  - Search: real-time filters all visible fields across all tasks
  - Filter dropdown: All / Human / Agent / Blocked / By Type / By Label / By Goal
  - Swimlane toggle: None / Assignee / Priority / Label / Goal
  - View toggle: Kanban / List / Timeline / Calendar (icon buttons)
  - Notification bell with unread badge (red pulse if agent blocked)
  - User avatar + name
```

---

### BOARD TAB (Kanban)

```
COLUMNS: BACKLOG · TODO · IN PROGRESS · REVIEW · DONE · BLOCKED

Column header:
  - Status name + count badge
  - WIP limit warning: turns red + shows "X/Y" if over limit
  - Collapse arrow: collapses column to thin strip showing count only
  - "+ Add Task" quick-add: inline input, press Enter to create with defaults

TASK CARD:
  - Left 3px border = task_type color
  - Top row: task type badge + priority badge (colored dot) + story points bubble
  - Title: 60 chars, bold
  - Assignee row: avatar (agent robot icon or human initials) + model chip
  - Middle row: ETA date colored (green=future/orange=<24h/red=overdue/grey=none)
  - If IN PROGRESS:
    - Live elapsed timer (ticking every second)
    - Animated progress bar (estimated vs elapsed %)
    - "Agent: {model} · {files_edited} files" live from log stream
    - Spinning green dot on avatar
  - If BLOCKED:
    - Red ⚠ icon + truncated last error (80 chars) + "Fix in progress..." if supervisor working
  - Labels: colored dots (up to 5, then "+X more")
  - Parent breadcrumb if subtask: "Epic > Story"
  - Git branch chip if set (no git in local setup — hidden if empty)
  - Card age opacity: 7d=0.85 / 14d=0.65 / 28d=0.45
  - Bottom: time logged + comment count icon + subtask progress "X/Y"
  - Goal link chip: shows which business goal this task contributes to

CARD INTERACTIONS:
  - Click = open detail panel
  - Drag = move between columns (SortableJS), fractional sort_order
  - Shift+click = multi-select (shows floating bulk action bar)
  - Right-click = context menu (8 options):
      Change Status / Change Priority / Assign / Add Label /
      Link to Goal / Create Subtask / Copy Link / Archive
  - Hover = shows full title + description tooltip if truncated
  - Double-click title = inline edit title without opening panel

SWIMLANES:
  When enabled: horizontal bands group cards
  Each swimlane shows sub-counts per column + sub-WIP limit
  Assignee swimlane: shows avatar header + "X tasks"
  Goal swimlane: shows goal title + % complete bar

BULK ACTION BAR (appears on multi-select):
  Floating bar at bottom: "X selected"
  Buttons: Change Status / Change Priority / Assign / Add Label / Move Sprint / Delete
  Each fires PATCH on all selected IDs in parallel
```

---

### TASK DETAIL PANEL (320px right slide-in, URL hash #task-{id})

```
HEADER:
  - Breadcrumb: Project > Epic > Story > Task (all clickable)
  - Task ID chip: #123
  - Status badge (clickable dropdown to change status — fires transition side effects)
  - Priority badge (clickable)
  - Close X (also Esc)

FIELDS (all inline editable — click to edit, Tab to next field):
  - Title (large, click to edit)
  - Description (textarea, Markdown rendered)
  - Task type dropdown
  - Assignee dropdown (human / local-agent / unassigned)
  - Agent model dropdown (auto / qwen2.5-coder / llama3.1)
  - Story points (1/2/3/5/8 pill selector)
  - Estimated hours (number input, recalculates ETA on change)
  - Due date picker
  - Sprint selector
  - Business goal link (dropdown, links task to a goal)
  - Labels (multi-tag input)

ETA PANEL:
  - Large: "ETA: [date]" colored green/orange/red
  - "Estimated: Xh · Elapsed: Yh · Remaining: Zh"
  - OLS prediction: "(Model predicts ~Xh actual for {task_type} on {model})"
  - Recalculates live when estimated_hours changes

AGENT LIVE VIEW (visible when in_progress):
  - Current file being edited (from log stream parsing)
  - Last 5 aider output lines (scrolling, real-time via SSE)
  - Elapsed timer + progress bar
  - "Stop Agent" button → fires IN PROGRESS → TODO transition

SUBTASKS:
  - Progress bar: X/Y done
  - List with status chips (inline status change)
  - "+ Add Subtask" → inline input

DEPENDENCIES:
  - "Blocks X tasks" / "Blocked by X tasks" pills
  - Click → navigates to that task
  - "+ Add Dependency" → search tasks

TIME TRACKER:
  - Start/Stop button (fires /time/start and /time/stop)
  - Total logged: Xh Ym
  - Sessions breakdown: [date] Xh by [user/agent]

GOAL IMPACT:
  - "Contributes to: [Goal Name]" (colored by goal)
  - Shows % of that goal this task represents

ACTIVITY FEED:
  - All activity_log + task_logs + comments merged, sorted DESC
  - Color-coded by source: agent=#93c5fd system=#fcd34d human=#d4d4d4 error=#f87171
  - Agent blocks: collapsible, shows "[▼] Agent run · model · started · elapsed"
  - Auto-scrolls to bottom on new entries if user is at bottom
  - Real-time via SSE polling

COMMENTS:
  - @mention support (dropdown on @)
  - Submit on Ctrl+Enter
  - Edit/delete own comments
```

---

### GOALS TAB (business goal tracking)

```
GOAL CARDS:
  Each goal:
  - Title + description
  - % complete bar (tasks done / total tasks linked to this goal)
  - ETA for goal completion (based on linked task ETAs)
  - List of linked tasks with status chips
  - Agents working on it: avatar row
  - Priority rank: drag to reorder goals by business priority

GOAL MAP VIEW (toggle):
  - Horizontal timeline showing each goal's projected completion
  - Tasks shown as bars under each goal
  - Color = status (green=done, blue=in_progress, grey=todo, red=blocked)

ADD GOAL:
  - Modal: name + description + target date + link tasks
  - Tasks can link to multiple goals

GOAL vs TASK MATRIX:
  - Table: goals as rows, task types as columns
  - Cell = count of tasks at each intersection
  - Click cell → filters board to that combination
```

---

### METRICS TAB

```
Row 1 — 4 big stat numbers (live polling every 30s):
  Done today / Done this week / ETA accuracy ±Xh / Agent vs Human %

Row 2 — Model performance bars:
  Per model: estimated vs actual hours (bar comparison)
  qwen2.5-coder / llama3.1 / human
  ETA accuracy %: green > 80%, orange > 60%, red < 60%

Row 3 — Charts (Chart.js):
  - Velocity: story points done per sprint (bar chart, last 6 sprints)
  - Burndown: remaining hours vs ideal line (current sprint)
  - Cycle time: avg time in each status column (funnel chart)
  - Lead time: created_at → done per task type (scatter)

Row 4 — Monte Carlo simulation:
  "85% confidence: done by [date]" histogram
  Based on velocity variance across last 10 sprints

Row 5 — Agent workload table:
  Per agent/model: tasks in_progress / done today / done this week / blocked / avg_hours
  Click row → filter board to that agent

Row 6 — Goal progress:
  Each business goal: % tasks done + ETA + on-track badge

Row 7 — Cost breakdown:
  Today $X / This week $X / This month $X
  Per model breakdown (even if $0 for local models)

Row 8 — Recent activity feed (last 20, polls every 10s):
  task title + action + agent/human + timestamp
```

---

### LOGS TAB (full terminal console)

```
TERMINAL PANEL (full height, dark #0d0d0d):
  Top controls:
  - Filter toggles: ALL · AGENT · SYSTEM · HUMAN · ERROR (toggle buttons)
  - Search input (real-time regex filter)
  - LIVE toggle (green=autoscroll on, grey=paused)
  - "↓" floating button when scrolled up (click = jump to bottom + resume live)
  - CLEAR (visual reset only, data preserved)
  - Copy All button
  - Service selector: ALL · api · agent · ollama · supervisor

  Log row format:
  [HH:MM:SS] [source badge] [project #ID · title-30chars] message

  Source badge colors:
  agent=#93c5fd  system=#fcd34d  human=#d4d4d4  error=#f87171bold  supervisor=#a78bfa

AGENT RUN BLOCKS (collapsible per task):
  [▼] Task #ID · title · model · path · Started HH:MM · live elapsed timer
      Body: all logs for that run, indented 2ch, streaming via SSE
  Done: header turns green, timer freezes, "DONE Xh Ym"
  Blocked: header turns red, timer freezes, "BLOCKED after X retries"
  "Stop Agent" button in header → fires status transition

SERVICE LOGS sub-tab (2×2 grid):
  API / AGENT / SUPERVISOR / OLLAMA panels
  Each: dark bg + monospace + auto-scroll + status dot
  Poll /logs/file?name={service} every 3s, last 100 lines
```

---

### KEYBOARD SHORTCUTS (full set)

```
C           → New task (opens modal)
J / K       → Navigate tasks up/down (arrow focus)
Enter       → Open focused task detail panel
X           → Select/deselect focused task
Shift+X     → Select all in column
S           → Change status of focused task (opens dropdown)
P           → Set priority (opens dropdown)
A           → Assign (opens dropdown)
E           → Edit title inline
D           → Set due date (opens date picker)
L           → Add label
T           → Start/stop timer on focused task
G           → Link to business goal
/           → Focus search input
Cmd+K       → Open command palette (ninja-keys)
?           → Keyboard shortcuts overlay
Esc         → Close all panels / deselect
Cmd+Z       → Undo last action (20-action stack)
1-6         → Jump to column (1=backlog, 2=todo, 3=in_progress, 4=review, 5=done, 6=blocked)
Tab         → Move focus to next task card
Shift+Tab   → Move focus to previous task card
```

---

### COMMAND PALETTE (Cmd+K, ninja-keys CDN)

```
All actions searchable:
  create task / create project / create sprint / create goal
  change status / change priority / assign / add label
  navigate to project / open logs / open metrics / open goals
  trigger agent on selected task / stop agent on selected task
  bulk operations (bulk status / bulk assign / bulk label)
  copy task link / archive task
  toggle swimlane / toggle view / toggle dark mode
  filter by assignee / filter by type / filter by goal
  undo / redo
```

---

### NOTIFICATION SYSTEM

```
TOAST (bottom-right, stacked):
  - Info: 4s auto-dismiss
  - Warning: 6s auto-dismiss
  - Error: persistent until dismissed (X button)
  - Agent done: green, task title + actual hours
  - Agent blocked: red, task title + error snippet + "Auto-fixing..."
  - ETA slip: orange, task name + new ETA

BELL DROPDOWN:
  - Unread list with mark-all-read
  - Grouped by type: agent updates / blocked alerts / comments
  - Red pulse animation if any critical alerts

IN-APP ALERTS:
  - Blocked count in sidebar pulses red if > 0
  - WIP over-limit column headers flash amber
  - Overdue tasks (ETA in past) show red border on cards
```

---

### UNDO SYSTEM

```
Action stack: last 20 actions stored in memory
Cmd+Z fires inverse PATCH on the API
Tracks: status changes, priority changes, assignment changes, moves
Toast on undo: "Undid: moved '{title}' back to {prev_status}"
Undo not available for: delete, archive, time entries
```

---

## STEP 9 — AUTOMATED TESTING (auto-run, auto-fix, never stop until done)

### Phase 1 — Unit + API tests

Write `$BOS/tests/test_api.py` covering every endpoint. Auto-loop until 100% pass:

```bash
# Every endpoint, every method, every response code
# POST /tasks — single dict body + array body + missing required fields (422) + extra fields (ignored)
# GET /tasks — filter by status + assignee + task_type + combined filters
# PATCH /tasks/{id}/status — all valid transitions + invalid value (422) + wrong id (404)
# GET /agent/queue — returns resolved_model matching task_type exactly
# GET /metrics/global-eta — all 7 fields present + percent_complete between 0-100
# GET /logs/stream — Content-Type: text/event-stream + never closes
# WS /ws/board — connects + receives broadcast JSON within 2s of task PATCH
# GET /settings + PATCH /settings — roundtrip values survive
# POST /tasks/{id}/logs + GET /tasks/{id}/logs — source field preserved
# GET /tasks/logs/recent — max 50 rows, sorted DESC by timestamp
# POST /admin/wal-checkpoint — 200 + no DB corruption after
# GET /health — all 3 fields (status, db, ollama) = "ok"

# Edge cases in Phase 1:
# Empty DB → all list endpoints return [] not 500
# task_id that doesn't exist → 404 not 500 not 200
# Malformed JSON body → 422 not 500
# Concurrent PATCH same task (10 threads) → no deadlock, last write wins
# task_type=code → resolved_model=qwen2.5-coder:7b (exact string match)
# task_type=research → resolved_model=llama3.1:8b (exact string match)
# Missing estimated_hours → supervisor auto-fills avg, task still queued
# status=in_progress task → agent/queue skips it
# retry_count=3 → escalation notification fired, NOT re-queued

while true; do
  cd $BOS && python3 -m pytest tests/test_api.py -x --tb=short -q \
    && echo "PHASE 1 PASS" && break
  echo "Phase 1 failed — auto-fixing and retrying in 3s..." && sleep 3
done
```

### Phase 2 — Resilience + edge case tests

Write `$BOS/tests/test_edge.py`. Auto-loop until 100% pass:

```bash
# Kill API mid-request → supervisord restarts within 5s → client gets reconnect
# Kill ollama process → supervisor-agent.py restarts it within 30s → gate re-passes
# POST 100 tasks simultaneously → all 100 inserted, no WAL lock error
# WAL checkpoint while agents writing → no data loss, checkpoint completes
# Log file manually inflated to 51MB → auto-rotated on next 5-min cycle
# Model returns empty response → gate marks FAIL → fix_ollama() called
# Blocked task: "No module named 'foo'" → pip install foo → task re-queued to todo
# Blocked task: SyntaxError in file → aider targeted fix → task re-queued
# Blocked task: test failure → aider fix with traceback → task re-queued
# in_progress task with started_at > 2h ago, not in worker slots → reset to todo
# 2 tasks with identical title → duplicate removed, oldest kept, task_log written
# PATCH /settings cloud_enabled=false → agent/queue skips cloud-assigned tasks
# PATCH /settings cloud_enabled=true → cloud tasks re-enter queue

while true; do
  cd $BOS && python3 -m pytest tests/test_edge.py -x --tb=short -q \
    && echo "PHASE 2 PASS" && break
  echo "Phase 2 failed — auto-fixing and retrying in 3s..." && sleep 3
done
```

### Phase 3 — Browser-controlled end-to-end (Playwright, real mouse clicks)

Playwright runs headless Chromium acting exactly as a real user.
Clicks every button. Fills every form. Tests every API from inside the browser.
Bypasses no permissions — tests the real permission flow.
Screenshots saved per step to `$BOS/tests/screenshots/` as proof.
Any failure → auto-fix code → retry. Never stops until 100% pass.

Write `$BOS/tests/test_browser.py`:

```python
# BOARD LOAD
# - navigate to localhost:PORT_FRONTEND
# - wait for .kanban-board selector (timeout 10s)
# - assert project name visible in sidebar
# - screenshot: board-loaded.png

# SIDEBAR: click every project in list
# - click project name → board reloads with that project's tasks
# - verify URL param ?project={id} updates
# - verify task count badge matches GET /tasks?project_id={id} count

# TABS: click every tab one by one
# - Board, Backlog, Sprints, Metrics, Logs, Chat
# - assert active tab has .active class
# - assert tab content panel is visible (not display:none)
# - screenshot per tab

# NEW TASK MODAL
# - click "+ New Task" button
# - assert modal opens (selector .task-modal visible)
# - fill title field with "Browser Test Task"
# - select task_type = "code" from dropdown
# - select priority = "high"
# - fill estimated_hours = "2"
# - click Submit
# - assert modal closes
# - assert "Browser Test Task" card appears on board
# - verify via GET /tasks → title exists in response
# - screenshot: task-created.png

# DRAG AND DROP
# - drag "Browser Test Task" card from TODO column to IN PROGRESS column
# - wait 500ms for animation
# - assert card is now in IN PROGRESS column DOM
# - verify via GET /tasks/{id} → status = "in_progress"
# - screenshot: drag-complete.png
# - drag same card to DONE
# - verify via GET /tasks/{id} → status = "done"

# TASK DETAIL PANEL
# - click any task card
# - assert detail panel visible with class .detail-panel
# - assert panel width = 320px (via getBoundingClientRect)
# - click title inline → assert contenteditable active
# - type " Updated" → press Tab
# - verify via GET /tasks/{id} → title contains "Updated"
# - change priority dropdown → verify card border-left color updates in DOM
# - type comment "test comment" → press Enter
# - assert comment appears in .activity-feed
# - click X button → assert panel not visible
# - screenshot: detail-panel.png

# RIGHT-CLICK CONTEXT MENU
# - right-click a task card
# - assert context menu appears with exactly 6 items
# - click "Change Status" → assert submenu shows all statuses
# - press Esc → menu closes

# MULTI-SELECT
# - shift+click 2 task cards
# - assert both have .selected class
# - assert floating bulk action bar visible
# - click "Change Priority" → select "low" → both tasks update
# - verify via GET /tasks → both have priority="low"

# KEYBOARD SHORTCUTS
# - focus document (click empty board area)
# - press C → assert new task modal opens → press Esc
# - press / → assert search input focused
# - press Cmd+K → assert command palette opens (ninja-keys) → press Esc
# - press ? → assert shortcuts overlay visible → press Esc
# - press Esc (all panels) → assert nothing is open

# BACKLOG TAB
# - click Backlog tab
# - assert task table renders with all tasks
# - verify task count matches GET /tasks count

# SPRINTS TAB
# - click Sprints tab
# - assert sprint cards visible
# - assert Chart.js burndown canvas rendered (canvas element exists in DOM)
# - click "New Sprint" → modal opens → fill name + dates + goal → submit
# - assert new sprint card appears

# METRICS TAB
# - click Metrics tab
# - assert 4 stat numbers rendered (not "--" or null)
# - assert all Chart.js canvas elements rendered (count >= 4)
# - screenshot: metrics-tab.png

# LOGS TAB
# - click Logs tab
# - assert EventSource connected (check window.__logStream__ status via evaluate)
# - wait 3s → assert at least 1 log row in DOM
# - type "agent" in search input → assert only "agent" source rows visible
# - clear search → scroll up → assert "↓" button appears
# - click "↓" → assert scrolled to bottom
# - screenshot: logs-tab.png

# API CALLS FROM BROWSER CONTEXT (via page.evaluate fetch)
# - POST /tasks with task_type=code → assert resolved_model=qwen2.5-coder:7b in response
# - POST /tasks with task_type=research → assert resolved_model=llama3.1:8b
# - PATCH /tasks/{id}/status with status=blocked → assert 200
# - PATCH /tasks/{id}/status with status=INVALID → assert 422
# - GET /metrics/global-eta → assert all 7 keys present: done, remaining, blocked,
#     hours_left, projected_completion, percent_complete, velocity_per_day
# - WebSocket test: open ws://localhost:PORT_API/ws/test → POST task via fetch →
#     assert WS message received within 2s containing task id

# WEBSOCKET REAL-TIME UPDATE
# - open board tab
# - in separate page.evaluate: create new task via fetch POST /tasks
# - assert new task card appears on board within 3s WITHOUT page refresh
# - (verifies WS broadcast → optimistic UI working)

# PERMISSION BYPASS TESTS (real flow, no shortcuts)
# - navigate to every protected endpoint directly in browser
# - assert /tasks returns data (no auth wall — CORS open by design)
# - assert /agent/queue returns data
# - assert /settings returns data
# - assert /logs/stream starts streaming (EventSource test)
# - all must return 200 not 401/403 (local setup, no auth required)

# EDGE CASES IN BROWSER
# - submit new task with empty title → assert form validation error shown
# - submit task with estimated_hours = 0 → assert 422 or inline warning
# - drag task to same column it's already in → no status change, no error
# - open 3 detail panels in rapid succession → only last one stays open
# - resize window to 375px wide (mobile) → board still renders, no overflow crash
# - network tab: verify WS stays connected for 30s (no disconnect)
# - screenshot every error state as proof of correct handling
```

```bash
# Run Phase 3 — auto-fix failures, retry until 100% pass
while true; do
  cd $BOS && python3 -m pytest tests/test_browser.py -x --tb=short \
    --screenshot=on --video=retain-on-failure \
    --output=$BOS/tests/screenshots/ \
    && echo "PHASE 3 PASS" && break
  echo "Browser test failed — fixing and retrying in 5s..."
  sleep 5
done

echo "All 3 phases passed. Screenshots at $BOS/tests/screenshots/"
```

### Phase 4 — Cleanup (only after all phases pass)

```bash
# 1. Remove test files and test deps
rm -rf $BOS/tests/
python3 -m pip uninstall -y pytest pytest-asyncio pytest-playwright 2>/dev/null || true
echo "Tests removed. Production code only."

# 2. Clean up DB — archive old done tasks, remove orphans, trim logs
python3 - << 'CLEANUP'
import sqlite3, os, datetime

db = sqlite3.connect(os.path.expandvars("$BOS/business.db"))
c = db.cursor()

# Archive done tasks older than 7d
c.execute("CREATE TABLE IF NOT EXISTS task_archive AS SELECT * FROM tasks WHERE 1=0")
c.execute("INSERT INTO task_archive SELECT * FROM tasks WHERE status='done' AND completed_at < datetime('now','-7 days')")
archived = c.rowcount
c.execute("DELETE FROM tasks WHERE status='done' AND completed_at < datetime('now','-7 days')")

# Remove orphaned logs, empty sprints, stale queue rows, old read notifications
c.execute("DELETE FROM task_logs WHERE task_id NOT IN (SELECT id FROM tasks) AND task_id NOT IN (SELECT id FROM task_archive)")
c.execute("DELETE FROM sprints WHERE status!='active' AND id NOT IN (SELECT DISTINCT sprint_id FROM tasks WHERE sprint_id IS NOT NULL)")
c.execute("DELETE FROM task_queue WHERE status='done' OR task_id NOT IN (SELECT id FROM tasks)")
c.execute("DELETE FROM notifications WHERE read=1 AND created_at < datetime('now','-3 days')")
db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
db.commit()
db.close()

print(f"Cleanup: {archived} done tasks archived, orphans removed, queue trimmed")
CLEANUP
```

---

## PROJECT TEARDOWN (run when project is fully complete)

Only when the project is done and you no longer need the OS running.
Exports full state first, then clears everything cleanly.

```bash
# 1. Stop all services
SUPCTL="$HOME/Library/Python/3.9/bin/supervisorctl -c $BOS/supervisord.conf"
$SUPCTL stop all && $SUPCTL shutdown
pkill -f "ollama serve" 2>/dev/null || true

# 2. Export final state before clearing
python3 - << 'EXPORT'
import sqlite3, json, os, datetime
db = sqlite3.connect(os.path.expandvars("$BOS/business.db"))
db.row_factory = sqlite3.Row
slug = os.environ.get("PROJECT_SLUG", "project")
out = f"{os.path.expanduser('~')}/{slug}-export-{datetime.date.today()}.json"
data = {}
for t in ["projects","sprints","tasks","task_archive","task_logs","activity_log","agent_metrics","api_usage"]:
    try: data[t] = [dict(r) for r in db.execute(f"SELECT * FROM {t}").fetchall()]
    except: pass
db.close()
with open(out, "w") as f: json.dump(data, f, indent=2, default=str)
print(f"Exported: {out}")
EXPORT

# 3. Wipe all projects, tasks, logs from DB
sqlite3 $BOS/business.db << 'SQL'
DELETE FROM task_queue; DELETE FROM task_logs; DELETE FROM activity_log;
DELETE FROM comments; DELETE FROM time_entries; DELETE FROM notifications;
DELETE FROM agent_metrics; DELETE FROM api_usage; DELETE FROM tasks;
DELETE FROM task_archive; DELETE FROM sprints; DELETE FROM labels;
DELETE FROM task_labels; DELETE FROM projects;
UPDATE settings SET value='false' WHERE key='setup_complete';
PRAGMA wal_checkpoint(TRUNCATE);
SQL

# 4. Remove BOS directory (uncomment to fully delete)
# rm -rf $BOS

# 5. Clean shell exports
sed -i '' "/BOS_HOME=/d" ~/.zshrc
sed -i '' "/OLLAMA_API_BASE=/d" ~/.zshrc

echo "Teardown complete. Export at ~/."
```

---

## CHAT WITH LOCAL MODELS (4 ways)

### 1. Terminal — works immediately, no setup

```bash
# reasoning / planning
ollama run llama3.1:8b

# code questions
ollama run qwen2.5-coder:7b
```

Type your message, press Enter. `/bye` to exit.
Use for: quick questions, testing a model, debugging task output.

### 2. Open WebUI — browser ChatGPT-like interface

```bash
pip3 install open-webui
open-webui serve --port 8080
```

Open `http://localhost:8080`. On first load: Settings → Connections → set Ollama URL to `http://localhost:11434`.
Both models appear automatically.
Use for: longer conversations, comparing outputs, prompt testing.

Add to supervisord to auto-start:

```ini
[program:%(ENV_PROJECT_SLUG)s-openwebui]
command=open-webui serve --port 8080
environment=OLLAMA_BASE_URL="http://localhost:11434",BOS_HOME="%(ENV_BOS_HOME)s"
autorestart=true
redirect_stderr=true
stdout_logfile=%(ENV_BOS_HOME)s/logs/openwebui.log
```

### 3. REST API directly

```bash
curl http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5-coder:7b",
    "messages": [{"role":"user","content":"hello"}],
    "stream": false,
    "options": {"num_ctx": 2048}
  }'
```

Keep `num_ctx` consistent on every request to prevent model reload between calls.

### 4. Project API — give agents work and watch them do it

```bash
curl -X POST localhost:$PORT_API/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 1,
    "title": "What you want done",
    "description": "Detailed description",
    "task_type": "code",
    "priority": "high",
    "assignee": "local-agent",
    "estimated_hours": 1.0
  }'

# Watch live
open http://localhost:$PORT_FRONTEND
open http://localhost:$PORT_FRONTEND/#logs
```

**Which to use:**

| Situation | Use |
|---|---|
| Quick question or test | Terminal (`ollama run`) |
| Longer conversation / prompt testing | Open WebUI (`:8080`) |
| Scripting or integrations | REST API (`:11434`) |
| Real project work you want tracked | Project API (`:$PORT_API`) |

---

## ADDING TASKS (give agents work)

Via API:

```bash
curl -X POST localhost:$PORT_API/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 1,
    "title": "Your task title",
    "description": "What needs to be done",
    "task_type": "code",
    "priority": "high",
    "assignee": "local-agent",
    "estimated_hours": 2.0,
    "story_points": 3
  }'
```

Via board: `http://localhost:$PORT_FRONTEND` → New Task → agents pick it up automatically.

`task_type` routes to model automatically:
- `code` / `bug` → `qwen2.5-coder:7b`
- `research` / `write` / `ops` / `design` → `llama3.1:8b`

---

## TRACKING PROGRESS

| Where | What |
|---|---|
| `http://localhost:$PORT_FRONTEND` | Kanban board — live task view |
| `http://localhost:$PORT_FRONTEND/#logs` | Live agent output |
| `http://localhost:$PORT_API/health` | System health |
| `http://localhost:$PORT_API/agent/status` | Worker-1 and Worker-2 current task |
| `http://localhost:$PORT_API/metrics/global-eta` | ETA + % complete |
| `tail -f $BOS/logs/agent.log` | Raw agent output |
| `tail -f $BOS/logs/supervisor.log` | Auto-fix activity |
| `python3 $BOS/status.py` | Live terminal dashboard (2s refresh) |

---

## WHAT IS NOT IN THIS SETUP

- No GitHub / git (removed entirely)
- No worktrees / branches
- No ntfy / Slack notifications (add via settings table webhook if needed)
- No mkcert / HTTPS
- No launchd auto-start (add supervisord to Login Items if needed)
- No deepseek-r1:14b (add to MODELS if RAM allows)
- No seed/sample tasks auto-created on DB init
- No documentation generation — agents do real implementation work only
- No codebase mapping (`--map-tokens` limits this intentionally)

---

## CURRENT STATE ($PROJECT_SLUG-os)

> `~/stacky-os` is a symlink → `~/Documents/stacky/local-agents/` (all agent files live there)

```
~/$PROJECT_SLUG-os/
  api.py                FastAPI server (port $PORT_API)
                          · worker_heartbeat_{id} in settings — restored on lifespan startup
  db.py                 SQLite + aiosqlite layer (WAL mode)
  agent_runner.py       Autonomous agent runner V3→V10 (replaces bare aider)
                          · Iterative tool-use loop: up to 8 rounds per task
                          · Full directive set: READ_FILE, LIST_DIR, SEARCH_CODE, PATCH_FILE
                          · WRITE_FILE: atomic (write→.tmp→rename) + auto-backup (.bak)
                          · ROLLBACK: restore from .bak
                          · MEMO: task scratchpad persists across retries
                          · CONFIDENCE: confidence gating before critical writes
                          · Planning V2: creates project + sprint + sub-tasks
                          · V8 auto-test: discovers + runs test_*.py after .py writes
                          · V10 self-review: quality summary after DONE
                          · FILE_HINTS: 40+ keyword→file mappings
                          · run_with_retry(max_attempts=2) with memo preservation
  agent-loop.sh         2-worker loop (delegates to agent_runner.py, no git, no browser)
                          · Writes task JSON to temp file, calls agent_runner.py
                          · PATCH /agent/heartbeat on task start (sets worker active on dashboard)
                          · Background heartbeat loop every 30s during execution
                          · Idle heartbeat on task complete (clears active state)
  supervisor-agent.py   Self-healing autonomous monitor (15s cycle)
                          · model_ready() uses /api/tags (fast) not /api/generate (slow)
                          · auto-completes review→done for local-agent tasks
                          · attempts fix for blocked tasks
  supervisord.conf      Process manager (pip supervisor)
  status.py             Live terminal dashboard (2s refresh)
  progress.py           Step progress tracker
  e2e_test.py           Playwright E2E test suite (89 tests, real browser)
                          · fill+dispatchEvent for React inputs (not press_sequentially)
                          · tracks created task IDs and hard-deletes via DELETE /tasks/{id}
                          · browser always closed in finally block
                          · test_agent_autonomy_file_write: creates task, waits for review, verifies file
                          · test_agent_queue_and_heartbeat: queue structure, heartbeat endpoint
  GOALS.md              Definition of done + gate rules
  .aider.model.metadata.json   Silences model warnings permanently
  business.db           SQLite DB (WAL mode)
  frontend/
    index.html          Advanced Kanban board (Board v2)
                          · Board view + Swimlane view (business goal grouping)
                          · Right-click context menu (status/assign/copy ID/delete)
                          · Activity feed panel (live agents + recent events)
                          · Keyboard shortcuts (? for modal, b/s/n/Esc/Ctrl+A)
                          · Bulk select (Shift+click) + batch status change
                          · Filter bar: assignee + priority + type chips
                          · Status side effects: todo→in_progress queues agent, in_progress→todo dequeues
                          · Chat tab: autonomous mode with live system context injection
                          · Project sidebar: stacked progress bar + ETA tag
  logs/
    api.log             (50MB max, 3 backups) — includes structured error traces
    agent.log           (100MB max, 5 backups)
    supervisor.log      (20MB max, 3 backups)
    ollama.log
    frontend.log
    gate.json           Gate status (read by agents before every task)
    setup-progress.json Step progress (read by status.py)
```

## E2E TESTING

Run the full test suite (closes browser on completion, hard-deletes test tasks):
```bash
cd $BOS && python3 e2e_test.py
```

Covers: 89 tests — 18 API endpoints + 71 browser/agent interactions.

**API tests (headless):**
- Health, tasks CRUD, projects, sprints, metrics, logs, agent status
- `DELETE /tasks/{id}` — hard delete
- `POST /tasks/{id}/dequeue` — stops agent pickup
- `POST /chat/message` — chat proxy
- `PATCH /agent/heartbeat` — worker heartbeat
- `GET /agent/queue` — queue structure validation

**Browser UI tests (real Playwright browser, headful):**
- All nav tabs (Board, Backlog, Sprints, Metrics, Logs, Chat)
- Board columns visible, filter chips (assignee/priority/type), search input
- Create task modal: open, fill title, close, task appears on board
- Task card click → detail panel opens
- Project sidebar: name visible, stacked progress bar, ETA tag, click to filter
- Logs tab: filter buttons
- Backlog: table rows rendered
- Sprints: sprint cards
- Metrics: 6 metric cards
- Board filter chips: click priority chip, board narrows, clear resets
- Board view toggle: ⊞ Board ↔ ≡ Swimlane
- Board context menu: right-click card, 12 items, Esc closes
- Board keyboard shortcuts: ? opens modal, closes
- Activity feed: toggle, sections visible
- Status side effects: context menu todo→in_progress, verifies via API
- Chat: welcome message, textarea focusable, model picker, mode toggle
- Chat turn 1: user message → assistant reply with model in meta
- Chat turn 2: multi-turn (history preserved)
- Chat send button click
- Task mode: create task → task card shown, correct model auto-selected
- /task command: task created in chat mode, type auto-detected
- Shift+Enter inserts newline (doesn't send), Enter sends
- Context ON toggle: live system answer verified
- Task from chat → board integration: task card + ID in conversation

**Agent system tests (API only):**
- `test_agent_autonomy_file_write` — creates write task assigned to local-agent, polls up to 90s for review/done status, verifies output file written
- `test_agent_queue_and_heartbeat` — worker schema, queue response, heartbeat endpoint

**Playwright rules:**
- Always `fill()` + `dispatchEvent('input')` for React inputs — `press_sequentially` drops chars
- Wait for `.chat-msg.assistant .chat-meta` count increase for reply detection (not `.chat-msg` count — loading indicator has no `.chat-meta`)
- Use `wait_for_function` with JS condition instead of `wait_for(state="enabled")` (older Playwright compat)

**Cleanup rule:** always hard-delete test tasks after run via `DELETE /tasks/{id}`.
Agents auto-pick any `todo` task — test tasks waste compute and pollute metrics.
Track IDs in a list, run `DELETE /tasks/{id}` for each at the end (in `finally` block).
Also `DELETE /projects/{id}` for any test projects (cascades all tasks/sprints/labels).

---

## AGENT RUNNER VERSION HISTORY

### V3 (baseline)
- Iterative tool-use loop (up to 8 rounds)
- Tools: READ_FILE, LIST_DIR, SEARCH_CODE, PATCH_FILE, WRITE_FILE, APPEND_FILE, RUN
- Inline Python syntax check on every WRITE_FILE

### V4 — Atomic Write + Rollback
- `write_file_atomic()`: writes to `.tmp` then renames (POSIX atomic), auto-backs up to `.bak`
- `ROLLBACK: /path` directive: restores file from `.bak`
- Prevents partial writes from corrupting files mid-task

### V5 — MEMO Scratchpad (cross-iteration persistence)
- `MEMO: key = value` directive saves to `/tmp/stacky_memo_{task_id}.json`
- Survives retries — V5 loads memos at start of every attempt
- Auto-cleared on success. Kept on failure for next retry.
- Previous iteration memos injected into feedback prompt

### V6 — Planning Mode (auto sub-task creation)
- Design tasks and tasks with `estimated_hours > 3` trigger planning
- LLM breaks task into 2-6 sub-tasks with `SUB_TASK: title | type | desc`
- Auto-creates sprint and sub-project via API if LLM names them
- Full try/except around project/sprint POST — failures are logged, not fatal

### V7 — Parallel File Read (NEW — 2026-03-24)
- `PARALLEL_READ: /path1 | /path2 | /path3` reads multiple files in one iteration step
- Returns all contents concatenated — saves 2-3 iterations on tasks needing multiple files
- Added to SYSTEM_PROMPT, `parse_response()`, and main tool loop

### V8 — Auto-Test Discovery
- After every `.py` WRITE_FILE: discovers `test_*.py` / `*_test.py` near the file
- Runs `pytest --tb=short -q` and feeds result back to LLM
- `CONFIDENCE: N` directive (1-10) — if < 5, injects "gather more info" warning
- Prevents shipping code without at least checking for adjacent tests

### V9 — TODO/FIXME Scanner + Quality Score (NEW — 2026-03-24)
- `SCAN_TODOS: /directory` greps for TODO, FIXME, HACK, XXX across .py/.sh/.md
- Returns: file:line:type:context for each hit
- Computes `quality_score = 100 - (issues/lines)*1000` (per-kloc density)
- Score logged to task, visible in self-review (V10)

### V10 — Self-Review + Confidence Gate
- After DONE: posts quality summary to task log
- Reviews: file sizes, line counts, syntax pass/fail, command success rate, memo count
- Confidence gate: CONFIDENCE < 5 injects "investigate more" into next LLM message
- Prevents low-confidence rewrites of large files

### Bug Fix (2026-03-24): Prose-Loop Self-Healing
- **Issue**: agents looped 8 iterations outputting prose (no directives), then gave up
- **Cause**: LLM said "FAILED: No tool directives detected" — became self-referential
- **Fix**: After 3 consecutive no-directive iterations, runner forces `DONE` and exits cleanly
- **Diagnostic**: local agents were failing task #163 (V6 fix) 3x for this reason
- **Symptom**: task log shows "[iter 8] no directives detected — prompting to conclude" repeated

---

## BENCHMARK: Claude vs Local Agents (V12)

### Scripts
- `benchmark_runner.py` — batch 5 standard tasks, track completion/time/quality/self-heals
- `claude_comparison.py` — run same task through local Ollama AND Claude API side-by-side

### Run benchmark
```bash
cd $BOS
python3 benchmark_runner.py           # full 5-task suite
python3 benchmark_runner.py --quick   # 2 tasks only
python3 benchmark_runner.py --leaderboard  # show latest report
python3 claude_comparison.py          # run demo comparison task
python3 claude_comparison.py --task "Write X"  # custom task
```

### Benchmark metrics tracked
| Metric | Description |
|--------|-------------|
| completion_rate | % of tasks that reach done/review status |
| avg_time_s | Average wall-clock seconds per task |
| avg_quality | Heuristic score: 50 base + retry penalty + speed bonus |
| self_heal_count | Tasks that hit blocked status and recovered |
| cost | Always $0 for local; Claude costs ~$0.002/task |

### Known issue: timeout calibration
- Local agents need 120-300s per task (Ollama inference is slower than Claude API)
- Benchmark default timeout is 300s per task
- If agents are busy with other tasks, add wait: `python3 benchmark_runner.py` waits for idle

### Claude baseline (haiku-4-5)
| Task | Time | Quality |
|------|------|---------|
| hello_world | 3.2s | 85/100 |
| fibonacci | 4.1s | 90/100 |
| scan_todos | 5.0s | 80/100 |
| patch_file | 6.5s | 75/100 |
| write_tests | 8.2s | 88/100 |

Local agents will keep upgrading (V13, V14...) until completion_rate ≥ 95% AND quality ≥ 80.

### Latest benchmark result (2026-03-24)
After V13 self-improvement patches + V14-V23 Anthropic harness design upgrades:

| Metric | Local (Ollama qwen2.5-coder:7b) | Claude (Haiku) | Winner |
|--------|--------------------------------|----------------|--------|
| Completion Rate | **100%** | 96% | **local** |
| Avg Time | 44s | 5.4s | claude |
| Avg Quality | **100/100** | 84/100 | **local** |
| Cost | **$0** | ~$0.004/task | **local** |

**V21-V23 additions (Anthropic harness article, 2026-03-24):**
- V21 External Evaluator: every DONE now triggers independent LLM scoring (score/100, pass/fail) — detects overconfident agents
- V22 Sprint Contracts: done-criteria extracted from description before work starts, stored in /tmp/contract_{id}.json
- V23 Checkpoint/Resume: per-iteration state saved to /tmp/ckpt_{id}.json — interrupted tasks resume from last artifact (fixes Opus 4.6 session-stop bug)

**New directives added to SYSTEM_PROMPT:**
- `SPRINT_CONTRACT: <criteria>` — register done conditions at task start
- `EVALUATE: <aspect>` — request mid-task independent evaluation

**V24-V26 additions (2026-03-24, same session):**
- V24 Token tracker: `reports/token_usage.json` — 150K tokens saved = $0.50 Claude equiv per session
- V25 RUN path normalization: `/stacky-os/file.py` in RUN commands now expands correctly
- V26 Protected files: agents can't nuke system files with stubs (supervisor-agent.py was corrupted, auto-restored from .bak)
- token_report.py: run for live Claude vs local cost comparison

**ULTRA-hard tasks (ULTRA-1 through ULTRA-10) — all rescued by Claude (Claude 10%):**
- HTTP/1.1 server, Myers diff, SQL parser, JSON parser, async scheduler
- B-tree, NFA regex, CLI time tracker, coroutine scheduler, data pipeline
- All verified with self-tests and assertions

**Result: Local agents WIN 2/3 categories. V21-V26 harness upgrades address top Opus frustrations (session stop, lazy fixes, self-evaluation bias, system file corruption).**

---

## ESCALATION PROTOCOL (updated 2026-03-24)

### When local agents fail 3x
1. Supervisor logs: `ESCALATE: #{id} failed 3x — needs Claude`
2. macOS notification fires
3. Claude Code receives the message, diagnoses root cause
4. Claude either: fixes the code, marks task done with explanation, or resets and re-queues

### Common root causes and Claude fixes
| Error | Root Cause | Claude Fix |
|-------|-----------|------------|
| `mktemp: File exists` | Stale `/tmp/stacky_task_*.json` | `rm -f /tmp/stacky_task_*.json` |
| `deepseek-r1:14b not found` | Model pulled but not available | Patch task: `agent_model→llama3.1:8b` |
| 8 iterations, no directives | Prose-loop bug (pre-2026-03-24 fix) | Force-DONE after 3 no-directive iters |
| `FATAL` agent in supervisord | Process crashed on bad task | `supervisorctl restart agents:stacky-agent-1` |

### Agent health check
```bash
/Users/jimmymalhan/Library/Python/3.9/bin/supervisorctl -c ~/stacky-os/supervisord.conf status
curl -sf localhost:8000/health
tail -20 ~/stacky-os/logs/agent.log
tail -20 ~/stacky-os/logs/supervisor.log | grep -E 'ESCALATE|DONE|ERROR'
```
