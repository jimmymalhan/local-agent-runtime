"""
velocity_tracker.py - Track agent throughput, identify blockers, forecast completion.

Logs every task, computes velocity, generates weekly reports.
Exposed in dashboard as "Tasks/day", "Success rate", "Top blockers".

Usage:
    tracker = VelocityTracker()
    tracker.log_task(task, result, duration_secs)
    report = tracker.weekly_report()
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path("local-agents/reports/velocity.db")


class VelocityTracker:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH))
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS task_log (
            id TEXT PRIMARY KEY,
            title TEXT,
            category TEXT,
            agent TEXT,
            started_at TEXT,
            finished_at TEXT,
            duration_secs REAL,
            quality INTEGER,
            success INTEGER,
            blocker_reason TEXT,
            tokens_used INTEGER,
            project_id TEXT,
            retry_count INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_category ON task_log(category);
        CREATE INDEX IF NOT EXISTS idx_started ON task_log(started_at);
        """)
        self.conn.commit()

    def log_task(self, task: dict, result: dict, duration_secs: float):
        quality = result.get("quality", 0)
        success = 1 if quality >= 60 else 0
        blocker = result.get("error", "") if not success else ""
        self.conn.execute("""
        INSERT OR REPLACE INTO task_log
        (id, title, category, agent, started_at, finished_at, duration_secs,
         quality, success, blocker_reason, tokens_used, project_id, retry_count)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            task.get("id", str(datetime.utcnow().timestamp())),
            task.get("title", "")[:100], task.get("category", "code_gen"),
            result.get("agent", result.get("agent_name", "unknown")),
            task.get("started_at", datetime.utcnow().isoformat()),
            datetime.utcnow().isoformat(),
            duration_secs, quality, success, (blocker or "")[:200],
            result.get("tokens_used", 0),
            task.get("project_id", ""), task.get("retry_count", 0)
        ))
        self.conn.commit()

    def velocity(self, days: int = 7) -> dict:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = self.conn.execute("""
        SELECT category, COUNT(*) as total, SUM(success) as ok,
               AVG(quality) as avg_q, AVG(duration_secs) as avg_dur
        FROM task_log WHERE started_at >= ?
        GROUP BY category ORDER BY total DESC
        """, (since,)).fetchall()
        total_row = self.conn.execute("""
        SELECT COUNT(*), SUM(success), AVG(quality)
        FROM task_log WHERE started_at >= ?
        """, (since,)).fetchone()
        return {
            "days": days,
            "total_tasks": total_row[0] or 0,
            "tasks_per_day": round((total_row[0] or 0) / days, 1),
            "success_rate": round((total_row[1] or 0) / max(total_row[0] or 1, 1) * 100, 1),
            "quality_avg": round(total_row[2] or 0, 1),
            "by_category": [
                {"category": r[0], "total": r[1], "ok": r[2],
                 "quality_avg": round(r[3] or 0, 1), "avg_secs": round(r[4] or 0, 1)}
                for r in rows
            ]
        }

    def top_blockers(self, n: int = 5) -> list:
        since = (datetime.utcnow() - timedelta(days=30)).isoformat()
        rows = self.conn.execute(
            "SELECT blocker_reason, COUNT(*) as cnt FROM task_log "
            "WHERE success=0 AND blocker_reason!='' AND started_at >= ? "
            "GROUP BY blocker_reason ORDER BY cnt DESC LIMIT ?",
            (since, n)).fetchall()
        return [{"pattern": r[0][:100], "count": r[1]} for r in rows]

    def forecast(self, remaining_tasks: int) -> dict:
        vel = self.velocity(7)
        tpd = vel["tasks_per_day"]
        if tpd <= 0:
            return {"days_remaining": None, "estimated_done": None, "confidence": "low"}
        days = remaining_tasks / tpd
        return {
            "days_remaining": round(days, 1),
            "estimated_done": (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d"),
            "confidence": "high" if vel["success_rate"] > 80 else "medium" if vel["success_rate"] > 60 else "low"
        }

    def burndown(self, project_id: str, total_tasks: int) -> list:
        """Return daily remaining tasks for burndown chart."""
        rows = self.conn.execute("""
        SELECT DATE(finished_at) as day, COUNT(*) as completed
        FROM task_log WHERE project_id=? AND success=1
        GROUP BY day ORDER BY day
        """, (project_id,)).fetchall()
        completed = 0
        burndown = []
        for row in rows:
            completed += row[1]
            burndown.append({
                "date": row[0],
                "remaining": max(0, total_tasks - completed),
                "completed": completed
            })
        return burndown

    def weekly_report(self) -> str:
        """Generate markdown weekly report."""
        vel = self.velocity(7)
        blockers = self.top_blockers(5)
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        out = [
            f"# Weekly Velocity Report - {date_str}",
            "",
            "## Summary",
            f"- Tasks completed: **{vel['total_tasks']}** ({vel['tasks_per_day']}/day)",
            f"- Success rate: **{vel['success_rate']}%**",
            f"- Quality avg: **{vel['quality_avg']}/100**",
            "",
            "## By Category",
        ]
        for c in vel["by_category"]:
            out.append(
                f"- {c['category']}: {c['total']} tasks, "
                f"{c['quality_avg']} avg quality, {c['avg_secs']:.0f}s avg"
            )
        if blockers:
            out.extend(["", "## Top Blockers"])
            for b in blockers:
                out.append(f"- ({b['count']}x) {b['pattern']}")
        nl = chr(10)
        report = nl.join(out)
        stamp = datetime.utcnow().strftime("%Y%m%d")
        rf = Path(f"local-agents/reports/weekly_{stamp}.md")
        rf.parent.mkdir(parents=True, exist_ok=True)
        rf.write_text(report)
        return report
