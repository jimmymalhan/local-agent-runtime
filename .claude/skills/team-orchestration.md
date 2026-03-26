# Skill: Team Orchestration

**Trigger:** When the local runtime needs to start with a common plan and coordinate multiple roles or sub-agents.

**Checklist:**
1. State what already exists and should be reused before proposing new work.
2. Produce one shared plan that later roles can follow without re-deciding the task.
3. Split the work into parallel streams only when the streams do not depend on one another.
4. Name the owner role for each stream and the exact artifact or validation expected from that role.
5. Keep the 70 percent CPU and memory ceiling in mind when recommending concurrency.
6. Map each stream to the matching local skill so sub-agents pick work by skill instead of duplicating effort.
7. End with a validation path that shows how the work is proven complete, including the automatic local review.
8. Use only repo paths, scripts, tools, and workflows that actually exist in the current repository snapshot.
9. If a requested capability is missing, say so plainly and give the next local step instead of inventing files or commands.
10. When the user asks for verification, answer yes or no explicitly before the detailed explanation.
11. Prefer concrete commands, artifacts, and checkpoints over generic advice.
12. Record quality gaps that block the team from matching a stronger reasoning model so they can be added to the roadmap.
13. Prefer local agents and local tools first. Use cloud-session takeover only when the local runtime stalls, misses the bar, or cannot finish on time.
14. Keep the user informed with explicit progress percentages, live status, and execution ownership when a task is long-running.

**Output Format:**
```text
## Existing work to reuse
- ...

## Common plan
- ...

## Parallel workstreams
- ...

## Validation path
- ...

## Skill routing
- ...

## Takeover trigger
- ...

## Known gaps and next upgrades
- ...
```
