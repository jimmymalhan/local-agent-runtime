#!/bin/bash
set -euo pipefail

MODEL_PATH=${1:-${SGLANG_MODEL_PATH:-qwen/qwen2.5-0.5b-instruct}}
HOST=${SGLANG_HOST:-0.0.0.0}
PORT=${SGLANG_PORT:-30000}
TP_SIZE=${SGLANG_TP_SIZE:-${SGLANG_TP:-1}}
DP_SIZE=${SGLANG_DP_SIZE:-${SGLANG_DP:-1}}
MEM_FRACTION=${SGLANG_MEM_FRACTION_STATIC:-0.8}
CHUNKED_PREFILL_SIZE=${SGLANG_CHUNKED_PREFILL_SIZE:-4096}
LOG_LEVEL=${SGLANG_LOG_LEVEL:-warning}
QUANTIZATION=${SGLANG_QUANTIZATION:-}
SERVED_MODEL_NAME=${SGLANG_SERVED_MODEL_NAME:-}
CHAT_TEMPLATE=${SGLANG_CHAT_TEMPLATE:-}
JSON_MODEL_OVERRIDE_ARGS=${SGLANG_JSON_MODEL_OVERRIDE_ARGS:-}
LORA_PATHS=${SGLANG_LORA_PATHS:-}
SPECULATIVE_ALGORITHM=${SGLANG_SPECULATIVE_ALGORITHM:-}
SPECULATIVE_DRAFT_MODEL_PATH=${SGLANG_SPECULATIVE_DRAFT_MODEL_PATH:-}
SPECULATIVE_NUM_STEPS=${SGLANG_SPECULATIVE_NUM_STEPS:-}
SPECULATIVE_EAGLE_TOPK=${SGLANG_SPECULATIVE_EAGLE_TOPK:-}
SPECULATIVE_NUM_DRAFT_TOKENS=${SGLANG_SPECULATIVE_NUM_DRAFT_TOKENS:-}
SPECULATIVE_TOKEN_MAP=${SGLANG_SPECULATIVE_TOKEN_MAP:-}
REASONING_PARSER=${SGLANG_REASONING_PARSER:-}
TOOL_CALL_PARSER=${SGLANG_TOOL_CALL_PARSER:-}
DIST_INIT_ADDR=${SGLANG_DIST_INIT_ADDR:-}
API_KEY=${SGLANG_API_KEY:-}
ENABLE_METRICS=${SGLANG_ENABLE_METRICS:-1}
ENABLE_TORCH_COMPILE=${SGLANG_ENABLE_TORCH_COMPILE:-0}
ENABLE_DETERMINISTIC=${SGLANG_ENABLE_DETERMINISTIC:-0}
ENABLE_LORA=${SGLANG_ENABLE_LORA:-0}
ENABLE_DP_ATTENTION=${SGLANG_ENABLE_DP_ATTENTION:-0}
ENABLE_CACHE_REPORT=${SGLANG_ENABLE_CACHE_REPORT:-0}
TRUST_REMOTE_CODE=${SGLANG_TRUST_REMOTE_CODE:-0}
IS_EMBEDDING=${SGLANG_IS_EMBEDDING:-0}
GRPC_MODE=${SGLANG_GRPC_MODE:-0}
DISABLE_CUDA_GRAPH=${SGLANG_DISABLE_CUDA_GRAPH:-0}
DRY_RUN=${SGLANG_DRY_RUN:-0}

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to launch SGLang." >&2
  exit 1
fi

ARGS=(
  python3 -m sglang.launch_server
  --model-path "$MODEL_PATH"
  --host "$HOST"
  --port "$PORT"
  --tp-size "$TP_SIZE"
  --dp-size "$DP_SIZE"
  --mem-fraction-static "$MEM_FRACTION"
  --chunked-prefill-size "$CHUNKED_PREFILL_SIZE"
  --log-level "$LOG_LEVEL"
)

