# Workflow: Agent Autopilot Upgrade Loop

This workflow is for the local agents to keep improving the runtime without waiting for a manual one-shot prompt each time.

## Goal

Keep the local-only runtime improving in a loop:

1. check what already exists
2. create a common plan
3. split work across roles and sub-agents
4. patch or update only what is missing
5. run review and validation
6. add the next gap to the upgrade roadmap
7. repeat under the 70 percent CPU and memory budget

## Lead and Sub-Agent Flow

1. **Researcher + Retriever** run first in parallel.
   They map repo state, scan docs, scripts, skills, workflows, prior artifacts, and external grounding already stored in the repo.
2. **Planner** writes `state/common-plan.md`.
   It must say what already exists, what can be reused, which streams can run in parallel, and what the validation path is.
3. **Architect + Implementer** run next.
   They turn the plan into concrete local changes, file paths, commands, and scale-path decisions.
4. **Reviewer + Debugger + Optimizer + Benchmarker** critique the draft.
   They must call out hallucinated paths, weak commands, poor coordination, memory-limit risks, and where the local stack still trails a stronger cloud reasoning model.
5. **QA + User Acceptance** decide whether the result is technically correct and understandable.
6. **Summarizer** publishes the user-facing answer.
   It must answer yes/no questions directly and keep repo facts separate from recommendations.

## Scale Path

When the task needs larger knowledge or ranking throughput:

1. retrieve broad candidates from local retrieval or Pinecone
2. normalize payloads into one candidate shape
3. rerank candidates on the dedicated local SGLang ranker
4. keep only the top-ranked passages
5. feed that reduced context into the local role pipeline

This preserves answer quality while avoiding an oversized final prompt.

## Resource Rules

1. Keep CPU and memory at or below 70 percent.
2. Use `OLLAMA_NUM_PARALLEL=3` and `OLLAMA_MAX_LOADED_MODELS=3` unless the hard memory governor changes those values.
3. If the live memory snapshot exceeds the target, the next hardening step is to pause, serialize, or downgrade active stages instead of continuing to oversubscribe memory.

## Commands

Start the background autopilot loop:

```bash
cd /Users/jimmymalhan/Doc/local-agent-runtime
bash scripts/start_autopilot.sh /Users/jimmymalhan/Doc/local-agent-runtime
```

Check status:

```bash
bash scripts/autopilot_status.sh
```

Stop it:

```bash
bash scripts/stop_autopilot.sh
```

Inside the local CLI:

```text
/autopilot start
/autopilot status
/autopilot log
/autopilot stop
/live
/review
```

## Validation

1. Auto-review runs at the end of task commands.
2. `scripts/qa_suite.sh` validates shell, Python, resource limits, and CLI smoke behavior.
3. `scripts/user_acceptance_suite.sh` validates non-technical clarity.
4. `scripts/release_gate.sh` creates a checkpoint, heals stale runtime state, runs QA, runs UAT, runs review, and triggers self-repair on failure.
5. Every iteration should append newly discovered quality gaps to `state/todo.md`.
