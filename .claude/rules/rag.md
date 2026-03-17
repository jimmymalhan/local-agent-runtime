# RAG (Retrieval-Augmented Generation) Standards

**Purpose:** Define quality criteria for retrieval pipelines and grounding mechanisms.

## Requirements
- Document how source data is chunked, indexed, and embedded.
- Provide citations in outputs and verify they correspond to actual source content.
- Establish freshness policies for indices and data re-ingestion plans.
- Include tests for retrieval relevance and metrics (e.g., recall@k) if available.
- Outline hallucination mitigation strategies (prompt constraints, grounding checks, etc.).

## Verification
- `rag-ai-engineer` evaluates indexing and search quality.
- `evidence-reviewer` checks that citations are real and not invented.
- `distinguished-engineer-reviewer` questions long-term sustainability of the pipeline.

## Failure Learning
- Any hallucination incident updates this rule with a new mitigation and is recorded in `.claude/PROJECT_STATUS.md`.
