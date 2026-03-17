#!/bin/bash
set -euo pipefail

QUERY=${1:-}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
STAMP=$(date '+%Y%m%d_%H%M%S')
OUT_DIR="$REPO_ROOT/logs/sglang-scale-pipeline-$STAMP"
ENABLE_SGLANG_RERANK=${ENABLE_SGLANG_RERANK:-1}
ENABLE_SGLANG_FINAL_ANSWER=${ENABLE_SGLANG_FINAL_ANSWER:-1}
SCALE_PROFILE=${SCALE_PROFILE:-balanced}
TOP_CONTEXTS=${TOP_CONTEXTS:-}
RERANK_CANDIDATE_LIMIT=${RERANK_CANDIDATE_LIMIT:-}

case "$SCALE_PROFILE" in
  fast)
    : "${RAG_TOP_K:=20}"
    : "${RERANK_CANDIDATE_LIMIT:=20}"
    : "${TOP_CONTEXTS:=4}"
    ;;
  exhaustive)
    : "${RAG_TOP_K:=80}"
    : "${RERANK_CANDIDATE_LIMIT:=60}"
    : "${TOP_CONTEXTS:=8}"
    ;;
  *)
    : "${RAG_TOP_K:=40}"
    : "${RERANK_CANDIDATE_LIMIT:=30}"
    : "${TOP_CONTEXTS:=6}"
    ;;
esac
export RAG_TOP_K RERANK_CANDIDATE_LIMIT

if [ -z "$QUERY" ]; then
  echo "Usage: $0 '<query>'" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"

bash "$SCRIPT_DIR/rag_retrieval.sh" "$QUERY" > "$OUT_DIR/retrieval.json"
python3 "$SCRIPT_DIR/normalize_retrieval_results.py" "$OUT_DIR/retrieval.json" > "$OUT_DIR/normalized-retrieval.json"

cat > "$OUT_DIR/manifest.json" <<EOF
{
  "query": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$QUERY"),
  "scale_profile": "$SCALE_PROFILE",
  "rag_top_k": $RAG_TOP_K,
  "rerank_candidate_limit": $RERANK_CANDIDATE_LIMIT,
  "top_contexts": $TOP_CONTEXTS,
  "principles": [
    "separate retrieval from reranking and final generation",
    "keep ranking on a scoring-focused fast path",
    "preserve dense batches where possible",
    "narrow the final prompt to the best reranked context"
  ]
}
EOF

SOURCE_JSON="$OUT_DIR/retrieval.json"
if [ "$ENABLE_SGLANG_RERANK" = "1" ]; then
  bash "$SCRIPT_DIR/sglang_ranker.sh" "$QUERY" "$OUT_DIR/retrieval.json" > "$OUT_DIR/rerank.json"
  SOURCE_JSON="$OUT_DIR/rerank.json"
fi

if [ "$ENABLE_SGLANG_FINAL_ANSWER" = "1" ]; then
  PROMPT_FILE="$OUT_DIR/final-prompt.txt"
  python3 - "$QUERY" "$OUT_DIR/normalized-retrieval.json" "$SOURCE_JSON" "$TOP_CONTEXTS" <<'PY' > "$PROMPT_FILE"
import json
import pathlib
import sys

query, retrieval_path, ranking_path, top_contexts = sys.argv[1:]
retrieval = json.loads(pathlib.Path(retrieval_path).read_text())
ranking = json.loads(pathlib.Path(ranking_path).read_text()) if pathlib.Path(ranking_path).exists() else {}
results = retrieval.get("results", [])

order = ranking.get("ranking") or ranking.get("results", {}).get("ranking") or []
ordered = []
for item in order:
    try:
        idx = int(item) - 1
    except Exception:
        continue
    if 0 <= idx < len(results):
        ordered.append(results[idx])
if not ordered:
    ordered = results

chunks = []
for idx, item in enumerate(ordered[: int(top_contexts)], start=1):
    text = item.get("text") or json.dumps(item)
    metadata = item.get("metadata", {})
    chunks.append(f"[{idx}] {text[:1600]}\nmetadata={json.dumps(metadata, ensure_ascii=True)}")

print("\n\n".join([
    "Answer the query using the reranked context below.",
    f"Query: {query}",
    "If the context is incomplete, say exactly what is missing.",
    "Context:",
    "\n\n".join(chunks),
]))
PY
  bash "$SCRIPT_DIR/sglang_chat.sh" "$(cat "$PROMPT_FILE")" > "$OUT_DIR/answer.json"
fi

echo "$OUT_DIR"
