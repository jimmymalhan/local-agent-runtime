# Skill: Generate Architecture

**Trigger:** When a new feature or project requires a high‑level system design.

**Inputs:**
- A description of the feature or idea.
- Summaries from `understand-project` or existing context files.

**Commands:**
1. Use Plan Mode to propose a five‑step implementation plan under 120 words.  Specify which files need to change and what new modules or services are required【723734941127503†L155-L241】.
2. Produce a system diagram or textual description identifying services, data models, and interactions.  Keep it concise and avoid adding unnecessary components.
3. Highlight test strategies and verification targets so Claude can validate its own work【723734941127503†L124-L141】.
4. Suggest creating or updating skill files if a similar feature is requested repeatedly.

**Output Format:**
```
## Plan (5 steps)
1. ...
2. ...
3. ...
4. ...
5. ...

## Architecture
- Services: ...
- Data models: ...
- Interactions: ...

## Verification
- Tests: ...

```

**Stop Conditions:**
- Stop when the five‑step plan and architecture description are provided.
