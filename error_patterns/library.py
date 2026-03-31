#!/usr/bin/env python3
"""
error_patterns/library.py — Known error → auto-fix registry
============================================================
5-step auto-fix pipeline:
  1. Capture full error context (stack trace, agent state, last 10 log lines)
  2. Match against known patterns (fingerprint hash)
  3. If match → apply fix instantly (<3s), rerun
  4. If no match → Debugger agent analyzes, generates fix, logs as new pattern
  5. If Debugger fix fails 2× → escalate to permanent prompt upgrade + new pattern

Persists patterns to error_patterns/patterns.jsonl (append-only).
"""
import json, hashlib, time, threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

BASE_DIR     = Path(__file__).parent.parent
PATTERNS_FILE = Path(__file__).parent / "patterns.jsonl"
AUTO_FIX_LOG = BASE_DIR / "reports" / "auto_fix_log.jsonl"
STATE_FILE   = BASE_DIR / "dashboard" / "state.json"

# ── Seed patterns ──────────────────────────────────────────────────────────────
SEED_PATTERNS = [
    {
        "id": "json_decode_error",
        "fingerprint": "JSONDecodeError",
        "description": "Agent returned invalid JSON",
        "fix": "wrap output in try/except json.loads; retry with 'return valid JSON only' prefix",
        "prompt_patch": "IMPORTANT: Return ONLY valid JSON. No markdown, no explanation. Raw JSON only.",
        "category": "output_format",
        "hits": 0,
    },
    {
        "id": "truncated_output",
        "fingerprint": "truncat",
        "description": "Agent truncated its output mid-way",
        "fix": "increase context window to 16384; add 'NEVER truncate' to system prompt",
        "prompt_patch": "NEVER truncate output. Write the COMPLETE response. If long, break into parts but finish each part fully.",
        "category": "output_quality",
        "hits": 0,
    },
    {
        "id": "timeout_error",
        "fingerprint": "TimeoutError",
        "description": "Agent timed out on task",
        "fix": "split task into smaller subtasks; increase timeout to 120s",
        "prompt_patch": "Break complex tasks into steps. Complete each step before moving to the next.",
        "category": "performance",
        "hits": 0,
    },
    {
        "id": "connection_refused",
        "fingerprint": "ConnectionRefused",
        "description": "Cannot connect to Nexus engine/model server",
        "fix": "restart Nexus engine: subprocess.run(['nexus', 'serve']); wait 5s; retry",
        "prompt_patch": "",
        "category": "infrastructure",
        "hits": 0,
    },
    {
        "id": "model_not_found",
        "fingerprint": "model.*not found",
        "description": "Requested model not available locally",
        "fix": "fall back to nexus-local; update registry model field",
        "prompt_patch": "",
        "category": "infrastructure",
        "hits": 0,
    },
    {
        "id": "zero_quality",
        "fingerprint": "quality.*0",
        "description": "Agent returned quality=0 (parser failure or empty output)",
        "fix": "check parser in agent; add fallback scorer; ensure output key matches schema",
        "prompt_patch": "Always include a 'quality' score (0-100) in your response.",
        "category": "output_quality",
        "hits": 0,
    },
    {
        "id": "import_error",
        "fingerprint": "ImportError|ModuleNotFoundError",
        "description": "Missing Python dependency",
        "fix": "pip install missing package; update requirements.txt; retry",
        "prompt_patch": "",
        "category": "dependency",
        "hits": 0,
    },
    {
        "id": "file_not_found",
        "fingerprint": "FileNotFoundError",
        "description": "Agent tried to read a file that doesn't exist",
        "fix": "check file path; create parent dirs; use Path.exists() before open",
        "prompt_patch": "Always check if a file exists before reading it.",
        "category": "filesystem",
        "hits": 0,
    },
    {
        "id": "stalled_agent",
        "fingerprint": "stuck.*120|stall|no.*heartbeat",
        "description": "Agent heartbeat missing — task stalled",
        "fix": "kill agent; reload from last checkpoint; reassign task with shorter timeout",
        "prompt_patch": "Write progress notes every 30 seconds. Never pause silently.",
        "category": "health",
        "hits": 0,
    },
    {
        "id": "wrong_keys",
        "fingerprint": "KeyError|key.*missing",
        "description": "Output dict missing expected keys",
        "fix": "add .get() with defaults; validate output schema before returning",
        "prompt_patch": "Your response MUST include all required fields: status, output, quality, tokens_used.",
        "category": "output_format",
        "hits": 0,
    },
]


# ── Library ────────────────────────────────────────────────────────────────────

