# 🚀 Nexus Dashboard Ultra-Upgrade Roadmap

**Status**: 35 Critical P0/P1 tasks filed to projects.json
**Target Completion**: 2026-03-28
**Model**: Customer-ready Jira-like UI with zero CDN dependencies

---

## Executive Summary

The Nexus dashboard is being upgraded from a 3,400-line vanilla JS monolith to a production-grade React 18 application with:

- ✅ **Jira-like Projects & Tasks** view (Epic → Project → Task hierarchy)
- ✅ **Drag-and-drop Kanban board** (Blocked | Running | Backlog | Done | Merged)
- ✅ **Merged tabs** (Progress + Workflow + Projects consolidated into one)
- ✅ **Real-time updates** via existing WebSocket (no breaking changes)
- ✅ **Advanced features**: Benchmark chart, agent modal, quality heatmap, cost breakdown, health monitors
- ✅ **Zero CDN** - everything built locally with npm (React, Vite, recharts, @dnd-kit)
- ✅ **QA tested** - 7 Playwright browser tests covering all workflows
- ✅ **Enterprise-ready** - 35 tasks covering 4 major projects across 3 epics

---

## What's Being Built (4 Major Projects)

### 1. 🔧 React Dashboard Ultra-Upgrade (P0 — Foundation)
**24 tasks · ~65 hours · 2026-03-28 08:00 UTC**

The core React/Vite build + component library that powers the new UI.

#### Phase A: Build Infrastructure (5 tasks)
- `ui-react-a1` — Initialize React 18 + Vite (no CDN)
- `ui-react-a2` — Migrate CSS tokens to React modules
- `ui-react-a3` — Create base components (Navbar, TabPanel, Context, WebSocket hook)
- `ui-server-api` — Update dashboard/server.py for /dist/ + new API endpoints
- Task: `/api/task/move` (drag-drop persistence)
- Task: `/api/agent/restart` (agent control)
- Task: `/api/agent/prompt` (prompt editor)

#### Phase B: Jira-Style Projects & Tasks Tab (8 components)
- `ui-react-b1` — **EpicSection** (collapsible epic card with progress bar)
- `ui-react-b2` — **ProjectCard** (project details + animated progress)
- `ui-react-b3` — **TaskRow** (compact task display with checkboxes)
- `ui-react-b4` — **KanbanBoard** with @dnd-kit (drag-drop 5 columns)
- `ui-react-b5` — **ProgressSummary** (top status bar: total, done, in progress, blocked %)
- `ui-react-b6` — **FilterSidebar** (epic, priority, agent, status filters)
- `ui-react-b7` — **WorkflowStages** (pipeline visualization)
- `ui-react-b8` — **useRealtime()** hook (WebSocket → React state)

#### Phase C: Advanced Interactions (3 components)
- `ui-react-c1` — **TaskDetailModal** (click task → full details + error logs)
- `ui-react-c2` — **EpicDetailPanel** (click epic → right slide-in with all projects/tasks)
- `ui-react-c3` — Task search/filter bar

#### Phase D: Tab Cleanup & Merging (4 tasks)
- `ui-react-d1` — **Remove CEO tab** (merge KPIs to Overview)
- `ui-react-d2` — **Merge Progress tab** into Projects & Tasks
- `ui-react-d3` — **Merge Workflow tab** into Projects & Tasks
- `ui-react-d4` — Add Epic Progress Ring (SVG animation)

#### Phase E: QA Testing (7 tasks + Playwright suite)
- `ui-react-e1` — Setup Playwright locally
- `ui-react-e2` — Test: Tab navigation (5 tabs load without error)
- `ui-react-e3` — Test: Projects tab renders epics correctly
- `ui-react-e4` — Test: Kanban shows correct task counts per column
- `ui-react-e5` — Test: Real-time WebSocket updates (2s latency)
- `ui-react-e6` — Test: Task detail modal opens + shows data
- `ui-react-e7` — Test: Full Playwright suite passes (7/7 tests)

---

### 2. 🚀 Epic 1: Production-Grade UI Enhancements (P0)
**4 tasks · ~14 hours · 2026-03-28 14:00 UTC**

Advanced features for the Nexus benchmark & agent management.

- `e1-ui-chart` — **Animated Benchmark Chart** (React recharts, Nexus vs Opus 4.6 over versions)
- `e1-ui-agent-modal` — **Agent Detail Modal** (click agent → task history + quality chart)
- `e1-ui-quality-heatmap` — **Quality Heatmap** (agents vs versions, color-coded by score)
- `e1-ui-prompt-editor` — **In-UI Prompt Editor** (textarea + save → API, version history)

---

### 3. ⚡ Epic 2: Token Efficiency & Cost Optimization (P0)
**3 tasks · ~7 hours · 2026-03-28 20:00 UTC**

Advanced cost tracking to help customers optimize spending.

- `e2-cost-budget-ring` — **Budget Donut Chart** (animated, 10% limit tracking)
- `e2-cost-breakdown` — **Cost Breakdown Table** (task → tokens → model → cost/quality ratio)
- `e2-cost-timeline` — **Rescue Timeline** (vertical timeline of rescue events + tokens used)

