"""
Quality Dashboards & Reports — Visualize quality metrics over time.

Reads from:
  - reports/eval_history.jsonl   (per-eval scores, latency, tokens)
  - reports/eval_trends.json     (daily aggregated trends)
  - reports/eval_alerts.jsonl    (regression alerts)
  - reports/v5_compare.jsonl     (local vs Opus quality comparison)
  - state/agent_success_stats.json (agent success rates)
  - state/autonomous_execution.jsonl (task execution log)

Produces:
  - Terminal-rendered quality dashboards (ANSI)
  - HTML report written to reports/quality_report.html
  - JSON summary written to reports/quality_summary.json
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"
STATE_DIR = BASE_DIR / "state"

EVAL_HISTORY = REPORTS_DIR / "eval_history.jsonl"
EVAL_TRENDS = REPORTS_DIR / "eval_trends.json"
EVAL_ALERTS = REPORTS_DIR / "eval_alerts.jsonl"
V5_COMPARE = REPORTS_DIR / "v5_compare.jsonl"
AGENT_STATS = STATE_DIR / "agent_success_stats.json"
EXEC_LOG = STATE_DIR / "autonomous_execution.jsonl"

# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file into a list of dicts, skipping bad lines."""
    records: list[dict] = []
    if not path.exists():
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def load_json(path: Path) -> Any:
    """Load a JSON file."""
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

