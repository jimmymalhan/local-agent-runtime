# React Component Implementation Guide

Quick reference for all 24 React components being built for the dashboard upgrade.

---

## Component Hierarchy & Dependencies

```
App.jsx (main, renders Navbar + active tab panel)
├── Navbar.jsx (shows 5 tabs, switches active tab on click)
│   └── removes CEO tab option
├── StateContext.jsx (global state provider, Redux-like but simpler)
├── useRealtime() hook (WebSocket listener, updates StateContext)
└── Tabs:
    ├── OverviewTab.jsx (benchmark chart, agent grid, KPIs)
    ├── AgentsTab.jsx (agent grid)
    ├── ProjectsAndTasksTab.jsx ⭐ THE MEGA COMPONENT
    │   ├── ProgressSummary.jsx (top bar)
    │   ├── FilterSidebar.jsx (left sidebar with filters)
    │   ├── EpicSection.jsx (repeating section, one per epic)
    │   │   ├── ProjectCard.jsx (repeating per project)
    │   │   │   └── TaskRow.jsx (repeating per task)
    │   │   └── TaskDetailModal.jsx (on task click)
    │   │   └── EpicDetailPanel.jsx (on epic click)
    │   ├── KanbanBoard.jsx (drag-drop board)
    │   │   └── KanbanColumn.jsx (Blocked | Running | Backlog | Done | Merged)
    │   │       └── KanbanCard.jsx (individual task card)
    │   └── WorkflowStages.jsx (bottom pipeline visualization)
    ├── LogsTab.jsx (exists, stays mostly the same)
    └── ChatTab.jsx (exists, stays mostly the same)
```

---

## Component Data Flow

### Real-Time State Updates

```
WebSocket (/ws)
  ↓
useRealtime() hook
  ↓
StateContext.dispatch({type: 'UPDATE_STATE', payload: newState})
  ↓
Any component using useContext(StateContext) re-renders
  ↓
ProjectsAndTasksTab re-renders:
  - EpicSection components get new task counts
  - ProgressSummary bar updates %
  - KanbanBoard moves tasks between columns
  - Health cards show new CPU/RAM readings
```

### Task Movement (Kanban Drag-Drop)

```
User drags task card in KanbanBoard
  ↓
@dnd-kit triggers onDragEnd handler
  ↓
Calls POST /api/task/move {task_id, from_column, to_column}
  ↓
backend/server.py:
  - Updates projects.json: task.status = to_column
  - Broadcasts WebSocket update to all clients
  ↓
useRealtime() receives update
  ↓
StateContext updates
  ↓
KanbanBoard re-renders with new position
```

---

## Core Components (The Must-Haves)

### 1. **StateContext.jsx**
Global Redux-like state management.

```javascript
// Context hook
const [state, dispatch] = useReducer(stateReducer, initialState);

// State shape
{
  projects: [{ id, name, tasks: [...] }],
  tasks: [...],
  epics: [{ id, name, tasks: [...] }],
  agents: { executor: {...}, planner: {...}, ... },
  benchmark: { local: 0, opus: 70, win_rate: 0 },
  hardware: { cpu: 44.8, ram: 57.0 },
  errors: [],
  ws_connected: bool
}

// Actions
dispatch({ type: 'UPDATE_STATE', payload: newState })
dispatch({ type: 'MOVE_TASK', payload: {task_id, from, to} })
dispatch({ type: 'SET_LOADING', payload: true })
```

### 2. **useRealtime() Hook**
Connects to WebSocket, updates StateContext.

```javascript
// Usage in App.jsx
const { state, dispatch } = useContext(StateContext);
useRealtime({ state, dispatch });

// Internally:
useEffect(() => {
  const ws = new WebSocket(`ws://${host}/ws`);
  ws.onmessage = (e) => {
    const newState = JSON.parse(e.data);
    dispatch({ type: 'UPDATE_STATE', payload: newState });
  };
  return () => ws.close();
}, [dispatch]);
```

### 3. **Navbar.jsx**
Tab navigation (5 tabs now, no CEO).

```javascript
const tabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'agents', label: 'Agents' },
  { id: 'tasks', label: 'Projects & Tasks' },
  { id: 'logs', label: 'Logs' },
  { id: 'chat', label: 'Chat' }
];

