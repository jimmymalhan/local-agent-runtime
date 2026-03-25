# Nexus — Personal Autonomous Agent Runtime

**Nexus** is your personal AI model. **Nexus** is the agent that runs it.
Self-improving. Local-first. Competing directly with Claude Opus 4.6.

---

## README Contract — Answers in Under 2 Minutes

| Question | Answer |
|----------|--------|
| **What is this repo?** | Local-first autonomous agent runtime that runs real coding tasks, self-heals, self-improves version-by-version, and beats Claude Opus on benchmarks |
| **How does work flow?** | Task → `agents/__init__.route()` → specialized agent → Ollama loop → reviewer scores → result. If quality < 40 after 3 tries → Claude rescue (200-token cap) |
| **Which layer owns my task?** | L1=Meta(docs/policy), L2=Supervisor(pre-flight), L3=Execution(agents), L4=Learning(auto-upgrade) |
| **Which file to read first?** | This README, then `docs/repo_map.md`, then `local-agents/agents/config.yaml` |
| **Where do I write outputs?** | `~/local-agents-work/` (BOS). **Never** in project root |
| **Where do I log changes?** | Runtime: `local-agents/reports/`. Code changes: git commit to feature branch |
| **How do I run tests?** | `python3 local-agents/orchestrator/main.py --version 1 --quick 3 --local-only` |
| **How do I replay a failure?** | Check `reports/v{N}_compare.jsonl` for the task, re-run with `--quick 1` |
| **How do I check benchmark scores?** | `cat docs/leaderboard.md` or `curl localhost:3001/api/state` |
| **How do I know if docs are stale?** | `git log -1 docs/repo_map.md` — if older than last code change, refresh docs |

---

## Current Benchmark Status

| Version | Local (Nexus) | Opus 4.6 | Win Rate | Claude Tokens |
|---------|--------------|----------|----------|---------------|
| v5      | 76.3/100     | 56.7/100 | **100%** | 289 total     |

Local agents own **90%** of all work. Claude rescue hard cap: ≤10% of tasks, 200 tokens per call.

---

## System Architecture — 4 Layers

```
LAYER 1: META         — docs, policy, repo structure, upgrade decisions
LAYER 2: SUPERVISOR   — pre-flight checks, heartbeat, stall detection, restarts
LAYER 3: EXECUTION    — 10 specialized agents do the actual work
LAYER 4: LEARNING     — failure detection, A/B prompt tests, auto-upgrade
```

```
┌─────────────────────────────────────────────────────────┐
│                    Nexus (via Nexus)                    │
│      Self-Improving Personal AI  —  v1→v100 Loop       │
├─────────────────────────────────────────────────────────┤
│  L3: Planner · Executor · Reviewer · Debugger           │
│      Architect · Refactor · TestEngineer · DocWriter    │
├─────────────────────────────────────────────────────────┤
│  L4: auto_upgrade → 8 failure patterns → A/B → commit  │
├──────────────────────┬──────────────────────────────────┤
│  LOCAL (90%)         │  RESCUE ONLY (≤10%)              │
│  qwen2.5-coder:7b    │  Claude Opus 4.6 CLI             │
│  deepseek-r1:8b      │  200-token cap per call          │
│  (any Ollama model)  │  Agent upgrades only             │
└──────────────────────┴──────────────────────────────────┘
```

---

## Setup

```bash
# 1. Install Ollama and pull primary model
ollama pull qwen2.5-coder:7b

# 2. Clone and start
git clone <this-repo>
cd local-agent-runtime
bash ./Local                    # interactive CLI

# 3. Verify system
python3 local-agents/orchestrator/resource_guard.py --check
curl http://localhost:3001/api/state   # dashboard live?
```

---

## Usage

### One-shot task
```bash
bash ./Local "Build a rate limiter with sliding window"
```

### Run benchmarks (local only, no API cost)
```bash
python3 local-agents/orchestrator/main.py --version 1 --quick 5 --local-only
```

### Run with Opus 4.6 comparison
```bash
python3 local-agents/orchestrator/main.py --version 1 --quick 5
```

### Full autonomous v1→v100 loop
```bash
python3 local-agents/orchestrator/main.py --auto 1
# - Runs 100 tasks per version
# - Compares local vs Opus 4.6 every task
# - Auto-upgrades failing agents after each version
# - Never stops until local beats Opus on all categories
```

### Deploy to any project (5 minutes)
```bash
python3 local-agents/deploy.py all --to /path/to/your/project
python3 /path/to/your/project/.local-agents/runner.py "Write a Redis cache wrapper"
```

