# SGLang Scale Blueprint

This document captures the practical scale path for `local-agent-runtime` when the goal is to keep generation local, push retrieval and ranking harder, and avoid paid model APIs.

## Objectives

- keep the final answer path local
- stay inside the 70 percent CPU and memory ceiling for the local-agent runtime
- make retrieval and ranking scale beyond a single local index
- preserve quality by narrowing the final prompt to the best context

## Common Architecture

### 1. Planning and Coordination

Every run starts with a common plan:

1. `Researcher` and `Retriever` gather context
2. `Planner` writes `state/common-plan.md`
3. downstream roles execute against that shared plan

This keeps the local team coordinated even when parts of the work run in parallel.

### 2. Retrieval Tier

Use one of two retrieval paths:

- local index through `scripts/rag_retrieval.sh`
- Pinecone for larger corpora or multi-tenant scale

When Pinecone is selected and `PINECONE_QUERY_VECTOR_JSON` is not already provided, `rag_retrieval.sh` now tries to derive the query embedding locally through `scripts/sglang_embeddings.sh`.

### 3. Ranking Tier

Use a dedicated local SGLang ranking path:

- `scripts/sglang_ranker.sh`
- `scripts/normalize_retrieval_results.py`

This is intentionally separated from the final answer generator. Ranking workloads should be:

- short-prompt
- dense-batch
- cache-friendly
- schema-constrained
- normalized across local-index and Pinecone payload shapes

### 4. Final Answer Tier

Use the reduced context only:

- `scripts/sglang_scale_pipeline.sh`
- or the local Ollama multi-role team in `scripts/local_team_run.py`

The goal is broad retrieval, cheap ranking, and focused final generation.

## Why This Maps to SGLang Well

The upstream SGLang project emphasizes:

- fast serving
- structured outputs
- embeddings
- speculative decoding
- cache-aware routing
- prefill/decode disaggregation

The LinkedIn SGLang ranking write-up reinforces the same pattern for scale:

- keep ranking on a scoring-focused fast path
- preserve dense batches
- maximize shared-prefix reuse
- separate ranking from heavier chat orchestration

That is why this repo uses SGLang as the ranking and serving tier rather than trying to force every role through the same heavy loop.

## Pinecone Pattern

For Pinecone-backed retrieval:

- keep namespaces per tenant or domain
- retrieve a larger top-k candidate set
- rerank locally with SGLang
- pass only the best subset to the final answer stage

Recommended environment variables:

```bash
export RAG_METHOD=pinecone
export PINECONE_API_KEY=...
export PINECONE_INDEX_NAME=...
export PINECONE_INDEX_HOST=...
export PINECONE_NAMESPACE=default
export RAG_TOP_K=40
export PINECONE_TOP_K=40
```

If `PINECONE_QUERY_VECTOR_JSON` is omitted, the repo will try to generate it locally through the SGLang embeddings endpoint.

## Fast vs Exhaustive

### Fast path

- lighter retrieval
- rerank fewer candidates
- fewer critique stages
- suitable for quick operator responses

### Exhaustive path

- larger prompt budgets
- same 70 percent CPU and memory ceiling
- more critique roles
- better suited for release gates, debugging, or high-stakes synthesis

The repo does not claim a true 10M token local context window. Instead it uses the largest practical local budgets that remain stable on this machine.

## Operational Commands

Health check:

```bash
bash ./scripts/sglang_healthcheck.sh
```

Gateway:

```bash
SGLANG_GATEWAY_WORKER_URLS="http://127.0.0.1:30000 http://127.0.0.1:30001" \
bash ./scripts/sglang_gateway.sh
```

Embeddings:

```bash
bash ./scripts/sglang_embeddings.sh "How do I use the local runtime?"
```

Scale pipeline:

```bash
RAG_METHOD=pinecone \
SCALE_PROFILE=exhaustive \
ENABLE_SGLANG_RERANK=1 \
ENABLE_SGLANG_FINAL_ANSWER=1 \
bash ./scripts/sglang_scale_pipeline.sh "How do I start the local runtime and recover from failures?"
```
