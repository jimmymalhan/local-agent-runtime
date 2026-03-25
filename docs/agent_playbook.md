# Agent Playbook — How to Act Safely in This Repo

**For any AI agent or new engineer entering this repo.**
Read this in full before writing a single line of code.
Estimated read time: 5 minutes.

---

## The 10 Questions You Must Answer First

Before acting, verify you can answer all 10:

| # | Question | Answer |
|---|----------|--------|
| 1 | What is this repo for? | Local-first autonomous agent runtime (Nexus/Jimmy) that beats Claude Opus on coding benchmarks |
| 2 | How does work flow? | Task → router (`agents/__init__.py`) → specialized agent → Ollama loop → reviewer scores → result |
| 3 | Which layer owns my task? | L1=Meta(docs/policy), L2=Supervisor(pre-flight), L3=Execution(agents), L4=Learning(upgrade) |
| 4 | Which file to read first? | `README.md`, then this file, then `registry/agents.json` |
| 5 | Where do I write outputs? | `~/local-agents-work/` (BOS). Never in project root |
| 6 | Where do I log changes? | `local-agents/reports/` for runtime logs; git commit for code changes |
| 7 | How do I run tests? | `python3 local-agents/orchestrator/main.py --version 1 --quick 3 --local-only` |
| 8 | How do I replay a failure? | Check `reports/v{N}_compare.jsonl` for the failing task, re-run with `--quick 1` |
| 9 | How do I check benchmark scores? | `cat docs/leaderboard.md` or `curl localhost:3001/api/state` |
| 10 | How do I know if docs are stale? | `git log -1 docs/repo_map.md` — if older than last code change, refresh docs |

---

## Step 1: Read Before Acting

```bash
# Always run this sequence first
cat README.md
cat docs/repo_map.md       # you are here
cat local-agents/agents/config.yaml
cat local-agents/registry/agents.json | python3 -m json.tool | head -40
curl -s http://localhost:3001/api/state | python3 -m json.tool | head -20
tail -20 local-agents/reports/auto_loop.log  # what's currently running
```

---

## Step 2: Understand the Task Flow

```
User task → bash ./Local OR orchestrator/main.py
         ↓
agents/__init__.route(task)          # picks agent by category
         ↓
agents/{executor|architect|...}.run(task)
         ↓
agent_runner.run_task()              # Ollama iterative loop
         ↓
exec_write_file() → ~/local-agents-work/   # all output here
         ↓
reviewer.run() → quality score (0-100)
         ↓
If quality >= 40: DONE
If quality < 40 and fail_count >= 3: auto_upgrade (Claude rescue, 200-token cap)
```

---

## Step 3: Find the Right Agent

```python
# In any Python file:
import sys; sys.path.insert(0, 'local-agents')
from agents import route, run_task

agent_name = route({'category': 'code_gen'})   # → 'executor'
result = run_task({'title': '...', 'description': '...', 'category': 'code_gen'})
```

**Category → Agent routing:**
| Category | Agent |
|----------|-------|
| code_gen, bug_fix | executor |
| tdd | test_engineer |
| scaffold, arch, e2e | architect |
| refactor | refactor |
| research | researcher |
| review | reviewer |
| debug | debugger |
| plan | planner |
| doc | doc_writer |

---

## Step 4: Check Registry Before Any Change

```bash
cat local-agents/registry/agents.json | python3 -c "
import sys,json; r=json.load(sys.stdin)
for name,a in r.get('agents',{}).items():
    print(f'{name}: v{a.get(\"version\")} | score={a.get(\"benchmark_scores\")} | status={a.get(\"status\")}')
"
```

**Never bump a version without:**
1. Benchmark run showing improvement
2. Updated `benchmark_scores` in registry
3. Updated `docs/leaderboard.md`

---

## Step 5: Make Safe Changes

**Safe (go ahead):**
- Edit agent system prompts in `agents/{name}.py` → AGENT_META["system_prompt"]
- Add new tasks to `tasks/task_suite.py`
- Edit `agents/config.yaml` thresholds
- Add docs

