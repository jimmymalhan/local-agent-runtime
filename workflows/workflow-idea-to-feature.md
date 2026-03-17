# Workflow: Idea to Feature

This workflow turns a prompt into a local-only multi-role session. It uses the same four installed Ollama models as a coordinated team:

1. **Researcher** maps the repo and names the important entrypoints.
2. **Retriever** pulls prior session history, tool inventory, and relevant artifacts.
3. **Planner** decides what already exists and writes the shared common plan to `state/common-plan.md`.
4. **Architect** shapes the implementation approach and tradeoffs against that shared plan.
5. **Implementer** generates the primary answer or change plan.
6. **Tester** defines exact validation.
7. **Reviewer** looks for regressions and weak assumptions.
8. **Debugger** diagnoses poor output quality or runtime issues.
9. **Optimizer** tightens the workflow for quality, speed, and local ROI.
10. **Benchmarker** compares the result against a strong coding-assistant bar.
11. **QA** performs the technical handoff gate.
12. **User Acceptance** checks the outcome from a non-technical perspective.
13. **Summarizer** produces the final answer.

Operating rules:

1. Check whether the requested capability already exists before creating or changing anything.
2. Create or verify a checkpoint before major changes, restores, or release gates.
3. Deprecate before deleting. Keep the older path recoverable until the replacement is live.
4. Stay local-only in the terminal runtime. The runtime uses Ollama models on the machine and a private local tool registry.
5. Keep CPU and memory at or below 70%; later stages wait when the machine is saturated.
6. Use the SGLang integration when the workload needs a dedicated serving, embedding, reranking, or gateway layer.

Validation path:

1. Run `/heal` or `python3 scripts/repair_runtime_state.py` to clear stale runtime state and refresh artifacts.
2. Run `/verify` or `bash scripts/qa_suite.sh` for shell, Python, resource-limit, and session smoke validation.
3. Run `/qa` for the local technical release readout.
4. Run `/uat` or `bash scripts/user_acceptance_suite.sh` for non-technical expectation checks.
5. Run `/quality` when you want a deeper quality-gap comparison.
6. Run `/repair` to generate a prioritized self-repair plan after failures.
7. Run `/release` for the full heal -> QA -> UAT -> final gate sequence.
8. Run `bash scripts/sglang_scale_pipeline.sh "<query>"` when the task needs retrieval + rerank + answer generation at larger corpus scale.
