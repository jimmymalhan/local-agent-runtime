#!/bin/bash
set -euo pipefail

QUERY=${1:-}
CANDIDATES_FILE=${2:-}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
SGLANG_MODEL=${SGLANG_MODEL:-qwen2.5-coder:7b}
RERANK_CANDIDATE_LIMIT=${RERANK_CANDIDATE_LIMIT:-20}

if [ -z "$QUERY" ] || [ -z "$CANDIDATES_FILE" ]; then
  echo "Usage: $0 '<query>' <candidates-json-file>" >&2
  exit 1
fi

if [ ! -f "$CANDIDATES_FILE" ]; then
  echo "Candidates file not found: $CANDIDATES_FILE" >&2
  exit 1
fi

PROMPT=$(python3 - "$QUERY" "$CANDIDATES_FILE" "$SCRIPT_DIR/normalize_retrieval_results.py" "$RERANK_CANDIDATE_LIMIT" <<'PY'
import json
import pathlib
import sys

query = sys.argv[1]
candidates_path = pathlib.Path(sys.argv[2])
normalizer_path = pathlib.Path(sys.argv[3])
limit = int(sys.argv[4])
body = json.loads(candidates_path.read_text())
normalized = json.loads(
    __import__("subprocess").run(
        ["python3", str(normalizer_path), str(candidates_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
)
items = normalized.get("results", [])

rendered = []
for idx, item in enumerate(items[:limit], start=1):
    text = item.get("text") or json.dumps(item)
    metadata = item.get("metadata", {})
    rendered.append(f"[{idx}] {text[:1200]}\nmetadata={json.dumps(metadata, ensure_ascii=True)}")

prompt = "\n\n".join(
    [
        "Rank the candidate passages for the query below.",
        f"Query: {query}",
        "Return only the best-first ranking and a short rationale.",
        "Candidates:",
        "\n".join(rendered),
    ]
)
print(prompt)
PY
)

SCHEMA_FILE=$(mktemp)
cat >"$SCHEMA_FILE" <<'EOF'
{
  "title": "rerank_result",
  "type": "object",
  "properties": {
    "ranking": {
      "type": "array",
      "items": {
        "type": "integer",
        "minimum": 1
      }
    },
    "rationale": {
      "type": "string"
    }
  },
  "required": ["ranking", "rationale"],
  "additionalProperties": false
}
EOF

trap 'rm -f "$SCHEMA_FILE"' EXIT
SGLANG_MODEL=$SGLANG_MODEL \
SGLANG_RESPONSE_FORMAT_SCHEMA_FILE="$SCHEMA_FILE" \
bash "$SCRIPT_DIR/sglang_chat.sh" "$PROMPT"
