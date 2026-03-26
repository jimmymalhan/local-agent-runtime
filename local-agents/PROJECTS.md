# Local Agent Runtime — Project Breakdown
# Claude rescue: cron 5min, 0 API tokens, writes lesson to memory/.

## P0 — START NOW
  [ ] python3 dashboard/live_state_updater.py &   (2s live refresh)
  [ ] python3 orchestrator/main.py --auto 6       (v6 loop)
  [ ] bash scripts/auto_merge_pr.sh              (merge #27-#34)

## P1 — TASKS
  [ ] P01  Real-world task suite (tasks/task_suite.py)
  [ ] P02  v6 loop runs, beats Opus 4.6
  [ ] P03  Write rescue_needed.json after 3 failures
  [ ] P04  Velocity tracking: reports/velocity.jsonl

## CRON RESCUE (PERMANENT)
  [x] Installed: */5 * * * * scripts/cron_claude_rescue.sh
  Action: writes lesson to memory/rescue_lessons.jsonl, 0 tokens

## DONE
  [x] Supervisor + auto-heal
  [x] VERSION=0.5.0
  [x] Dashboard CEO view
  [x] CI fixed
