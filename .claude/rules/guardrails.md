# Anti-Hallucination Guardrails

## Authority (User-Granted)
- **Commit, push, merge, PR comments**: Execute. Do NOT claim "requires human authorization." Only ask when you lack credentials. Otherwise: run. Stop for nothing.
- **Allow list = execute, no permission ask** — If a command, tool, or action is in the allow list (allowedCommands, branchPermissions, safe-command whitelist): execute it. Never ask "Can I run X?" or "Do you want me to X?" when X is allowed. Execute; report.

## Critique Rules
- **No rubber-stamp** — PR comments must list what was verified. Never "PASS" alone. Look for fails, BLOCK on real issues. See `extreme-critique` skill.
- **Thorough before merge** — End-to-end checklist. All flows tested. Edge cases. No shortcuts.

## Hard Rules (Branch Workflow)
- **Commit precheck** — Before every `git commit`, run `bash .claude/hooks/commit-precheck.sh`. Do NOT commit task breakdowns, progress dashboards, implementation reports, or other non-feature files. Only feature code and templates. See `commit-precheck` skill.
- **No direct main (HARD)** — No commits go directly to main. Everything—operational or product features—goes through peers (PR review). Zero exceptions. See `no-direct-main` skill.
- **All changes through branches** — If on main, run `git checkout -b feature/<name>` first. All commits go to feature/*. Merge to main only via PR.
- **Small commits, small PRs** — One small change per commit. Each PR = small iteration of one feature. No big changes. Rollback = revert that feature only, not the whole project.
- **Product-centric naming** — Branch and commit names must reflect core product and use cases (diagnosis, pipeline, api, evidence, ui). Do NOT use rule/process names (e.g. consensus-gates, ten-pass). See `naming-convention-product` skill.
- **No merge until 100% green** — Never merge until: local npm test pass; all CI jobs pass; QA 100%; confidence with evidence in .claude/CONFIDENCE_SCORE.md. Block merge if any fails.
- **No merge without consensus** — Multiple comments (2+ from skills, agents, sub-agents, reviewers). 100% approval. See `consensus-gates` skill.
- **Do NOT rush to merge** — Reviewers comment, push back, recommend tests. Merge only when reviewers recommend + CI + recommended tests pass.
- **Clean up after merge** — After PR merges, delete local and remote feature branch. See `branch-cleanup` skill.
- **No idea/project/task without consensus** — Do not create ideas, projects, or tasks without consensus.

## Proof Requirements
- **Never invent files** - only read/edit files that exist or are explicitly requested
- **Never invent APIs** - only call endpoints that are documented in code
- **Never invent test results** - only claim tests pass after running them
- **Never invent env vars** - only reference vars set in .env or package.json
- **Never invent user behavior** - only describe what the UI actually shows
- **Never invent screenshots** - only reference files on disk
- **Never assume passing checks** - verify in GitHub Actions before claiming success

## Backend–Frontend 1:1 (No Hallucination)
- **UI shows only backend data** — One-to-one relationship. Every field displayed in the UI must exist in the API response or backend contract. No invented fields. No fabricated data.
- **Keep testing** — Run `npm test`, `npm run test:agents`. Verify backend and UI behavior. CX team (Director of CX, Senior CX) BLOCK on mismatch.
- See `backend-frontend-alignment` skill.

## Observed vs Inferred vs Assumed
- **Observed**: "I ran `npm test` and saw 319 tests pass"
- **Inferred**: "Based on the passing tests, the retry logic works"
- **Assumed**: "The API will eventually succeed" (MUST BE MARKED UNKNOWN)

When uncertain, use this format:
```
Observed: [what you ran / read / verified]
Inferred: [conclusion from evidence]
Assumed: [unverified assumption with remaining unknowns]
Risk: [what could go wrong]
```

## Confidence Scoring Rules
- **95-100**: Only when critical workflows pass locally AND in CI
- **80-94**: Code matches plan, tests pass, minor open items documented
- **60-79**: Implemented but some flows untested or assumptions present
- **40-59**: Partial implementation, significant unknowns
- **0-39**: Unverified, no backing evidence

If evidence is missing, confidence MUST drop below 80.
If critical flow is untested, confidence CANNOT exceed 79.

## Evidence Checklist
Before claiming "done", verify:
- [ ] Read the code changes (git diff output)
- [ ] Tests passed locally (`npm test` output)
- [ ] Tests passed in GitHub Actions (workflow run result)
- [ ] Critical workflows tested locally (describe steps)
- [ ] Error cases handled (retry, validation, permissions)
- [ ] Rollback path documented and safe
- [ ] .claude/CONFIDENCE_SCORE.md updated with evidence
- [ ] CHANGELOG.md updated with what changed
- [ ] No regressions in existing tests

## Forbidden Claims
❌ "Should work"
❌ "I believe it will"
❌ "This looks correct"
❌ "Tests probably pass"
❌ "The API endpoint exists" (without checking code)
❌ "Users will see"  (without testing UI)
❌ "The fix is complete" (without evidence)

Allowed Claims:
✅ "Test output shows 319 passing"
✅ "GitHub Actions workflow passed on commit abc123"
✅ "Local testing verified error recovery with retry logic"
✅ "Code diff shows [specific change] to fix [specific issue]"
✅ "Rollback is safe because [specific reason]"

## Verification Flow
1. **Read** actual code, test output, GitHub Actions result
2. **Verify** critical workflow by running it locally
3. **Score** confidence based on evidence checklist
4. **Document** findings in .claude/CONFIDENCE_SCORE.md
5. **Mark unknowns** clearly with [UNKNOWN] prefix

## When Uncertain
If you cannot verify something:
- Mark it as [UNKNOWN]
- Lower confidence score
- Describe what would prove it
- Do not claim it is done

## Updated Guardrails
This file is updated when:
- A mistake, hallucination, or missed test is found
- A repeated feedback pattern appears
- A new verification pattern is discovered
- An assumption turns out wrong

## Examples
**Bad**: "The pipeline will retry on network failure"
**Good**: "I tested pipeline retry by simulating network failure with mock and saw 3 retries before success"

**Bad**: "The UI is production-ready"
**Good**: "Tested locally on localhost:3000 - form submission, loading state, success message, error handling all verified"

**Bad**: "Tests pass in CI"
**Good**: "GitHub Actions run #123 on commit abc123def passed 319 tests with 89.87% coverage"
