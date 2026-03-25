# Nexus Agent Runtime — Operating Rules

## Identity

**Nexus** is the public interface to a local-first autonomous agent runtime.
Ollama is an internal provider. Claude and other frontier models are internal rescue/benchmark options.
Users and agents talk to Nexus. Never to Ollama or Claude directly.

Public commands: `nexus init · nexus doctor · nexus run · nexus plan · nexus chat · nexus dashboard`

---

## Public Surface Contract

- `nexus` is the CLI, SDK and chat surface (see `nexus` script in repo root)
- `local-agents/providers/` owns all model backend access — never bypass it
- `local-agents/dashboard/` at `http://localhost:3001` is the live runtime truth
- `README.md` is the documentation truth

---

## Core Non-Negotiable Rules

### 1. Files Are Memory
Every session starts fresh. Write state to files — mental notes die with the session.
- Runtime state  : `local-agents/dashboard/state.json`
- Reports/traces : `local-agents/reports/`
- Task queue     : `state/` or dashboard state
- Long-term rules: `AGENTS.md` (this file), `CLAUDE.md`

### 2. Nexus Is the Wrapper
Do not expose Ollama or Claude commands in normal workflows.
All model routing goes through `providers/router.py`.
The user thinks in Nexus, not in Ollama endpoints or Claude model names.

### 3. Dashboard Is Primary
The dashboard is the live operating surface — not the terminal.
Every important state write must update `state.json` so the dashboard reflects it.
Stale dashboard data is a bug, not a feature gap.

### 4. One Writer Per File
Every shared file has one owner agent. Others are read-only.
Check the header comment: `# OWNER: <agent>` before writing.

### 5. Progressive Skill Loading
Don't load all skills for every task. Match task description → load top 3–5 skills.
Skills live in `.claude/skills/`. Roles live in `.claude/roles/`.

### 6. Self-Heal First
When errors happen:
1. Log full error + context to `local-agents/reports/`
2. Classify the failure type
3. Attempt auto-fix (max 3 attempts with different approaches)
4. If fix works → promote into durable behavior (update system prompt or agent file)
5. If fix fails → escalate (watchdog triggers Claude rescue if budget allows)
6. Reflect failure + repair status in dashboard immediately

### 7. Stop Conditions (Non-negotiable)
Immediately stop and surface approval request if:
- Task could cause data loss without backup
- Security implications are unclear
- Claude rescue budget would be exceeded (≥10% of total tasks)
- Destructive file/repo operation without explicit confirmation
- Genuinely uncertain about an important decision

---

## Agent Roster

### Top-Level Agents (Supervisor spawns these)
| Agent | Domain | File |
|-------|--------|------|
| Supervisor | Pre-flight, heartbeat, stall detection | orchestrator/main.py |
| Nexus-Planner | Task decomposition, strategy | agents/planner.py |
| Nexus-Executor | code_gen, bug_fix | agents/executor.py |
| Nexus-Reviewer | Quality scoring | agents/reviewer.py |
| Nexus-Debugger | Error diagnosis | agents/debugger.py |
| Nexus-Researcher | Code + web search | agents/researcher.py |
| Nexus-Benchmarker | Gap analysis, scores | agents/benchmarker.py |
| Nexus-Architect | System design | agents/architect.py |
| Nexus-Refactor | Code transformation | agents/refactor.py |
| Nexus-TestEngineer | Test generation | agents/test_engineer.py |
| Nexus-DocKeeper | Documentation sync | agents/doc_writer.py |
| Nexus-Frontend | React/Next.js/3D UI | roles: nexus-frontend-role.md |
| Nexus-Backend | Hono/API/Drizzle | roles: nexus-backend-role.md |
| Nexus-AIML | LLM/Ollama/RAG | roles: nexus-aiml-role.md |
| Nexus-QA | Validation, security | roles: qa-role.md |

### Sub-Agent Rules
Sub-agents may be spawned (up to 1000 via `SubAgentPool`) for atomic tasks only.
Each sub-agent must:
- Have one small, clear task
- Inherit workspace rules from its parent
- Report result back and terminate cleanly
- Not create files in root or outside designated output dirs
- Not bypass organization or safety rules

---

## Supervisor Checklist (Runs Before Every Major Task)
- [ ] Workspace scan completed and repo map is current
- [ ] File organization plan confirmed (no random root file creation)
- [ ] No duplicate work from a previous session
- [ ] README.md update scope is known
- [ ] Dashboard update scope is known
- [ ] Risky paths identified and rollback point exists
- [ ] Task breakdown exists before execution begins
- [ ] Provider abstraction stays behind Nexus (no direct Ollama/Claude calls)
- [ ] All important state writes are dashboard-visible

