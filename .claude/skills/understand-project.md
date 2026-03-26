# Skill: Understand Project

**Trigger:** When asked to build an overview of an unfamiliar repository or to summarise its structure.

**Inputs:**
- A path to the repository or specific module to explore.

**Commands:**
1. Read only `@README.md`, `@CLAUDE.md`, and other high‑level docs.  Build a one‑page map listing key entrypoints, the test command, five important files, and any directories to avoid touching.  Limit the overview to 120 words.
2. When investigating a module, read only `@src/<area>` and `@tests/<area>`; return root cause of the issue, exact files involved, and the smallest possible fix【723734941127503†L155-L241】.  Do not implement code yet.
3. Summarise large files before passing context into later steps.  Use file‑first analysis and extract dependency graphs to understand relationships before reasoning【390377402365791†L257-L266】.

**Output Format:**
```
## Overview
- Entrypoints: ...
- Test command: ...
- Important files: ...
- Avoid: ...

## Investigation
- Root cause: ...
- Files to modify: ...
- Minimal fix: ...

## Summary
...
```

**Stop Conditions:**
- Stop when the overview and investigation sections are completed.
