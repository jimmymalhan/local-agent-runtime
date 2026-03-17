# LinkedIn SGLang Ranking Pattern

This note explains how the LinkedIn SGLang ranking approach maps into `local-agent-runtime` when the goal is to scale RAG and ranking without paying for external generation APIs.

## Core Pattern

The pattern is:

1. retrieve broadly
2. keep ranking on a dedicated scoring path
3. preserve dense batches and shared-prefix reuse
4. narrow the final generation prompt to only the best contexts

This repository now maps that pattern as follows:

## Tier 1: Retrieval

Use `scripts/rag_retrieval.sh`.

Supported paths:

- local index
- Pinecone

For Pinecone scale:

- isolate tenants or domains with namespaces
- retrieve more candidates than the final prompt can tolerate
- keep retrieval broad and cheap

If `PINECONE_QUERY_VECTOR_JSON` is not supplied, the repo can now try to derive it locally through `scripts/sglang_embeddings.sh`.

## Tier 2: Ranking

Use `scripts/sglang_ranker.sh`.

Important design choice:

- ranking is not the same as final answer generation
- ranking stays short-prompt and scoring-focused
- the reranker receives normalized contexts, not raw mixed payloads

This is why the repo now includes `scripts/normalize_retrieval_results.py`: Pinecone and local-index retrieval return different shapes, but the ranking path needs one normalized candidate list.

## Tier 3: Final Answer

Use `scripts/sglang_scale_pipeline.sh` or the local multi-role team.

The scale pipeline now creates:

- `retrieval.json`
- `normalized-retrieval.json`
- `rerank.json`
- `manifest.json`
- `answer.json`

The final answer only sees the best reranked contexts, which is the main quality-preserving step when operating at scale.

## Fast vs Exhaustive Scale Profiles

The scale pipeline now supports:

- `SCALE_PROFILE=fast`
- `SCALE_PROFILE=balanced`
- `SCALE_PROFILE=exhaustive`

These profiles adjust:

- `RAG_TOP_K`
- `RERANK_CANDIDATE_LIMIT`
- `TOP_CONTEXTS`

The goal is:

- `fast`: lower latency and fewer candidates
- `balanced`: practical default
- `exhaustive`: broader retrieval and more final context without breaking the repo’s 70 percent machine ceiling

## Why This Matters

The local-agent runtime should not try to brute-force everything through one long chat loop. At scale, the quality-preserving move is:

- retrieve wide
- rank cheap
- answer narrow

That is the operating model this repo now uses for the SGLang plus RAG plus Pinecone path.
