# TODO List

## Runtime Consolidation + Session Bar

- [x] [shared] Move all remaining workspace dependencies onto `local-agent-runtime`.
- [x] [local] Import or retire the last useful legacy state/log/checkpoint artifacts before deleting the retired legacy repo copy.
- [x] [local] Make todo progress lane-aware for local, cloud, shared, and general work.
- [x] [local] Add a reproducible session compare flow for the same task across local-codex and local-claude.
- [x] [shared] Tighten local-agent prompts and skills so every run starts from a common plan and skill-based parallel pickup.
- [x] [cloud] Capture user feedback from same-task session comparisons and iterate before marking the session UX done.

## Active Work

- [x] Create a concrete plan for renaming the runtime around its actual feature set and preserving launcher compatibility.
- [x] Rename the runtime identity to `local-agent-runtime` across the main docs, scripts, and MCP setup.
- [x] Tighten local summarizer/session guidance so answers read more like a pragmatic Codex-style CLI session.
- [x] Create the new sibling repo directory `local-agent-runtime`, initialize git, and push it to GitHub.
- [x] Run focused validation and a local-agent feedback pass on the new interaction style before handoff.
- [ ] Fix the remaining local model execution gap after preflight: progress is now visible, but the first role can still fail to start on this machine during some self-review runs.
- [x] Add a multi-role local CLI with progress bars, checkpoints, and auto-review.
- [x] Add `/team`, `/qa`, `/uat`, `/quality`, `/verify`, `/heal`, `/repair`, and `/release`.
- [x] Add a scripted QA suite for shell, Python, resource-limit, and session smoke validation.
- [x] Add a scripted non-technical user acceptance suite.
- [x] Add deterministic runtime self-heal for stale locks, stale session state, and artifact refresh.
- [x] Add common-plan-first coordination and a shared planner handoff artifact.
- [x] Expand SGLang integration with chat, embeddings, gateway, healthcheck, and scale-pipeline wrappers.
- [x] Auto-derive Pinecone query vectors from local SGLang embeddings when available.
- [ ] Re-run the full release gate once no other long-running local task is holding the runtime lock.
- [x] Initialize git for `local-agent-runtime` and publish it as a private reusable template.
- [x] Create, merge, and clean up feature PRs for the runtime rename, status UX, CI, and checkpoint migration work.

## Optimization Sprint

- [ ] [shared] Plan the local-runtime hardening pass around project-only checkpoints, common-plan-first coordination, and faster takeover on stalls.
- [ ] [local] Fix checkpoint scope so only the target project is checkpointed and the runtime repo never self-checkpoints.
- [ ] [local] Tighten the lead/common-plan/skill-routing prompt contract so local agents coordinate like a Codex-style CLI session.
- [ ] [local] Reduce idle waiting: stop stalling on resource pressure, downgrade or hand off sooner, and record the runtime lesson.
- [ ] [shared] Validate the updated live status view so it shows current focus, local-vs-cloud split, and product/business progress from `state/todo.md`.
- [ ] [cloud] Run the same action through local-codex and local-claude, capture feedback, and iterate before marking the sprint done.

## GitHub Governance Sprint

- [ ] [shared] Plan the GitHub governance pass: protect `main`, require real checks, and keep the local runtime honest about repo governance state.
- [ ] [local] Add a runtime-visible governance check so `/governance` reports whether `main` is protected or blocked by plan limits.
- [ ] [cloud] Create and merge a governance PR with CI validation after the branch protection path is either applied or explicitly blocked by GitHub plan limits.
- [ ] [business] Keep the branch protection blocker visible in the runtime until the repository plan supports private-repo protections or the repo visibility changes.

## Claude/Codex Sessions + Local Agents (in progress)

- [x] Plan: session-first flow, claude/codex run local agents after spinning up
- [x] Restore script: `bash scripts/restore_local_agent_claude_codex.sh`
- [x] Persona welcomes: Claude (local), Codex (local) on session startup
- [x] /feedback command → `state/feedback-sessions.md`
- [x] **User test**: run `claude` and `codex`, same action in both, use `/feedback <text>`
- [x] **Iterate** based on feedback before calling done

See `state/plan-claude-codex-sessions.md` for full plan.

## Claude/Codex Sessions + Local Agents (in progress)

- [x] Plan, restore claude/codex → local agents, session-first flow
- [x] **User test:** Run `claude` and `codex` in separate terminals, same action in both, use `/feedback <text>`
- [x] Iterate from `state/feedback-sessions.md` until approved
- See `state/plan-claude-codex-sessions.md` for full plan.

## Current Focus

- [ ] Verify `scripts/release_gate.sh` end to end after the active local comparison task finishes.
- [ ] Review model/profile tuning after stabilizing the new 70% CPU and memory ceilings.
- [ ] Add a deeper SGLang smoke test once a local SGLang server is available on the machine.
- [ ] Add a private git template flow only if the destination should stay non-public.
- [ ] Tighten planner and summarizer outputs so they never cite non-existent files, fake limits, or stale repo assumptions.
- [x] Add a live status stream command that prints the current task percent, active roles, and remaining work every few seconds without starting a second model run.
- [x] Add an explicit background autopilot workflow and CLI entrypoints so local agents can keep self-upgrading without manual loop glue.
- [ ] Enforce the 70 percent memory ceiling during active model execution; `/live` currently shows the planner stage can still drive system memory above the target.

