#!/bin/bash
set -euo pipefail

QUERY=${1:-}
METHOD=${RAG_METHOD:-local}
RAG_TOP_K=${RAG_TOP_K:-5}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
LOCAL_INDEX_DIR=${LOCAL_INDEX_DIR:-"$(dirname "$0")/../memory/index"}
PINECONE_TOP_K=${PINECONE_TOP_K:-$RAG_TOP_K}
PINECONE_NAMESPACE=${PINECONE_NAMESPACE:-}
PINECONE_INCLUDE_METADATA=${PINECONE_INCLUDE_METADATA:-1}

if [ -z "$QUERY" ]; then
  echo "Usage: $0 '<query>'" >&2
  exit 1
fi

case "$METHOD" in
  pinecone)
    if ! python3 -c "from pinecone import Pinecone" >/dev/null 2>&1; then
      echo "pinecone library not found; install via 'pip install pinecone'" >&2
      echo "Falling back to local retrieval" >&2
      METHOD="local"
    fi
    if [ -z "${PINECONE_API_KEY:-}" ] || { [ -z "${PINECONE_INDEX_NAME:-}" ] && [ -z "${PINECONE_INDEX_HOST:-}" ]; }; then
      echo "PINECONE_API_KEY plus PINECONE_INDEX_NAME or PINECONE_INDEX_HOST must be set for Pinecone retrieval" >&2
      echo "Falling back to local retrieval" >&2
      METHOD="local"
    fi
    if [ -z "${PINECONE_QUERY_VECTOR_JSON:-}" ]; then
      if EMBEDDING_JSON=$(bash "$SCRIPT_DIR/sglang_embeddings.sh" "$QUERY" 2>/dev/null); then
        if PINECONE_QUERY_VECTOR_JSON=$(python3 - "$EMBEDDING_JSON" <<'PY'
import json
import sys

body = json.loads(sys.argv[1])
data = body.get("data", [])
if not data:
    raise SystemExit(1)
print(json.dumps(data[0].get("embedding", [])))
PY
        ); then
          export PINECONE_QUERY_VECTOR_JSON
        else
          echo "Unable to derive Pinecone query vector from local SGLang embeddings" >&2
          echo "Falling back to local retrieval" >&2
          METHOD="local"
        fi
      else
        echo "PINECONE_QUERY_VECTOR_JSON is not set and local SGLang embeddings are unavailable" >&2
        echo "Falling back to local retrieval" >&2
        METHOD="local"
      fi
    fi
    ;;
esac

if [ "$METHOD" = "pinecone" ]; then
  python3 - "$QUERY" <<'PYEOF'
import json
import os
import sys

from pinecone import Pinecone

query = sys.argv[1]
api_key = os.environ["PINECONE_API_KEY"]
index_name = os.environ.get("PINECONE_INDEX_NAME")
index_host = os.environ.get("PINECONE_INDEX_HOST")
namespace = os.environ.get("PINECONE_NAMESPACE", "")
top_k = int(os.environ.get("PINECONE_TOP_K", os.environ.get("RAG_TOP_K", "5")))
include_metadata = os.environ.get("PINECONE_INCLUDE_METADATA", "1") != "0"
query_vector = json.loads(os.environ["PINECONE_QUERY_VECTOR_JSON"])
sparse_indices = os.environ.get("PINECONE_SPARSE_INDICES_JSON")
sparse_values = os.environ.get("PINECONE_SPARSE_VALUES_JSON")

pc = Pinecone(api_key=api_key)
index = pc.Index(host=index_host) if index_host else pc.Index(index_name)

kwargs = {
    "vector": query_vector,
    "top_k": top_k,
    "include_metadata": include_metadata,
}
if namespace:
    kwargs["namespace"] = namespace
if sparse_indices and sparse_values:
    kwargs["sparse_vector"] = {
        "indices": json.loads(sparse_indices),
        "values": json.loads(sparse_values),
    }

response = index.query(**kwargs)
payload = response.to_dict() if hasattr(response, "to_dict") else response
print(json.dumps({"query": query, "method": "pinecone", "results": payload}, indent=2))
PYEOF
  exit 0
fi

python3 - "$QUERY" "$LOCAL_INDEX_DIR" "$RAG_TOP_K" <<'PYEOF'
import json
import pathlib
import sys

query = sys.argv[1]
index_dir = pathlib.Path(sys.argv[2])
top_k = int(sys.argv[3])

try:
    from llama_index.core import StorageContext, load_index_from_storage
except ImportError:
    print(
        json.dumps(
            {
                "query": query,
                "method": "local",
                "error": "llama-index is not installed; install with 'pip install llama-index'",
            },
            indent=2,
        )
    )
    raise SystemExit(1)

if not index_dir.exists():
    print(
        json.dumps(
            {
                "query": query,
                "method": "local",
                "error": f"Local index directory '{index_dir}' not found. Build it with scripts/llamaindex_update.sh",
            },
            indent=2,
        )
    )
    raise SystemExit(1)

storage_context = StorageContext.from_defaults(persist_dir=str(index_dir))
index = load_index_from_storage(storage_context)
engine = index.as_query_engine(similarity_top_k=top_k)
response = engine.query(query)
nodes = []
for source in getattr(response, "source_nodes", [])[:top_k]:
    nodes.append(
        {
            "score": getattr(source, "score", None),
            "text": getattr(getattr(source, "node", None), "text", "")[:1600],
            "metadata": getattr(getattr(source, "node", None), "metadata", {}),
        }
    )

print(json.dumps({"query": query, "method": "local", "response": str(response), "results": nodes}, indent=2))
PYEOF