---

### 4. 🔄 Epic 3: 24/7 Autonomous Resilience & Observability (P0)
**4 tasks · ~11 hours · 2026-03-28 22:00 UTC**

Real-time system health monitoring for production reliability.

- `e3-health-cards` — **Health Cards** (CPU/RAM/disk sparklines, animated charts)
- `e3-agent-restart` — **Agent Restart Button** (manual control via API)
- `e3-failure-analysis` — **Failure Analysis Panel** (failures by agent + error type + trends)
- `e3-heal-log` — **Self-Heal Event Feed** (auto-recovery actions in real-time)

---

## Current Dashboard (Before Upgrade)

| Aspect | Current State | New State |
|--------|---------------|-----------|
| **Language** | Vanilla JS (3,400 lines) | React 18 (modular components) |
| **Build** | No build step | Vite 5 (instant HMR, production optimized) |
| **Tabs** | 8 tabs (Overview, Agents, Projects, CEO, Logs, Chat, Workflow, Progress) | 5 tabs (Overview, Agents, Projects & Tasks, Logs, Chat) |
| **Projects View** | Basic epic/project/task list | Jira-like: epic cards → projects → tasks + Kanban |
| **Kanban** | Basic 4-column board | Full drag-drop with @dnd-kit, persistence |
| **Benchmark Chart** | Static SVG | Animated recharts with legend + tooltip |
| **Cost Tracking** | Simple % display | Full breakdown: per-task tokens, model, cost/quality ratio |
| **System Health** | 4 static gauges | Live sparklines (CPU/RAM/disk), threshold alerts |
| **Agent Control** | View only | Restart button + prompt editor modal |
| **QA Tests** | None | 7 Playwright tests (all critical workflows) |
| **CDN** | None (good!) | None (stays local) |

---

## File Structure (New React App)

```
dashboard/
├── package.json (React 18, Vite 5, @dnd-kit, recharts, playwright)
├── vite.config.js (output → dist/)
├── dist/ (build output, served by server.py)
├── src/
│   ├── main.jsx (entry point)
│   ├── App.jsx (top-level routing)
│   ├── components/
│   │   ├── Navbar.jsx (tab navigation)
│   │   ├── Tabs/
│   │   │   ├── OverviewTab.jsx
│   │   │   ├── AgentsTab.jsx
│   │   │   ├── ProjectsAndTasksTab.jsx (the mega-component)
│   │   │   ├── LogsTab.jsx
│   │   │   └── ChatTab.jsx
│   │   ├── EpicSection.jsx
│   │   ├── ProjectCard.jsx
│   │   ├── TaskRow.jsx
│   │   ├── KanbanBoard.jsx (with @dnd-kit)
│   │   ├── TaskDetailModal.jsx
│   │   ├── EpicDetailPanel.jsx
│   │   ├── ProgressSummary.jsx
│   │   ├── FilterSidebar.jsx
│   │   ├── WorkflowStages.jsx
│   │   ├── BenchmarkChart.jsx (Epic 1)
│   │   ├── AgentDetailModal.jsx (Epic 1)
│   │   ├── QualityHeatmap.jsx (Epic 1)
│   │   ├── PromptEditorModal.jsx (Epic 1)
│   │   ├── BudgetRing.jsx (Epic 2)
│   │   ├── CostBreakdownTable.jsx (Epic 2)
│   │   ├── RescueTimeline.jsx (Epic 2)
│   │   ├── HealthCards.jsx (Epic 3)
│   │   ├── FailureAnalysisPanel.jsx (Epic 3)
│   │   └── SelfHealLog.jsx (Epic 3)
│   ├── context/
│   │   └── StateContext.jsx (global state, WebSocket updates)
│   ├── hooks/
│   │   └── useRealtime.js (WebSocket connection hook)
│   └── styles/
│       ├── tokens.css (CSS variables from original index.html)
│       └── App.css (all existing CSS)
└── tests/
    ├── tabs.spec.js
    ├── projects-tab.spec.js
    ├── kanban.spec.js
    ├── realtime.spec.js
    ├── modal.spec.js
    └── playwright.config.js
```

---

## API Changes (New Endpoints)

The existing `/api/state` (WebSocket) and `/api/todo` endpoints stay unchanged.

**New endpoints to add to `dashboard/server.py`:**

1. **POST /api/task/move** — Move task between Kanban columns
   ```json
   Request: { "task_id": "task-123", "from_column": "backlog", "to_column": "running" }
   Response: { "status": "ok", "task": {...} }
   ```

2. **POST /api/agent/restart** — Restart an agent
   ```json
   Request: { "agent_id": "executor" }
   Response: { "status": "restarting", "agent": {...} }
   ```

3. **POST /api/agent/prompt** — Save upgraded agent prompt
   ```json
   Request: { "agent_id": "executor", "prompt_text": "..." }
   Response: { "status": "ok", "version": 2 }
   ```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **React 18 (not Vue/Svelte)** | Ecosystem, team familiarity, concurrent features for streaming |