// onClick: setActiveTab(id) → parent App re-renders with active tab
```

### 4. **ProjectsAndTasksTab.jsx** ⭐ THE MEGA COMPONENT
This is the core of the upgrade. It orchestrates:
- ProgressSummary (top)
- FilterSidebar (left)
- EpicSection × 3 (epic 1, epic 2, epic 3)
  - ProjectCard × N
    - TaskRow × N
      - TaskDetailModal (on click)
  - EpicDetailPanel (on click)
- KanbanBoard (full width, drag-drop)
- WorkflowStages (bottom)

```javascript
export function ProjectsAndTasksTab() {
  const { state } = useContext(StateContext);
  const [filters, setFilters] = useState({epicId: null, priority: null, agent: null});
  const [selectedTask, setSelectedTask] = useState(null); // for modal
  const [selectedEpic, setSelectedEpic] = useState(null); // for panel

  // Filter projects/tasks based on filters
  const filtered = filterProjects(state.projects, filters);

  // Group by epic
  const epicGroups = groupByEpic(filtered);

  return (
    <div className="projects-and-tasks">
      <ProgressSummary progress={state.progress} />
      <div className="layout">
        <FilterSidebar filters={filters} setFilters={setFilters} />
        <div className="main">
          <div className="epic-list">
            {epicGroups.map(epic => (
              <EpicSection
                key={epic.id}
                epic={epic}
                onTaskClick={setSelectedTask}
                onEpicClick={setSelectedEpic}
              />
            ))}
          </div>
          <KanbanBoard tasks={state.tasks} />
          <WorkflowStages stages={state.workflow} />
        </div>
      </div>
      {selectedTask && (
        <TaskDetailModal task={selectedTask} onClose={() => setSelectedTask(null)} />
      )}
      {selectedEpic && (
        <EpicDetailPanel epic={selectedEpic} onClose={() => setSelectedEpic(null)} />
      )}
    </div>
  );
}
```

---

## Data Structures (What StateContext Contains)

### projects (from projects.json)
```javascript
[
  {
    id: "epic1-xxx",
    name: "Epic 1 Name",
    description: "...",
    status: "pending" | "completed",
    tasks: [
      {
        id: "task-1",
        title: "...",
        description: "...",
        status: "pending" | "in_progress" | "completed" | "failed" | "blocked",
        priority: "P0" | "P1" | "P2" | "P3",
        agent: "executor",
        quality_score: 85,
        eta_hours: 4,
        files: ["src/x.js"],
        success_criteria: "..."
      }
    ]
  }
]
```

### task_queue (from state.json)
```javascript
{
  total: 365,
  completed: 120,
  in_progress: 45,
  blocked: 30,
  pending: 170,
  failed: 0
}
```

### agents (from state.json)
```javascript
{
  executor: {
    status: "idle" | "running" | "blocked",
    task: "task title",
    task_id: "task-123",
    elapsed_s: 45.2,
    last_activity: "2026-03-27T19:00:00",
    quality: 85
  },
  // 9 more agents...
}
```

### benchmark (from state.json)
```javascript
{
  avg_local: 45.2,
  avg_opus: 70.0,
  win_rate: 0.0,
  history: [
    { version: 1, local: 0, opus: 70, win_rate: 0.0 }
  ]
}
```

---

## Component Specs (What Each Component Does)

### ProgressSummary
**Location**: Top of ProjectsAndTasksTab
**Props**: `{progress: {total, completed, in_progress, blocked, pending}}`
**Shows**:
- "365 Tasks" large number
- 4-stat row: "120 done" | "45 running" | "30 blocked" | "33%" complete
- Animated gradient bar (blue → green → purple) showing % complete
**Update**: Every WebSocket message

### FilterSidebar
**Location**: Left side of ProjectsAndTasksTab
**Props**: `{filters, setFilters}`
**Shows**:
- Epic filter buttons (Epic 1, Epic 2, Epic 3, All)
- Priority checkboxes (P0, P1, P2, P3)
- Agent dropdown (executor, planner, reviewer, ...)
- Status checkboxes (done, running, pending, blocked)
**Interaction**: Debounce on change, re-filter main view

### EpicSection
**Location**: Repeating in ProjectsAndTasksTab
**Props**: `{epic, onTaskClick, onEpicClick}`
**Shows**:
- Epic header (collapsible): name, description, status badge, % complete, progress bar
- List of ProjectCard components
**Interaction**: Click header → toggle expand, click epic name → open EpicDetailPanel

### ProjectCard
**Location**: Inside EpicSection
**Props**: `{project, onTaskClick}`
**Shows**:
- Project name, description, agent, priority badge
- Animated progress bar (blue → green)
- Task counts breakdown: 15 total, 8 done, 4 running, 2 blocked, 1 pending
- ETA hours
**Interaction**: Click title → open ProjectDetailModal (similar to TaskDetailModal)

### TaskRow
**Location**: Inside ProjectCard (or flat list)
**Props**: `{task, onTaskClick}`
**Shows**: Single row
- Checkbox (done/pending toggle)
- Task ID (NX-123)
- Task title (truncated to 60 chars)
- Agent badge (executor, planner, etc.)
- Priority pill (P0 red, P1 orange, P2 yellow, P3 gray)
- Quality score (85 green, 50 orange, 20 red)
- Status pill (pending gray, running blue, done green, blocked red)
- ETA hours (light gray)
**Interaction**: Click row → open TaskDetailModal

### TaskDetailModal
**Location**: Overlay when task clicked
**Props**: `{task, onClose}`
**Shows**: Full task details
- Title, description, agent, priority, quality, ETA
- Files list (clickable, would open in IDE ideally)
- Success criteria
- Error log (if failed)
- Attempts, last_attempt timestamp
- Buttons: [Retry] [Assign to me] [Close]
**Interaction**: POST /api/task/retry on Retry, POST /api/task/assign on Assign

### EpicDetailPanel
**Location**: Right slide panel when epic clicked
**Props**: `{epic, onClose}`
**Shows**:
- Epic name, description
- Overall progress for epic (% complete)
- List of all projects in epic
  - For each project: name, % done, task list
- Timeline of completed tasks (newest first)
- Buttons: [Close]
**Animation**: Slide in from right, semi-transparent overlay

### KanbanBoard
**Location**: Full width below epic list
**Props**: `{tasks}`
**Shows**: 5 draggable columns
- Blocked (red): Tasks with status="blocked", count in header
- Running (blue): Tasks with status="in_progress"
- Backlog (gray): Tasks with status="pending"
- Done (green): Tasks with status="completed"
- Merged (light purple): Tasks merged to main
**Cards in each column**:
- Task ID (NX-123)
- Task title
- Agent badge
- Quality color (red/orange/green)
**Interaction**:
- Drag task between columns
- On drop: POST /api/task/move {task_id, from, to}
- Wait for API response, then update UI

### WorkflowStages
**Location**: Below KanbanBoard
**Props**: `{stages}`
**Shows**: Horizontal pipeline (inline diagram)
- 5 boxes connected with arrows:
  1. Agent Assignment (~100ms)
  2. Execution (~3500ms)
  3. Validation (~500ms)
  4. Committing (~200ms)
  5. Merging (~300ms)
- Current stage highlighted (bright blue)
- Durations below each box
**Animation**: Highlight animates as current stage progresses
**Data source**: state.json.workflow

---

## Epic 1 Components (Benchmark & Agent Features)

### BenchmarkChart
**Library**: recharts (Area + Line)
**Props**: `{history, localScores, opusScores}`
**Shows**: X-axis = versions, Y-axis = score (0-100)
- Area chart (light blue) for local agent scores
- Line chart (dark blue) for Opus 4.6 baseline
- Smooth animation on mount + update
**Interaction**: Hover → tooltip shows exact values

### AgentDetailModal
**Props**: `{agent, onClose}`
**Shows**:
- Agent name, status, current task
- Bar chart: quality scores over last 10 completed tasks
- Table: recent tasks (task_id, quality, duration, status)
- Button: [Show All History]
**Data**: From state.json.agents[agent_id] + task history

### QualityHeatmap
**Library**: recharts (Scatter? Or custom CSS grid)
**Props**: `{agents, versions}`
**Shows**: Grid
- Rows = agent names (executor, planner, reviewer, ...)
- Columns = version numbers (v1, v2, v3, v4, ...)
- Cell color: green (≥90), orange (40-90), red (<40)
- Cell text: exact score (85, 45, etc.)
**Interaction**: Hover → tooltip with agent + version + exact score

### PromptEditorModal
**Props**: `{agent, onClose, onSave}`
**Shows**:
- Agent selector dropdown
- Large textarea for prompt text
- "Save" button (POST /api/agent/prompt)
- "View History" link → shows past versions
**Interaction**:
- Select agent → load current prompt
- Edit text → enable Save button
- Click Save → POST to /api/agent/prompt

---

## Epic 2 Components (Cost Tracking)

### BudgetRing
**Library**: recharts (PieChart or custom SVG)
**Props**: `{usedTokens, totalBudget}`
**Shows**: Donut chart
- Inner circle: percentage used
- Outer ring: colored by usage %
  - Green: <5% (0-0.5 tokens)
  - Yellow: 5-8% (0.5-0.8 tokens)
  - Red: >8% (>0.8 tokens)
- Center text: "3.2% used" or "32,000 / 1,000,000 tokens"
**Update**: Every state update
**Data**: state.json.token_usage.{claude_tokens, budget_pct}

### CostBreakdownTable
**Props**: `{tasks}`
**Shows**: Sortable table
- Columns: Task ID | Task Title | Tokens Used | Model (local/claude) | Quality | Cost Ratio (quality/tokens)
- Rows: All tasks (or filtered by filter)
- Sort by clicking column header (ascending/descending toggle)
**Interaction**:
- Click row → open TaskDetailModal
- Sort by tokens DESC → see most expensive tasks
- Sort by cost_ratio DESC → see best bang-for-buck

### RescueTimeline
**Props**: `{rescueEvents}`
**Shows**: Vertical timeline (newest at top)
- Each event has:
  - Timestamp (2026-03-27 14:23:15)
  - Agent name
  - Tokens used
  - Outcome (success, failed, retry)
  - Colored circle (green=success, red=failed, yellow=retry)
- Connecting line between events
**Interaction**: Hover → tooltip with full details

---

## Epic 3 Components (Health & Resilience)

### HealthCards
**Props**: `{hardware: {cpu, ram, disk, network_latency}}`
**Shows**: 4 cards in a row (responsive 2×2 on mobile)
- Each card has:
  - Metric name + current value (45.8%)
  - Animated sparkline chart (recharts + D3 maybe) showing last 1 hour
  - Color: green (<60%), orange (60-80%), red (>80%)
  - Status text: "healthy" | "warning" | "critical"
**Update**: Every hardware update (every 5 seconds)

### AgentRestartButton
**Location**: On each agent card in AgentsTab
**Props**: `{agent}`
**Shows**: Small button
- Text: "Restart" (or icon-only)
- Disabled if agent is already restarting
- Animated spinner while restarting
**Interaction**:
- Click → confirm dialog: "Restart agent {name}?"
- POST /api/agent/restart {agent_id}
- Show spinner until agent comes back up (status="idle")
- Show success toast

### FailureAnalysisPanel
**Props**: `{failures}`
**Shows**:
- Dropdown: filter by agent (all, executor, planner, ...)
- Dropdown: filter by error type (all, network, timeout, validation, ...)
- Line chart: failures per day (last 7 days)
- Table: recent failures (timestamp, agent, error type, error message)
- Click row → expand to show full stack trace
**Data**: state.json.failure_log

### SelfHealLog
**Props**: `{healEvents}`
**Shows**: Feed (newest first)
- Each event: card with:
  - Timestamp (2026-03-27 14:23:15)
  - Issue detected (e.g., "executor timeout after 5min")
  - Action taken (e.g., "restarted executor")
  - Outcome (success/partial/failed)
  - Colored dot (green=success, yellow=partial, red=failed)
- Click to expand → show full logs/details
**Data**: state.json.auto_heal_status + custom tracking

---

## CSS/Styling Notes

### Keep Using Existing Tokens
All original CSS variables should be preserved:
```css
:root {
  --bg: #f5f5f7;
  --card: #ffffff;
  --blue: #0071e3;
  --green: #34c759;
  --orange: #ff9500;
  --red: #ff3b30;
  --purple: #af52de;
  --t1: #1d1d1f;
  --t2: #6e6e73;
  --t3: #aeaeb2;
  --r: 18px;
  --shadow: 0 2px 20px rgba(0,0,0,.07);
}
```

### Component-Level CSS Modules
Each component should have its own `.module.css`:
```
components/
├── EpicSection.jsx
├── EpicSection.module.css
├── ProjectCard.jsx
├── ProjectCard.module.css
```

### No Tailwind Needed
The original design is clean and works great. Just import CSS modules + use CSS variables.

---

## Testing Checklist (For QA)

Each component should pass:
- [ ] Renders without errors
- [ ] Props passed correctly update display
- [ ] State updates (WebSocket → context → re-render)
- [ ] Click interactions work (modals, filters, drag-drop)
- [ ] Mobile responsive (≥768px layout, <768px "desktop only" message)
- [ ] No console errors or warnings
- [ ] Accessibility: keyboard nav (Tab, Enter, Escape), ARIA labels
- [ ] Performance: list of 365 tasks renders in <2s

---

## Deployment Checklist

Before merging to main:
- [ ] `npm run build` succeeds
- [ ] `npm run test:ui` passes all 7 Playwright tests
- [ ] No warnings in build output
- [ ] No CDN scripts in dist/index.html (verify with grep)
- [ ] Dashboard server configured to serve /dist/
- [ ] WebSocket /ws endpoint working
- [ ] All 3 new API endpoints (/api/task/move, /api/agent/restart, /api/agent/prompt) tested
- [ ] CSS imports working, no missing styles
- [ ] Staging environment tested with real data
