#!/bin/bash
set -euo pipefail

GATEWAY_MODE=${SGLANG_GATEWAY_MODE:-router}
HOST=${SGLANG_GATEWAY_HOST:-0.0.0.0}
PORT=${SGLANG_GATEWAY_PORT:-30080}
POLICY=${SGLANG_GATEWAY_POLICY:-cache_aware}
LOG_LEVEL=${SGLANG_GATEWAY_LOG_LEVEL:-info}
MODEL_PATH=${SGLANG_GATEWAY_MODEL_PATH:-}
TOKENIZER_PATH=${SGLANG_GATEWAY_TOKENIZER_PATH:-}
WORKER_URLS=${SGLANG_GATEWAY_WORKER_URLS:-}
REASONING_PARSER=${SGLANG_GATEWAY_REASONING_PARSER:-}
TOOL_CALL_PARSER=${SGLANG_GATEWAY_TOOL_CALL_PARSER:-}
PREFILL=${SGLANG_GATEWAY_PREFILL:-}
DECODE=${SGLANG_GATEWAY_DECODE:-}
PREFILL_POLICY=${SGLANG_GATEWAY_PREFILL_POLICY:-cache_aware}
DECODE_POLICY=${SGLANG_GATEWAY_DECODE_POLICY:-power_of_two}
ENABLE_IGW=${SGLANG_GATEWAY_ENABLE_IGW:-0}
PD_DISAGGREGATION=${SGLANG_GATEWAY_PD_DISAGGREGATION:-0}
GRPC_MODE=${SGLANG_GATEWAY_GRPC_MODE:-0}
DRY_RUN=${SGLANG_DRY_RUN:-0}

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to launch the SGLang gateway." >&2
  exit 1
fi

case "$GATEWAY_MODE" in
  router)
    ARGS=(
      python3 -m sglang_router.launch_router
      --host "$HOST"
      --port "$PORT"
      --policy "$POLICY"
      --log-level "$LOG_LEVEL"
    )
    if [ -n "$MODEL_PATH" ]; then
      ARGS+=(--model-path "$MODEL_PATH")
    fi
    if [ -n "$TOKENIZER_PATH" ]; then
      ARGS+=(--tokenizer-path "$TOKENIZER_PATH")
    fi
    if [ -n "$REASONING_PARSER" ]; then
      ARGS+=(--reasoning-parser "$REASONING_PARSER")
    fi
    if [ -n "$TOOL_CALL_PARSER" ]; then
      ARGS+=(--tool-call-parser "$TOOL_CALL_PARSER")
    fi
    if [ "$ENABLE_IGW" = "1" ]; then
      ARGS+=(--enable-igw)
    fi
    if [ "$PD_DISAGGREGATION" = "1" ]; then
      ARGS+=(--pd-disaggregation --prefill-policy "$PREFILL_POLICY" --decode-policy "$DECODE_POLICY")
      if [ -n "$PREFILL" ]; then
        # shellcheck disable=SC2206
        PREFILL_ITEMS=($PREFILL)
        ARGS+=(--prefill "${PREFILL_ITEMS[@]}")
      fi
      if [ -n "$DECODE" ]; then
        # shellcheck disable=SC2206
        DECODE_ITEMS=($DECODE)
        ARGS+=(--decode "${DECODE_ITEMS[@]}")
      fi
    elif [ -n "$WORKER_URLS" ]; then
      # shellcheck disable=SC2206
      WORKER_ITEMS=($WORKER_URLS)
      ARGS+=(--worker-urls "${WORKER_ITEMS[@]}")
    fi
    if [ "$GRPC_MODE" = "1" ]; then
      ARGS+=(--grpc-mode)
    fi
    ;;
  server)
    MODEL=${1:-${SGLANG_GATEWAY_MODEL_PATH:-}}
    if [ -z "$MODEL" ]; then
      echo "Set SGLANG_GATEWAY_MODEL_PATH or pass a model path for server mode." >&2
      exit 1
    fi
    TP_SIZE=${SGLANG_GATEWAY_TP_SIZE:-1}
    DP_SIZE=${SGLANG_GATEWAY_DP_SIZE:-1}
    ROUTER_POLICY=${SGLANG_GATEWAY_ROUTER_POLICY:-cache_aware}
    ARGS=(
      python3 -m sglang_router.launch_server
      --model "$MODEL"
      --host "$HOST"
      --port "$PORT"
      --tp-size "$TP_SIZE"
      --dp-size "$DP_SIZE"
      --router-policy "$ROUTER_POLICY"
      --log-level "$LOG_LEVEL"
    )
    if [ "$GRPC_MODE" = "1" ]; then
      ARGS+=(--grpc-mode)
    fi
    if [ -n "$TOOL_CALL_PARSER" ]; then
      ARGS+=(--router-tool-call-parser "$TOOL_CALL_PARSER")
    fi
    if [ -n "$MODEL_PATH" ]; then
      ARGS+=(--router-model-path "$MODEL_PATH")
    fi
    ;;
  *)
    echo "Unknown SGLANG_GATEWAY_MODE: $GATEWAY_MODE" >&2
    exit 1
    ;;
esac

printf 'Launching SGLang gateway:\n%s\n' "${ARGS[*]}"
if [ "$DRY_RUN" = "1" ]; then
  exit 0
fi
exec "${ARGS[@]}"
