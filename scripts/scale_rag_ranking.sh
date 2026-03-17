#!/bin/bash
set -euo pipefail

QUERY=${1:-}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
STAMP=$(date '+%Y%m%d_%H%M%S')
OUT_DIR="$REPO_ROOT/logs/rag-ranking-$STAMP"

if [ -z "$QUERY" ]; then
  echo "Usage: $0 '<query>'" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
bash "$SCRIPT_DIR/rag_retrieval.sh" "$QUERY" > "$OUT_DIR/retrieval.json"

if [ "${ENABLE_SGLANG_RERANK:-0}" = "1" ]; then
  bash "$SCRIPT_DIR/sglang_ranker.sh" "$QUERY" "$OUT_DIR/retrieval.json" > "$OUT_DIR/rerank.json"
  echo "$OUT_DIR/rerank.json"
else
  echo "$OUT_DIR/retrieval.json"
fi
