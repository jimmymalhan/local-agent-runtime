# Repeatable Commands

## /test-agents
Run signed test agents: APIUseCaseTester, UIUseCaseTester, BackendUseCaseTester, LocalhostE2ETester. Tests localhost, API, UI, backend with use-case matrix. Critical feedback → .claude/local/test-feedback.log. Iterate without user. **Requires server running** (`npm start`).

**Usage**: /test-agents [or run `npm run test:agents`]

**Agents** (signed to skills):
- **APIUseCaseTester** — API/latency, database, auth/5xx, payments, oncall-SRE, CI-flaky, microservices
- **UIUseCaseTester** — /, /orchestration.html, /api-reference.html
- **BackendUseCaseTester** — /health, validation, batch
- **LocalhostE2ETester** — Chaos: invalid JSON, huge payload, timeout

**Output**: Feedback log; BLOCK/HIGH on failures. Auto-iterate on feedback.

## /stack-rank
Run TeamLead + TeamCoordinator to cross-review work and stack rank open items (idea→production→GitHub). They make final calls on priorities. Requires stack-rank-priorities and sales skills.

**Usage**: /stack-rank [or when prioritizing backlog]

**Agents**: TeamLead (final call on delivery), TeamCoordinator (final call on scope/effort). Both use Haiku. Cross-review each other.

## /market-research
Run MarketResearchAgent: research market for the product, identify features needed from competition/trends, add to plan, implement automatically. Founder perspective—keep updating UI and backend based on market research.

**Usage**: /market-research [or "what features from market", "founder wants updates"]

**Flow**: ProductScout → MarketResearcher (WebSearch) → PlanInjector (checklist) → AutoExecutor (plan-and-execute). No wait. Implement automatically.

## /full-cycle-automation
Run the complete automation loop: branch cleanup → PR comments → merge → learn from mistakes → upgrade skillset.

**Usage**: /full-cycle-automation [|resume]

**Process**:
1. **Branch cleanup** — Delete merged branches, close abandoned PRs (branch-cleanup skill, 5 phases)
2. **PR comments** — Ten-pass critiques post to PRs (per-agent identity)
3. **Merge** — When 10 comments + consensus, merge and delete branch
4. **Learn** — skills-self-update adds lessons from fixes/failures
5. **Upgrade** — repository-audit-to-skillset updates skills from repo evidence

**Output**: Summary of each phase. All automatic; no approval gates.

## /plan
Create work breakdown before implementing.

**Usage**: /plan [task description]

**Process**:
1. Read CLAUDE.md and .claude/CONFIDENCE_SCORE.md
2. Understand existing architecture
3. Break work into small, testable units
4. Identify critical flows
5. Plan review and QA steps
6. Define rollback path
7. Get user approval before coding

**Output**: Work breakdown with:
- Tasks in order
- Critical flows
- Review checklist
- QA checklist
- Rollback steps

## /execute-ui
Implement UI changes with proof.

**Usage**: /execute-ui [feature]

**Process**:
1. Use /plan first
2. Check .claude/rules/ui.md standards
3. Build the UI
4. Test locally on http://localhost:3000
5. Verify all states (loading, error, success, empty)
6. Check accessibility
7. Verify business language (no technical terms)
8. Run npm test (ensure no regressions)
9. Update .claude/CONFIDENCE_SCORE.md with evidence

**Evidence Required**:
- Screenshots or manual testing notes
- Test output (npm test)
- Browser console clean (no errors)
- Accessibility checks passing

## /execute-backend
Implement backend changes with proof.

**Usage**: /execute-backend [feature]

**Process**:
1. Use /plan first
2. Check .claude/rules/backend.md standards
3. Add validation, retries, timeouts, logging
4. Write tests (unit, integration, error cases)
5. Test critical workflows
6. Run npm test (100% passing)
7. Verify coverage thresholds
8. Run npm run test:ci (CI simulation)
9. Update .claude/CONFIDENCE_SCORE.md with evidence

**Evidence Required**:
- Test output: "319 passing, 973 total"
- Coverage: ">85% critical modules"
- GitHub Actions simulation passing
- Error cases tested and passing

## /score-confidence
Update .claude/CONFIDENCE_SCORE.md with evidence.

**Usage**: /score-confidence

**Process**:
1. Gather evidence:
   - npm test output
   - npm run test:ci output
   - Manual testing results
   - Code review findings
2. Document unknowns
3. Check critical flows tested
4. Calculate confidence score (0-100)
5. Update .claude/CONFIDENCE_SCORE.md
6. Explain reasoning

**Output**: Updated confidence ledger with:
- Test results
- Coverage metrics
- Critical flows verified
- Unknowns listed
- Confidence score + reason

## /map-repo
Understand codebase structure.

**Usage**: /map-repo

**Output**: 
- Key files and directories
- Architecture overview
- Test structure
- CI/CD setup
- Build commands

## /test-critical-flows
Verify critical workflows work end-to-end.

**Usage**: /test-critical-flows

**Critical Flows** (from CLAUDE.md):
1. Request intake → API call → Response
2. Pipeline execution → 4 agents → Results
3. Error recovery → Retry → Success
4. Permission check → Validation → Result
5. Audit logging → Immutable trail → Retrieval
6. Failure handling → Error message → Recovery

**Process**:
1. npm start (run server)
2. Test each flow:
   - Happy path
   - Error case
   - Recovery
3. Document results
4. Update .claude/CONFIDENCE_SCORE.md

## /github-test
Simulate GitHub Actions locally.

**Usage**: /github-test

**Process**:
1. npm run test:ci
2. Check output for:
   - All tests passing
   - Coverage thresholds met
   - No errors
3. View coverage report
4. Push to main (GitHub Actions runs automatically)

## /check-proof
Verify all proof requirements before merge.

**Usage**: /check-proof

**Checklist**:
- [ ] npm test passes locally
- [ ] npm run test:ci passes
- [ ] Coverage ≥ 60% global
- [ ] Manual testing completed
- [ ] .claude/CONFIDENCE_SCORE.md updated
- [ ] CHANGELOG.md updated
- [ ] No unknowns without [UNKNOWN] mark
- [ ] Rollback path documented
- [ ] Ready to merge

## /project-governance-template
Apply the governance template to this or another project. Portable template from user prompts.

**Usage**: /project-governance-template [apply | list | customize]

**Apply**: Copy org-chart, org-feedback-loop, commit-precheck, backend-frontend-alignment, stakeholder-feedback, consensus-gates to target project. See `.claude/TEMPLATE_APPLY.md`.

**List**: Show all template components (skills, hooks, rules).

**Customize**: Show variables to replace (PROJECT_NAME, ROADMAP_FILE, TEAM_SIZE, CX_TEAM_SIZE, DONE_CONDITION).

**User prompts captured**:
1. Org chart 50+ roles, feedback, pushbacks, automate until roadmap done
2. Clean PRs: no task breakdowns, commit-precheck, only feature files
3. README: exact status, roadmap, What's Next, keep updating
4. CX team 15: stakeholder yes on products, features, tasks, milestones, reviews, push; backend-frontend 1:1
5. Template for other projects

## /rollback
Safely revert changes.

**Usage**: /rollback [commit]

**Process**:
1. git revert [commit] (creates new commit)
2. Or: git reset --hard [previous-commit]
3. Run npm test
4. Verify system works
5. Update .claude/CONFIDENCE_SCORE.md

**Note**: Prefer revert (leaves history) over reset (destructive)
