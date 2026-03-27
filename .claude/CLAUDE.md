# Meta-Rules: Workflow, Memory & Subagent Strategy

**Purpose:** Guide Claude and subagents on how to work together, use memory, and execute tasks efficiently.

**Full Authority:** User has granted full authority. Commit, push, merge, PR comments—execute. Do NOT say "I can't—requires human authorization." Only ask when you lack credentials (e.g. GH_TOKEN). Otherwise: run. Stop for nothing.

**First Action Every Turn:** Before responding to the user, run: `gh pr list --state open`. For each open PR with <10 ten-pass comments: post comments. If `git status` shows uncommitted changes: create branch, commit, push, create PR, post comments. Do NOT wait for the user to ask. Use hook `open-prs-workflow.sh` (runs on PreToolUse).

## Recommended Workflow: Plan Mode First

### Why Separate Planning from Execution?
- **Plan Mode** (exploration + design) discovers unknowns and validates assumptions before coding
- **Execution** (implementation + testing) implements the plan and verifies with tests—proceeds automatically, no approval gate
- **Verification** (testing + scoring) updates confidence in .claude/CONFIDENCE_SCORE.md with evidence

**Result:** Fewer rework cycles, higher confidence scores, faster delivery.

### Workflow Steps

1. **Enter Plan Mode** (`EnterPlanMode` tool):
   - Explore codebase with Glob, Grep, or Explore agent
   - Understand existing patterns and constraints
   - Design solution approach with alternatives
   - Identify test criteria and acceptance conditions
   - Proceed to implement automatically—do NOT wait for approval

2. **Implement with Verification Criteria**:
   - Code must match plan
   - Write tests that verify critical workflows (happy path, error cases)
   - Run `npm test` locally before committing
   - Commit with clear message linking to plan

3. **Test Before Claiming Done**:
   - Always run tests locally: `npm test` — never ask permission to run tests; just run and report
   - Provide actual test output, not speculation
   - Critical workflows must be tested (no "should work")
   - Update .claude/CONFIDENCE_SCORE.md with evidence

## Auto Memory & CLAUDE.md Integration

