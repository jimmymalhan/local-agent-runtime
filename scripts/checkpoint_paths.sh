#!/bin/bash

canonical_path() {
  local input=${1:-}
  if [ -z "$input" ]; then
    return 1
  fi
  python3 - "$input" <<'PY'
import pathlib
import sys

print(pathlib.Path(sys.argv[1]).resolve())
PY
}

checkpoint_root() {
  local target_dir=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
  local canon
  canon=$(canonical_path "$target_dir") || return 1
  printf '%s\n' "$canon/.local-agent/checkpoints"
}

legacy_runtime_checkpoint_root() {
  printf '%s\n' "$REPO_ROOT/checkpoints"
}

legacy_project_checkpoint_root() {
  local target_dir=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
  local canon
  canon=$(canonical_path "$target_dir") || return 1
  printf '%s\n' "$canon/checkpoints"
}

refresh_latest_checkpoint_link() {
  local root=$1
  mkdir -p "$root"
  local newest
  newest=$(find "$root" -mindepth 1 -maxdepth 1 -type d | sort -r | head -n 1)
  if [ -n "$newest" ]; then
    ln -sfn "$newest" "$root/latest"
  else
    rm -f "$root/latest"
  fi
}

metadata_source_dir() {
  local meta=$1
  python3 - "$meta" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    body = json.loads(path.read_text())
except Exception:
    raise SystemExit(1)
print(body.get("source_dir", ""))
PY
}

move_legacy_checkpoint_dir() {
  local source_dir=$1
  local destination_root=$2
  [ -e "$source_dir" ] || return 0
  mkdir -p "$destination_root"
  local destination="$destination_root/$(basename "$source_dir")"
  if [ ! -e "$destination" ]; then
    mv "$source_dir" "$destination_root/"
  fi
}

migrate_legacy_checkpoints() {
  local target_dir=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
  local target_canon
  target_canon=$(canonical_path "$target_dir") || return 1

  local root
  root=$(checkpoint_root "$target_canon")
  mkdir -p "$root"

  local legacy_runtime
  legacy_runtime=$(legacy_runtime_checkpoint_root)
  if [ -d "$legacy_runtime" ]; then
    shopt -s nullglob
    local path
    for path in "$legacy_runtime"/*; do
      [ "$(basename "$path")" = "latest" ] && continue
      [ -d "$path" ] || continue
      local meta="$path/metadata.json"
      [ -f "$meta" ] || continue
      local source=""
      source=$(metadata_source_dir "$meta" 2>/dev/null || true)
      if [ -n "$source" ] && [ "$(canonical_path "$source" 2>/dev/null || true)" = "$target_canon" ]; then
        move_legacy_checkpoint_dir "$path" "$root"
      fi
    done
    shopt -u nullglob
    rm -f "$legacy_runtime/latest"
    rmdir "$legacy_runtime" 2>/dev/null || true
  fi

  local legacy_project
  legacy_project=$(legacy_project_checkpoint_root "$target_canon")
  if [ -d "$legacy_project" ]; then
    shopt -s nullglob
    local legacy_path
    for legacy_path in "$legacy_project"/*; do
      [ "$(basename "$legacy_path")" = "latest" ] && continue
      [ -e "$legacy_path" ] || continue
      move_legacy_checkpoint_dir "$legacy_path" "$root"
    done
    shopt -u nullglob
    rm -f "$legacy_project/latest"
    rmdir "$legacy_project" 2>/dev/null || true
  fi

  refresh_latest_checkpoint_link "$root"
}
