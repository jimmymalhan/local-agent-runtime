#!/bin/bash
set -uo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TARGET_REPO=${LOCAL_AGENT_TARGET_REPO:-$PWD}
LOCAL_AGENT_MODE=${LOCAL_AGENT_MODE:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("default_profile", "balanced"))' "$REPO_ROOT/config/runtime.json")}
LOCAL_AGENT_AUTO_REVIEW=${LOCAL_AGENT_AUTO_REVIEW:-1}
export LOCAL_AGENT_MODE
export LOCAL_AGENT_AUTO_REVIEW

python3 "$SCRIPT_DIR/private_tool_registry.py" >/dev/null 2>&1 || true
if [ -d "$TARGET_REPO" ]; then
  export LOCAL_AGENT_TARGET_REPO=$(cd "$TARGET_REPO" && pwd)
fi

show_help() {
cat <<EOF
Local CLI session for local-agent-runtime.

Slash commands:
  /help                      show this help
  /models                    show the resolved local model team and installed models
  /model                     show the default coding model
  /modes                     show available execution modes
  /mode [name]               show or set the current execution mode
  /team                      show which local roles are doing what with percentage bars
  /plan <task>               run the planning subset locally
  /run <task>                alias for /pipeline
  /progress                  show tracked pipeline progress
  /status                    show current resource snapshot
  /watch                     watch progress in real time
  /live                      watch full live status in real time
  /tail                      alias for /live
  /autopilot                 show autopilot usage
  /autopilot start [path]    start the local self-upgrade loop in background
  /autopilot status          show autopilot status
  /autopilot stop            stop the background autopilot loop
  /autopilot log             tail the autopilot log
  /limits                    show resource limits
  /project                   show the current target project
  /session                   show active session state
  /history                   show recent local session history for this repo
  /clear                     clear local session history for this repo
  /context                   show the latest generated project summary
  /checkpoint [label]        create a checkpoint for the target repo
  /restore <checkpoint>      restore a checkpoint into the target repo
  /review                    review current git changes in the target repo
  /qa                        run the technical QA review subset
  /uat                       run the scripted non-technical user acceptance suite
  /quality                   compare the latest answer against the local quality bar
  /verify                    run the scripted end-to-end QA suite
  /heal                      repair stale runtime state and refresh artifacts
  /repair                    run the local self-repair analysis loop
  /release                   run the final QA + user acceptance gate
  /doctor                    inspect local runtime and session health
  /pipeline <task>           run the local model pipeline
  /diff                      show target repo status and diff summary
  /files <pattern>           list matching files in the target repo
  /grep <pattern>            search file content in the target repo
  /open <path>               print the first part of a file from the target repo
  /tool <name> [args...]     run a script from scripts/
  /tools                     list available local scripts
  /roles                     list role files
  /skills                    list skill files
  /workflows                 list workflow files
  /todo                      show state/todo.md
  /todo-progress             show progress bars derived from state/todo.md
  /todo-watch                watch todo progress bars in real time
  /todo add <text>           add an item to state/todo.md
  /todo done <text>          mark the first matching todo item complete
  /ledger                    show state/ledger.md
  /exit | /quit              leave the session

  Codex-style commands:
  /compact                   summarize session history to free context
  /undo                      restore latest checkpoint (revert recent changes)
  /copy                      copy latest response to clipboard
  /mention <path>            attach file to context for next pipeline run
  /new                       start fresh conversation (clear history for repo)
  /init                      generate AGENTS.md scaffold in target repo
  /personality [style]        show or set style: friendly, pragmatic, none
  /debug-config              print config and runtime diagnostics
  /mcp                       list detected local MCP descriptors if present
  /feedback [text]           record session feedback (for iteration)
  /session-compare <task>    run the same task through local-codex and local-claude

Plain text without a slash is treated as /pipeline <task>.

Repo root:
  $REPO_ROOT
Target repo:
  ${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}
Execution mode:
  ${LOCAL_AGENT_MODE}
EOF
}

show_progress() {
  python3 "$SCRIPT_DIR/progress_tracker.py" show
}

show_models() {
  python3 "$SCRIPT_DIR/model_registry.py"
}

show_default_model() {
  python3 - "$REPO_ROOT" <<'PY'
import json, pathlib, sys
cfg = json.loads((pathlib.Path(sys.argv[1]) / "config" / "runtime.json").read_text())
print(cfg.get("default_model", "unknown"))
PY
}

show_team_status() {
  python3 "$SCRIPT_DIR/team_status.py"
}

