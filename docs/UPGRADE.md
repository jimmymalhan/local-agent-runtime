# Upgrading and Customizing Skills and Workflows

This guide explains how to evolve the skills and workflows of your local autonomous engineering system so that it remains reusable across projects and adaptable to project‑specific workflows.  The system logs every prompt and workflow outcome; review these logs regularly to drive improvements and to avoid manual intervention.

## Generic Skill Upgrades

- **Monitor logs:** Use `feedback/prompt-log.md` and `feedback/workflow-evolution.md` to identify recurring tasks or inefficiencies.  When you notice a pattern, create or update a skill to handle it automatically.  Keep global rules in `CLAUDE.md` and move specialized instructions into skills【390377402365791†L321-L327】.
- **Version skills:** To refine a skill (for example, improving the implementation process), copy the original skill file to a new version (e.g. `implement-feature-v2.md`), update its instructions, and update workflows to reference the new file.  Versioning makes it easy to track improvements over time.
- **Follow the skill structure:** Each skill file should include a **Trigger** (when the skill should run), **Inputs** (expected arguments or context), **Commands** (step‑by‑step instructions), **Output Format** (the expected output structure), and **Stop Conditions**.  Use targeted file reads, subagents, hooks, and `/clear` to minimise context【390377402365791†L190-L201】.
- **Optimize resources:** Use `/cost` or `/stats` after running a skill to monitor token usage【390377402365791†L196-L199】.  Refine instructions to avoid unnecessary file reads or large test runs【390377402365791†L257-L266】.
- **Test skills:** After updating a skill, run a representative task and verify that Claude invokes the skill correctly and produces the expected output.  If necessary, adjust the skill’s YAML frontmatter (name, description, allowed tools, etc.).

## Creating Project‑Specific Skills

- **Identify unique tasks:** When your project requires a workflow not covered by the generic skills (for example, PR reviews, database migrations, or repository triage), create a new skill in the `skills/` directory.  Choose a descriptive file name (e.g. `db-migration.md`).
- **Write clear triggers:** The skill’s trigger should precisely describe when Claude should run it.  For example, a PR review skill might trigger when a pull request diff is available.
- **Define inputs and commands:** List required inputs (e.g. path to the diff) and provide commands that follow the investigation‑plan‑implement‑review pattern【723734941127503†L155-L241】.  Use subagents for verbose operations to keep the main context lean【605794428636802†L904-L911】.
- **Specify output and stop conditions:** Define the expected output format (e.g. list of issues and recommendations) and stop when the task is complete.
- **Keep global guidance in CLAUDE.md:** Only include project‑agnostic rules (like build commands or code style) in `CLAUDE.md`.  All specialized playbooks should live in skills【390377402365791†L321-L327】.

## Customizing Workflows for a Project

- **Create new workflow definitions:** To tailor the system to a project’s development processes, create or modify files under `workflows/`.  Each workflow lists the agents to run and the sequence in which they execute.  Use the provided workflows as templates (e.g. `workflow-idea-to-feature.md`).
- **Update existing workflows:** If you create a new skill for a project, update relevant workflows to call that skill in the appropriate step.  For example, add a `pr-review-agent` after implementation in your pipeline.
- **Integrate continuous integration or deployment:** For CI/CD projects, define a workflow that runs tests, builds the project, and deploys if tests pass.  Use targeted test commands and hooks to minimise context【390377402365791†L257-L266】.

## Integrating the Framework into Your Project

- **Copy the repository:** To use this framework in an existing project, copy the `local-agent-runtime` directory into your project root (e.g. `.ai/` or `.claude/`).  You can also symlink it if you prefer.
- **Update `CLAUDE.md`:** Provide project‑specific build and test commands, code style rules, and any quirks of your environment.  Keep it lean; place domain‑specific instructions in skills【390377402365791†L321-L327】.
- **Create or update skills:** Write new skills for tasks unique to your project.  Use the templates and patterns described above.  Version your skills as they evolve.
- **Define workflows:** Create new workflows that match your project’s development lifecycle (feature development, refactoring, debugging).  Use the investigation‑plan‑implement‑review pattern and include your project‑specific skills.
- **Adjust resource thresholds:** If your machine has different resource constraints, modify `state/workflow-state.json` to set new CPU and memory thresholds, or edit `scripts/monitor_resources.sh` to change the `THRESHOLD` variable.

## Continuous Improvement

- **Review logs regularly:** The `feedback/prompt-log.md` records every user prompt, and `feedback/workflow-evolution.md` records changes to workflows and skills.  Use these logs to detect patterns and opportunities for new or refined skills.
- **Version skills:** Maintain separate versions of each skill (e.g. `implement-feature-v1.md`, `implement-feature-v2.md`) to track improvements and ensure reproducibility.  Update workflows to reference the latest version.
- **Use hooks and subagents:** Offload heavy operations to hooks or subagents to keep your main context clean and reduce token usage【605794428636802†L904-L911】.  For example, use a hook to filter test output so only failures are returned【390377402365791†L257-L266】.
- **Test regularly:** Validate that updated skills and workflows behave as expected.  Use targeted tests and plan mode to minimise context when exploring and implementing changes【723734941127503†L155-L241】.

## Start, Investigate, Plan, Implement, Review Patterns

- **Start Prompt:** Ask Claude to read `@CLAUDE.md`, `@README.md`, and the relevant repo segment, then build a concise map of entrypoints, test commands, important files, and areas to avoid.
- **Investigation and Plan Prompts:** Direct Claude to investigate only the relevant files or modules (`@src/<area>` and `@tests/<area>`), return the root cause of an issue, and propose a five‑step plan under 120 words【723734941127503†L155-L241】.
- **Implementation and Review Prompts:** Instruct the implementation agent to carry out only the first plan step, change as few files as possible, run targeted tests, and produce a diff summary.  Use a subagent for edge‑case review and run `/cost` or `/stats` afterwards【390377402365791†L196-L199】.
- **Skill Prompts:** Create reusable skills for repetitive tasks (PR review, DB migration, repo triage).  Each skill should specify its trigger, inputs, commands, output format, and stop conditions.  Keep your global rules in `CLAUDE.md` and specialised playbooks in skills【390377402365791†L321-L327】.

By following these guidelines you can continually improve your local AI engineering system, keep your skills reusable across projects, and tailor workflows to your unique development processes.