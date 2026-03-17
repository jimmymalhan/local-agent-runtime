# PR Reviewers — Production House Workflow

**Purpose**: Act like a production house. Reviewers come in on PRs, make comments, push back, recommend additional tests. Iterate until business-level, production-level code. Do not rush to merge.

---

## Reviewer Flow

```
PR ready to merge
       ↓
Reviewers (agents) review PR
       ↓
Reviewers post comments, push back
       ↓
Author iterates on feedback
       ↓
Reviewers recommend additional tests (if needed)
       ↓
Run CI + reviewer-recommended tests
       ↓
Reviewers recommend merge? → Merge
Reviewers do NOT recommend? → Create new branch, work harder
```

---

## Reviewer Agents (Invoked on PR)

| Reviewer | Role | Comments On | Push Back If |
|----------|------|-------------|--------------|
| **ProductionReviewer** | Production readiness | Error handling, logging, observability, rollback | Missing error paths, no structured logging, unsafe rollback |
| **BusinessReviewer** | Business logic, edge cases | Requirements, user flows, edge cases | Missing validation, unclear behavior, untested edge cases |
| **SecurityReviewer** | Security, secrets, injection | Auth, input validation, secrets | Secrets in code, SQL injection, XSS |
| **CodeReviewer** | DRY, style, maintainability | Duplication, style, guardrails | Duplicate logic, console.log, commented code |
| **QAReviewer** | Tests, coverage, flows | Test gaps, coverage, critical paths | Missing tests, low coverage, untested error paths |

---

## Rules

1. **Do NOT rush to merge** — Reviewers must recommend merge. Merge only when all reviewers pass.
2. **Iterate on comments** — Address every reviewer comment. Trade on feedback. Improve.
3. **Recommend additional tests** — Reviewers can recommend new tests. Run them before merge.
4. **If reviewers do NOT recommend merge** — Create a new branch. Work harder. Fix issues. Resubmit.
5. **All CI + reviewer-recommended tests must pass** — No merge until 100% green.
6. **Production-level quality** — Code must meet business-level, production-level standards before merge.

---

## Integration

- Invoked when PR is "ready to merge" (before merge button)
- Uses five-agent-verification + reviewer comments
- pr-reviewers skill orchestrates: spawn reviewers → collect comments → iterate → re-review → recommend or block