show_modes() {
  python3 - "$REPO_ROOT" "$LOCAL_AGENT_MODE" <<'PY'
import json
import pathlib
import sys

cfg = json.loads((pathlib.Path(sys.argv[1]) / "config" / "runtime.json").read_text())
active = sys.argv[2]
for name, body in cfg.get("profiles", {}).items():
    marker = "*" if name == active else " "
    print(f"{marker} {name}: {body.get('description', '')}")
PY
}

set_mode() {
  local next_mode=${1:-}
  if [ -z "$next_mode" ]; then
    echo "$LOCAL_AGENT_MODE"
    return 0
  fi
  if ! python3 - "$REPO_ROOT" "$next_mode" <<'PY'
import json
import pathlib
import sys

cfg = json.loads((pathlib.Path(sys.argv[1]) / "config" / "runtime.json").read_text())
raise SystemExit(0 if sys.argv[2] in cfg.get("profiles", {}) else 1)
PY
  then
    echo "Unknown mode: $next_mode" >&2
    return 1
  fi
  LOCAL_AGENT_MODE=$next_mode
  export LOCAL_AGENT_MODE
  echo "mode=$LOCAL_AGENT_MODE"
}

show_status() {
  python3 "$SCRIPT_DIR/resource_status.py"
}

watch_progress() {
  while true; do
    clear
    python3 "$SCRIPT_DIR/progress_tracker.py" show || true
    python3 "$SCRIPT_DIR/resource_status.py" || true
    sleep 2
  done
}

watch_live_status() {
  while true; do
    clear
    python3 "$SCRIPT_DIR/team_status.py" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}" || true
    echo
    echo "TODO LANES"
    python3 "$SCRIPT_DIR/todo_progress.py" || true
    echo
    echo "RESOURCE SNAPSHOT"
    python3 "$SCRIPT_DIR/resource_status.py" || true
    echo
    echo "LATEST PROGRESS TICKS"
    tail -n 8 "$REPO_ROOT/logs/progress.log" 2>/dev/null || echo "No progress log yet."
    sleep 2
  done
}

show_autopilot_usage() {
cat <<EOF
/autopilot start [target_repo]
/autopilot status
/autopilot stop
/autopilot log
EOF
}

start_autopilot() {
  local target=${1:-${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}}
  bash "$SCRIPT_DIR/start_autopilot.sh" "$target"
}

show_autopilot_status() {
  bash "$SCRIPT_DIR/autopilot_status.sh"
}

stop_autopilot() {
  bash "$SCRIPT_DIR/stop_autopilot.sh"
}

show_autopilot_log() {
  tail -n 120 "$REPO_ROOT/logs/autopilot.log" 2>/dev/null || echo "No autopilot log yet."
}

show_limits() {
  python3 - "$REPO_ROOT" "$LOCAL_AGENT_MODE" <<'PY'
import json, pathlib, sys
cfg = json.loads((pathlib.Path(sys.argv[1]) / "config" / "runtime.json").read_text())
profile = cfg.get("profiles", {}).get(sys.argv[2], {})
limits = dict(cfg.get("resource_limits", {}))
limits.update(profile.get("resource_limits", {}))
for key, value in limits.items():
    print(f"{key}={value}")
PY
}

