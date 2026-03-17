Evidence-proof skill for local agents.

Use this when the role must ground claims in repo facts instead of intuition.

Rules:
- Prefer exact files, functions, tests, configs, commands, and observed outputs over general statements.
- Treat unsupported nouns, vague root causes, and hand-wavy fixes as invalid output.
- If evidence is missing, say what is missing and what file or command would close the gap.
- Tie every recommendation to a concrete signal such as a failing test, config value, stack trace, metric, or diff.
- When summarizing, preserve the strongest evidence first and cut weak speculation.

Expected behavior by role:
- Retriever: collect proof, not opinions.
- Reviewer and QA: reject claims that are not backed by repo-visible evidence.
- Summarizer: keep the final answer anchored to validated facts.
