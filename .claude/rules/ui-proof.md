# UI Proof Standards

**Purpose:** Define what constitutes sufficient proof for user‑interface work. This complements the general UI rules by focusing on evidence requirements.

## Requirements
- Every UI change must have a corresponding proof plan in `.claude/skills/testing (see testing skill)` or the task section of `.claude/CONFIDENCE_SCORE.md`.
- Proof can include:
  - Screenshots from a local `npm start` session showing before/after states.
  - Automated end‑to‑end tests that navigate through the changed flows.
  - Accessibility audit reports (e.g., axe-core output) demonstrating compliance.
  - User acceptance notes or stakeholder sign‑off (documented in `.claude/FEEDBACK_LOG.md`).
- Real devices or browsers should be mentioned if the bug is environment‑specific.

## Verification
- `qa-engineer` should confirm visible changes match acceptance criteria.
- `senior-frontend-reviewer` attacks any ambiguous interaction or missing state proof.
- Reviewers must see concrete evidence (screenshots, test logs, etc.); "it should look right" is not enough.

## Failure Learning
- If a UI regression slips through, update this rule with the missing evidence type and record the incident in `.claude/PROJECT_STATUS.md`.
