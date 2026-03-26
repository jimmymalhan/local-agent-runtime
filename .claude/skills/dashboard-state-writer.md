# Skill: dashboard-state-writer

## Purpose
Guide every local agent on how to write live data to the dashboard state. Agents that do NOT call these functions leave the dashboard showing empty/blank values.

## Policy — HARD RULES
- **Claude main session NEVER fixes dashboard code.** All dashboard fixes are tasks in `projects.json` picked up by `frontend_agent`.
- Every agent must write to `dashboard/state.json` **before** starting a task and **after** finishing.
- Dashboard must never show blank values. If an agent runs without calling state_writer, file a bug task via `task_intake.intake()`.

---

## Required calls — every agent, every task

### 1. Before starting a task
```python
from dashboard.state_writer import update_agent
update_agent(agent_name, status="executing", task=task["title"], task_id=task["id"])
```

### 2. After finishing a task
```python
update_agent(agent_name, status="done", task=task["title"], task_id=task["id"],
             elapsed_s=elapsed, quality=result["quality"])
# ↑ quality field is required — without it, agent card shows blank score
```

### 3. Sub-agents (SubAgentPool workers)
```python
from dashboard.state_writer import update_sub_agents
update_sub_agents(agent_name, workers=[
    {"id": 0, "status": "running", "task": title, "model": AGENT_META["model"],
     "elapsed_s": 0.0, "quality": 0},
])
# ↑ model must be AGENT_META["model"] (e.g. "qwen2.5-coder:7b") — never empty string
```

### 4. Task queue progress
```python
from dashboard.state_writer import update_task_queue
update_task_queue(total=100, completed=N, in_progress=1, failed=0)
```

### 5. Version changelog (orchestrator only — after each version)
```python
from dashboard.state_writer import update_version_changelog
update_version_changelog(version=N, changes=[
    f"Tasks done: {done}",
    f"Avg quality: {avg_q}",
    f"Win rate: {wr}%",
])
```

### 6. Research findings (researcher + benchmarker agents)
```python
from dashboard.state_writer import add_research_finding
add_research_finding(
    finding="Pattern discovered: X works better than Y",
    source="benchmarker",
    confidence=0.85,
)
```

---

## live_state_updater.py — what it must write on every tick()

| Field | Source | Empty symptom |
|---|---|---|
| `benchmark_scores` | `reports/v*_compare.jsonl` | Nexus Score, Win Rate show "—" |
| `token_usage` with `claude_tokens`, `local_tokens`, `total_tokens`, `rescued_tasks` | `claude_token_log.jsonl` | Token counts show 0 |
| `recent_tasks` | Last 10 entries from compare files | Tasks tab shows empty |
| `projects_summary` | `projects/projects.json` | Projects tab shows empty counts |
| `hardware` | psutil | CPU/RAM show 0% |
| `business_summary.headline` | computed | Company bar shows stale text |

If `live_state_updater.py` stops running:
- Stale banner fires after 10s (implemented in index.html `_checkStaleness()`)
- Cron restarts it within 60s (task `t-ac528ed7` in queue)

---

## Diagnosing empty dashboard values

Run this audit:
```bash
python3 -c "
import json
s = json.load(open('dashboard/state.json'))
checks = [
  ('benchmark_scores', bool(s.get('benchmark_scores')), 'Nexus Score/Win Rate show —'),
  ('token_usage.claude_tokens', 'claude_tokens' in s.get('token_usage',{}), 'Token counts blank'),
  ('recent_tasks', bool(s.get('recent_tasks')), 'Tasks tab empty'),
  ('agents[*].quality', all('quality' in a for a in s.get('agents',{}).values()), 'Agent quality blank'),
  ('version_changelog', bool(s.get('version_changelog')), 'CEO changelog empty'),
  ('research_feed', bool(s.get('research_feed')), 'Logs tab empty'),
]
for name, ok, symptom in checks:
    print('OK' if ok else 'FAIL', name, '-', symptom if not ok else '')
"
```

## Filing a fix task (use task_intake — never fix directly in Claude main)
```python
from orchestrator.task_intake import intake
intake(
    "Dashboard field X shows empty",
    description="Root cause: Y. Fix: agent Z must call state_writer.method() with field X.",
    category="dashboard"
)
# → task auto-routed to frontend_agent in p-dashboard/e-dash-uptime, picked up by continuous_loop
```
