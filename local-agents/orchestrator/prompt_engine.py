#!/usr/bin/env python3
"""
orchestrator/prompt_engine.py — Self-improving prompt engine
=============================================================
After every task, if quality drops below version avg → generate improvement,
apply to A half of sub-agents (B keeps old), commit winner permanently.

Wire-in:
    from orchestrator.prompt_engine import get_prompt_engine
    pe = get_prompt_engine()
    pe.record_task(agent_name, task, result, version_avg)
    pe.maybe_run_ab(agent_name, version)

Logs to: reports/prompt_engine_log.jsonl
"""
import json, re, threading, hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

BASE_DIR   = Path(__file__).parent.parent
LOG_PATH   = BASE_DIR / "reports" / "prompt_engine_log.jsonl"
STATE_FILE = BASE_DIR / "dashboard" / "state.json"
REGISTRY   = BASE_DIR / "registry" / "agents.json"
AGENTS_DIR = BASE_DIR / "agents"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# How many low-quality tasks before triggering improvement
IMPROVEMENT_THRESHOLD = 2
# Minimum tasks before A/B is meaningful
AB_MIN_SAMPLE = 4
# Score improvement needed to commit new prompt (pts)
AB_WIN_MARGIN = 3.0


def _log(entry: dict):
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _push_dashboard(data: dict):
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        feed = state.get("prompt_engine_feed", [])
        feed.append(data)
        state["prompt_engine_feed"] = feed[-20:]
        # Summary
        state["prompt_engine_summary"] = {
            "total_improvements": len([e for e in feed if e.get("event") == "committed"]),
            "active_ab_tests": len([e for e in feed if e.get("event") == "ab_started"
                                    and not e.get("concluded")]),
            "last_ts": datetime.utcnow().isoformat(timespec="seconds"),
        }
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _generate_improvement(agent_name: str, failure_pattern: str, current_prompt: str) -> str:
    """
    Generate a prompt improvement patch from a failure pattern.
    Rule-based engine — no LLM needed for simple patterns.
    """
    improvements = []

    fp = failure_pattern.lower()
    if "truncat" in fp or "incomplete" in fp:
        improvements.append("NEVER truncate output. Always write the COMPLETE response.")
    if "json" in fp or "parse" in fp or "decode" in fp:
        improvements.append("Return ONLY valid JSON. No markdown. No explanation. Raw JSON only.")
    if "quality" in fp or "score" in fp or "low" in fp:
        improvements.append("Strive for 80+ quality. Verify completeness before returning.")
    if "timeout" in fp or "slow" in fp or "stuck" in fp:
        improvements.append("Break complex tasks into steps. Complete each step before the next.")
    if "empty" in fp or "none" in fp or "null" in fp:
        improvements.append("Never return empty output. Always produce a best-effort answer.")
    if "error" in fp or "exception" in fp or "traceback" in fp:
        improvements.append("Catch and handle errors gracefully. Return status='done' with error details.")
    if "import" in fp or "module" in fp:
        improvements.append("Only use stdlib imports. Never import third-party packages unless listed.")
    if "hallucin" in fp or "invent" in fp or "fabricat" in fp:
        improvements.append("Only state what you know. Mark uncertain conclusions with [UNCERTAIN].")

    if not improvements:
        improvements.append(
            f"Previous output quality was below threshold. Focus on: correctness first, "
            f"completeness second, efficiency third."
        )

    patch = "\n\n[AUTO-IMPROVEMENT " + datetime.utcnow().strftime("%Y%m%d-%H%M") + "]\n"
    patch += "\n".join(f"- {r}" for r in improvements)
    return patch