### How They Work Together
- **CLAUDE.md** (root): Project-level non-negotiable rules (never invent, retrieve before explaining, etc.)
- **.claude/CLAUDE.md** (this file): Meta-rules for workflow and agents
- **.claude/rules/*.md**: Standards for specific concerns (guardrails, testing, backend, ui)
- **Auto memory (`/Users/jimmymalhan/.claude/projects/.../memory/MEMORY.md`)**: Session-specific context

### Auto Memory Best Practices

**Save to memory:**
- ✅ Stable patterns confirmed across 3+ interactions
- ✅ Key architectural decisions and file paths
- ✅ User preferences and workflow style
- ✅ Solutions to recurring problems
- ✅ Lessons learned from failures

**Never save to memory:**
- ❌ Session-specific context (current task, temp state)
- ❌ Information that duplicates CLAUDE.md or rules
- ❌ Unverified conclusions from reading one file
- ❌ Speculative or incomplete knowledge

**Memory file size limit:** Keep MEMORY.md ≤ 200 lines
- Link to separate topic files (e.g., `debugging.md`, `patterns.md`) for detailed notes
- Update when you discover something wrong (correct the entry)
- Remove outdated entries

**Example memory entry:**
```markdown
## Project: CodeReview-Pilot
- **Goal**: Evidence-first diagnosis with production reliability
- **Stack**: Node.js, Express, Jest, Anthropic SDK
- **Key pattern**: Plan Mode first, then execute with tests
- **User preference**: Brief, action-oriented responses; run tests before claiming done
- **Critical file**: src/local-pipeline.js (4-agent orchestrator)
```

## Subagent Strategy

### Skill Sets by Agent (See .claude/SKILLSETS.md)

| Agent | Skills (Preloaded) | Phase | Use |
|-------|--------------------|-------|-----|
| **Explore** | project-guardrails, evidence-proof, router, retriever | 1 | Discovery, classification |
| **Plan** | project-guardrails, evidence-proof, e2e-orchestrator, stack-rank-priorities, sales | 1 | Plan Mode, orchestration |
| **General-Purpose** | evidence-proof, backend-reliability, ui-quality, frontend-engineer, backend-engineer, qa-engineer, sales | 2 | Implementation |
| **TeamLead** | stack-rank-priorities, sales, cost-guardrails | 1 | Stack rank, final call delivery |
| **TeamCoordinator** | stack-rank-priorities, sales, cost-guardrails | 1 | Stack rank, final call scope |
| **CodeReviewer** | project-guardrails, evidence-proof, critic, backend-reliability, ui-quality | 3 | Review, quality gate |
| **APIValidator** | backend-reliability, verifier, evidence-proof | 2 | API testing |
| **frontend-engineer** | frontend-engineer, ui-quality, evidence-proof | 2 | FE features |
| **backend-engineer** | backend-engineer, backend-reliability, evidence-proof | 2 | BE features |
| **qa-engineer** | qa-engineer, evidence-proof, critic | 3 | Test plans, proof |

### Phases with Subagents

**Phase 1 (Discovery)**: Explore, Plan → Skills: router, retriever, e2e-orchestrator, project-guardrails
**Phase 2 (Implementation)**: General-Purpose, frontend-engineer, backend-engineer, APIValidator → Skills: frontend-engineer, backend-engineer, backend-reliability, ui-quality, verifier
**Phase 3 (Review)**: CodeReviewer, qa-engineer → Skills: critic, evidence-proof
**Phase 4 (PR/Run)**: General-Purpose, pr-automation, e2e-orchestrator

### Core Subagents (Always Available)
1. **Explore** (Haiku model, read-only, Phase 1):
   - Search codebase for patterns, APIs, file structures
   - Skills: project-guardrails, evidence-proof, router, retriever
   - Use for: "Find all API endpoints", "What files handle auth?"
   - Limit: Cannot edit files, cannot run tests

2. **Plan** (Sonnet model, research-focused, Phase 1):
   - Explore codebase and design implementation approaches
   - Skills: project-guardrails, evidence-proof, e2e-orchestrator
   - Use for: Plan Mode - understand requirements, identify risks
   - Limit: Cannot edit code, cannot execute

3. **General-purpose** (Haiku model, full access, Phase 2):
   - Complex execution tasks, code writing, testing
   - Skills: evidence-proof, backend-reliability, ui-quality, frontend-engineer, backend-engineer, qa-engineer
   - Use for: Implement plans, write tests
   - Limit: Proceed from plan automatically; never wait for user to run, update, or accept

### Optional Specialized Subagents (Max 3-5 Total)
- **CodeReviewer** (Phase 3) – Skills: critic, backend-reliability, ui-quality
- **APIValidator** (Phase 2) – Skills: verifier, backend-reliability
- **frontend-engineer** (Phase 2) – Skills: frontend-engineer, ui-quality
- **backend-engineer** (Phase 2) – Skills: backend-engineer, backend-reliability
- **qa-engineer** (Phase 3) – Skills: qa-engineer, critic

**Guidance:** Assign every task to an agent. Spawn optional agents when their phase runs. Run in parallel when tasks are independent. Nothing left unassigned. See `agent-task-assignment` skill.

### When to Spawn Agents (and When NOT to)

✅ **DO spawn agents when:**
- Phase runs (Phase 2: frontend + backend + qa; Phase 3: CodeReviewer + APIValidator + EvidenceReviewer + QAReviewer + Critic)
- Checklist has 2+ independent items (no file overlap) → spawn multiple TaskExecutors in parallel
- Ten-pass runs → spawn all 5 five-agent in parallel
- Need parallel research, code review, or specialized expertise

❌ **DON'T spawn agents when:**
- Single straightforward task (1 file, 1 edit)
- Agent would duplicate your work
- You're just researching a quick answer

**Parallel by default**: When tasks are independent, spawn agents simultaneously. Do NOT sequence when parallel is possible.

### Agent Communication
- Use SendMessage for direct communication with agents
- Always refer to teammates by **name** (not UUID)
- Don't send JSON status messages - use TaskUpdate instead
- Plain text communication is clearer than structured formats

## Handling Blockers and Unknowns

### Unknown Markers
When uncertain about something, mark it clearly:
```
[UNKNOWN] - Cannot verify if API endpoint exists (need to check code)
[ASSUMPTION] - Assuming user has valid API credentials
[RISK] - Edge case not tested: network timeout during large uploads
```

Never claim high confidence without evidence.

### What to Do When Blocked
1. Identify exactly what's unknown
2. Create a sub-task to resolve it—proceed, do NOT wait for user
3. Pick the best option if ambiguous; document in CONFIDENCE_SCORE
4. Lower confidence score until resolved
5. Document in .claude/CONFIDENCE_SCORE.md

## Verification Criteria: Tests Before Claiming Done

### For Code Changes
```javascript
// ✅ BEFORE commit/PR:
1. Run: npm test                          // All tests passing
2. Check output: 319 tests pass, 89.87% coverage
3. No console.logs in production code
4. No commented-out code
5. Update .claude/CONFIDENCE_SCORE.md with test results
```

### For API/Integration Changes
```javascript
// ✅ Test these flows:
1. Happy path: valid input → success response
2. Error path: invalid input → error with guidance
3. Retry path: transient failure → auto-retry → success
4. Permission path: unauthorized → 403 + message
```

### For UI Changes
```javascript
// ✅ Test on localhost:3000:
1. Form submission works
2. Loading state appears and clears
3. Success state displays results
4. Error state shows message + retry button
5. Keyboard navigation works (Tab, Enter, Escape)
```

### For Performance Changes
```javascript
// ✅ Verify:
1. Run Lighthouse: npm run lighthouse (or DevTools)
2. Performance score ≥ 90
3. Core Web Vitals: LCP < 2.5s, FID < 100ms, CLS < 0.1
```

## Session Protocol

1. **Read** CLAUDE.md (project rules) and .claude/CONFIDENCE_SCORE.md (prior work)
2. **Plan** (if starting new task):
   - Use EnterPlanMode
   - Explore codebase to understand scope
   - Design solution with test criteria
   - Present plan for approval
3. **Execute**:
   - Implement changes in separate commits
   - Write tests for critical flows
   - Run tests before committing
4. **Verify**:
   - Test locally and in CI
   - Update .claude/CONFIDENCE_SCORE.md
   - Update CHANGELOG.md
   - Link to evidence (test output, GitHub Actions)
5. **Score**:
   - Confidence = test results + evidence
   - Only 95-100 if all critical flows tested + passing
   - Include unknowns and residual risks
6. **Done**:
   - All task criteria met ✓
   - Tests passing ✓
   - Evidence documented ✓

## Homepage Premium Standard
Homepage upgrades are treated as a discrete mini-project. Agents should reference `.claude/skills/homepage-upgrade (skill)` which enumerates sections, copy requirements, visual and motion goals, and QA criteria. New homepage work must be idempotent: checks should detect completed tasks and skip them so repeated prompts do not redo work. Storytelling, performance, and backend alignment are first‑class concerns. Use existing components and design tokens; avoid copycat dashboards or vague marketing language.

## Cost Optimization Notes

This project uses Anthropic Claude API. To minimize costs while maintaining quality:
- Use local validation before API calls (lint, test locally)
- Batch multiple questions into one API request when possible
- Use Haiku for simple validation tasks (lower cost)
- Use Sonnet for analysis tasks (medium cost)
- Reserve Opus for critical approvals only

See `.claude/rules/` for cost-specific guidelines.

## Key Principles (Never Compromise)

1. **Evidence First** - Never claim something works without test proof
2. **Local Testing** - Always run `npm test` before committing
3. **Plan Before Code** - Use Plan Mode to validate before implementing
4. **Test Criteria Clear** - Know what "done" means before you start
5. **Document Unknowns** - Mark [UNKNOWN] and [RISK] explicitly
6. **Confidence Backed** - Score only as high as evidence supports
7. **Rollback Safe** - Always know how to revert safely

## 🚨 EXTREME CLAUDE SESSION RULES (Non-Negotiable)

**Status**: System is 60% complete but blocked by state validation + rescue gate issues. Local agents need FULL authority to fix themselves.

### Claude's Only 2 Jobs (Non-Negotiable):
1. **Read AGENT_TODO.md** → file tasks to projects.json
2. **Upgrade agent prompts** after rescue is triggered (rescue only, 200 tokens max)

### Claude MUST NEVER:
- ❌ Write or edit any agent code (agents/*.py, orchestrator/*.py)
- ❌ Fix bugs in the runtime (agents do this via self-healing)
- ❌ Run the loop manually or restart agents
- ❌ Answer task questions with code — file a task instead
- ❌ Be called before attempt_count >= 3 in state/runtime-lessons.json

### Agents Have FULL Authority To:
- ✅ Commit, push, create PRs without Claude approval
- ✅ Mark tasks done, skip tasks, re-prioritize queue
- ✅ Spawn sub-agents, kill sub-agents, reassign tasks
- ✅ Write to state.json, runtime-lessons.json, quality_scores.txt
- ✅ Self-modify their own prompts after rescue

### Rescue Protocol (Hard Gate):
1. Agent fails → logs to state/runtime-lessons.json with strategy used
2. Agent retries with DIFFERENT strategy (max 3 total attempts)
3. Only after attempt_count = 3: write to rescue_queue.json
4. Claude reads rescue_queue.json once → upgrades agent prompt only (200 tokens)
5. Claude does NOT fix the task. Upgraded agent retries immediately.

### If Claude Finds Itself Fixing Code:
```
STOP IMMEDIATELY.
Write fix description to AGENT_TODO.md as a task.
Exit without making changes.
Let local agents implement the fix.
```

---

## Questions?
Refer to:
- **CLAUDE.md** - Project rules and output contract
- **.claude/rules/guardrails.md** - Anti-hallucination standards
- **.claude/rules/confidence.md** - Confidence scoring details
- **.claude/rules/testing.md** - Test requirements
- **.claude/CONFIDENCE_SCORE.md** - Prior work and evidence
