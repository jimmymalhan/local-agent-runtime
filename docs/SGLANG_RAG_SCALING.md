# Scaling RAG and Ranking with SGLang

This repository’s baseline interactive session is optimized for single-user local work. To scale the same ideas for larger corpora and higher request volume, split the system into retrieval, ranking, and answer generation tiers.

## Recommended Scaled Path

1. Use **Pinecone** or another vector service for candidate retrieval at corpus scale when you accept managed-service spend, or stay on a local index / local vector store when the goal is zero-dollar operation.
2. Use a **local SGLang reranking service** to score retrieved passages or candidates efficiently.
3. Pass only the top reranked items into the final local generation stage.
4. Keep the final local-agent orchestration inside the repo's 70 percent CPU and memory guardrail.

## Why SGLang Fits the Ranking Tier

The LinkedIn engineering write-up on scaling LLM-based ranking with SGLang emphasizes patterns that matter for high-throughput scoring:

- keep ranking on a **prefill-only, scoring-focused fast path** instead of a full chat loop
- preserve **batch boundaries and batch tokenization** so GPU work stays dense
- maximize **shared-prefix reuse / KV reuse** to avoid repeated work
- separate or parallelize preprocessing and scheduling bottlenecks around the Python layer
- use **multi-process scheduling** when one Python process becomes the bottleneck
- move heavy ranking traffic into a dedicated inference tier instead of mixing it with everything else

These ideas map cleanly to this repo:

- `scripts/rag_retrieval.sh` handles candidate retrieval
- `scripts/sglang_embeddings.sh` can derive Pinecone query vectors locally when they are not precomputed
- `scripts/normalize_retrieval_results.py` normalizes local-index and Pinecone payloads into one candidate shape
- `scripts/sglang_ranker.sh` handles local reranking through a local endpoint
- `scripts/scale_rag_ranking.sh` chains retrieval and reranking into a single scalable path
- `scripts/sglang_scale_pipeline.sh` extends the same flow through final answer generation

## Pinecone at Scale

For Pinecone-backed retrieval, prefer:

- namespaces for tenant or domain isolation
- one namespace per tenant for multitenant isolation and lower read cost
- top-k candidate retrieval before reranking
- optional hybrid search by providing dense plus sparse vectors
- rerank the merged candidate set before final prompt construction
- selective metadata indexing only for fields that will actually be filtered
- dedicated retrieval configuration per workload instead of one global index setting

In this repo the Pinecone path is controlled by environment variables such as:

```bash
export RAG_METHOD=pinecone
export PINECONE_API_KEY=...
export PINECONE_INDEX_NAME=...
export PINECONE_INDEX_HOST=...
export PINECONE_NAMESPACE=default
export PINECONE_QUERY_VECTOR_JSON='[0.1, 0.2, ...]'
export PINECONE_SPARSE_INDICES_JSON='[1, 9, 42]'
export PINECONE_SPARSE_VALUES_JSON='[0.3, 0.9, 0.4]'
```

If `PINECONE_QUERY_VECTOR_JSON` is omitted and a local SGLang embeddings endpoint is available, the repo now tries to derive that vector automatically through `scripts/sglang_embeddings.sh`.

If the goal is strict zero-dollar local execution, do not enable the Pinecone path. Keep `RAG_METHOD=local` and use the same reranking stage with a local index instead.

## Operational Pattern

At scale, the recommended flow is:

1. Retrieve 20-200 candidates from Pinecone or the local index.
2. Normalize the candidate payload into one ranking shape.
3. Send those candidates to a dedicated local SGLang ranking service that is optimized for scoring rather than chat.
4. Keep only the top ranked passages for the final agent prompt.
5. Feed the reduced context into the local multi-role team.
6. Cache prefixes, reuse embeddings, and reuse retrieval results when the user repeats adjacent queries.

This keeps retrieval broad, ranking cheap, and final generation focused.
