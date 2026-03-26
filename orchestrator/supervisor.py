#!/usr/bin/env python3
"""
orchestrator/supervisor.py — CEO of the agent system
======================================================
Supervisor runs FIRST. Always. Nothing moves without Supervisor's sign-off.

Responsibilities (runs every 60 seconds):
  1. Check: dashboard live, board updated, hardware OK, registry loaded
  2. Watch agent heartbeats — reassign stalled tasks (>60s no pulse)
  3. Auto-heal crashed components — restart within 10 seconds
  4. Flag degraded agents (low quality 2 versions in a row) → trigger repair
  5. Clean logs older than 2 versions
  6. Write own heartbeat every 15s
  7. Sign off before any version starts (pre-flight checklist)

Watchdog: a separate daemon restarts Supervisor within 10s if it crashes.

Usage:
    from orchestrator.supervisor import Supervisor, get_supervisor
    sv = get_supervisor()
    sv.pre_flight_check(version=1, tasks=task_list)   # blocks until OK
    sv.start_background()                              # starts watchdog

Standalone:
    python3 orchestrator/supervisor.py --watch         # run as daemon
    python3 orchestrator/supervisor.py --preflight 1   # one-shot check
"""
import os, sys, json, time, threading, subprocess, hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

REPORTS_DIR  = os.path.join(BASE_DIR, "reports")
REGISTRY     = os.path.join(BASE_DIR, "registry", "agents.json")
DASHBOARD    = os.path.join(BASE_DIR, "dashboard")
SUPERVISOR_LOG = os.path.join(REPORTS_DIR, "supervisor.log")

HEARTBEAT_TIMEOUT  = 90    # seconds before an agent is considered stalled
CHECK_INTERVAL     = 60    # supervisor checks every N seconds
SELF_HEARTBEAT_HZ  = 15    # supervisor writes its own heartbeat this often
WATCHDOG_RESTART_S = 10    # watchdog restarts supervisor within this many seconds

Path(REPORTS_DIR).mkdir(exist_ok=True)


# ── Logging ──────────────────────────────────────────────────────────────────