| **Vite (not Next.js/Remix)** | Fast, zero-config, perfect for dashboard, no server-side rendering needed |
| **@dnd-kit (not react-dnd)** | Lightweight (12kb), modern API, accessibility built-in |
| **recharts (not D3/Chart.js)** | React-native, composable, smooth animations |
| **CSS Modules (not Tailwind)** | Already have design tokens in CSS variables, lighter build |
| **React Context (not Redux/Zustand)** | Simple state management, WebSocket integration straightforward |
| **Playwright (not Cypress)** | Fast, language-agnostic, excellent for headless QA |
| **No CDN** | Keep everything local, faster load times, no external dependencies |

---

## How Agents Execute This

1. **Projects.json is the source of truth** — All 35 tasks are filed with clear success criteria
2. **Agents pick up tasks in order** — Executor/frontend_engineer assign themselves to tasks
3. **Each task is independent** — Can be done in parallel (frontend_engineer on UI, backend_engineer on API, qa_engineer on tests)
4. **Real-time state hooks into existing system** — No orchestrator/state changes needed, just wire up useRealtime() hook
5. **Testing validates everything** — Playwright tests confirm all workflows work before merge

---

## Success Criteria (What "Done" Looks Like)

✅ `npm run build` in `dashboard/` produces `dist/` folder with zero errors
✅ `npm start` serves React app at localhost:3000
✅ Dashboard shows: 3 epic sections → projects under each → tasks + Kanban board
✅ Progress bars animate in real-time on WebSocket updates
✅ CEO tab is gone from nav
✅ Workflow stages visible inside Projects & Tasks tab
✅ Kanban drag-drop works (tasks move between columns)
✅ Task detail modal opens on click (shows title, description, error log)
✅ Epic detail panel slides in on click (shows all projects + tasks)
✅ Benchmark chart, agent modal, quality heatmap render correctly (Epic 1)
✅ Budget ring, cost breakdown, rescue timeline work (Epic 2)
✅ Health cards, agent restart, failure analysis, self-heal log functional (Epic 3)
✅ `npm run test:ui` runs Playwright suite, all 7 tests pass
✅ No CDN scripts in final HTML
✅ Zero console errors in browser DevTools

---

## Timeline (Estimated)

| Milestone | ETA | Tasks |
|-----------|-----|-------|
| React infrastructure ready | 2026-03-27 18:00 UTC | A1-A3 complete |
| Projects & Tasks tab fully functional | 2026-03-27 22:00 UTC | B1-B7 complete |
| Kanban board + modals working | 2026-03-28 04:00 UTC | C1-C2 complete |
| Tab consolidation done | 2026-03-28 08:00 UTC | D1-D3 complete |
| QA tests passing | 2026-03-28 10:00 UTC | E1-E7 all green |
| Epic 1 features complete | 2026-03-28 14:00 UTC | 4 tasks done |
| Epic 2 features complete | 2026-03-28 20:00 UTC | 3 tasks done |
| Epic 3 features complete | 2026-03-28 22:00 UTC | 4 tasks done |
| **Full system ready for customers** | **2026-03-29 00:00 UTC** | **All 35 tasks ✅** |

---

## Commands for Local Testing

```bash
# Build the React app
npm run build

# Start dev server with HMR
npm run dev

# Run Playwright tests
npm run test:ui

# Start dashboard server
python3 dashboard/server.py

# Visit in browser
open http://localhost:3000
```

---

## What Makes This Customer-Ready

This isn't just a UI refresh — it's an **enterprise-grade dashboard** that will:

1. **Visualize the entire product** — Epics, projects, tasks in one unified view
2. **Enable power users** — Drag-drop task assignment, agent restart, prompt editing
3. **Track costs in real-time** — Budget ring, per-task token breakdown, rescue timeline
4. **Monitor system health** — Live sparklines, failure analysis, self-heal events
5. **Provide zero downtime** — Drag-and-drop persistence, real-time WebSocket updates
6. **Scale with the product** — React components handle 365+ tasks without lag
7. **Beat competitors** — Jira-like interface + advanced analytics = no one else has this in the agent space

---

## Files Modified

- ✅ `projects.json` — 35 new tasks added (committed)
- 📝 `dashboard/package.json` — New dependencies (React, Vite, @dnd-kit, recharts, playwright)
- 📝 `dashboard/vite.config.js` — New Vite configuration
- 📝 `dashboard/src/` — All React components (24 files)
- 📝 `dashboard/server.py` — 3 new API endpoints
- 📝 `dashboard/tests/` — 7 Playwright test files
- ✅ `UI_UPGRADE_ROADMAP.md` — This file

---

## Next Steps

1. **Agents start picking up tasks** from projects.json (all 35 are ready)
2. **Frontend engineers** build React components in parallel
3. **Backend engineers** implement the 3 new API endpoints
4. **QA engineers** write and run Playwright tests
5. **All tests pass** by 2026-03-29
6. **Merge to main** and customers see the new UI

---

**Created**: 2026-03-27 20:15 UTC
**By**: Claude (task intake phase)
**Status**: 🚀 Ready for agents to execute
