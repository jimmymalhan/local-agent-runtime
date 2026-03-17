# SGLang Integration

This repository does not try to reimplement upstream SGLang. It uses a practical integration layer so the local-agent stack can take advantage of the upstream serving features that matter most for local and scaled deployments.

## Included SGLang Tools

- `scripts/sglang_server.sh`
  Launches a local SGLang server with support for embeddings, tool-call parsers, reasoning parsers, speculative decoding flags, LoRA, quantization, DP attention, and dry-run inspection.
- `scripts/sglang_gateway.sh`
  Launches an SGLang router or co-launch gateway path for worker routing, PD disaggregation, gRPC mode, and cache-aware load-balancing policies.
- `scripts/sglang_healthcheck.sh`
  Verifies the local SGLang endpoint and optionally runs a lightweight chat smoke test.
- `scripts/sglang_chat.sh`
  Sends a generic OpenAI-compatible chat request to a local SGLang endpoint, with optional tools and optional JSON-schema response format.
- `scripts/sglang_embeddings.sh`
  Calls `/v1/embeddings` for text or JSON input payloads and supports Matryoshka-style output dimension control.
- `scripts/sglang_structured_output.sh`
  Keeps a dedicated JSON-schema wrapper for structured output workflows.
- `scripts/sglang_ranker.sh`
  Uses the structured-output path to rerank candidate passages with schema-constrained JSON.
- `scripts/sglang_scale_pipeline.sh`
  Chains retrieval, reranking, and final answer generation into a scale-oriented local flow.

## Why These Features Matter

The upstream SGLang project emphasizes:

- high-performance OpenAI-compatible serving
- structured outputs
- embeddings
- speculative decoding
- routing and gateway control
- prefill/decode disaggregation
- cache-aware and scale-oriented inference

Those are the parts that materially improve this repo:

1. A local-agent runtime needs a fast serving layer.
2. RAG at scale needs embeddings plus reranking.
3. Multi-agent orchestration benefits from schema-constrained intermediate outputs.
4. A scale path needs gateway routing rather than one monolithic local process.

## Example: Launch a Local SGLang Server

```bash
cd /Users/jimmymalhan/Doc/local-agent-runtime
SGLANG_MODEL_PATH=Qwen/Qwen3-Embedding-0.6B \
SGLANG_IS_EMBEDDING=1 \
bash ./scripts/sglang_server.sh
```

Reasoning/tool parser example:

```bash
SGLANG_MODEL_PATH=Qwen/Qwen3-32B \
SGLANG_REASONING_PARSER=qwen3 \
SGLANG_TOOL_CALL_PARSER=qwen3_coder \
bash ./scripts/sglang_server.sh
```

Speculative decoding example:

```bash
SGLANG_MODEL_PATH=meta-llama/Meta-Llama-3.1-8B-Instruct \
SGLANG_SPECULATIVE_ALGORITHM=EAGLE3 \
SGLANG_SPECULATIVE_DRAFT_MODEL_PATH=jamesliu1/sglang-EAGLE3-Llama-3.1-Instruct-8B \
SGLANG_SPECULATIVE_NUM_STEPS=3 \
SGLANG_SPECULATIVE_EAGLE_TOPK=4 \
SGLANG_SPECULATIVE_NUM_DRAFT_TOKENS=16 \
bash ./scripts/sglang_server.sh
```

## Example: Launch a Gateway

Regular router:

```bash
SGLANG_GATEWAY_WORKER_URLS="http://127.0.0.1:30000 http://127.0.0.1:30001" \
SGLANG_GATEWAY_POLICY=cache_aware \
bash ./scripts/sglang_gateway.sh
```

PD-disaggregated router:

```bash
SGLANG_GATEWAY_PD_DISAGGREGATION=1 \
SGLANG_GATEWAY_PREFILL="http://127.0.0.1:31000 9001" \
SGLANG_GATEWAY_DECODE="http://127.0.0.1:32000" \
bash ./scripts/sglang_gateway.sh
```

## Example: Chat, Embeddings, and Reranking

Chat:

```bash
bash ./scripts/sglang_chat.sh "Explain this repository in 5 bullets."
```

Embeddings:

```bash
SGLANG_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-0.6B \
bash ./scripts/sglang_embeddings.sh "How do I use the local runtime?"
```

Reranking:

```bash
bash ./scripts/sglang_ranker.sh "How do I start the local runtime?" path/to/candidates.json
```

## Scale-Oriented Pipeline

The scale path in this repo is:

1. Retrieve broadly from a local index or Pinecone.
2. Use local SGLang to rerank the larger candidate set.
3. Send only the top passages into the final generation step.

That is implemented in `scripts/sglang_scale_pipeline.sh` and described in more detail in `docs/SGLANG_SCALE_BLUEPRINT.md`.