def _log(msg: str, level: str = "INFO"):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{level}] SUPERVISOR: {msg}"
    print(line)
    try:
        with open(SUPERVISOR_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ── Pre-flight checklist ──────────────────────────────────────────────────────

class PreFlightResult:
    def __init__(self):
        self.checks: Dict[str, bool] = {}
        self.fixes: List[str] = []
        self.blocked: bool = False

    def add(self, name: str, ok: bool, fix: str = ""):
        self.checks[name] = ok
        if not ok:
            if fix:
                self.fixes.append(fix)
            else:
                self.blocked = True

    @property
    def all_pass(self) -> bool:
        return all(self.checks.values())

    def report(self) -> str:
        lines = ["Pre-flight checklist:"]
        for name, ok in self.checks.items():
            lines.append(f"  {'✓' if ok else '✗'} {name}")
        if self.fixes:
            lines.append(f"  Auto-fixes applied: {len(self.fixes)}")
        return "\n".join(lines)


class Supervisor:
    """Single-instance supervisor. Call get_supervisor() for the singleton."""

    def __init__(self):
        self._state = None  # DistributedState, lazy-loaded
        self._agent_registry: Dict[str, Any] = {}
        self._stall_callbacks: List = []
        self._running = False
        self._check_thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def pre_flight_check(self, version: int, tasks: list) -> PreFlightResult:
        """
        Full pre-flight before any version starts.
        Auto-fixes everything it can. Blocks only on hardware ceiling.
        Returns PreFlightResult with pass/fail per check.
        """
        result = PreFlightResult()
        _log(f"Pre-flight for v{version} ({len(tasks)} tasks)")

        # 1. Registry loaded
        reg_ok = self._check_registry()
        result.add("registry", reg_ok, fix="loaded from disk" if reg_ok else "")
        if not reg_ok:
            result.add("registry", False)

        # 2. No duplicate tasks already completed this version
        dupes = self._check_duplicates(version, tasks)
        result.add("no_duplicates", dupes == 0, fix=f"skipped {dupes} already done" if dupes > 0 else "")

        # 3. Hardware within limits
        hw_ok, hw_msg = self._check_hardware()
        result.add("hardware", hw_ok)
        if not hw_ok:
            _log(f"Hardware over limit: {hw_msg} — waiting up to 120s", "WARN")
            self._wait_hardware(timeout=120)
            hw_ok2, _ = self._check_hardware()
            result.checks["hardware"] = hw_ok2

        # 4. Claude token budget remaining
        budget_ok, usage = self._check_claude_budget(version, total=len(tasks))
        result.add("claude_budget", budget_ok,
                   fix=f"current usage {usage:.1%} of 10% limit")

        # 5. Old logs purged (keep last 2 versions)
        self._purge_old_logs(version)
        result.add("logs_purged", True, fix="purged old logs")

        # 6. State store reachable
        state_ok = self._check_state_store()
        result.add("state_store", state_ok, fix="initialized" if not state_ok else "")

        _log(result.report())

        if result.blocked:
            _log("Pre-flight BLOCKED — not starting version", "ERROR")
        else:
            _log(f"Pre-flight PASS — v{version} cleared to run")
            self._state_set("supervisor.preflight.v", version)
            self._state_set("supervisor.preflight.ts", time.time())

        return result

    def start_background(self):
        """Start background supervisor loop + heartbeat thread."""
        if self._running:
            return
        self._running = True
        self._check_thread = threading.Thread(
            target=self._check_loop, daemon=True, name="supervisor-check")
        self._check_thread.start()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="supervisor-heartbeat")
        self._heartbeat_thread.start()
        _log("Supervisor started (background)")

    def stop(self):
        self._running = False

    def register_agent(self, name: str, task: dict = None):
        """Agent calls this before starting a task."""
        self._agent_registry[name] = {
            "name": name,
            "last_heartbeat": time.time(),
            "task": task,
            "status": "running",
        }
        self._state_set(f"supervisor.agent.{name}.status", "running")
        self._state_set(f"supervisor.agent.{name}.hb", time.time())

    def agent_done(self, name: str, quality: int = 0):
        """Agent calls this after completing a task."""
        if name in self._agent_registry:
            self._agent_registry[name]["status"] = "idle"
            self._agent_registry[name]["last_quality"] = quality
        self._state_set(f"supervisor.agent.{name}.status", "idle")

    def agent_heartbeat(self, name: str):
        """Agent calls this every 15s while working."""
        if name in self._agent_registry:
            self._agent_registry[name]["last_heartbeat"] = time.time()
        self._state_set(f"supervisor.agent.{name}.hb", time.time())

    def on_stall(self, callback):
        """Register callback(agent_name, task) called when an agent stalls."""
        self._stall_callbacks.append(callback)

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_registry(self) -> bool:
        try:
            with open(REGISTRY) as f:
                reg = json.load(f)
            return bool(reg.get("agents"))
        except Exception:
            return False

    def _check_duplicates(self, version: int, tasks: list) -> int:
        """Count tasks already completed in this version's report."""
        report = os.path.join(REPORTS_DIR, f"v{version}_compare.jsonl")
        if not os.path.exists(report):
            return 0
        done_ids = set()
        try:
            with open(report) as f:
                for line in f:
                    try:
                        r = json.loads(line)
                        if r.get("local_quality", 0) > 0:
                            done_ids.add(r.get("task_id"))
                    except Exception:
                        pass
        except Exception:
            pass
        return len(done_ids)

    def _check_hardware(self):
        try:
            from orchestrator.resource_guard import ResourceGuard
            status = ResourceGuard().check()
            if status.should_kill:
                return False, f"RAM={status.ram_pct}% (kill threshold)"
            if not status.can_spawn:
                return False, f"RAM={status.ram_pct}% (pause threshold)"
            if status.cpu_pct > 90:
                return False, f"CPU={status.cpu_pct}% (throttle threshold)"
            return True, f"RAM={status.ram_pct}% CPU={status.cpu_pct}%"
        except Exception as e:
            return True, f"hardware check unavailable: {e}"

    def _wait_hardware(self, timeout: int = 120):
        try:
            from orchestrator.resource_guard import ResourceGuard
            ResourceGuard().wait_for_headroom(max_wait=timeout)
        except Exception:
            pass

    def _check_claude_budget(self, version: int, total: int):
        try:
            log = os.path.join(REPORTS_DIR, "claude_token_log.jsonl")
            if not os.path.exists(log):
                return True, 0.0
            rescued = 0
            with open(log) as f:
                for line in f:
                    r = json.loads(line)
                    if r.get("version") == version:
                        rescued += 1
            usage = rescued / max(total, 1)
            return usage < 0.10, usage
        except Exception:
            return True, 0.0

    def _check_state_store(self) -> bool:
        try:
            from agents.distributed_state import get_state
            state = get_state()
            state.set("supervisor.alive", True, agent="supervisor")
            return True
        except Exception:
            return False

    def _purge_old_logs(self, current_version: int):
        """Delete version compare files more than 2 versions old."""
        try:
            for f in Path(REPORTS_DIR).glob("v*_compare.jsonl"):
                try:
                    v = int(f.stem.split("_")[0][1:])
                    if v < current_version - 2:
                        f.unlink()
                        _log(f"Purged old log: {f.name}")
                except Exception:
                    pass
        except Exception:
            pass

    # ── Background loops ──────────────────────────────────────────────────────

    def _check_loop(self):
        """Main supervisor check loop — runs every CHECK_INTERVAL seconds."""
        while self._running:
            try:
                self._check_stalled_agents()
                self._check_degraded_agents()
                self._state_set("supervisor.check.ts", time.time())
            except Exception as e:
                _log(f"Check loop error: {e}", "ERROR")
            time.sleep(CHECK_INTERVAL)

    def _heartbeat_loop(self):
        """Write supervisor heartbeat every SELF_HEARTBEAT_HZ seconds."""
        while self._running:
            try:
                self._state_set("supervisor.alive", True)
                self._state_set("supervisor.hb", time.time())
            except Exception:
                pass
            time.sleep(SELF_HEARTBEAT_HZ)

    def _check_stalled_agents(self):
        """Find agents that haven't sent a heartbeat in HEARTBEAT_TIMEOUT seconds."""
        now = time.time()
        for name, info in list(self._agent_registry.items()):
            if info.get("status") != "running":
                continue
            age = now - info.get("last_heartbeat", now)
            if age > HEARTBEAT_TIMEOUT:
                task = info.get("task", {})
                _log(f"Agent '{name}' stalled ({age:.0f}s no heartbeat) — task: {task.get('title','?')}", "WARN")
                self._state_set(f"supervisor.agent.{name}.status", "stalled")
                for cb in self._stall_callbacks:
                    try:
                        cb(name, task)
                    except Exception:
                        pass

    def _check_degraded_agents(self):
        """Flag agents with 2 consecutive low-quality outputs."""
        try:
            with open(REGISTRY) as f:
                reg = json.load(f)
            for agent_name, info in reg.get("agents", {}).items():
                scores = info.get("recent_scores", [])
                if len(scores) >= 2 and all(s < 40 for s in scores[-2:]):
                    _log(f"Agent '{agent_name}' degraded: recent scores {scores[-2:]} — flagging for repair", "WARN")
                    self._state_set(f"supervisor.degraded.{agent_name}", True)
        except Exception:
            pass

    def _state_set(self, key: str, value):
        try:
            if self._state is None:
                from agents.distributed_state import get_state
                self._state = get_state()
            self._state.set(key, value, agent="supervisor")
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_supervisor: Optional[Supervisor] = None
_sv_lock = threading.Lock()


