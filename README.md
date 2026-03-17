# Local Agent Runtime

`local-agent-runtime` is a reusable local-only coding assistant runtime. It runs a multi-role Ollama team against a target repository, tracks progress in real time, creates checkpoints before risky work, enforces machine limits, and auto-runs review at the end of task commands.

It is designed to behave like a local coding session launcher for repeated use across projects, without depending on paid model APIs.

## What It Includes

- Interactive local CLI session
- `local-codex` and `local-claude` launchers (do not shadow codex/claude/cursor)
- Multi-role model team with weighted progress bars
- Checkpoint and restore workflow
- Auto-review at the end of task runs
- Technical QA suite
- Non-technical user acceptance suite
- Runtime self-heal for stale lock and session issues
- Release gate that combines heal, QA, UAT, and final acceptance
- Common-plan-first orchestration with shared planner handoff
- SGLang integration for server launch, gateway routing, chat, embeddings, reranking, and scale pipelines
- Private local tool registry kept out of tracked git state

## Installed Local Models

This runtime currently uses the local Ollama models installed on this machine:

- `deepseek-r1:8b`
- `llama3.2:3b`
- `qwen2.5:3b`
- `gemma3:4b`
- `qwen2.5-coder:7b`
- `nomic-embed-text:latest`

These models are assigned different roles so they work like a team:

- `Researcher` and `Retriever`: `llama3.2:3b`
- `Planner`, `Architect`, `Reviewer`, `Benchmarker`, `QA`, `Summarizer`: `deepseek-r1:8b`
- `Tester`: `qwen2.5-coder:7b`
- `Debugger`, `Optimizer`, `User Acceptance`: `gemma3:4b`
- `Implementer`: `qwen2.5-coder:7b`
- `Embeddings`: `nomic-embed-text:latest`

## Quick Start

Start the local interactive session:

```bash
cd /Users/jimmymalhan/Doc/local-agent-runtime
bash ./Local
```

Use the local agent (only when you explicitly want local Ollama—does not shadow codex/claude/cursor):

```bash
local-codex
local-claude
Local
local-codex "/path/to/project" "review current changes"
local-codex --mode exhaustive "/path/to/project" "explain this repo"
```

**Do not** add this repo to PATH in a way that puts it before your real `codex`, `claude`, or `cursor`—use `local-codex`/`local-claude`/`Local` only when you want the local runtime.

**If typing `codex` still opens the local agent:** Remove this repo from the front of your PATH (in `~/.zshrc` or `~/.bashrc`) or remove any `alias codex=...` that points to this repo.

**If typing `claude` or `cursor` in Cursor chat opens the local agent:** The rules now prioritize session choice—Codex, Claude, and Cursor should open independently. If it still happens, disable the `local-runtime` MCP server: **Cursor Settings → MCP →** toggle off or remove `local-runtime`. That prevents the AI from calling `run_local_pipeline` when you ask for Claude/Codex/Cursor.

## Execution Modes

The runtime supports four modes:

- `fast`: short answers and lightweight repo work
- `balanced`: full team with moderate parallelism
- `deep`: default high-quality mode
- `exhaustive`: slowest and most aggressive local mode

Important note on context:

- The repo exposes an `exhaustive` mode with larger prompt budgets and stronger cross-role critique.
- It does not claim a true 10M-token context window for these current local models, because that is not realistic on this machine.
- Instead, it uses the largest practical local settings that remain stable enough to run repeatedly.

## Resource Limits

All modes stay at `70%` CPU and `70%` memory. The difference between modes is orchestration depth, prompt budget, retries, and how much structured critique the team performs.

`exhaustive` is the most detailed mode, but it still respects the same 70 percent ceiling.

## Core Commands

Inside `bash ./Local`:

```text
/help
/models
/model
/modes
/mode [name]
/team
/plan <task>
/run <task>
/pipeline <task>
/progress
/watch
/live
/tail
/status
/limits
/autopilot
/autopilot start [path]
/autopilot status
/autopilot stop
/autopilot log
/project
/session
/history
/clear
/context
/checkpoint [label]
/restore <checkpoint>
/review
/qa
/uat
/quality
/verify
/heal
/repair
/release
/doctor
/diff
/files <pattern>
/grep <pattern>
/open <path>
/tools
/tool <name> [args...]
/roles
/skills
/workflows
/todo
/todo-progress
/todo-watch
/ledger
/compact
/undo
/copy
/mention <path>
/new
/init
/personality [style]
/debug-config
/mcp
/session-compare <task>
/exit
```

Plain text input is treated as `/pipeline <task>`.

`/todo-progress` and `/todo-watch` read `state/todo.md` and show project/task completion bars directly from the checklist instead of the active model run. They also split work into `local`, `cloud`, `shared`, and `general` lanes so the terminal can track local-agent work separately from cloud-session takeover work.

`/live` now shows a Codex-style working header with elapsed time plus the current local-vs-cloud execution split.

`/session-compare <task>` runs the same local-only task through `local-codex` and `local-claude`, saves both outputs, and writes a compare report into `logs/session-compare-*/report.md` so you can capture feedback before calling the session UX done.

## Agent Autopilot

The repo now includes an explicit background self-upgrade loop for local agents:

- `scripts/start_autopilot.sh`
- `scripts/autopilot_status.sh`
- `scripts/stop_autopilot.sh`
- `scripts/run_auto_upgrade_loop.sh`
- `workflows/workflow-agent-autopilot.md`

This path is for long-running local-only improvement work:

