# Skill: Benchmark Against Quality

**Trigger:** When a local answer needs one final comparison pass against a very high quality assistant standard.

**Rules:**
- Do not call external APIs or hosted assistants.
- Compare against the local quality rubric and any locally stored benchmark notes.
- Focus on factual accuracy, repo awareness, concrete commands, risk callouts, and directness.
- Upgrade weak sections instead of only critiquing them.

**Output Format:**
```
## Quality Gaps
- ...

## Improvements
- ...

## Stronger Draft
...
```