**Requires benchmark verification:**
- Changing scoring logic in `reviewer.py`
- Changing routing in `agents/__init__.py`
- Changing parser logic in `agent_runner.py`
- Changing orchestrator loop in `orchestrator/main.py`

**Never do without Meta approval:**
- Delete an agent file
- Change the registry schema
- Change the BOS path logic
- Merge to `main` without CI passing

---

## Step 6: Run Tests

```bash
# Quick sanity (3 tasks, local only, no Opus calls)
python3 local-agents/orchestrator/main.py --version 1 --quick 3 --local-only

# Full version with Opus comparison
python3 local-agents/orchestrator/main.py --version 1 --quick 10

# Single agent test
python3 -c "
import sys; sys.path.insert(0,'local-agents')
from agents import run_task
r = run_task({'title':'Binary search','description':'...','category':'code_gen'})
print(r.get('quality'), r.get('status'))
"
```

---

## Step 7: Log and Commit

**Runtime logs (automatic, no manual action):**
- `reports/v{N}_compare.jsonl` — every task result
- `reports/auto_upgrade_log.jsonl` — every prompt change
- `reports/claude_token_log.jsonl` — every Claude call

**Code changes:**
```bash
git checkout -b feature/<descriptive-name>
git add <specific-files>    # never git add -A
git commit -m "fix: <what> — <why>"
git push origin feature/<name>
# CI must pass before merge to main
```

---

## Step 8: Recover From Failure

**If agent outputs garbage 3 times:**
```bash
# Check what pattern it's hitting
python3 local-agents/orchestrator/auto_upgrade.py --version N --dry-run
# Apply manual prompt fix to agents/{name}.py AGENT_META["system_prompt"]
# Re-run benchmark on that agent specifically
```

**If loop crashes:**
```bash
pkill -f "main.py"
tail -50 local-agents/reports/auto_loop.log   # find error
nohup python3 -u local-agents/orchestrator/main.py --auto 1 >> local-agents/reports/auto_loop.log 2>&1 &
```

**If BOS files appear in project root:**
```bash
mv *.py ~/local-agents-work/   # never should happen with BOS fix in exec_write_file
```

**If dashboard dies:**
```bash
python3 local-agents/dashboard/server.py --port 3001 &
echo "http://localhost:3001" > DASHBOARD.txt
```

---

## Step 9: Propose an Upgrade

Upgrades go through auto_upgrade.py — not manual edits.

```python
# In orchestrator/auto_upgrade.py, add to FAILURE_PATTERNS:
"my_new_pattern": {
    "detect": lambda code: bool(re.search(r'pattern', code)),
    "fix": "System prompt addition that fixes this pattern",
    "dimension": "code_correctness",
}
```

The auto_upgrade engine will:
1. Detect the pattern in failed outputs
2. A/B test the fix against 3 baseline tasks
3. Commit if improvement >= 5 points

---

## Step 10: Roll Back

```bash
# Find the commit that caused regression
git log --oneline local-agents/agents/{agent}.py | head -5
# Revert the specific file
git checkout <commit-hash>^ -- local-agents/agents/{agent}.py
git commit -m "revert: roll back {agent} to last known good"
```

---

## Non-Negotiable Rules

1. **No file output in project root** — all writes go to `~/local-agents-work/`
2. **No direct main branch commits** — feature branches + PR + CI
3. **No Claude calls without 3 local failures** — rescue-only at ≤10%
4. **No version bump without benchmark evidence** — measured delta required
5. **No code change without doc check** — if README is stale, fix it first
6. **No blind work** — read repo_map.md before acting

---

## 5-Minute System Understanding

```
1. It's a loop: v1 → v2 → ... → v100
2. Each version: run 100 tasks, compare local vs Opus 4.6
3. After each version: auto_upgrade detects failures, patches prompts
4. Local agents do 90% — Ollama models via agent_runner.py
5. Claude is rescue-only at 10% budget, 200 tokens per call
6. Dashboard at http://localhost:3001 shows everything live
7. All outputs go to ~/local-agents-work/ (BOS), never project root
8. Registry tracks agent versions and benchmark scores
9. Leaderboard at docs/leaderboard.md shows version-by-version progress
10. System never stops — self-heals, self-improves, never asks for input
```
