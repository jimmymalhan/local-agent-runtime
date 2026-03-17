#!/bin/bash
set -euo pipefail

PROMPT=${1:-}
SGLANG_API_URL=${SGLANG_API_URL:-http://127.0.0.1:30000/v1/chat/completions}
SGLANG_MODEL=${SGLANG_MODEL:-qwen2.5-coder:7b}
SGLANG_SYSTEM_PROMPT=${SGLANG_SYSTEM_PROMPT:-}
SGLANG_MESSAGES_FILE=${SGLANG_MESSAGES_FILE:-}
SGLANG_TOOLS_FILE=${SGLANG_TOOLS_FILE:-}
SGLANG_TOOL_CHOICE=${SGLANG_TOOL_CHOICE:-}
SGLANG_RESPONSE_FORMAT_SCHEMA_FILE=${SGLANG_RESPONSE_FORMAT_SCHEMA_FILE:-}
SGLANG_TEMPERATURE=${SGLANG_TEMPERATURE:-0}
SGLANG_TOP_P=${SGLANG_TOP_P:-1}
SGLANG_MAX_TOKENS=${SGLANG_MAX_TOKENS:-1024}
SGLANG_STREAM=${SGLANG_STREAM:-0}

if [ -z "$PROMPT" ] && [ -z "$SGLANG_MESSAGES_FILE" ]; then
  echo "Usage: $0 '<prompt>'" >&2
  echo "Or set SGLANG_MESSAGES_FILE to a JSON messages array." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required to call the local SGLang endpoint." >&2
  exit 1
fi

PAYLOAD=$(python3 - "$PROMPT" "$SGLANG_MODEL" "$SGLANG_SYSTEM_PROMPT" "$SGLANG_MESSAGES_FILE" "$SGLANG_TOOLS_FILE" "$SGLANG_TOOL_CHOICE" "$SGLANG_RESPONSE_FORMAT_SCHEMA_FILE" "$SGLANG_TEMPERATURE" "$SGLANG_TOP_P" "$SGLANG_MAX_TOKENS" "$SGLANG_STREAM" <<'PY'
import json
import pathlib
import sys

prompt, model, system_prompt, messages_file, tools_file, tool_choice, schema_file, temperature, top_p, max_tokens, stream = sys.argv[1:]

if messages_file:
    messages = json.loads(pathlib.Path(messages_file).read_text())
else:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

payload = {
    "model": model,
    "messages": messages,
    "temperature": float(temperature),
    "top_p": float(top_p),
    "max_tokens": int(max_tokens),
    "stream": stream == "1",
}

if tools_file:
    payload["tools"] = json.loads(pathlib.Path(tools_file).read_text())
if tool_choice:
    payload["tool_choice"] = tool_choice
if schema_file:
    schema = json.loads(pathlib.Path(schema_file).read_text())
    payload["response_format"] = {
        "type": "json_schema",
        "json_schema": {
            "name": schema.get("title", "structured_output"),
            "schema": schema,
        },
    }

print(json.dumps(payload))
PY
)

if [ "$SGLANG_STREAM" = "1" ]; then
  curl --no-buffer -sS "$SGLANG_API_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"
else
  curl -sS "$SGLANG_API_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD"
fi