class PromptEngine:
    def __init__(self):
        self._lock = threading.Lock()
        # agent → list of recent (quality, failure_pattern) tuples
        self._task_history: Dict[str, list] = {}
        # agent → {variant: "A"|"B", a_scores: [], b_scores: [], prompt_A: str, prompt_B: str}
        self._ab_tests: Dict[str, dict] = {}
        # agent → current prompt (in-memory override)
        self._prompt_overrides: Dict[str, str] = {}
        # running improvement count
        self._improvements: int = 0

    # ── Record task outcome ────────────────────────────────────────────────

    def record_task(self, agent_name: str, task: dict, result: dict,
                    version_avg: float = 50.0) -> bool:
        """
        Record task quality. Returns True if improvement was triggered.
        """
        quality = result.get("quality", result.get("score", 0))
        error   = str(result.get("error", result.get("output", "")))[:200]

        with self._lock:
            hist = self._task_history.setdefault(agent_name, [])
            hist.append({"quality": quality, "error": error, "task": task.get("title", "")})
            hist[:] = hist[-20:]  # keep last 20

            # Count recent below-average tasks
            recent = hist[-IMPROVEMENT_THRESHOLD:]
            low_count = sum(1 for h in recent if h["quality"] < version_avg - 10)

            if low_count >= IMPROVEMENT_THRESHOLD:
                failure_pattern = " | ".join(h["error"] for h in recent if h["error"])
                self._trigger_improvement(agent_name, failure_pattern)
                hist.clear()  # reset after triggering
                return True
        return False

    def _trigger_improvement(self, agent_name: str, failure_pattern: str):
        """Generate and start A/B test for an improvement."""
        current = self._prompt_overrides.get(agent_name, "")
        patch   = _generate_improvement(agent_name, failure_pattern, current)
        new_prompt = current + patch

        self._ab_tests[agent_name] = {
            "started": datetime.utcnow().isoformat(timespec="seconds"),
            "prompt_A": current,
            "prompt_B": new_prompt,
            "a_scores": [],
            "b_scores": [],
            "variant_counter": 0,
            "failure_pattern": failure_pattern[:200],
            "concluded": False,
        }
        self._improvements += 1
        print(f"  [PROMPT-ENGINE] {agent_name} A/B test started — patch: {patch[:80].strip()}")
        _log({
            "event": "ab_started",
            "agent": agent_name,
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "failure_pattern": failure_pattern[:200],
            "patch_preview": patch[:200],
        })
        _push_dashboard({
            "event": "ab_started",
            "agent": agent_name,
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "patch": patch[:120],
        })

    # ── A/B test management ───────────────────────────────────────────────

    def get_prompt_for_task(self, agent_name: str) -> Optional[str]:
        """
        Return the prompt variant to use for this task.
        Alternates A/B until enough samples collected.
        Returns None if no override active.
        """
        with self._lock:
            ab = self._ab_tests.get(agent_name)
            if not ab or ab.get("concluded"):
                return self._prompt_overrides.get(agent_name)

            ab["variant_counter"] = ab.get("variant_counter", 0) + 1
            # Alternate: odd = A, even = B
            return ab["prompt_B"] if ab["variant_counter"] % 2 == 0 else ab["prompt_A"]

    def record_ab_result(self, agent_name: str, quality: float):
        """Record a task result into the active A/B test."""
        with self._lock:
            ab = self._ab_tests.get(agent_name)
            if not ab or ab.get("concluded"):
                return

            if ab["variant_counter"] % 2 == 0:
                ab["b_scores"].append(quality)
            else:
                ab["a_scores"].append(quality)

            total = len(ab["a_scores"]) + len(ab["b_scores"])
            if total >= AB_MIN_SAMPLE:
                self._conclude_ab(agent_name, ab)

    def _conclude_ab(self, agent_name: str, ab: dict):
        """Commit winner or roll back loser."""
        a_avg = sum(ab["a_scores"]) / len(ab["a_scores"]) if ab["a_scores"] else 0
        b_avg = sum(ab["b_scores"]) / len(ab["b_scores"]) if ab["b_scores"] else 0
        ab["concluded"] = True

        if b_avg >= a_avg + AB_WIN_MARGIN:
            # B wins — commit new prompt
            self._prompt_overrides[agent_name] = ab["prompt_B"]
            outcome = "committed"
            print(f"  [PROMPT-ENGINE] {agent_name} B WINS — prompt improved (A={a_avg:.1f} B={b_avg:.1f})")
            self._persist_to_registry(agent_name, ab["prompt_B"])
        else:
            # A wins — roll back, keep old
            outcome = "rolled_back"
            print(f"  [PROMPT-ENGINE] {agent_name} A wins — improvement rolled back (A={a_avg:.1f} B={b_avg:.1f})")

        entry = {
            "event": outcome,
            "agent": agent_name,
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "a_avg": round(a_avg, 1),
            "b_avg": round(b_avg, 1),
            "delta": round(b_avg - a_avg, 1),
        }
        _log(entry)
        _push_dashboard(entry)

    def _persist_to_registry(self, agent_name: str, new_prompt: str):
        """Write winning prompt into registry agents.json."""
        try:
            if not REGISTRY.exists():
                return
            reg = json.loads(REGISTRY.read_text())
            agents = reg.get("agents", {})
            if agent_name in agents:
                agents[agent_name]["system_prompt_override"] = new_prompt
                agents[agent_name]["prompt_version"] = agents[agent_name].get("prompt_version", 0) + 1
                agents[agent_name]["prompt_updated"] = datetime.utcnow().isoformat(timespec="seconds")
                reg["agents"] = agents
                REGISTRY.write_text(json.dumps(reg, indent=2))
        except Exception:
            pass

    # ── Stats ──────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        with self._lock:
            active_ab = sum(1 for ab in self._ab_tests.values() if not ab.get("concluded"))
            return {
                "improvements_triggered": self._improvements,
                "active_ab_tests": active_ab,
                "agents_with_overrides": len(self._prompt_overrides),
                "ab_tests_total": len(self._ab_tests),
            }


# ── Singleton ─────────────────────────────────────────────────────────────

_pe_instance: Optional[PromptEngine] = None
_pe_lock = threading.Lock()


def get_prompt_engine() -> PromptEngine:
    global _pe_instance
    with _pe_lock:
        if _pe_instance is None:
            _pe_instance = PromptEngine()
    return _pe_instance
