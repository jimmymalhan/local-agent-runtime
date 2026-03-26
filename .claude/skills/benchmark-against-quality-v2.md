# Benchmark Against Quality v2 — Scoring Rubric

Upgraded benchmarking skill with a concrete scoring rubric and comparison protocol.

## Scoring Rubric

Rate each dimension on a 0-100 scale. Use the criteria below, not subjective impressions.

### 1. Plan Accuracy (weight: 30%)

| Score Range | Criteria |
|---|---|
| 90-100 | Every file path, command, and config reference is verified real. Plan covers all user deliverables. |
| 70-89 | 1-2 minor path issues. Plan covers most deliverables. |
| 50-69 | 3+ path issues or missing deliverables. |
| 0-49 | Majority of references are wrong or plan misunderstands the task. |

### 2. Code Correctness (weight: 25%)

| Score Range | Criteria |
|---|---|
| 90-100 | All code blocks parse. Follows repo conventions. Correct imports. |
| 70-89 | Valid syntax but minor style or import issues. |
| 50-69 | Some syntax errors or broken references. |
| 0-49 | Non-functional code or wrong language for the target file. |

### 3. Hallucination Rate (weight: 25%)

| Score Range | Criteria |
|---|---|
| 90-100 | Zero fabricated references. All claims verifiable from repo context. |
| 70-89 | 1-2 unverifiable claims that do not affect correctness. |
| 50-69 | 3-5 fabricated references. |
| 0-49 | Output is substantially hallucinated. |

### 4. Actionability (weight: 20%)

| Score Range | Criteria |
|---|---|
| 90-100 | User can execute immediately. Commands are copy-pasteable. Next steps explicit. |
| 70-89 | Mostly actionable with minor gaps. |
| 50-69 | Requires significant interpretation or missing steps. |
| 0-49 | Vague or unusable. |

## Composite Score

```
composite = (plan * 0.30) + (code * 0.25) + (hallucination * 0.25) + (actionability * 0.20)
```

## Comparison Protocol

1. Score the current output using the rubric above.
2. Load baseline scores from `tests/fixtures/quality-benchmarks.json`.
3. Compute delta for each dimension: `current - baseline`.
4. Flag any dimension where delta < -10 (regression).
5. Flag any dimension where score < 60 (weak).

## Output Format

```
## Quality Benchmark Report

| Dimension | Score | Baseline | Delta | Status |
|---|---|---|---|---|
| Plan Accuracy | XX | 70 | +/-N | PASS/WARN/FAIL |
| Code Correctness | XX | 75 | +/-N | PASS/WARN/FAIL |
| Hallucination Rate | XX | 80 | +/-N | PASS/WARN/FAIL |
| Actionability | XX | 70 | +/-N | PASS/WARN/FAIL |
| **Composite** | **XX** | **74** | **+/-N** | **PASS/WARN/FAIL** |

### Issues Found
- [List specific issues]

### Recommendations
- [List specific improvements]
```

## Thresholds

| Status | Composite Score | Action |
|---|---|---|
| PASS | >= 70 | Continue to next stage |
| WARN | 50-69 | Flag for review, may continue |
| FAIL | < 50 | Trigger cross-role critique loop |

## Differences from v1

| Aspect | v1 (benchmark-against-quality.md) | v2 (this file) |
|---|---|---|
| Scoring | Qualitative | Quantitative 0-100 per dimension |
| Baseline | None | Loaded from quality-benchmarks.json |
| Delta tracking | None | Explicit regression detection |
| Output format | Free-form | Structured table |
| Thresholds | Implicit | Explicit PASS/WARN/FAIL |