### Live dashboard (1 view — everything)
```bash
python3 local-agents/dashboard/server.py --port 3001
# Open: http://localhost:3001
# Shows: version, agent status, queue, scores, Claude budget, hardware
```

### Monitor running loop
```bash
tail -f local-agents/reports/auto_loop.log
cat docs/leaderboard.md                     # version-by-version scores
```

---

## Directory Map

```
local-agents/
  agents/             10 specialized agents + router + distributed state
  orchestrator/       v1→v100 loop, supervisor, auto-upgrade, resource guard
  tasks/              100-task benchmark suite (7 categories, 100 tasks)
  benchmarks/         Frustration research pipeline (Reddit/HN/Blind)
  dashboard/          FastAPI + WebSocket live dashboard (port 3001)
  registry/           Agent versions + benchmark scores (source of truth)
  agent_runner.py     Core Ollama iterative loop
  opus_runner.py      Opus 4.6 comparison via claude CLI
  deploy.py           Deploy Nexus to any project in 5 minutes

docs/
  repo_map.md         Full directory map with ownership rules
  agent_playbook.md   Step-by-step guide for any agent entering repo
  local_agents_setup.md  Full setup reference
  leaderboard.md      Auto-updated benchmark scores per version

~/local-agents-work/  ALL agent file outputs (BOS — never project root)
local-agents/reports/ Runtime logs (gitignored)
```

---

## Self-Improve Loop

```
v1: Run 100 tasks → score each (static + dynamic execution) → find top 3 failure patterns
    → auto-inject targeted prompt fix → A/B test (5 sub-agents each)
    → if fix wins by ≥5pts → commit permanently to agent file

v2: Same loop. New prompts. Better scores.

v100: Nexus beats Opus 4.6 across all 7 categories. System is done.
```

**8 failure patterns detected + auto-fixed:**
`truncated_code` · `placeholder_path` · `missing_assertions` · `syntax_error`
`stub_functions` · `no_main_guard` · `hallucinated_import` · `wrong_command`

---

## 10 Specialized Agents (Layer 3)

| Agent | Handles | File |
|-------|---------|------|
| Executor | code_gen, bug_fix | `agents/executor.py` |
| Planner | task decomposition | `agents/planner.py` |
| Reviewer | quality scoring | `agents/reviewer.py` |
| Debugger | error diagnosis | `agents/debugger.py` |
| Researcher | code search | `agents/researcher.py` |
| Benchmarker | gap analysis | `agents/benchmarker.py` |
| Architect | scaffold, arch, e2e | `agents/architect.py` |
| Refactor | code transformation | `agents/refactor.py` |
| Test Engineer | pytest generation | `agents/test_engineer.py` |
| Doc Writer | documentation | `agents/doc_writer.py` |

---

## 100-Task Benchmark Suite

| Category | Tasks | Routed to |
|----------|-------|-----------|
| code_gen | 25 | executor |
| bug_fix | 20 | executor |
| tdd | 20 | test_engineer |
| scaffold | 15 | architect |
| refactor | 10 | refactor |
| arch | 5 | architect |
| e2e | 5 | architect |

---

## Claude Hard Guardrails

```
Before ANY Claude rescue call (checked in _check_claude_rescue_eligible):
  1. Task failed 3+ times with different approaches?
  2. Rescue count still < 10% of total tasks?
  3. Category is rescue-eligible (not research/doc)?

Per call: 200-token hard cap. Agent prompt upgrade only. Never fixes tasks.
Budget logged: reports/claude_token_log.jsonl
```

---

## Resource Limits

| Threshold | Action |
|-----------|--------|
| RAM 80% | Stop spawning new agents |
| RAM 85% | Kill lowest-priority agent |
| CPU 90% | Single agent at a time |

---

## Key Files — Source of Truth

| File | What it controls |
|------|-----------------|
| `local-agents/agents/config.yaml` | Model, timeouts, quality threshold |
| `local-agents/registry/agents.json` | Agent versions, capabilities, scores |
| `docs/repo_map.md` | Directory ownership and write rules |
| `docs/agent_playbook.md` | Safe operation guide for any AI agent |
| `docs/leaderboard.md` | Auto-written benchmark scores |
| `AGENTS.md` | Runtime rules |
| `CLAUDE.md` | AI session rules |

---

## Branch Protection

- Never commit directly to `main` — feature branches + PRs only
- PR must pass `Validate Runtime` CI before merge
- Run `bash scripts/merge_gate.sh "$PWD"` before any merge