show_project() {
  echo "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

show_session() {
  local state_file="$REPO_ROOT/state/session-state.json"
  if [ -f "$state_file" ]; then
    sed -n '1,200p' "$state_file"
  else
    echo '{"status":"idle"}'
  fi
}

show_history() {
  python3 - "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}" "$REPO_ROOT/state/session-history.jsonl" <<'PY'
import json
import pathlib
import sys

target_repo = str(pathlib.Path(sys.argv[1]).resolve())
path = pathlib.Path(sys.argv[2])
if not path.exists():
    print("No session history.")
    raise SystemExit(0)
items = []
for line in path.read_text().splitlines():
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        continue
    if item.get("target_repo") == target_repo:
        items.append(item)
for item in items[-8:]:
    print(f"[{item['timestamp']}] {item['role']}:")
    print(item["content"][:800])
    print()
PY
}

clear_history() {
  python3 - "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}" "$REPO_ROOT/state/session-history.jsonl" <<'PY'
import json
import pathlib
import sys

target_repo = str(pathlib.Path(sys.argv[1]).resolve())
path = pathlib.Path(sys.argv[2])
if not path.exists():
    print("No session history.")
    raise SystemExit(0)
kept = []
for line in path.read_text().splitlines():
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        continue
    if item.get("target_repo") != target_repo:
        kept.append(json.dumps(item))
path.write_text(("\n".join(kept) + "\n") if kept else "")
print(f"Cleared session history for {target_repo}")
PY
}

show_context() {
  local path="$REPO_ROOT/context/project-summary.md"
  if [ -f "$path" ]; then
    sed -n '1,240p' "$path"
  else
    echo "No project summary generated yet."
  fi
}

create_checkpoint() {
  local label=${1:-manual}
  bash "$SCRIPT_DIR/create_checkpoint.sh" "$label" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

restore_checkpoint() {
  local ref=${1:-}
  if [ -z "$ref" ]; then
    echo "Usage: /restore <checkpoint>" >&2
    return 1
  fi
  bash "$SCRIPT_DIR/restore_checkpoint.sh" "$ref" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

review_current_changes() {
  python3 "$SCRIPT_DIR/review_current_changes.py" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

run_release_gate() {
  bash "$SCRIPT_DIR/release_gate.sh" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

show_doctor() {
  echo "== project =="
  show_project
  echo
  echo "== session =="
  show_session
  echo
  echo "== mode =="
  echo "$LOCAL_AGENT_MODE"
  echo
  echo "== limits =="
  show_limits
  echo
  echo "== models =="
  python3 "$SCRIPT_DIR/model_registry.py" || true
  echo
  echo "== status =="
  show_status || true
  echo
  echo "== latest checkpoint =="
  ls -ld "$REPO_ROOT/checkpoints/latest" 2>/dev/null || echo "No latest checkpoint"
  echo
  echo "== interactive sessions =="
  python3 "$SCRIPT_DIR/session_health.py" || true
}

show_tools() {
  python3 - "$REPO_ROOT" <<'PY'
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1]) / "state" / "private-tool-registry.json"
if not path.exists():
    print("No private tool registry available.")
    raise SystemExit(0)
data = json.loads(path.read_text())
print(f"tools={len(data.get('tools', []))}")
for item in data.get("tools", []):
    print(f"{item['id']} | {item['path']}")
PY
}

run_tool() {
  local tool_name=$1
  shift || true
  local tool_path="$SCRIPT_DIR/${tool_name}.sh"
  if [ ! -f "$tool_path" ]; then
    echo "Tool not found: $tool_name" >&2
    return 1
  fi
  bash "$tool_path" "$@"
}

run_pipeline_task() {
  local task=$1
  python3 "$SCRIPT_DIR/local_team_run.py" "$task" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
  if [ "$LOCAL_AGENT_AUTO_REVIEW" = "1" ]; then
    echo
    echo "== auto review =="
    review_current_changes || true
  fi
}

run_session_compare() {
  local task=$1
  python3 "$SCRIPT_DIR/session_compare.py" "$task" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

run_role_task() {
  local roles=$1
  shift
  local task=$1
  LOCAL_AGENT_ONLY_ROLES=$roles python3 "$SCRIPT_DIR/local_team_run.py" "$task" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
  if [ "$LOCAL_AGENT_AUTO_REVIEW" = "1" ]; then
    echo
    echo "== auto review =="
    review_current_changes || true
  fi
}

run_qa_review() {
  LOCAL_AGENT_MODE=${LOCAL_AGENT_MODE:-deep} run_role_task \
    "tester,reviewer,qa,summarizer" \
    "Run the technical QA gate for the current target repo. Use any current validation artifacts, highlight concrete failures, and decide whether the workflow is technically ready."
}

run_user_acceptance_review() {
  bash "$SCRIPT_DIR/user_acceptance_suite.sh" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

run_quality_compare() {
  bash "$SCRIPT_DIR/compare_quality.sh" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

run_verify_suite() {
  bash "$SCRIPT_DIR/qa_suite.sh" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

run_runtime_heal() {
  python3 "$SCRIPT_DIR/repair_runtime_state.py" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

run_self_repair() {
  bash "$SCRIPT_DIR/self_repair.sh" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

list_dir_files() {
  local rel_dir=$1
  find "$REPO_ROOT/$rel_dir" -maxdepth 1 -type f | sort | sed "s#^$REPO_ROOT/##"
}

show_diff() {
  local repo=${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}
  git -C "$repo" status --short --branch 2>/dev/null || {
    echo "Target repo is not a git repository."
    return 0
  }
  echo
  git -C "$repo" diff --stat || true
  echo
  git -C "$repo" diff --name-only || true
}

list_matching_files() {
  local pattern=${1:-}
  local repo=${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}
  if [ -z "$pattern" ]; then
    echo "Usage: /files <pattern>" >&2
    return 1
  fi
  if command -v rg >/dev/null 2>&1; then
    rg --files "$repo" \
      -g '!checkpoints/**' \
      -g '!logs/**' \
      -g '!memory/**' \
      -g '!**/__pycache__/**' | rg -i "$pattern" || true
  else
    find "$repo" -type f | grep -i "$pattern" || true
  fi
}

search_repo() {
  local pattern=${1:-}
  local repo=${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}
  if [ -z "$pattern" ]; then
    echo "Usage: /grep <pattern>" >&2
    return 1
  fi
  if command -v rg >/dev/null 2>&1; then
    rg -n --hidden \
      --glob '!.git' \
      --glob '!checkpoints/**' \
      --glob '!logs/**' \
      --glob '!memory/**' \
      --glob '!**/__pycache__/**' \
      "$pattern" "$repo" || true
  else
    grep -RIn "$pattern" "$repo" || true
  fi
}

open_file() {
  local requested=${1:-}
  local repo=${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}
  if [ -z "$requested" ]; then
    echo "Usage: /open <path>" >&2
    return 1
  fi
  local candidate="$requested"
  if [ ! -f "$candidate" ]; then
    candidate="$repo/$requested"
  fi
  if [ ! -f "$candidate" ]; then
    echo "File not found: $requested" >&2
    return 1
  fi
  sed -n '1,220p' "$candidate"
}

copy_latest_response() {
  local path="$REPO_ROOT/logs/latest-response.md"
  if [ ! -f "$path" ]; then
    echo "No latest response. Run /pipeline first." >&2
    return 1
  fi
  if command -v pbcopy >/dev/null 2>&1; then
    pbcopy < "$path"
    echo "Copied latest response to clipboard."
  elif command -v xclip >/dev/null 2>&1; then
    xclip -selection clipboard < "$path"
    echo "Copied latest response to clipboard."
  elif command -v xsel >/dev/null 2>&1; then
    xsel --clipboard --input < "$path"
    echo "Copied latest response to clipboard."
  else
    echo "No clipboard tool (pbcopy/xclip/xsel). Outputting:" >&2
    head -n 100 "$path"
  fi
}

undo_latest() {
  local latest="$REPO_ROOT/checkpoints/latest"
  if [ ! -d "$latest" ] || [ ! -L "$latest" ]; then
    echo "No checkpoint to restore. Create one with /checkpoint first." >&2
    return 1
  fi
  bash "$SCRIPT_DIR/restore_checkpoint.sh" "$latest" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
  echo "Restored from latest checkpoint."
}

compact_history() {
  python3 - "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}" "$REPO_ROOT/state/session-history.jsonl" "$REPO_ROOT/state/session-summary.md" <<'PY'
import json
import pathlib
import sys

target_repo = str(pathlib.Path(sys.argv[1]).resolve())
hist_path = pathlib.Path(sys.argv[2])
sum_path = pathlib.Path(sys.argv[3])

if not hist_path.exists():
    print("No session history.")
    raise SystemExit(0)

items_for_repo = []
kept_lines = []
for line in hist_path.read_text().splitlines():
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        kept_lines.append(line)
        continue
    if item.get("target_repo") == target_repo:
        items_for_repo.append(item)
    else:
        kept_lines.append(line)

if len(items_for_repo) <= 4:
    print("History has 4 or fewer items for this repo; no compaction needed.")
    raise SystemExit(0)

summary = [
    "# Session Summary (compacted)",
    "",
    f"Target repo: {target_repo}",
    f"Items summarized: {len(items_for_repo)}",
    "",
    "## Recent highlights"
]
for item in items_for_repo[-4:]:
    summary.append(f"\n### {item.get('role', 'unknown')}")
    content = item.get("content", "") or ""
    summary.append(content[:600] + ("..." if len(content) > 600 else ""))
sum_path.write_text("\n".join(summary))
hist_path.write_text("\n".join(kept_lines) + ("\n" if kept_lines else ""))
print(f"Compacted {len(items_for_repo)} items. Summary in state/session-summary.md")
PY
}

do_new_conversation() {
  clear_history
  rm -f "$REPO_ROOT/state/mentioned-files.txt"
  echo "Started new conversation."
}

init_agents_md() {
  bash "$SCRIPT_DIR/init_agents_md.sh" "${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}"
}

mention_file() {
  local path=${1:-}
  local repo=${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}
  local out="$REPO_ROOT/state/mentioned-files.txt"
  if [ -z "$path" ]; then
    if [ -f "$out" ]; then
      echo "Mentioned files:"
      cat "$out"
    else
      echo "No files mentioned. Usage: /mention <path>"
    fi
    return 0
  fi
  local candidate="$path"
  if [ ! -f "$candidate" ]; then
    candidate="$repo/$path"
  fi
  if [ ! -f "$candidate" ]; then
    echo "File not found: $path" >&2
    return 1
  fi
  local abs=$(cd "$(dirname "$candidate")" && pwd)/$(basename "$candidate")
  echo "$abs" >> "$out"
  echo "Mentioned: $abs"
}

personality_cmd() {
  local style=${1:-}
  local prefs="$REPO_ROOT/state/session-preferences.json"
  mkdir -p "$(dirname "$prefs")"
  if [ -z "$style" ]; then
    if [ -f "$prefs" ]; then
      python3 -c "import json; d=json.load(open('$prefs')); print('personality=' + d.get('personality','pragmatic'))"
    else
      echo "personality=pragmatic (default)"
    fi
    return 0
  fi
  case "$style" in
    friendly|pragmatic|none)
      python3 - "$prefs" "$style" <<'PY'
import json, sys
p, s = sys.argv[1], sys.argv[2]
d = json.loads(open(p).read()) if __import__("pathlib").Path(p).exists() else {}
d["personality"] = s
open(p, "w").write(json.dumps(d, indent=2))
PY
      echo "personality=$style"
      ;;
    *)
      echo "Unknown personality. Use: friendly, pragmatic, none" >&2
      return 1
      ;;
  esac
}

show_debug_config() {
  echo "== config/runtime.json =="
  head -n 50 "$REPO_ROOT/config/runtime.json"
  echo ""
  echo "== state/session-state.json =="
  cat "$REPO_ROOT/state/session-state.json" 2>/dev/null || echo "{}"
  echo ""
  echo "== state/session-preferences.json =="
  cat "$REPO_ROOT/state/session-preferences.json" 2>/dev/null || echo "{}"
  echo ""
  echo "== LOCAL_AGENT_* env =="
  env | grep -E '^LOCAL_AGENT_' || true
}

show_mcp_tools() {
  local mcp_dir="$REPO_ROOT/../mcps"
  [ -d "$mcp_dir" ] || mcp_dir="$HOME/.cursor/projects/$(basename "$REPO_ROOT")/mcps"
  [ -d "$mcp_dir" ] || mcp_dir=""
  if [ -n "$mcp_dir" ]; then
    echo "MCP descriptors:"
    find "$mcp_dir" -name "*.json" -path "*/tools/*" 2>/dev/null | head -20
  else
    echo "No MCP tools configured (local agents use Ollama only)."
  fi
}

record_feedback() {
  local msg="$*"
  local out="$REPO_ROOT/state/feedback-sessions.md"
  mkdir -p "$(dirname "$out")"
  echo "- $(date '+%Y-%m-%d %H:%M:%S') [${SESSION_PERSONA:-local}] $msg" >> "$out"
  echo "Feedback recorded. Use /feedback to add more."
}

show_persona_welcome() {
  case "${SESSION_PERSONA:-local}" in
    claude)
      echo ""
      echo "== Claude (local) =="
      echo "Ready. Type a task or /pipeline <task>."
      echo "Progress is tracked automatically. Use /watch, /live, or /feedback <text>."
      echo ""
      ;;
    codex)
      echo ""
      echo "== Codex (local) =="
      echo "Ready. Type a task or /pipeline <task>."
      echo "Progress is tracked automatically. Use /watch, /live, or /feedback <text>."
      echo ""
      ;;
    *)
      echo ""
      echo "== Local agent session =="
      echo "Ready. Type a task or /help. Use /watch, /live, or /feedback <text>."
      echo ""
      ;;
  esac
}

PROMPT="${SESSION_PERSONA:-local}> "
show_persona_welcome
show_help

while true; do
  printf "%s" "$PROMPT"
  if ! IFS= read -r user_input; then
    break
  fi

  case "$user_input" in
    "")
      continue
      ;;
    /help|help)
      show_help
      ;;
    /models)
      show_models
      ;;
    /model)
      show_default_model
      ;;
    /modes)
      show_modes
      ;;
    /mode)
      set_mode
      ;;
    /mode\ *)
      set_mode "${user_input#"/mode "}"
      ;;
    /team)
      show_team_status
      ;;
    /exit|/quit|exit|quit)
      break
      ;;
    /compact)
      compact_history
      ;;
    /undo)
      undo_latest
      ;;
    /copy)
      copy_latest_response
      ;;
    /mention)
      mention_file
      ;;
    /mention\ *)
      mention_file "${user_input#"/mention "}"
      ;;
    /new)
      do_new_conversation
      ;;
    /init)
      init_agents_md
      ;;
    /personality)
      personality_cmd
      ;;
    /personality\ *)
      personality_cmd "${user_input#"/personality "}"
      ;;
    /debug-config)
      show_debug_config
      ;;
    /mcp)
      show_mcp_tools
      ;;
    /feedback)
      record_feedback "(no text)"
      ;;
    /feedback\ *)
      record_feedback "${user_input#"/feedback "}"
      ;;
    /session-compare\ *)
      run_session_compare "${user_input#"/session-compare "}"
      ;;
    /progress|progress)
      show_progress
      ;;
    /status|status)
      show_status
      ;;
    /watch)
      watch_progress
      ;;
    /live|/tail)
      watch_live_status
      ;;
    /autopilot)
      show_autopilot_usage
      ;;
    /autopilot\ start)
      start_autopilot
      ;;
    /autopilot\ start\ *)
      start_autopilot "${user_input#"/autopilot start "}"
      ;;
    /autopilot\ status)
      show_autopilot_status
      ;;
    /autopilot\ stop)
      stop_autopilot
      ;;
    /autopilot\ log)
      show_autopilot_log
      ;;
    /limits)
      show_limits
      ;;
    /project)
      show_project
      ;;
    /session)
      show_session
      ;;
    /history)
      show_history
      ;;
    /clear)
      clear_history
      ;;
    /context)
      show_context
      ;;
    /checkpoint\ *)
      create_checkpoint "${user_input#"/checkpoint "}"
      ;;
    /checkpoint)
      create_checkpoint "manual"
      ;;
    /restore\ *)
      restore_checkpoint "${user_input#"/restore "}"
      ;;
    /review)
      review_current_changes
      ;;
    /qa)
      run_qa_review
      ;;
    /uat)
      run_user_acceptance_review
      ;;
    /quality)
      run_quality_compare
      ;;
    /verify)
      run_verify_suite
      ;;
    /heal)
      run_runtime_heal
      ;;
    /repair)
      run_self_repair
      ;;
    /release)
      run_release_gate
      ;;
    /doctor)
      show_doctor
      ;;
    /plan\ *)
      task=${user_input#"/plan "}
      run_role_task "researcher,retriever,planner,summarizer" "$task"
      ;;
    /run\ *)
      task=${user_input#"/run "}
      run_pipeline_task "$task"
      ;;
    /tools)
      show_tools
      ;;
    /roles)
      list_dir_files roles
      ;;
    /skills)
      list_dir_files skills
      ;;
    /workflows)
      list_dir_files workflows
      ;;
    /todo)
      sed -n '1,200p' "$REPO_ROOT/state/todo.md"
      ;;
    /todo-progress)
      python3 "$SCRIPT_DIR/todo_progress.py"
      ;;
    /todo-watch)
      python3 "$SCRIPT_DIR/todo_progress.py" --watch
      ;;
    /todo\ add\ *)
      bash "$SCRIPT_DIR/update_todo.sh" add "${user_input#"/todo add "}" "local-session"
      ;;
    /todo\ done\ *)
      bash "$SCRIPT_DIR/update_todo.sh" done "${user_input#"/todo done "}"
      ;;
    /ledger)
      sed -n '1,200p' "$REPO_ROOT/state/ledger.md"
      ;;
    /pipeline\ *)
      task=${user_input#"/pipeline "}
      run_pipeline_task "$task"
      ;;
    /diff)
      show_diff
      ;;
    /files\ *)
      list_matching_files "${user_input#"/files "}"
      ;;
    /grep\ *)
      search_repo "${user_input#"/grep "}"
      ;;
    /open\ *)
      open_file "${user_input#"/open "}"
      ;;
    /tool\ *)
      tool_cmd=${user_input#"/tool "}
      tool_name=${tool_cmd%% *}
      if [ "$tool_name" = "$tool_cmd" ]; then
        run_tool "$tool_name"
      else
        tool_args=${tool_cmd#"$tool_name "}
        # shellcheck disable=SC2086
        run_tool "$tool_name" $tool_args
      fi
      ;;
    *)
      run_pipeline_task "$user_input"
      ;;
  esac
done
