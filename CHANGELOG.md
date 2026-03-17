# Changelog

## 0.2.1 - 2026-03-16

- fix the Lighthouse workflow so repos without a Node web target skip FC-007 cleanly instead of failing on missing npm lockfiles
- make the local runtime fail fast under lock and resource pressure, downgrade to cheaper models sooner, and emit takeover guidance for Codex/Claude
- expand live todo and team status output with next-focus lanes and use-case rollups, backed by regression tests

## 0.2.0 - 2026-03-16

- move checkpoint storage into each target project under `.local-agent/checkpoints/`
- improve Codex-style live status with local/cloud execution ownership
- add todo lane progress for local, cloud, shared, and general work
- add repo-appropriate CI validation and session comparison coverage
- prepare GitHub release workflow for semantic version tags