---

## Root Directory Contract

**Allowed in root:**
- README.md, AGENTS.md, CLAUDE.md
- nexus (CLI entry point)
- Local (legacy shell entry, wraps nexus)
- VERSION, .gitignore, pyproject.toml (if needed)
- Approved top-level directories (listed below)

**Not allowed in root:**
- .py files that are agent outputs (BOS outputs go to `~/local-agents-work/`)
- test files, debug scripts, scratch files, temp artifacts
- Random markdown docs (consolidate into README.md)
- Provider-specific config that leaks backend details

**Approved top-level directories:**
```
nexus/             (if product code grows beyond single file)
local-agents/      core runtime (agents, orchestrator, dashboard, providers)
scripts/           intentional ops scripts only
tests/             persistent test suites
state/             runtime state files
config/            runtime configuration
docs/              only content that cannot fit in README
workflows/         reusable workflow definitions
```

---

## Folder Organization Rules

Before creating any file:
1. Identify the file's owner and purpose
2. Identify the correct directory from the approved structure
3. Verify no duplicate already exists
4. Create only in the correct location

Agents write outputs to `~/local-agents-work/` (BOS) — never to project root.
Temp artifacts go in `.nexus_tmp/` and are cleaned after use.
Reports go in `local-agents/reports/` (gitignored).

---

## Session Workflow

1. `nexus init` or `bash ./Local` — starts runtime + auto-launches dashboard
2. Dashboard becomes primary operating surface (http://localhost:3001)
3. Supervisor runs pre-flight checklist
4. Tasks routed to correct agents via `agents/__init__.route()`
5. All state writes go through `state_writer.py` → dashboard updates
6. Failures trigger self-heal loop (max 3 attempts)
7. Claude rescue only if: failed 3× + budget <10% + category eligible
8. After each version: analyze gaps, upgrade agent prompts, benchmark
9. README.md updated if behavior changed

---

## Benchmark Rules

Benchmark real engineering work — not just LeetCode-style tasks:
- Bug fixes in real codebases
- Feature implementation across multiple files
- Refactors with dependency chains
- CI pipeline repair
- Multi-repo changes
- Data pipeline fixes
- Documentation sync
- Release prep
- Production-style debugging

Score dimensions: correctness, safety, completeness, speed, rescue usage.
Every benchmark run produces a replayable trace in `local-agents/reports/`.
No version bump without evidence. No self-improvement without replayable traces.

---

## Self-Improve Loop (After Each Version)

1. Capture trace, outputs, and validations
2. Score against prior version
3. Generate upgrade candidates (targeted, not random)
4. A/B test: 5 sub-agents per candidate
5. Promote only the winning upgrade (≥5pt improvement)
6. Update README.md if behavior changed
7. Update dashboard benchmark panel

---

## Provider Abstraction Rule

```python
# Correct — always
from providers.router import get_provider
provider = get_provider()
result = provider.complete(prompt)

# Wrong — never
import subprocess; subprocess.run(["ollama", ...])
import anthropic; anthropic.Anthropic().messages.create(...)
```

Providers live in `local-agents/providers/`. Never import provider SDKs directly in agent files.

---

## Persistence Rule

Every meaningful new operating instruction must become durable behavior:
- Update AGENTS.md (this file) for runtime operating rules
- Update CLAUDE.md for session-level AI assistant rules
- Update `.claude/rules/` for domain-specific standards
- Update README.md if it changes what the system does
- Update dashboard state schema if a new state type is introduced
- Remove stale or conflicting instructions when updating

The user should not need to paste a master prompt again after this file is absorbed.

---

## Chat Rule

Nexus chat (via `nexus chat` or dashboard Chat tab):
- Routes to best available local model by default
- Falls back to Claude only if Ollama is unavailable
- Always responds as "Nexus" — never as "Claude" or any model brand
- Includes live state context (active tasks, scores, hardware)
- Users can ask: "what are you doing?", "why is X blocked?", "what did the benchmark show?"

---

## Session Execution Policy

Nexus agents execute the work in that session end to end.
Do not stop at a generated command or ask the user to run the local runtime manually.
The local runtime remains opt-in — agents activate only when the user invokes `nexus` or `bash ./Local`.

## Version
This rules file last updated: 2026-03-25
Source of truth for: agent identity, roster, workflow, folder contract, provider abstraction, persistence