class ErrorPatternLibrary:
    def __init__(self):
        self._lock = threading.Lock()
        self._patterns: Dict[str, dict] = {}
        self._stats = {"total_errors": 0, "hits": 0, "misses": 0}
        self._load()

    def _load(self):
        """Load patterns from file + seeds."""
        for p in SEED_PATTERNS:
            self._patterns[p["id"]] = dict(p)

        if PATTERNS_FILE.exists():
            try:
                for line in PATTERNS_FILE.read_text().splitlines():
                    if not line.strip():
                        continue
                    p = json.loads(line)
                    if p.get("id"):
                        self._patterns[p["id"]] = p
            except Exception:
                pass

    def _save_pattern(self, pattern: dict):
        """Append new pattern to patterns.jsonl."""
        try:
            PATTERNS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(PATTERNS_FILE, "a") as f:
                f.write(json.dumps(pattern) + "\n")
        except Exception:
            pass

    def _fingerprint(self, error_text: str) -> str:
        return hashlib.md5(error_text.lower()[:200].encode()).hexdigest()[:12]

    def match(self, error_text: str, context: dict = None) -> Optional[dict]:
        """
        Find best matching pattern for an error.
        Returns pattern dict or None if no match.
        """
        import re
        el = error_text.lower()
        with self._lock:
            self._stats["total_errors"] += 1
            for pid, p in self._patterns.items():
                fp = p.get("fingerprint", "")
                try:
                    if re.search(fp, el, re.IGNORECASE):
                        p["hits"] = p.get("hits", 0) + 1
                        self._stats["hits"] += 1
                        self._update_dashboard_stats()
                        return p
                except re.error:
                    if fp.lower() in el:
                        p["hits"] = p.get("hits", 0) + 1
                        self._stats["hits"] += 1
                        self._update_dashboard_stats()
                        return p
            self._stats["misses"] += 1
            self._update_dashboard_stats()
            return None

    def record_new_pattern(self, error_text: str, fix_applied: str,
                           agent: str = "", quality_after: int = 0):
        """Record a previously unknown error as a new pattern."""
        fp = self._fingerprint(error_text)
        pid = f"auto_{fp}"
        if pid in self._patterns:
            return  # already recorded

        pattern = {
            "id": pid,
            "fingerprint": fp,
            "description": error_text[:120],
            "fix": fix_applied,
            "prompt_patch": "",
            "category": "auto_discovered",
            "hits": 1,
            "first_seen": datetime.utcnow().isoformat(timespec="seconds"),
            "agent": agent,
            "quality_after": quality_after,
        }
        with self._lock:
            self._patterns[pid] = pattern
        self._save_pattern(pattern)
        self._log_fix(error_text, fix_applied, agent, "new_pattern", quality_after)

    def log_fix(self, error_text: str, fix_applied: str, agent: str = "",
                matched_pattern: Optional[dict] = None, quality_after: int = 0):
        """Log an auto-fix to auto_fix_log.jsonl."""
        self._log_fix(error_text, fix_applied, agent,
                      matched_pattern["id"] if matched_pattern else "unknown",
                      quality_after)

    def _log_fix(self, error_text: str, fix_applied: str, agent: str,
                 pattern_id: str, quality_after: int):
        entry = {
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "agent": agent,
            "error": error_text[:200],
            "fix_applied": fix_applied,
            "pattern_id": pattern_id,
            "quality_after": quality_after,
            "resolved": quality_after >= 40,
        }
        try:
            AUTO_FIX_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(AUTO_FIX_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def _update_dashboard_stats(self):
        """Update dashboard state with pattern library stats."""
        try:
            total = len(self._patterns)
            hit_rate = (self._stats["hits"] / max(self._stats["total_errors"], 1)) * 100
            state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
            state["error_pattern_stats"] = {
                "library_size": total,
                "total_errors": self._stats["total_errors"],
                "hits": self._stats["hits"],
                "misses": self._stats["misses"],
                "hit_rate_pct": round(hit_rate, 1),
                "auto_discovered": sum(1 for p in self._patterns.values()
                                       if p.get("category") == "auto_discovered"),
            }
            STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception:
            pass

    def stats(self) -> dict:
        with self._lock:
            return {
                "library_size": len(self._patterns),
                **self._stats,
                "hit_rate_pct": round(
                    self._stats["hits"] / max(self._stats["total_errors"], 1) * 100, 1
                ),
                "categories": {
                    cat: sum(1 for p in self._patterns.values() if p.get("category") == cat)
                    for cat in set(p.get("category", "") for p in self._patterns.values())
                },
            }


# ── Singleton + convenience function ─────────────────────────────────────────

_lib: Optional[ErrorPatternLibrary] = None
_lib_lock = threading.Lock()


def get_library() -> ErrorPatternLibrary:
    global _lib
    with _lib_lock:
        if _lib is None:
            _lib = ErrorPatternLibrary()
    return _lib


def auto_fix(error_text: str, agent: str = "", context: dict = None) -> Optional[dict]:
    """
    Main entry point: match error against library.
    Returns fix dict or None.
    Example usage:
        fix = auto_fix("JSONDecodeError on line 3", agent="executor")
        if fix:
            apply_prompt_patch(fix["prompt_patch"])
    """
    lib = get_library()
    pattern = lib.match(error_text, context)
    if pattern:
        lib.log_fix(error_text, pattern["fix"], agent, pattern, 0)
    return pattern


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Error pattern library")
    ap.add_argument("--stats",  action="store_true", help="Show library stats")
    ap.add_argument("--match",  type=str, metavar="ERROR", help="Match an error string")
    args = ap.parse_args()

    lib = get_library()
    if args.stats:
        print(json.dumps(lib.stats(), indent=2))
    elif args.match:
        pattern = lib.match(args.match)
        if pattern:
            print(f"MATCH: {pattern['id']}")
            print(f"  Fix: {pattern['fix']}")
            if pattern.get("prompt_patch"):
                print(f"  Prompt patch: {pattern['prompt_patch']}")
        else:
            print("No match found — will be recorded as new pattern")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