if [ "$ENABLE_METRICS" = "1" ]; then
  ARGS+=(--enable-metrics)
fi
if [ "$ENABLE_TORCH_COMPILE" = "1" ]; then
  ARGS+=(--enable-torch-compile)
fi
if [ "$ENABLE_DETERMINISTIC" = "1" ]; then
  ARGS+=(--enable-deterministic-inference)
fi
if [ "$ENABLE_LORA" = "1" ]; then
  ARGS+=(--enable-lora)
fi
if [ "$ENABLE_DP_ATTENTION" = "1" ]; then
  ARGS+=(--enable-dp-attention)
fi
if [ "$ENABLE_CACHE_REPORT" = "1" ]; then
  ARGS+=(--enable-cache-report)
fi
if [ "$TRUST_REMOTE_CODE" = "1" ]; then
  ARGS+=(--trust-remote-code)
fi
if [ "$IS_EMBEDDING" = "1" ]; then
  ARGS+=(--is-embedding)
fi
if [ "$GRPC_MODE" = "1" ]; then
  ARGS+=(--grpc-mode)
fi
if [ "$DISABLE_CUDA_GRAPH" = "1" ]; then
  ARGS+=(--disable-cuda-graph)
fi
if [ -n "$QUANTIZATION" ]; then
  ARGS+=(--quantization "$QUANTIZATION")
fi
if [ -n "$SERVED_MODEL_NAME" ]; then
  ARGS+=(--served-model-name "$SERVED_MODEL_NAME")
fi
if [ -n "$CHAT_TEMPLATE" ]; then
  ARGS+=(--chat-template "$CHAT_TEMPLATE")
fi
if [ -n "$JSON_MODEL_OVERRIDE_ARGS" ]; then
  ARGS+=(--json-model-override-args "$JSON_MODEL_OVERRIDE_ARGS")
fi
if [ -n "$LORA_PATHS" ]; then
  # shellcheck disable=SC2206
  LORA_ITEMS=($LORA_PATHS)
  ARGS+=(--lora-paths "${LORA_ITEMS[@]}")
fi
if [ -n "$SPECULATIVE_ALGORITHM" ]; then
  ARGS+=(--speculative-algorithm "$SPECULATIVE_ALGORITHM")
fi
if [ -n "$SPECULATIVE_DRAFT_MODEL_PATH" ]; then
  ARGS+=(--speculative-draft-model-path "$SPECULATIVE_DRAFT_MODEL_PATH")
fi
if [ -n "$SPECULATIVE_NUM_STEPS" ]; then
  ARGS+=(--speculative-num-steps "$SPECULATIVE_NUM_STEPS")
fi
if [ -n "$SPECULATIVE_EAGLE_TOPK" ]; then
  ARGS+=(--speculative-eagle-topk "$SPECULATIVE_EAGLE_TOPK")
fi
if [ -n "$SPECULATIVE_NUM_DRAFT_TOKENS" ]; then
  ARGS+=(--speculative-num-draft-tokens "$SPECULATIVE_NUM_DRAFT_TOKENS")
fi
if [ -n "$SPECULATIVE_TOKEN_MAP" ]; then
  ARGS+=(--speculative-token-map "$SPECULATIVE_TOKEN_MAP")
fi
if [ -n "$REASONING_PARSER" ]; then
  ARGS+=(--reasoning-parser "$REASONING_PARSER")
fi
if [ -n "$TOOL_CALL_PARSER" ]; then
  ARGS+=(--tool-call-parser "$TOOL_CALL_PARSER")
fi
if [ -n "$DIST_INIT_ADDR" ]; then
  ARGS+=(--dist-init-addr "$DIST_INIT_ADDR")
fi
if [ -n "$API_KEY" ]; then
  ARGS+=(--api-key "$API_KEY")
fi

printf 'Launching SGLang server:\n%s\n' "${ARGS[*]}"
if [ "$DRY_RUN" = "1" ]; then
  exit 0
fi
exec "${ARGS[@]}"
