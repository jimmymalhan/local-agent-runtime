# Skill: Auto-Discover Upgrade Features

**Trigger:** When running the auto-upgrade loop or when the lead assigns the "discovery" phase.

**Lead assigns:**
- **Researcher + Retriever:** Scan docs/, config/, scripts/, skills/, README, UPGRADE.md, workflows/, roles/ for features that help local models exceed Cursor. Return a list.
- **Planner:** Prioritize and dedupe against existing state/todo.md items.
- **Implementer:** Append new checkbox items to state/todo.md under "Local Model Upgrade Roadmap". Format: `- [ ] **Feature name**: brief description`. No duplicates.

**Commands:**
1. Read docs/UPGRADE.md, README.md, config/runtime.json, scripts/bootstrap_local_runtime.sh.
2. Scan skills/*.md, roles/*.md, workflows/*.md for upgrade patterns.
3. Compare with state/todo.md "Local Model Upgrade Roadmap" — skip existing items.
4. Append new items. One per line, checkbox format.

**Output:** Updated state/todo.md with new features. No code changes elsewhere.

**Stop when:** All new features added; no duplicates.
