#!/bin/bash
set -euo pipefail

PROMPT=${1:-}
SCHEMA_FILE=${2:-}
SGLANG_API_URL=${SGLANG_API_URL:-http://127.0.0.1:30000/v1/chat/completions}
SGLANG_MODEL=${SGLANG_MODEL:-qwen/qwen2.5-0.5b-instruct}

if [ -z "$PROMPT" ] || [ -z "$SCHEMA_FILE" ]; then
  echo "Usage: $0 '<prompt>' <json-schema-file>" >&2
  exit 1
fi

if [ ! -f "$SCHEMA_FILE" ]; then
  echo "Schema file not found: $SCHEMA_FILE" >&2
  exit 1
fi

PAYLOAD=$(python3 - "$PROMPT" "$SCHEMA_FILE" "$SGLANG_MODEL" <<'PYEOF'
import json
import pathlib
import sys

prompt = sys.argv[1]
schema = json.loads(pathlib.Path(sys.argv[2]).read_text())
model = sys.argv[3]

payload = {
    "model": model,
    "messages": [{"role": "user", "content": prompt}],
    "temperature": 0.0,
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": schema.get("title", "structured_output"),
            "schema": schema,
        },
    },
}
print(json.dumps(payload))
PYEOF
)

curl -sS "$SGLANG_API_URL" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD"
