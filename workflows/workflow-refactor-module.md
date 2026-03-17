# Workflow: Refactor Module

Use this workflow to refactor a specific module without altering external behaviour.

1. **Idea Capture Agent** – records the refactoring goal and module path.
2. **Understand Project Agent** – summarises the module structure using the `understand-project` skill, identifying key functions and dependencies.
3. **Plan Agent** – generates a concise plan to refactor the module while preserving the public API.
4. **Implementation Agent** – implements one refactoring step at a time and runs targeted tests.
5. **Review Agent** – validates that the refactored module behaves identically to the original.
6. **Summary Agent** – summarises changes, updates skills, and logs the workflow for future reuse.

This workflow emphasises incremental refactoring, targeted testing, and resource awareness to minimise token usage and CPU/memory consumption.