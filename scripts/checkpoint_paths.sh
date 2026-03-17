#!/bin/bash

checkpoint_root() {
  printf '%s\n' "$REPO_ROOT/state/checkpoints"
}

legacy_checkpoint_root() {
  printf '%s\n' "$REPO_ROOT/checkpoints"
}

refresh_latest_checkpoint_link() {
  local root=${1:-$(checkpoint_root)}
  mkdir -p "$root"
  local newest
  newest=$(find "$root" -mindepth 1 -maxdepth 1 -type d | sort -r | head -n 1)
  if [ -n "$newest" ]; then
    ln -sfn "$newest" "$root/latest"
  else
    rm -f "$root/latest"
  fi
}

migrate_legacy_checkpoints() {
  local legacy_root=${1:-$(legacy_checkpoint_root)}
  local root=${2:-$(checkpoint_root)}

  [ -d "$legacy_root" ] || return 0
  mkdir -p "$root"

  local legacy_latest=""
  if [ -L "$legacy_root/latest" ]; then
    legacy_latest=$(basename "$(readlink "$legacy_root/latest")")
  fi

  local moved=0
  shopt -s nullglob
  local path
  for path in "$legacy_root"/*; do
    [ "$(basename "$path")" = "latest" ] && continue
    if [ -e "$path" ] && [ ! -e "$root/$(basename "$path")" ]; then
      mv "$path" "$root/"
      moved=1
    fi
  done
  shopt -u nullglob

  if [ -n "$legacy_latest" ] && [ -d "$root/$legacy_latest" ]; then
    ln -sfn "$root/$legacy_latest" "$root/latest"
  elif [ "$moved" -eq 1 ] || { [ -L "$legacy_root/latest" ] && [ ! -L "$root/latest" ]; }; then
    refresh_latest_checkpoint_link "$root"
  fi

  rm -f "$legacy_root/latest"
  rmdir "$legacy_root" 2>/dev/null || true
}
