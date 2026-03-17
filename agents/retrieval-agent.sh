#!/bin/bash
# Agent: Retrieval
# Performs retrieval‑augmented generation (RAG) by pulling relevant
# context from a local vector store (via LlamaIndex) or an optional
# Pinecone index.  This agent runs before architecture planning so
# that downstream agents receive enriched context.

PROMPT="$1"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="$(dirname "$0")/../logs"
mkdir -p "$LOG_DIR"

# The RAG retrieval method can be set via the RAG_METHOD environment
# variable.  Valid values are "local" (default) or "pinecone".  When
# using Pinecone, ensure that PINECONE_API_KEY and PINECONE_INDEX_NAME
# are set in your environment.  See scripts/rag_retrieval.sh for
# details.

METHOD=${RAG_METHOD:-local}

echo "$TIMESTAMP – retrieval-agent starting (method: $METHOD)" >> "$LOG_DIR/agents.log"

"$(dirname "$0")/../scripts/rag_retrieval.sh" "$PROMPT" >> "$LOG_DIR/retrieval.log" 2>&1

echo "$TIMESTAMP – retrieval-agent finished" >> "$LOG_DIR/agents.log"

exit 0