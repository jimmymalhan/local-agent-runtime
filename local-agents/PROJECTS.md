# Project Breakdown — Local Agent Runtime
# Claude: EXITED. Local agents own all work. Cron rescue = Claude teaches (0 API tokens).
# 2026-03-25

## ❌ BLOCKER (fixes all 17 failing PRs)
Agent: test_engineer
Run:   python3 -m pytest tests/ -x -q
Fix:
  tests/test_executive_roles.py:18     role file missing or content wrong
  tests/test_response_contract.py      summarizer role missing codex-style output
  tests/test_takeover_policy.py        extra_skill_text missing 3 strings
Done when: pytest exits 0

## PROJECT 1 — pr-pipeline (after CI green)
Agent: reviewer
Run:   bash scripts/auto_merge_pr.sh
Tasks:
  [ ] Merge #27–#43 oldest first
  [ ] Rebase on conflict, delete branch after merge

## PROJECT 2 — nexus-loop (v6→v1000)
Agent: orchestrator
Run:   cd local-agents && python3 orchestrator/main.py --auto 6
Tasks:
  [ ] Real-world task suite (tasks/task_suite.py, 100 tasks)
  [ ] Loop running, Opus 4.6 comparison per version
  [ ] Write reports/rescue_needed.json after 3 same-task failures

## PROJECT 3 — dashboard (2s live)
Agent: live_state_updater
Run:   cd local-agents && python3 dashboard/live_state_updater.py &
Tasks:
  [ ] Version, agents, scores, PRs, velocity, hardware pushed every 2s
  [ ] Watch: watch -n2 "python3 -c \"import json; d=json.load(open('local-agents/dashboard/state.json')); print(d['version'], d.get('velocity',{}))\"" 

## PROJECT 4 — cron-rescue (PERMANENT)
Cron:   */5 * * * * scripts/cron_claude_rescue.sh
Action: writes lesson to local-agents/memory/rescue_lessons.jsonl (0 tokens)
Status: [x] INSTALLED

## START ORDER
1. python3 -m pytest tests/ -x -q                           # fix CI
2. cd local-agents && python3 dashboard/live_state_updater.py &
3. bash scripts/auto_merge_pr.sh                            # merge PRs
4. cd local-agents && python3 orchestrator/main.py --auto 6 # loop
