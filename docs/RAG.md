# Retrieval‑Augmented Generation (RAG)

Retrieval‑augmented generation (RAG) is an approach that combines a
large language model (LLM) with an **external knowledge store**
(typically a vector database) to provide more accurate, up‑to‑date
responses.  Instead of relying solely on the LLM’s internal
parameters, RAG systems retrieve relevant information from your own
documents and inject it into the model’s prompt.  This reduces
hallucinations and enables the model to answer questions about
proprietary or recent data【462684992376271†L120-L133】.

## Core Components

The RAG pipeline consists of four stages【462684992376271†L120-L133】:

1. **Ingestion** – Your source documents are parsed, chunked and
   embedded into vectors.  These vectors are stored in a vector
   database (e.g. a local index built with LlamaIndex or a remote
   Pinecone index).
2. **Retrieval** – When a user query arrives, the system generates a
   query embedding and performs a similarity search against the vector
   database to retrieve the most relevant documents【462684992376271†L139-L142】.
3. **Augmentation** – The retrieved documents are combined with the
   user query to create a richer prompt, grounding the LLM’s response
   on authoritative data【462684992376271†L139-L142】.
4. **Generation** – The LLM produces an answer using both the query and
   the retrieved context【462684992376271†L139-L142】.  This yields outputs
   that are more factual, trustworthy and aligned with your data【462684992376271†L145-L156】.

Benefits of RAG include access to real‑time or proprietary data,
increased trustworthiness and reduced hallucination【462684992376271†L145-L156】.

## RAG in This Repository

This framework supports RAG through a **retrieval agent** and the
`scripts/rag_retrieval.sh` helper.  By default, retrieval uses a
local vector store built with **LlamaIndex**.  Alternatively, you can
optionally query a remote **Pinecone** index when explicitly
configured.  Use RAG only when your project requires grounding on
external documents—many tasks can be solved without retrieval.

### Building a Local Index

1. Install LlamaIndex: `pip install llama-index`.
2. Collect the documents you want to search and place them in a
   directory (e.g. `./documents`).
3. Build the index by running:

   ```bash
   ./scripts/llamaindex_update.sh ./documents ./memory/index
   ```

This script reads all files in the `documents` directory, creates a
vector index and saves it to `memory/index`.  You can rebuild
the index whenever your documents change.

### Running Retrieval

The **retrieval agent** (`agents/retrieval-agent.sh`) runs before
architecture planning.  It calls `scripts/rag_retrieval.sh` with the
user’s prompt.  The helper script checks whether the `RAG_METHOD`
environment variable is set to `pinecone` or `local` (default).  If
`pinecone` is selected, the script attempts to query a Pinecone
index using your `PINECONE_API_KEY` and either `PINECONE_INDEX_NAME`
or `PINECONE_INDEX_HOST`.  It also supports namespace-aware retrieval,
top-k controls, and optional dense+sparse hybrid search when you
provide sparse vectors.  If those variables are missing or the
Pinecone client is unavailable, the script falls back to local
retrieval.

Example usage from the command line:

```bash
export RAG_METHOD=local  # or pinecone
./scripts/rag_retrieval.sh "How does the billing system work?"
```

The output will be the retrieved context relevant to your query.

### Pinecone (Optional)

Pinecone is a managed vector database.  To use Pinecone with this
framework, set `RAG_METHOD=pinecone` and provide the following
variables:

```bash
export PINECONE_API_KEY="<your-api-key>"
export PINECONE_INDEX_NAME="<your-index-name>"
export PINECONE_NAMESPACE="default"
export PINECONE_QUERY_VECTOR_JSON='[0.1, 0.2, ...]'
```

Ensure you have installed the Pinecone Python package (`pip install
pinecone`) and implemented a local embedding pipeline to generate the
query vector JSON.  If you want hybrid search, also provide sparse
indices and sparse values.  The helper is designed to query Pinecone
once you provide these vectors.

## Scaling Retrieval and Ranking

For higher-throughput workloads, keep retrieval and ranking separate:

1. retrieve many candidates from Pinecone or the local index
2. rerank them with a dedicated local SGLang service
3. send only the best passages into the final generation step

See `docs/SGLANG_RAG_SCALING.md` and `scripts/scale_rag_ranking.sh`.

### Agentic RAG Workflows

For complex tasks, agents can orchestrate RAG by constructing
queries, retrieving data, evaluating the results and applying
reasoning to decide which context to trust or discard【462684992376271†L160-L174】.
This repository’s nested sub‑agent architecture (see
`docs/NESTED_AGENTS.md`) allows you to implement multi‑step RAG
workflows where a high‑level agent delegates retrieval and
evaluation to sub‑agents.  Use such workflows when answers depend on
detailed research or multiple sources.