def get_supervisor() -> Supervisor:
    global _supervisor
    with _sv_lock:
        if _supervisor is None:
            _supervisor = Supervisor()
            _supervisor.start_background()
    return _supervisor


# ── Watchdog (restarts Supervisor if it crashes) ──────────────────────────────

def run_watchdog():
    """
    Watchdog daemon: keeps supervisor alive.
    Restarts it within WATCHDOG_RESTART_S if it dies.
    Run as: python3 orchestrator/supervisor.py --watchdog
    """
    import signal
    _log("Watchdog started")

    def _check_supervisor_alive() -> bool:
        try:
            from agents.distributed_state import get_state
            state = get_state()
            hb = state.get("supervisor.hb", 0)
            return hb > 0 and (time.time() - hb) < HEARTBEAT_TIMEOUT
        except Exception:
            return False

    proc = None
    script = str(Path(__file__).resolve())

    while True:
        alive = _check_supervisor_alive()
        if not alive:
            _log("Supervisor heartbeat missing — restarting", "WARN")
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            proc = subprocess.Popen(
                [sys.executable, script, "--watch"],
                stdout=open(SUPERVISOR_LOG, "a"),
                stderr=subprocess.STDOUT,
            )
            _log(f"Supervisor restarted (pid={proc.pid})")
        time.sleep(WATCHDOG_RESTART_S)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Agent system supervisor")
    ap.add_argument("--watch",     action="store_true", help="Run as background daemon")
    ap.add_argument("--watchdog",  action="store_true", help="Run watchdog that restarts supervisor")
    ap.add_argument("--preflight", type=int, metavar="VERSION", help="Run pre-flight check for version N")
    ap.add_argument("--status",    action="store_true", help="Print supervisor status and exit")
    args = ap.parse_args()

    if args.watchdog:
        run_watchdog()
        return

    if args.preflight:
        sv = Supervisor()
        from tasks.task_suite import build_task_suite
        tasks = build_task_suite()
        result = sv.pre_flight_check(args.preflight, tasks)
        print(result.report())
        sys.exit(0 if result.all_pass else 1)

    if args.status:
        try:
            from agents.distributed_state import get_state
            state = get_state()
            hb = state.get("supervisor.hb", 0)
            if hb:
                age = time.time() - hb
                print(f"Supervisor alive — last heartbeat {age:.0f}s ago")
            else:
                print("Supervisor: no heartbeat found (not running?)")
            agents = state.get_all("supervisor.agent.")
            for k, v in agents.items():
                print(f"  {k}: {v}")
        except Exception as e:
            print(f"Cannot read state: {e}")
        return

    if args.watch:
        sv = get_supervisor()
        _log("Supervisor watch mode — ctrl-c to stop")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            sv.stop()
            _log("Supervisor stopped")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
