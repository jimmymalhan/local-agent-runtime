#!/bin/bash
set -euo pipefail

INPUT_TEXT=${1:-}
SGLANG_EMBEDDING_API_URL=${SGLANG_EMBEDDING_API_URL:-http://127.0.0.1:30000/v1/embeddings}
SGLANG_EMBEDDING_MODEL=${SGLANG_EMBEDDING_MODEL:-Qwen/Qwen3-Embedding-0.6B}
SGLANG_INPUT_FILE=${SGLANG_INPUT_FILE:-}
SGLANG_ENCODING_FORMAT=${SGLANG_ENCODING_FORMAT:-float}
SGLANG_DIMENSIONS=${SGLANG_DIMENSIONS:-}

if [ -z "$INPUT_TEXT" ] && [ -z "$SGLANG_INPUT_FILE" ]; then
  echo "Usage: $0 '<text to embed>'" >&2
  echo "Or set SGLANG_INPUT_FILE to a JSON string/list payload file." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to call the local SGLang embedding endpoint." >&2
  exit 1
fi

PAYLOAD=$(python3 - "$INPUT_TEXT" "$SGLANG_EMBEDDING_MODEL" "$SGLANG_INPUT_FILE" "$SGLANG_ENCODING_FORMAT" "$SGLANG_DIMENSIONS" <<'PY'
import json
import pathlib
import sys

input_text, model, input_file, encoding_format, dimensions = sys.argv[1:]

if input_file:
    input_value = json.loads(pathlib.Path(input_file).read_text())
else:
    input_value = input_text

payload = {
    "model": model,
    "input": input_value,
    "encoding_format": encoding_format,
}
if dimensions:
    payload["dimensions"] = int(dimensions)

print(json.dumps(payload))
PY
)

curl -sS "$SGLANG_EMBEDDING_API_URL" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD"
