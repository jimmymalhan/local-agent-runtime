# Skill: Optimize System

**Trigger:** After code has been implemented and validated, when performance or resource efficiency needs improvement.

**Inputs:**
- Code and test results from previous steps.
- System performance metrics (CPU, memory usage) captured during execution.

**Commands:**
1. Analyse current resource usage and identify hotspots using local profiling tools.  Focus on files or functions with high CPU or memory consumption.
2. Refactor or optimise code to reduce complexity and improve performance.  Avoid premature optimisation; target the specific bottlenecks you observed.
3. Re‑run the relevant tests and compare performance metrics before and after optimisation.  Ensure functionality remains correct.
4. Suggest updates to the `monitor_resources.sh` script or state thresholds if consistent resource patterns emerge.

**Output Format:**
```
## Optimisation Summary
- Bottlenecks: ...
- Changes made: ...
- Before vs. after metrics: ...

```

**Stop Conditions:**
- Stop when optimised code passes tests and demonstrates reduced resource usage.