class QualityMetrics:
    """Compute and hold quality metrics from raw data."""

    def __init__(self) -> None:
        self.eval_history: list[dict] = load_jsonl(EVAL_HISTORY)
        self.eval_trends: list[dict] = load_json(EVAL_TRENDS) or []
        self.eval_alerts: list[dict] = load_jsonl(EVAL_ALERTS)
        self.comparisons: list[dict] = load_jsonl(V5_COMPARE)
        self.agent_stats: dict = load_json(AGENT_STATS) or {}
        self.exec_log: list[dict] = [
            r for r in load_jsonl(EXEC_LOG)
            if r.get("action") == "execute_task"
        ]

    # -- Agent success rates --------------------------------------------------
    def agent_success_rates(self) -> dict[str, dict]:
        """Return {agent: {success, total, rate, tokens}}."""
        out = {}
        for agent, info in self.agent_stats.items():
            out[agent] = {
                "success": info.get("success", 0),
                "total": info.get("total", 0),
                "rate": round(info.get("success_rate", 0) * 100, 1),
                "tokens": info.get("tokens", 0),
            }
        return out

    # -- Eval scores by agent -------------------------------------------------
    def scores_by_agent(self) -> dict[str, list[float]]:
        """Group eval scores by agent name."""
        by_agent: dict[str, list[float]] = defaultdict(list)
        for rec in self.eval_history:
            agent = rec.get("agent", "unknown")
            score = rec.get("score")
            if score is not None:
                by_agent[agent].append(float(score))
        return dict(by_agent)

    # -- Eval scores by category ----------------------------------------------
    def scores_by_category(self) -> dict[str, list[float]]:
        by_cat: dict[str, list[float]] = defaultdict(list)
        for rec in self.eval_history:
            cat = rec.get("category", "unknown")
            score = rec.get("score")
            if score is not None:
                by_cat[cat].append(float(score))
        return dict(by_cat)

    # -- Latency stats --------------------------------------------------------
    def latency_stats(self) -> dict[str, float]:
        """Compute p50, p95, p99, mean latency from eval history."""
        lats = [r["latency_s"] for r in self.eval_history if "latency_s" in r]
        if not lats:
            return {"p50": 0, "p95": 0, "p99": 0, "mean": 0, "count": 0}
        lats.sort()
        n = len(lats)
        return {
            "p50": round(lats[int(n * 0.5)], 2),
            "p95": round(lats[int(n * 0.95)], 2),
            "p99": round(lats[min(int(n * 0.99), n - 1)], 2),
            "mean": round(statistics.mean(lats), 2),
            "count": n,
        }

    # -- Quality over time (from exec log) ------------------------------------
    def quality_over_time(self, bucket_minutes: int = 60) -> list[dict]:
        """Bucket execution quality scores by time window."""
        if not self.exec_log:
            return []
        buckets: dict[str, list[float]] = defaultdict(list)
        for rec in self.exec_log:
            ts = rec.get("ts", "")
            quality = rec.get("quality")
            if not ts or quality is None:
                continue
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                continue
            bucket_key = dt.replace(
                minute=(dt.minute // bucket_minutes) * bucket_minutes,
                second=0, microsecond=0,
            ).isoformat()
            buckets[bucket_key].append(float(quality))
        result = []
        for ts_key in sorted(buckets):
            scores = buckets[ts_key]
            result.append({
                "timestamp": ts_key,
                "avg_quality": round(statistics.mean(scores), 1),
                "min_quality": round(min(scores), 1),
                "max_quality": round(max(scores), 1),
                "count": len(scores),
            })
        return result

    # -- Local vs Opus comparison ---------------------------------------------
    def local_vs_opus(self) -> dict:
        """Summarize local vs Opus comparison data."""
        if not self.comparisons:
            return {"total": 0, "local_wins": 0, "win_rate": 0, "avg_gap": 0}
        wins = sum(1 for c in self.comparisons if c.get("local_won"))
        gaps = [c.get("gap", 0) for c in self.comparisons]
        return {
            "total": len(self.comparisons),
            "local_wins": wins,
            "win_rate": round(wins / len(self.comparisons) * 100, 1),
            "avg_gap": round(statistics.mean(gaps), 1) if gaps else 0,
            "by_category": self._compare_by_category(),
        }

    def _compare_by_category(self) -> dict[str, dict]:
        cats: dict[str, list[dict]] = defaultdict(list)
        for c in self.comparisons:
            cats[c.get("category", "unknown")].append(c)
        out = {}
        for cat, recs in cats.items():
            local_avg = statistics.mean(r.get("local_quality", 0) for r in recs)
            opus_avg = statistics.mean(r.get("opus_quality", 0) for r in recs)
            wins = sum(1 for r in recs if r.get("local_won"))
            out[cat] = {
                "local_avg": round(local_avg, 1),
                "opus_avg": round(opus_avg, 1),
                "win_rate": round(wins / len(recs) * 100, 1),
                "count": len(recs),
            }
        return out

    # -- Alerts summary -------------------------------------------------------
    def alerts_summary(self) -> list[dict]:
        return [
            {
                "severity": a.get("severity"),
                "metric": a.get("metric"),
                "agent": a.get("agent"),
                "current": a.get("current_value"),
                "baseline": a.get("baseline_value"),
                "delta_pct": a.get("delta_pct"),
                "message": a.get("message"),
            }
            for a in self.eval_alerts
        ]

    # -- Full summary ---------------------------------------------------------
    def full_summary(self) -> dict:
        agent_scores = self.scores_by_agent()
        cat_scores = self.scores_by_category()
        return {
            "generated_at": datetime.now().isoformat(),
            "eval_count": len(self.eval_history),
            "exec_count": len(self.exec_log),
            "agent_success_rates": self.agent_success_rates(),
            "agent_avg_scores": {
                a: round(statistics.mean(s), 1) for a, s in agent_scores.items()
            },
            "category_avg_scores": {
                c: round(statistics.mean(s), 1) for c, s in cat_scores.items()
            },
            "latency": self.latency_stats(),
            "local_vs_opus": self.local_vs_opus(),
            "quality_over_time": self.quality_over_time(),
            "alerts": self.alerts_summary(),
            "trends": self.eval_trends,
        }


# ---------------------------------------------------------------------------
# Terminal dashboard (ANSI)
# ---------------------------------------------------------------------------

def _bar(value: float, max_val: float = 100, width: int = 30) -> str:
    """Render a horizontal bar chart segment."""
    filled = int(round(value / max_val * width))
    filled = max(0, min(width, filled))
    empty = width - filled
    if value >= 90:
        color = "\033[92m"  # green
    elif value >= 70:
        color = "\033[93m"  # yellow
    else:
        color = "\033[91m"  # red
    reset = "\033[0m"
    return f"{color}{'█' * filled}{'░' * empty}{reset} {value:5.1f}"


def _section(title: str) -> str:
    line = "─" * 60
    return f"\n\033[1;36m{line}\n  {title}\n{line}\033[0m"


def render_terminal_dashboard(metrics: QualityMetrics) -> str:
    """Produce a full terminal dashboard string."""
    lines: list[str] = []
    lines.append("\033[1;37m")
    lines.append("╔══════════════════════════════════════════════════════════════╗")
    lines.append("║           QUALITY DASHBOARD & METRICS REPORT                ║")
    lines.append(f"║           Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):>36s}   ║")
    lines.append("╚══════════════════════════════════════════════════════════════╝")
    lines.append("\033[0m")

    # --- Agent Success Rates ---
    lines.append(_section("AGENT SUCCESS RATES"))
    rates = metrics.agent_success_rates()
    for agent, info in sorted(rates.items(), key=lambda x: -x[1]["rate"]):
        lines.append(
            f"  {agent:<16s} {_bar(info['rate'])}% "
            f"({info['success']}/{info['total']} tasks, {info['tokens']:,} tokens)"
        )

    # --- Agent Eval Scores ---
    lines.append(_section("AGENT AVERAGE EVAL SCORES"))
    agent_scores = metrics.scores_by_agent()
    for agent, scores in sorted(agent_scores.items(), key=lambda x: -statistics.mean(x[1])):
        avg = statistics.mean(scores)
        std = statistics.stdev(scores) if len(scores) > 1 else 0
        lines.append(
            f"  {agent:<16s} {_bar(avg)} "
            f"(n={len(scores)}, σ={std:.1f})"
        )

    # --- Category Scores ---
    lines.append(_section("SCORES BY CATEGORY"))
    cat_scores = metrics.scores_by_category()
    for cat, scores in sorted(cat_scores.items(), key=lambda x: -statistics.mean(x[1])):
        avg = statistics.mean(scores)
        lines.append(f"  {cat:<16s} {_bar(avg)} (n={len(scores)})")

    # --- Latency ---
    lines.append(_section("LATENCY (seconds)"))
    lat = metrics.latency_stats()
    lines.append(f"  {'p50':<8s} {lat['p50']:>6.2f}s")
    lines.append(f"  {'p95':<8s} {lat['p95']:>6.2f}s")
    lines.append(f"  {'p99':<8s} {lat['p99']:>6.2f}s")
    lines.append(f"  {'mean':<8s} {lat['mean']:>6.2f}s")
    lines.append(f"  {'count':<8s} {lat['count']:>6d}")

    # --- Local vs Opus ---
    lines.append(_section("LOCAL vs OPUS 4.6"))
    comp = metrics.local_vs_opus()
    lines.append(f"  Total comparisons: {comp['total']}")
    lines.append(f"  Local wins:        {comp['local_wins']} ({comp['win_rate']}%)")
    lines.append(f"  Avg gap:           {comp['avg_gap']:+.1f} (negative = local better)")
    if comp.get("by_category"):
        lines.append("")
        lines.append(f"  {'Category':<16s} {'Local':>7s} {'Opus':>7s} {'Win%':>7s} {'N':>5s}")
        lines.append(f"  {'─' * 44}")
        for cat, info in sorted(comp["by_category"].items()):
            lines.append(
                f"  {cat:<16s} {info['local_avg']:>7.1f} {info['opus_avg']:>7.1f} "
                f"{info['win_rate']:>6.1f}% {info['count']:>5d}"
            )

    # --- Quality Over Time (last 10 buckets) ---
    lines.append(_section("QUALITY OVER TIME"))
    qot = metrics.quality_over_time()
    display = qot[-10:] if len(qot) > 10 else qot
    if display:
        lines.append(f"  {'Time':<22s} {'Avg':>6s} {'Min':>6s} {'Max':>6s} {'N':>5s}  Chart")
        lines.append(f"  {'─' * 66}")
        for bucket in display:
            ts_short = bucket["timestamp"][11:16] if "T" in bucket["timestamp"] else bucket["timestamp"][:16]
            mini_bar = "█" * int(bucket["avg_quality"] / 5)
            lines.append(
                f"  {ts_short:<22s} {bucket['avg_quality']:>6.1f} "
                f"{bucket['min_quality']:>6.1f} {bucket['max_quality']:>6.1f} "
                f"{bucket['count']:>5d}  {mini_bar}"
            )
    else:
        lines.append("  No execution data available.")

    # --- Alerts ---
    lines.append(_section("ACTIVE ALERTS"))
    alerts = metrics.alerts_summary()
    if alerts:
        for a in alerts:
            sev_color = "\033[91m" if a["severity"] == "critical" else "\033[93m"
            lines.append(f"  {sev_color}[{a['severity'].upper()}]\033[0m {a['message']}")
    else:
        lines.append("  \033[92mNo active alerts.\033[0m")

    # --- Trends ---
    lines.append(_section("DAILY TRENDS"))
    if metrics.eval_trends:
        for trend in metrics.eval_trends[-7:]:
            lines.append(
                f"  {trend.get('date', 'N/A'):<12s} "
                f"avg={trend.get('avg_score', 0):>5.1f}  "
                f"min={trend.get('min_score', 0):>5.1f}  "
                f"max={trend.get('max_score', 0):>5.1f}  "
                f"evals={trend.get('total_evals', 0)}"
            )
    else:
        lines.append("  No trend data available.")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report generator
# ---------------------------------------------------------------------------

def generate_html_report(metrics: QualityMetrics) -> str:
    """Generate a self-contained HTML quality report."""
    summary = metrics.full_summary()
    agent_rates = summary["agent_success_rates"]
    agent_avgs = summary["agent_avg_scores"]
    cat_avgs = summary["category_avg_scores"]
    lat = summary["latency"]
    comp = summary["local_vs_opus"]
    alerts = summary["alerts"]
    qot = summary["quality_over_time"]

    def score_color(val: float) -> str:
        if val >= 90:
            return "#22c55e"
        if val >= 70:
            return "#eab308"
        return "#ef4444"

    agent_rows = ""
    for agent in sorted(agent_rates):
        info = agent_rates[agent]
        avg_score = agent_avgs.get(agent, 0)
        agent_rows += f"""
        <tr>
          <td>{agent}</td>
          <td><div class="bar-bg"><div class="bar" style="width:{info['rate']}%;background:{score_color(info['rate'])}"></div></div></td>
          <td>{info['rate']}%</td>
          <td>{info['success']}/{info['total']}</td>
          <td style="color:{score_color(avg_score)}">{avg_score:.1f}</td>
          <td>{info['tokens']:,}</td>
        </tr>"""

    cat_rows = ""
    for cat in sorted(cat_avgs):
        avg = cat_avgs[cat]
        cat_rows += f"""
        <tr>
          <td>{cat}</td>
          <td><div class="bar-bg"><div class="bar" style="width:{avg}%;background:{score_color(avg)}"></div></div></td>
          <td style="color:{score_color(avg)}">{avg:.1f}</td>
        </tr>"""

    alert_rows = ""
    for a in alerts:
        sev_class = "alert-critical" if a["severity"] == "critical" else "alert-warning"
        alert_rows += f"""
        <tr class="{sev_class}">
          <td>{a['severity'].upper()}</td>
          <td>{a['agent']}</td>
          <td>{a['metric']}</td>
          <td>{a['current']}</td>
          <td>{a['baseline']}</td>
          <td>{a['delta_pct']:+.1f}%</td>
        </tr>"""

    comp_cat_rows = ""
    for cat, info in sorted((comp.get("by_category") or {}).items()):
        comp_cat_rows += f"""
        <tr>
          <td>{cat}</td>
          <td>{info['local_avg']:.1f}</td>
          <td>{info['opus_avg']:.1f}</td>
          <td style="color:{score_color(info['win_rate'])}">{info['win_rate']:.1f}%</td>
          <td>{info['count']}</td>
        </tr>"""

    qot_labels = json.dumps([b["timestamp"][11:16] if "T" in b["timestamp"] else b["timestamp"][:16] for b in qot[-24:]])
    qot_avg = json.dumps([b["avg_quality"] for b in qot[-24:]])
    qot_min = json.dumps([b["min_quality"] for b in qot[-24:]])
    qot_max = json.dumps([b["max_quality"] for b in qot[-24:]])

    agent_chart_labels = json.dumps(sorted(agent_avgs.keys()))
    agent_chart_values = json.dumps([agent_avgs[a] for a in sorted(agent_avgs.keys())])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Quality Dashboard — Agent Runtime</title>
<style>
  :root {{ --bg: #0f172a; --card: #1e293b; --border: #334155; --text: #e2e8f0;
           --accent: #38bdf8; --green: #22c55e; --yellow: #eab308; --red: #ef4444; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); padding: 24px; }}
  h1 {{ color: var(--accent); margin-bottom: 8px; font-size: 28px; }}
  h2 {{ color: var(--accent); margin: 24px 0 12px; font-size: 20px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
  .subtitle {{ color: #94a3b8; font-size: 14px; margin-bottom: 24px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .stat-card {{ background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }}
  .stat-card .label {{ color: #94a3b8; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}
  .stat-card .value {{ font-size: 32px; font-weight: 700; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 12px; overflow: hidden; margin-bottom: 16px; }}
  th {{ background: #0f172a; padding: 10px 14px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; color: #94a3b8; }}
  td {{ padding: 10px 14px; border-top: 1px solid var(--border); }}
  .bar-bg {{ background: #334155; border-radius: 4px; height: 12px; width: 100%; min-width: 120px; }}
  .bar {{ height: 12px; border-radius: 4px; transition: width 0.3s; }}
  .alert-critical td {{ background: rgba(239,68,68,0.1); }}
  .alert-warning td {{ background: rgba(234,179,8,0.1); }}
  canvas {{ background: var(--card); border-radius: 12px; padding: 16px; border: 1px solid var(--border); max-width: 100%; }}
  .chart-container {{ margin-bottom: 24px; }}
</style>
</head>
<body>

<h1>Quality Dashboard</h1>
<p class="subtitle">Generated {summary['generated_at'][:19]} &mdash; {summary['eval_count']} evaluations, {summary['exec_count']} executions</p>

<!-- KPI Cards -->
<div class="grid">
  <div class="stat-card">
    <div class="label">Overall Avg Score</div>
    <div class="value" style="color:{score_color(summary['trends'][0]['avg_score'] if summary['trends'] else 0)}">{summary['trends'][0]['avg_score'] if summary['trends'] else 'N/A'}</div>
  </div>
  <div class="stat-card">
    <div class="label">Local Win Rate</div>
    <div class="value" style="color:{score_color(comp['win_rate'])}">{comp['win_rate']}%</div>
  </div>
  <div class="stat-card">
    <div class="label">p95 Latency</div>
    <div class="value">{lat['p95']}s</div>
  </div>
  <div class="stat-card">
    <div class="label">Active Alerts</div>
    <div class="value" style="color:{'var(--red)' if alerts else 'var(--green)'}">{len(alerts)}</div>
  </div>
  <div class="stat-card">
    <div class="label">Total Evaluations</div>
    <div class="value">{summary['eval_count']}</div>
  </div>
  <div class="stat-card">
    <div class="label">Avg Gap vs Opus</div>
    <div class="value" style="color:{'var(--green)' if comp['avg_gap'] < 0 else 'var(--red)'}">{comp['avg_gap']:+.1f}</div>
  </div>
</div>

<!-- Agent Performance -->
<h2>Agent Performance</h2>
<table>
  <thead><tr><th>Agent</th><th>Success Rate</th><th>Rate</th><th>Tasks</th><th>Avg Score</th><th>Tokens</th></tr></thead>
  <tbody>{agent_rows}</tbody>
</table>

<!-- Category Scores -->
<h2>Scores by Category</h2>
<table>
  <thead><tr><th>Category</th><th>Score Distribution</th><th>Average</th></tr></thead>
  <tbody>{cat_rows}</tbody>
</table>

<!-- Latency -->
<h2>Latency Profile</h2>
<div class="grid">
  <div class="stat-card"><div class="label">p50</div><div class="value">{lat['p50']}s</div></div>
  <div class="stat-card"><div class="label">p95</div><div class="value">{lat['p95']}s</div></div>
  <div class="stat-card"><div class="label">p99</div><div class="value">{lat['p99']}s</div></div>
  <div class="stat-card"><div class="label">Mean</div><div class="value">{lat['mean']}s</div></div>
</div>

<!-- Quality Over Time Chart -->
<h2>Quality Over Time</h2>
<div class="chart-container">
  <canvas id="qualityChart" height="100"></canvas>
</div>

<!-- Agent Radar -->
<h2>Agent Score Comparison</h2>
<div class="chart-container">
  <canvas id="agentChart" height="80"></canvas>
</div>

<!-- Local vs Opus -->
<h2>Local vs Opus 4.6</h2>
<div class="grid">
  <div class="stat-card"><div class="label">Total Comparisons</div><div class="value">{comp['total']}</div></div>
  <div class="stat-card"><div class="label">Local Wins</div><div class="value" style="color:var(--green)">{comp['local_wins']}</div></div>
  <div class="stat-card"><div class="label">Win Rate</div><div class="value" style="color:{score_color(comp['win_rate'])}">{comp['win_rate']}%</div></div>
</div>
<table>
  <thead><tr><th>Category</th><th>Local Avg</th><th>Opus Avg</th><th>Win Rate</th><th>Count</th></tr></thead>
  <tbody>{comp_cat_rows}</tbody>
</table>

<!-- Alerts -->
<h2>Alerts</h2>
{"<table><thead><tr><th>Severity</th><th>Agent</th><th>Metric</th><th>Current</th><th>Baseline</th><th>Delta</th></tr></thead><tbody>" + alert_rows + "</tbody></table>" if alerts else '<p style="color:var(--green)">No active alerts.</p>'}

<!-- Charts (Chart.js CDN) -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
const qLabels = {qot_labels};
const qAvg = {qot_avg};
const qMin = {qot_min};
const qMax = {qot_max};

if (qLabels.length > 0) {{
  new Chart(document.getElementById('qualityChart'), {{
    type: 'line',
    data: {{
      labels: qLabels,
      datasets: [
        {{ label: 'Avg Quality', data: qAvg, borderColor: '#38bdf8', backgroundColor: 'rgba(56,189,248,0.1)', fill: true, tension: 0.3 }},
        {{ label: 'Min', data: qMin, borderColor: '#ef4444', borderDash: [4,4], pointRadius: 0, tension: 0.3 }},
        {{ label: 'Max', data: qMax, borderColor: '#22c55e', borderDash: [4,4], pointRadius: 0, tension: 0.3 }},
      ]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
        y: {{ min: 0, max: 100, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
      }}
    }}
  }});
}}

const aLabels = {agent_chart_labels};
const aValues = {agent_chart_values};

if (aLabels.length > 0) {{
  new Chart(document.getElementById('agentChart'), {{
    type: 'bar',
    data: {{
      labels: aLabels,
      datasets: [{{ label: 'Avg Score', data: aValues, backgroundColor: aValues.map(v => v >= 90 ? '#22c55e' : v >= 70 ? '#eab308' : '#ef4444'), borderRadius: 6 }}]
    }},
    options: {{
      responsive: true,
      plugins: {{ legend: {{ labels: {{ color: '#e2e8f0' }} }} }},
      scales: {{
        x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
        y: {{ min: 0, max: 100, ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
      }}
    }}
  }});
}}
</script>

</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# JSON summary writer
# ---------------------------------------------------------------------------

def write_json_summary(metrics: QualityMetrics, path: Path | None = None) -> Path:
    """Write full quality summary to JSON file."""
    out_path = path or REPORTS_DIR / "quality_summary.json"
    summary = metrics.full_summary()
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)
    return out_path


def write_html_report(metrics: QualityMetrics, path: Path | None = None) -> Path:
    """Write HTML quality report."""
    out_path = path or REPORTS_DIR / "quality_report.html"
    html = generate_html_report(metrics)
    with open(out_path, "w") as f:
        f.write(html)
    return out_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    metrics = QualityMetrics()

    # --- Assertions: verify correctness of metric computations ---

    # 1. Agent success rates load correctly
    rates = metrics.agent_success_rates()
    assert isinstance(rates, dict), "agent_success_rates must return dict"
    if rates:
        for agent, info in rates.items():
            assert "rate" in info, f"Missing 'rate' for agent {agent}"
            assert 0 <= info["rate"] <= 100, f"Rate out of range for {agent}: {info['rate']}"
            assert info["total"] >= info["success"], f"success > total for {agent}"
        print(f"  [PASS] Agent success rates: {len(rates)} agents loaded")

    # 2. Scores by agent
    agent_scores = metrics.scores_by_agent()
    assert isinstance(agent_scores, dict), "scores_by_agent must return dict"
    for agent, scores in agent_scores.items():
        assert all(0 <= s <= 100 for s in scores), f"Score out of range for {agent}"
        avg = statistics.mean(scores)
        assert 0 <= avg <= 100, f"Avg score out of range for {agent}: {avg}"
    print(f"  [PASS] Scores by agent: {len(agent_scores)} agents, {sum(len(s) for s in agent_scores.values())} scores")

    # 3. Scores by category
    cat_scores = metrics.scores_by_category()
    assert isinstance(cat_scores, dict), "scores_by_category must return dict"
    for cat, scores in cat_scores.items():
        assert all(0 <= s <= 100 for s in scores), f"Score out of range for {cat}"
    print(f"  [PASS] Scores by category: {len(cat_scores)} categories")

    # 4. Latency stats
    lat = metrics.latency_stats()
    assert "p50" in lat and "p95" in lat and "p99" in lat and "mean" in lat
    if lat["count"] > 0:
        assert lat["p50"] <= lat["p95"] <= lat["p99"], "Percentiles must be non-decreasing"
        assert lat["mean"] > 0, "Mean latency must be positive"
    print(f"  [PASS] Latency stats: p50={lat['p50']}s p95={lat['p95']}s p99={lat['p99']}s (n={lat['count']})")

    # 5. Quality over time
    qot = metrics.quality_over_time()
    assert isinstance(qot, list), "quality_over_time must return list"
    for bucket in qot:
        assert "timestamp" in bucket and "avg_quality" in bucket
        assert bucket["min_quality"] <= bucket["avg_quality"] <= bucket["max_quality"]
        assert bucket["count"] > 0
    print(f"  [PASS] Quality over time: {len(qot)} time buckets")

    # 6. Local vs Opus
    comp = metrics.local_vs_opus()
    assert "total" in comp and "win_rate" in comp
    if comp["total"] > 0:
        assert 0 <= comp["win_rate"] <= 100
        assert comp["local_wins"] <= comp["total"]
    print(f"  [PASS] Local vs Opus: {comp['local_wins']}/{comp['total']} wins ({comp['win_rate']}%)")

    # 7. Alerts
    alerts = metrics.alerts_summary()
    assert isinstance(alerts, list)
    for a in alerts:
        assert "severity" in a and "message" in a
    print(f"  [PASS] Alerts: {len(alerts)} active")

    # 8. Full summary integrity
    summary = metrics.full_summary()
    required_keys = {
        "generated_at", "eval_count", "exec_count", "agent_success_rates",
        "agent_avg_scores", "category_avg_scores", "latency",
        "local_vs_opus", "quality_over_time", "alerts", "trends",
    }
    assert required_keys.issubset(set(summary.keys())), f"Missing keys: {required_keys - set(summary.keys())}"
    print(f"  [PASS] Full summary: {len(summary)} top-level keys")

    # 9. Write JSON summary
    json_path = write_json_summary(metrics)
    assert json_path.exists(), "JSON summary file not written"
    reloaded = json.loads(json_path.read_text())
    assert reloaded["eval_count"] == summary["eval_count"]
    print(f"  [PASS] JSON summary written to {json_path}")

    # 10. Write HTML report
    html_path = write_html_report(metrics)
    assert html_path.exists(), "HTML report file not written"
    html_content = html_path.read_text()
    assert "Quality Dashboard" in html_content
    assert "chart.js" in html_content.lower() or "Chart" in html_content
    assert len(html_content) > 1000, "HTML report suspiciously short"
    print(f"  [PASS] HTML report written to {html_path}")

    # 11. Terminal dashboard renders
    terminal_output = render_terminal_dashboard(metrics)
    assert "QUALITY DASHBOARD" in terminal_output
    assert "AGENT SUCCESS RATES" in terminal_output
    assert len(terminal_output) > 200
    print(f"  [PASS] Terminal dashboard rendered ({len(terminal_output)} chars)")

    # 12. Bar chart helper
    assert "█" in _bar(75)
    assert "░" in _bar(50)
    bar_100 = _bar(100)
    bar_0 = _bar(0)
    assert "█" in bar_100
    print(f"  [PASS] Bar chart rendering OK")

    print(f"\n{'='*60}")
    print(f"  ALL 12 ASSERTIONS PASSED")
    print(f"{'='*60}")

    # Print the terminal dashboard
    print(render_terminal_dashboard(metrics))
