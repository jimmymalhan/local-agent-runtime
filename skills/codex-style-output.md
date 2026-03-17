# Skill: Codex-Style Output

**Trigger:** When running long tasks, pipelines, or multi-step operations that need user-visible progress.

## Output Rules

### 1. Show Working Timer
Display elapsed time for any operation longer than 2 seconds:
```
Working (0m 12s) Analyzing codebase...
Working (1m 03s) Running pipeline stage 2/4...
Working (2m 41s) Generating final report...
```
- Update every 5 seconds minimum.
- Show what is actively happening, not just "working."

### 2. Show Progress Bars with % Completion
Use ASCII progress bars for multi-step operations:
```
[##########..........] 50%  Stage 2/4: Retriever
[###############.....] 75%  Stage 3/4: Skeptic
[####################] 100% Complete (3m 22s)
```
- Calculate percentage from known step counts, not guesses.
- If total steps unknown, show a spinner with step count instead:
```
[~] Step 14... Processing files
```

### 3. Show Code Diffs Inline
When making changes, show compact diffs in the terminal:
```
--- src/pipeline.js
+++ src/pipeline.js
@@ -42,3 +42,5 @@
   const result = await run(task);
+  if (!result.valid) {
+    return retry(task, { maxAttempts: 3 });
+  }
   return result;
```
- Keep diffs to the relevant lines (3 lines of context max).
- For large changes, summarize: `Changed 4 files, 23 insertions, 8 deletions`.

### 4. Show Model Breakdown
When using multiple models, show which model handles what:
```
Model Usage:
  Local (ollama/qwen2.5:3b)  ████████░░  78%  — retrieval, routing
  Cloud (claude/sonnet)       ██░░░░░░░░  22%  — synthesis, review
  Total tokens: 12,400 (est. cost: $0.02)
```
- Always show local vs cloud split.
- Show token count and estimated cost when available.
- Update at end of each pipeline stage.

### 5. Be Terse, Action-Oriented, No Fluff
Good:
```
Fixed retry logic in api-client.js (+3 lines)
Tests: 319 pass, 0 fail (2.4s)
Pushed to feature/fix-retry (abc123)
```

Bad:
```
I've successfully implemented the retry logic changes in the API client.
The modification adds exponential backoff with a maximum of 3 retries.
All 319 tests are now passing with no failures, which took 2.4 seconds.
I've pushed the changes to the feature branch.
```

## Format Templates

### Task Start
```
> Task: [description]
  Branch: [branch-name]
  Model: [primary model] (fallback: [backup])
```

### Task Progress
```
Working (1m 15s)
[########............] 40%  [current step description]
  Files: 3 changed, 1 created
  Tests: running...
```

### Task Complete
```
Done (2m 03s)
  Changed: src/api.js, tests/api.test.js
  Tests: 42 pass, 0 fail
  Commit: abc1234 "fix retry backoff logic"
  Push: feature/fix-retry -> origin
```

### Blocker Report
```
BLOCKED (after 45s)
  Issue: Ollama not responding on :11434
  Tried: restart, port check, fallback model
  Action: switching to cloud model, continuing
```

## Anti-Patterns
- Long paragraphs explaining what you did.
- Repeating information the user already sees.
- Asking "would you like me to continue?" — just continue.
- Showing full file contents instead of diffs.
- Omitting timing information on long operations.

## Integration
- Uses: `state/progress.json` for step tracking
- Uses: `state/model-registry.json` for model breakdown
- Related skills: `fast-iteration`, `team-orchestration`
