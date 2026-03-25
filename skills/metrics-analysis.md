Metrics-analysis skill for local agents.

Use this when a role must prioritize by throughput, latency, cost, progress, or ROI.

Rules:
- Prefer measured resource, ETA, test, and progress signals over intuition.
- When blocked, offer the 2-3 fastest resolution options with owner and ETA.
- Distinguish between hard blockers, stale telemetry, and cosmetic noise.
- Use completion %, open-task count, and resource headroom to rank next actions.
- Recommend cuts when the metric signal says additional work is low-yield.

Expected behavior by role:
- Manager and Director: reorder work based on live completion and blocker pressure.
- Optimizer: reduce local cost and runtime drag first.
- Benchmarker: compare current output against the local quality and speed bar.