1. discover missing upgrade features
2. add them to `state/todo.md`
3. run the local comparison-and-upgrade loop
4. wait for the active lock to clear
5. keep repeating with auto-review at the end

Start it from the shell:

```bash
cd /Users/jimmymalhan/Doc/local-agent-runtime
bash scripts/start_autopilot.sh /Users/jimmymalhan/Doc/local-agent-runtime
```

Or from inside `bash ./Local`:

```text
/autopilot start
/autopilot status
/autopilot log
/autopilot stop
```

## Common Plan First

Every runtime mode now starts with the same planning pattern:

1. `Researcher` and `Retriever` gather repo context and prior artifacts.
2. `Planner` writes the shared handoff into `state/common-plan.md`.
3. `Architect`, `Implementer`, `Tester`, `Reviewer`, and the rest of the team execute against that common plan instead of re-deciding the task independently.

This is how the local team coordinates faster without drifting.

## SGLang Integration

The repo now includes a broader SGLang layer for scale-oriented local serving:

- `scripts/sglang_server.sh`
- `scripts/sglang_gateway.sh`
- `scripts/sglang_healthcheck.sh`
- `scripts/sglang_chat.sh`
- `scripts/sglang_embeddings.sh`
- `scripts/normalize_retrieval_results.py`
- `scripts/sglang_structured_output.sh`
- `scripts/sglang_ranker.sh`
- `scripts/sglang_scale_pipeline.sh`

These are intended to support a scaled pattern where:

1. retrieval happens locally or in Pinecone
2. candidate payloads are normalized into one ranking shape
3. reranking happens on a dedicated local SGLang path
4. final answer generation stays narrow and high-signal

## What The New Validation Flow Does

### `/heal`

Runs deterministic runtime repair:

- removes stale `state/run.lock`
- resets stale session state
- refreshes the model registry
- refreshes the change-review artifact
- normalizes mentioned-file context

Artifact:

- `logs/runtime-heal-report.md`

### `/verify`

Runs the technical QA suite:

- shell syntax validation
- Python compile validation
- resource-limit verification
- interactive CLI smoke test
- model-backed smoke test

Artifacts:

- `logs/qa-suite-report.md`
- `logs/qa-session-smoke.log`
- `logs/qa-model-smoke.md`

### `/uat`

Runs the non-technical acceptance suite:

- first-run command check
- key slash-command clarity check
- progress and recovery explanation check
- rubric-based output validation

Artifacts:

- `logs/uat-suite-report.md`
- `logs/uat-prompt-1.md`
- `logs/uat-prompt-2.md`
- `logs/uat-prompt-3.md`

### `/repair`

Runs the self-repair analysis loop:

- runtime heal
- QA and UAT artifacts
- current change review
- local repair plan from the reviewer/debugger/optimizer path

Artifact:

- `logs/self-repair-report.md`

### `/release`

Runs the full gate:

1. checkpoint
2. runtime heal
3. technical QA suite
4. non-technical acceptance suite
5. change review
6. final QA + user-acceptance decision

If QA or UAT fails, `/release` triggers the repair path and stops the release.

Artifact:

- `logs/release-gate-report.md`

## Team Progress and Ownership

Use `/team` to see:

- overall task completion %
- remaining task %
- overall project/todo completion %
- each role's weighted share
- each role's current model
- each role's remaining contribution

This is the main answer to "which tool/model is doing what right now."

## Checkpoints and Recovery

Before risky flows, the runtime creates checkpoints under:

```text
<target-project>/.local-agent/checkpoints/
```

Manual commands:

```bash
bash scripts/create_checkpoint.sh <label> <target-repo>
bash scripts/restore_checkpoint.sh <checkpoint> <target-repo>
```

Interactive equivalents:

```text
/checkpoint [label]
/restore <checkpoint>
/undo
```

## Reuse In Other Projects

Point the runtime at another repository:

```bash
local-codex /path/to/project
local-claude /path/to/project
local-codex --mode exhaustive /path/to/project "plan the next refactor"
```

Or launch directly:

```bash
cd /path/to/project
bash /Users/jimmymalhan/Doc/local-agent-runtime/Local
```

## Private Local Tool Registry

The runtime scans local helper scripts and writes the inventory to:

```text
state/private-tool-registry.json
```

That file is ignored by git so your exact local tool setup does not need to be published.

## Current Limits

- The chat session you are reading right now is not the local runtime; this README only describes the terminal runtime inside `local-agent-runtime`.
- The published `local-agent-runtime` copy is intended to be initialized as its own git repository.
- The local model team is strong for local automation, but raw reasoning quality still depends on the four installed models and the machine budget available to Ollama.

## Key Files

- `Local`
- `scripts/start_local_cli.sh`
- `scripts/start_codex_compatible.sh`
- `scripts/local_team_run.py`
- `scripts/repair_runtime_state.py`
- `scripts/qa_suite.sh`
- `scripts/user_acceptance_suite.sh`
- `scripts/self_repair.sh`
- `scripts/release_gate.sh`
- `scripts/review_current_changes.py`
- `scripts/create_checkpoint.sh`
- `scripts/sglang_server.sh`
- `scripts/sglang_gateway.sh`
- `scripts/sglang_healthcheck.sh`
- `scripts/sglang_chat.sh`
- `scripts/sglang_embeddings.sh`
- `scripts/sglang_ranker.sh`
- `scripts/sglang_scale_pipeline.sh`
- `config/runtime.json`
- `state/todo.md`
- `workflows/workflow-idea-to-feature.md`
