#!/usr/bin/env python3
"""
resource_guard.py — Hardware-aware resource monitor
====================================================
Monitors CPU and RAM usage. Signals orchestrator when to pause/kill agents.

Thresholds:
  RAM <80%  : allow spawning up to cpu_count * 2 agents
  RAM 80-85%: pause new spawns, let current agents finish
  RAM >85%  : kill lowest-priority agent (lowest quality score)
  CPU >90%  : throttle to 1 concurrent agent

Usage:
  from orchestrator.resource_guard import ResourceGuard
  guard = ResourceGuard()
  guard.check()                  # returns ResourceStatus
  guard.max_concurrent_agents()  # returns int

  python3 resource_guard.py --check  # CLI status check
"""
import os, sys, subprocess, time, argparse
from dataclasses import dataclass
from typing import Optional


@dataclass
class ResourceStatus:
    ram_pct: float
    cpu_pct: float
    cpu_count: int
    can_spawn: bool
    should_kill: bool
    max_agents: int
    action: str   # "normal" | "pause" | "kill" | "throttle"

    @property
    def max_workers(self) -> int:
        """Alias for max_agents — how many concurrent agents to spawn."""
        return self.max_agents


def _get_ram_pct() -> float:
    """Return used RAM as percentage on macOS via vm_stat."""
    try:
        out = subprocess.check_output(["vm_stat"], text=True)
        lines = {l.split(":")[0].strip(): l.split(":")[1].strip()
                 for l in out.splitlines() if ":" in l}
        page_size = 4096
        free    = int(lines.get("Pages free", "0").rstrip(".")) * page_size
        active  = int(lines.get("Pages active", "0").rstrip(".")) * page_size
        inactive = int(lines.get("Pages inactive", "0").rstrip(".")) * page_size
        wired   = int(lines.get("Pages wired down", "0").rstrip(".")) * page_size
        total   = free + active + inactive + wired
        used    = active + wired
        return round(used / total * 100, 1) if total > 0 else 0.0
    except Exception:
        # Fallback: try sysctl
        try:
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            total_bytes = int(out)
            # vm.swapusage for used — rough estimate
            vm_out = subprocess.check_output(["sysctl", "-n", "vm.swapusage"], text=True)
            return 50.0   # default safe assumption
        except Exception:
            return 50.0


def _get_cpu_pct() -> float:
    """Return CPU usage % via top snapshot (macOS)."""
    try:
        out = subprocess.check_output(
            ["top", "-l", "1", "-n", "0", "-s", "0"],
            text=True, timeout=5
        )
        for line in out.splitlines():
            if "CPU usage" in line or "CPU Usages" in line:
                # e.g. "CPU usage: 12.34% user, 5.67% sys, 81.99% idle"
                parts = line.replace(",", "").split()
                for i, p in enumerate(parts):
                    if p.endswith("%") and i > 0 and "idle" in parts[i+1] if i+1 < len(parts) else False:
                        idle = float(p.rstrip("%"))
                        return round(100.0 - idle, 1)
        return 20.0  # safe default
    except Exception:
        return 20.0


def _get_cpu_count() -> int:
    try:
        out = subprocess.check_output(["sysctl", "-n", "hw.ncpu"], text=True).strip()
        return max(1, int(out))
    except Exception:
        return os.cpu_count() or 4


class ResourceGuard:
    PAUSE_RAM   = 80.0
    KILL_RAM    = 85.0
    THROTTLE_CPU = 90.0

    def check(self) -> ResourceStatus:
        ram_pct  = _get_ram_pct()
        cpu_pct  = _get_cpu_pct()
        cpu_count = _get_cpu_count()

        if ram_pct > self.KILL_RAM:
            action = "kill"
            can_spawn = False
            should_kill = True
            max_agents = 1
        elif ram_pct > self.PAUSE_RAM:
            action = "pause"
            can_spawn = False
            should_kill = False
            max_agents = 1
        elif cpu_pct > self.THROTTLE_CPU:
            action = "throttle"
            can_spawn = True
            should_kill = False
            max_agents = 1
        else:
            action = "normal"
            can_spawn = True
            should_kill = False
            max_agents = min(cpu_count * 2, 8)

        return ResourceStatus(
            ram_pct=ram_pct,
            cpu_pct=cpu_pct,
            cpu_count=cpu_count,
            can_spawn=can_spawn,
            should_kill=should_kill,
            max_agents=max_agents,
            action=action,
        )

    def wait_for_headroom(self, poll_interval: int = 10, max_wait: int = 300):
        """Block until RAM drops below PAUSE threshold. Max wait: max_wait seconds."""
        waited = 0
        while waited < max_wait:
            status = self.check()
            if status.can_spawn:
                return status
            print(f"[RESOURCE] RAM={status.ram_pct}% — waiting for headroom ({waited}s/{max_wait}s)")
            time.sleep(poll_interval)
            waited += poll_interval
        return self.check()  # return current status even if still over threshold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="Print resource status and exit")
    ap.add_argument("--watch", type=int, default=0, metavar="SECS",
                    help="Watch resources every N seconds")
    args = ap.parse_args()

    guard = ResourceGuard()

    if args.watch > 0:
        while True:
            s = guard.check()
            print(f"[RESOURCE] RAM={s.ram_pct}%  CPU={s.cpu_pct}%  "
                  f"CPUs={s.cpu_count}  max_agents={s.max_agents}  action={s.action}")
            time.sleep(args.watch)
    else:
        s = guard.check()
        print(f"RAM:        {s.ram_pct}%")
        print(f"CPU:        {s.cpu_pct}%")
        print(f"CPU count:  {s.cpu_count}")
        print(f"Max agents: {s.max_agents}")
        print(f"Can spawn:  {s.can_spawn}")
        print(f"Action:     {s.action}")


if __name__ == "__main__":
    main()
