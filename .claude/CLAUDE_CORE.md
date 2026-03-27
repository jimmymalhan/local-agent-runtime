# Core Rules — Jimmy Agent Runtime

**Non-Negotiable Standards** (150 lines, loaded every session)

## Authority & Execution
- **Full authority granted**: Execute commits, pushes, merges, PR comments. Do NOT ask "Can I run X?" when action is allowed. Execute; report.
- **Ask only for**: Missing credentials (GH_TOKEN), clarification on ambiguous requirements

## No Direct Main (HARD)
- ✅ Branch workflow: `feature/<name>`, PR review, merge only via GitHub
- ✅ All commits (product or operational) go through peer review
- ❌ Never commit directly to main. Zero exceptions.

## Proof Requirements (No Hallucination)
- ❌ Never invent: files, APIs, test results, env vars, user behavior
- ✅ Read code before modifying. Verify test output before claiming success.
- ✅ Observed vs Assumed: Mark assumptions [UNKNOWN], describe what would prove them

## Confidence Scoring: Evidence Only
| Score | Condition |
|-------|-----------|
| 95-100 | All critical flows tested locally + in GitHub Actions, 90%+ coverage, rollback verified |
| 80-94 | Code matches plan, tests pass, minor unknowns documented |
| 60-79 | Implemented, some flows untested, assumptions present |
| <60 | Incomplete or untested — do not release |

**Merge Gate**: Confidence must be 95+% with evidence in .claude/CONFIDENCE_SCORE.md + local `npm test` pass + all CI green.

## Testing Before Done
- Run `npm test` locally before every commit
- Verify critical workflows: happy path, error handling, retry logic, permissions
- Coverage ≥ 60% global, ≥ 85% for critical modules
- Never merge on CI failure

## Minimal Proof Checklist
- [ ] Code reviewed (git diff)
- [ ] Tests pass locally + in GitHub Actions
- [ ] Critical workflows tested manually or with E2E
- [ ] Error cases covered (validation, timeout, permission denied)
- [ ] .claude/CONFIDENCE_SCORE.md updated with evidence
- [ ] CHANGELOG.md updated

## Small Commits, Clear Naming
- One change per commit (e.g., "fix(api): add validation to POST /diagnose")
- Branch names reflect product (diagnosis, pipeline, api, evidence, ui), not process
- PR = small iteration of one feature, easy to revert

## Observed Facts Only
```
✅ "Ran `npm test`, saw 319 tests pass"
✅ "GitHub Actions #123 passed commit abc123def"
✅ "Tested locally: form submission → error message shown → retry button clicked → success"

❌ "Should work"
❌ "Tests probably pass"
❌ "The endpoint exists" (without checking code)
```

---

## Where to Find Detailed Standards

Reference (not auto-loaded, read as needed):
- `.claude/rules-archive/guardrails.md` — Anti-hallucination details, PR critique, consensus
- `.claude/rules-archive/testing.md` — Test categories, file naming, flaky tests
- `.claude/rules-archive/backend.md` — Production-grade reliability, retries, logging
- `.claude/rules-archive/ui.md` — Desktop-first design, user journeys, states
- `.claude/rules-archive/api.md` — REST error codes, endpoint contracts

Emergency only:
- `.claude/CLAUDE.md` (old, 400+ lines) — deprecated, use CLAUDE_CORE.md instead