## Local Model Upgrade Roadmap (to exceed Cursor's highest-reasoning model)

**Gap: Cursor's model is ~55–65% ahead** on hardest reasoning, long-context, and multi-step coding tasks vs current 3B–7B local models.

- [ ] **Upgrade Implementer** to qwen2.5-coder:14b or deepseek-coder:33b (largest local model that fits RAM).
- [ ] **Upgrade Reviewer/Summarizer** to 14b+ models for stronger quality judgments and final answers.
- [ ] **Add RAG pipeline** with Pinecone or local vector DB for retrieval-augmented context at scale.
- [ ] **Integrate SGLang** for high-throughput inference (LinkedIn-style ranking/scoring at scale).
- [ ] **Increase num_ctx** to 128K+ for models that support it (e.g. qwen2.5 72b, deepseek 33b).
- [ ] **Add speculative decoding** for faster token generation without quality loss.
- [ ] **Skill upgrades**: richer role prompts, chain-of-thought scaffolding, concrete benchmarks per stage.
- [ ] **MCP tool extensions**: add local search, file-grep, and RAG query tools for sub-agents.
- [ ] **Parallel sub-agent pools**: run multiple implementer/reviewer instances in parallel where hardware allows.
- [ ] **SGLang server integration**: wire server launch flags, OpenAI-compatible APIs, structured outputs, embeddings, reasoning parsers, tool parsers, routing/gateway, speculative decoding (see README SGLang integration).
- [ ] **Bootstrap TEAM_MODELS**: add qwen2.5-coder:14b, deepseek-coder:33b to bootstrap pull list for install.
- [ ] **Feedback loop**: implement feedback/prompt-log.md and feedback/workflow-evolution.md for pattern detection and skill evolution.
- [ ] **Skill versioning**: create implement-feature-v2.md, benchmark-against-quality-v2.md with chain-of-thought scaffolding.
- [ ] **Hooks and subagents**: offload heavy ops (test filtering, file grep) to hooks to reduce context and token use.
- [ ] **Token/stats monitoring**: add /cost or /stats to track token usage and refine prompts.
- [ ] **Pinecone embed + retrieve**: wire embeddings API to Pinecone for RAG retrieval at scale.
- [ ] **Reasoning parsers**: add structured output parsing for chain-of-thought and step-by-step reasoning extraction.
- [ ] **MoE or mixture-of-experts routing for task-specific model selection**
- [ ] **Continuous batching for SGLang to maximize GPU utilization**
- [ ] **KV cache optimization for 128K+ context without OOM**
- [ ] **OpenAI-compatible /v1/chat/completions gateway in front of Ollama**
- [ ] **Structured output (JSON schema) enforcement for implementer/reviewer**
- [ ] **Chain-of-thought few-shot examples in planner and architect prompts**
- [ ] **Embedding model (nomic-embed) for RAG chunk indexing**
- [ ] **Reranker model for RAG retrieval quality (e.g. BAAI/bge-reranker)**
- [ ] **Adaptive temperature per role based on task uncertainty**
- [ ] **Model fallback chain: 14b->7b->3b on OOM or timeout**
- [ ] **Prefill-only ranker path**: add a scoring-only SGLang service for rerank/rank tasks instead of running chat-style completions.
- [ ] **Batch tokenization + shared-prefix cache**: preserve batch shape and reuse KV/prefix state across repeated ranking prefixes.
- [ ] **Namespace-per-tenant Pinecone layout**: isolate each customer/domain into its own namespace and split different workloads across different indexes.
- [ ] **Selective metadata indexing**: index only filterable fields to reduce Pinecone build/query overhead.
- [ ] **Hybrid retrieval + hosted/local rerank switch**: support dense+sparse retrieval and then rerank locally or with Pinecone-hosted rerankers.
- [ ] **Hierarchical memory for effective 10M context**: add rolling summaries, retrieval shards, and map-reduce context packing because a literal 10M local context window is not realistic on current hardware.
- [ ] **Quality benchmark corpus**: keep a fixed repo-aware eval set with pass/fail thresholds for plan accuracy, file-path correctness, and non-hallucinated edits.
- [ ] **Planner factuality gate**: reject any planner/common-plan output that references files, commands, or workflows not present in the current repo snapshot.
- [ ] **Final-answer factuality gate**: add a summarizer check that compares cited paths and commands against real repo files before publishing the answer.
- [x] **Status streaming UX**: add `/live` or `/tail` to stream `state/progress.json` and role transitions in real time from the local session.
- [ ] **Runtime hard memory governor**: pause, serialize, or downgrade model stages when live system memory exceeds the configured ceiling instead of only checking before dispatch.
- [ ] **Grounded answer corpus**: save good local answers plus review feedback and use them as few-shot examples for planner, QA, and summarizer roles.
- [ ] **Quality delta harness**: add a local eval set that compares current local outputs against a stronger reasoning baseline and scores plan accuracy, code correctness, and hallucination rate.
- [ ] **Install larger local coding/reasoning models when hardware permits**: evaluate qwen2.5-coder:14b, qwen2.5:14b, deepseek-coder-v2, or larger reasoning-capable local models under the same 70% budget.
- [ ] **Cross-role critique loop**: let reviewer and benchmarker automatically send one concrete revision request back to planner/implementer before QA when output quality is weak.
- [ ] **RAG source citation enforcement**: require final answers to distinguish repo facts, retrieved docs, and inferred recommendations so scale-path claims stay auditable.
- [ ] **Sub-agent skill pack expansion**: add broader skill families and routing rules so the lead can delegate to more specialized local sub-agents without collapsing back into one generic planner.
- [ ] **Autopilot policy guardrails**: teach the background loop when to stop, checkpoint, escalate, or wait so it does not spin uselessly on stale locks or weak plans.

