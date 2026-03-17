#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
RUNTIME_JSON="$REPO_ROOT/config/runtime.json"

ACTIVE_PROFILE=${LOCAL_AGENT_MODE:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("default_profile", "balanced"))' "$RUNTIME_JSON")}
eval "$(python3 - "$RUNTIME_JSON" "$ACTIVE_PROFILE" <<'PY'
import json
import shlex
import sys

cfg = json.load(open(sys.argv[1]))
profile = cfg.get("profiles", {}).get(sys.argv[2], {})
limits = dict(cfg.get("resource_limits", {}))
limits.update(profile.get("resource_limits", {}))
values = {
    "DEFAULT_MODEL": cfg["default_model"],
    "CPU_LIMIT_DEFAULT": limits.get("cpu_percent", 70),
    "MEMORY_LIMIT_DEFAULT": limits.get("memory_percent", 70),
    "OLLAMA_NUM_PARALLEL_DEFAULT": limits.get("ollama_num_parallel", 2),
    "OLLAMA_MAX_LOADED_MODELS_DEFAULT": limits.get("ollama_max_loaded_models", 2),
    "OLLAMA_KEEP_ALIVE_DEFAULT": limits.get("ollama_keep_alive", "5m"),
    "OLLAMA_NUM_CTX_DEFAULT": profile.get("num_ctx", cfg.get("num_ctx", 32768)),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(str(value))}")
PY
)"
CPU_LIMIT=${LOCAL_AGENT_MAX_CPU_PERCENT:-$CPU_LIMIT_DEFAULT}
MEMORY_LIMIT=${LOCAL_AGENT_MAX_MEMORY_PERCENT:-$MEMORY_LIMIT_DEFAULT}
OLLAMA_NUM_PARALLEL=${OLLAMA_NUM_PARALLEL:-$OLLAMA_NUM_PARALLEL_DEFAULT}
OLLAMA_MAX_LOADED_MODELS=${OLLAMA_MAX_LOADED_MODELS:-$OLLAMA_MAX_LOADED_MODELS_DEFAULT}
OLLAMA_KEEP_ALIVE=${OLLAMA_KEEP_ALIVE:-$OLLAMA_KEEP_ALIVE_DEFAULT}
OLLAMA_NUM_CTX=${OLLAMA_NUM_CTX:-$OLLAMA_NUM_CTX_DEFAULT}
TEAM_MODELS=$(python3 - "$RUNTIME_JSON" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1]))
models = [cfg["default_model"]]
for item in cfg.get("team", {}).values():
    if item.get("model"):
        models.append(item["model"])
    models.extend(item.get("fallback_models", []))
seen = []
for model in models:
    if model not in seen:
        seen.append(model)
print("\n".join(seen))
PY
)

mkdir -p "$REPO_ROOT/logs" "$REPO_ROOT/state" "$REPO_ROOT/memory" "$REPO_ROOT/context"

export OLLAMA_NUM_PARALLEL
export OLLAMA_MAX_LOADED_MODELS
export OLLAMA_KEEP_ALIVE

if ! command -v ollama >/dev/null 2>&1; then
  echo "ollama is required but not installed." >&2
  exit 1
fi

if ! ollama list >/dev/null 2>&1; then
  python3 - "$REPO_ROOT/logs/ollama.log" "$REPO_ROOT/state/ollama.pid" <<'PY'
import os
import pathlib
import subprocess
import sys

log_path = pathlib.Path(sys.argv[1])
pid_path = pathlib.Path(sys.argv[2])
env = os.environ.copy()
with log_path.open("ab") as log_handle:
    proc = subprocess.Popen(
        ["ollama", "serve"],
        stdin=subprocess.DEVNULL,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
pid_path.write_text(f"{proc.pid}\n")
PY
  sleep 5
fi

while IFS= read -r model; do
  [ -n "$model" ] || continue
  if ! ollama list | awk '{print $1}' | grep -Fx "$model" >/dev/null 2>&1; then
    ollama pull "$model" >/dev/null
  fi
done <<< "$TEAM_MODELS"

python3 "$SCRIPT_DIR/model_registry.py" --write >/dev/null 2>&1 || true

cat >"$REPO_ROOT/state/runtime.env" <<EOF
LOCAL_AGENT_BACKEND=ollama
LOCAL_AGENT_BASE_URL=http://127.0.0.1:11434
LOCAL_AGENT_DEFAULT_MODEL=$DEFAULT_MODEL
LOCAL_AGENT_MODE=$ACTIVE_PROFILE
LOCAL_AGENT_TARGET_REPO=${LOCAL_AGENT_TARGET_REPO:-$PWD}
LOCAL_AGENT_MAX_CPU_PERCENT=$CPU_LIMIT
LOCAL_AGENT_MAX_MEMORY_PERCENT=$MEMORY_LIMIT
OLLAMA_NUM_PARALLEL=$OLLAMA_NUM_PARALLEL
OLLAMA_MAX_LOADED_MODELS=$OLLAMA_MAX_LOADED_MODELS
OLLAMA_KEEP_ALIVE=$OLLAMA_KEEP_ALIVE
EOF

echo "$REPO_ROOT/state/runtime.env"
