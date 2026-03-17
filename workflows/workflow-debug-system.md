# Workflow: Debug System

This workflow isolates and fixes bugs in a system.

1. **Idea Capture Agent** – logs the bug description and affected area.
2. **Understand Project Agent** – investigates the specific area using targeted reading and summarises root causes【723734941127503†L155-L241】.
3. **Generate Architecture Agent** – proposes a fix strategy and outlines necessary changes.
4. **Implementation Agent** – applies the smallest fix possible, runs targeted tests, and records the diff summary.
5. **Review Agent** – checks the fix for unintended side effects or hallucinations.
6. **Test Agent** – writes a failing test before the fix (if necessary) and verifies that it passes after implementation.
7. **Summary Agent** – documents the bug, the fix, and updates skills and workflows accordingly.

Use this workflow to ensure thorough investigation, targeted fixes, and robust verification.