## Rules

- Check whether the requested work already exists before creating anything new.
- Create or verify a current checkpoint before major workflow changes, restores, or releases.
- Deprecate before deleting. Keep an older version recoverable until the replacement is live.
- Keep private local tool inventory out of tracked git content.
- End implementation flows with an automatic local review pass.
- Prefer realistic local runtime settings over inflated paper limits that degrade reliability.
- [ ] Compare Cursor's highest-reasoning cloud model vs this repo's local Ollama agents for coding tasks. Which is better? If Cursor/cloud is stronger: (1) Recommend and implement specific upgrades to local models, config, skills, and MCP to close the gap. (2) Use up to 70% CPU/memory, scale agents/skills/MCP for parallel coordination so work finishes simultaneously and responses are faster. (3) Design for RAG + Pinecone + SGLang at scale (see https://www.linkedin.com/blog/engineering/ai/scaling-llm-based-ranking-systems-with-sglang-at-linkedin/) - exhaustive option, quick response, no quality compromise. (4) Make local agents coordinate like sub-agents working simultaneously. Be thorough and actionable. Implement upgrades end to end. | agents: researcher,retriever,planner,architect,implementer,tester,reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer | added: 2026-03-16 16:10:44
- [ ] what is the exact local start command and key CLI commands for this repo | agents: researcher,retriever,planner,architect,implementer,tester,reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer | added: 2026-03-16 16:18:54
- [ ] Compare Cursor's highest-reasoning cloud model vs this repo's local Ollama agents for coding tasks. Which is better? If Cursor/cloud is stronger: (1) Recommend and implement specific upgrades to local models, config, skills, and MCP to close the gap. (2) Use up to 70% CPU/memory, scale agents/skills/MCP for parallel coordination so work finishes simultaneously and responses are faster. (3) Design for RAG + Pinecone + SGLang at scale (see https://www.linkedin.com/blog/engineering/ai/scaling-llm-based-ranking-systems-with-sglang-at-linkedin/) - exhaustive option, quick response, no quality compromise. (4) Make local agents coordinate like sub-agents working simultaneously. Be thorough and actionable. Implement upgrades end to end. | agents: researcher,retriever,planner,architect,implementer,tester,reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer | added: 2026-03-16 16:31:50
- [ ] Validate the patched local runtime. Confirm the local-only routing, 70 percent CPU and memory limits, stronger stage model selection, skill-based coordination, and whether auto-review runs. Be concrete and repo-aware. | agents: researcher,retriever,planner,architect,implementer,tester,reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer | added: 2026-03-16 16:31:56
- [ ] Smoke-test the patched local runtime. Verify stronger stage model selection, skill-based coordination, exact local routing, 70 percent CPU and memory limits, and final auto-review. Keep it repo-aware and concise. | agents: researcher,retriever,planner,architect,implementer,tester,reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer | added: 2026-03-16 16:35:37
- [ ] Scan this repo (docs/, config/, scripts/, skills/, README, UPGRADE.md, workflows/, roles/) for features that help local Ollama models exceed Cursor. Lead: assign Researcher+Retriever to scan, Planner to prioritize, Implementer to append new items to state/todo.md under Local Model Upgrade Roadmap. No duplicates. Exhaustive. Follow skills/auto-discover-upgrade-features.md. | agents: researcher,retriever,planner,architect,implementer,tester,reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer | added: 2026-03-16 16:47:03
- [ ] Scan this repo (docs/, config/, scripts/, skills/, README, UPGRADE.md, workflows/, roles/) for features that help local Ollama models exceed Cursor. Lead: assign Researcher+Retriever to scan, Planner to prioritize, Implementer to append new items to state/todo.md under Local Model Upgrade Roadmap. No duplicates. Exhaustive. Follow skills/auto-discover-upgrade-features.md. | agents: researcher,retriever,planner,architect,implementer,tester,reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer | added: 2026-03-16 16:48:07
