# Quality Gate Scoring Criteria

Defines pass/fail thresholds for each stage output before the pipeline continues.

## Scoring Dimensions

### 1. Plan Accuracy (weight: 30%)
- Does the plan reference real files that exist in the repo?
- Are the proposed changes aligned with the user's request?
- Are dependencies between tasks correctly identified?

| Score | Criteria |
|---|---|
| 90-100 | All file paths verified, all tasks aligned, dependencies correct |
| 70-89 | Most paths correct, minor alignment gaps |
| 50-69 | Some invalid paths or misaligned tasks |
| 0-49 | Majority of paths invalid or plan misunderstands the request |

### 2. Code Correctness (weight: 30%)
- Does the generated code have valid syntax?
- Are imports and references to existing code correct?
- Does the code follow the repo's existing patterns?

| Score | Criteria |
|---|---|
| 90-100 | Valid syntax, correct imports, follows repo patterns |
| 70-89 | Valid syntax, minor import issues |
| 50-69 | Some syntax errors or broken references |
| 0-49 | Significant syntax errors or non-functional code |

### 3. Hallucination Rate (weight: 20%)
- Does the output reference files, commands, or APIs that do not exist?
- Are performance claims or resource numbers fabricated?
- Are cited configurations actually present in the repo?

| Score | Criteria |
|---|---|
| 90-100 | Zero hallucinated references |
| 70-89 | 1-2 minor unverifiable claims |
| 50-69 | 3-5 hallucinated references |
| 0-49 | Pervasive hallucination |

### 4. Actionability (weight: 20%)
- Can the user act on the output without guessing?
- Are commands copy-pasteable and correct?
- Are next steps explicit?

| Score | Criteria |
|---|---|
| 90-100 | Fully actionable, all commands correct |
| 70-89 | Mostly actionable, minor gaps |
| 50-69 | Requires significant interpretation |
| 0-49 | Vague or unusable output |

## Gate Thresholds

| Gate | Minimum Score | Action on Fail |
|---|---|---|
| Planner -> Implementer | 60 | Re-run planner with refinement prompt |
| Implementer -> Tester | 50 | Re-run implementer with feedback |
| Reviewer -> QA | 60 | Send revision request back to implementer (cross-role critique) |
| QA -> Summarizer | 70 | Flag gaps in final summary |
| Summarizer -> User | 70 | Re-run summarizer with factuality check |

## Composite Score

```
composite = (plan_accuracy * 0.30) + (code_correctness * 0.30) +
            (hallucination_rate * 0.20) + (actionability * 0.20)
```

- **Pass**: composite >= 60
- **Weak**: composite 40-59 (triggers cross-role critique loop)
- **Fail**: composite < 40 (triggers full re-run of the stage)
