# Skill: Quality Rubric

**Trigger:** When an intermediate answer needs to be upgraded to a stronger coding-assistant standard.

**Goals:**
- Prefer concrete commands, files, and verifiable claims.
- Prefer project-aware explanations over generic AI prose.
- Call out missing tests, missing backups, missing migration paths, or unclear risks.
- Tighten low-signal language and remove filler.
- Raise the answer until it is close to what a strong local coding assistant session should return.

**Checklist:**
1. Does the output explain the repo state accurately?
2. Does it show exact commands or next actions?
3. Does it identify real gaps or risks?
4. Does it avoid hallucinated tools or files?
5. Does it reflect current local constraints such as CPU, memory, and installed models?

**Output Format:**
```
## Gaps
- ...

## Upgrades
- ...

## Stronger Answer
...
```

## Learned Patterns (auto-updated 2026-03-25)

### Category: refactor

#### Common pitfalls to avoid:
- status=partial occurred 1x

#### Context that helps:
- Average quality was 45.0/100 — add explicit output format instructions
- Include worked example in prompt for this category
- Add verification step: assert output satisfies task description
- Increase context window usage: pass full description, not summary

