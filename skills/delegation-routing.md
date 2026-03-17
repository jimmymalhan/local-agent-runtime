# Delegation Routing Rules

Maps skill families to roles so the lead agent can delegate to the right sub-agent.

## Routing Table

| Skill Family | Primary Role | Fallback Role | When to Use |
|---|---|---|---|
| Code implementation | implementer | architect | New features, bug fixes, refactors |
| Code review / critique | reviewer | benchmarker | Post-implementation quality gate |
| Test generation | tester | qa | Unit tests, integration tests, E2E |
| Architecture design | architect | planner | System design, dependency analysis |
| Project planning | planner | manager | Task breakdown, prioritization |
| Debugging / root cause | debugger | implementer | Failures, flaky behavior, race conditions |
| Performance tuning | optimizer | implementer | Speed, memory, concurrency improvements |
| Quality benchmarking | benchmarker | reviewer | Compare output against quality bar |
| User acceptance | user_acceptance | qa | Non-technical validation |
| Final summary | summarizer | reviewer | User-facing answer generation |
| Research / discovery | researcher | retriever | Codebase exploration, pattern finding |
| Context retrieval | retriever | researcher | Pull supporting facts, prior session data |
| Executive decisions | ceo, cto, director | manager | ROI, release, architecture calls |
| Operational management | manager | director | Blockers, ownership, fallback decisions |

## Routing Rules

1. **Exact match first**: If a task directly names a role (e.g., "review this code"), route to that role.
2. **Skill keyword match**: Match task keywords against skill families above.
3. **Complexity escalation**: If a 3B model fails on a task, re-route to a role that uses a larger model.
4. **Parallel when independent**: If two skill families are needed and have no data dependency, run both roles in parallel.
5. **Sequential when dependent**: If role B needs role A's output (e.g., reviewer needs implementer output), run sequentially.
6. **Fallback on failure**: If the primary role produces generic or empty output, retry with the fallback role.

## Skill-to-File Mapping

| Skill File | Best Role |
|---|---|
| implement-feature.md | implementer |
| validate-logic.md | reviewer |
| qa-validation.md | qa |
| benchmark-against-quality.md | benchmarker |
| understand-project.md | retriever, researcher |
| generate-architecture.md | architect |
| lead-coordination.md | planner, manager |
| team-orchestration.md | manager, director |
| confidence-scoring.md | reviewer, benchmarker |
| quality-rubric.md | benchmarker, qa |
| change-safety.md | reviewer, tester |
| fast-iteration.md | implementer, optimizer |
| codex-style-output.md | summarizer |
| evidence-proof.md | reviewer, qa |
| counter-analysis.md | debugger, reviewer |
| self-coordination.md | planner |
