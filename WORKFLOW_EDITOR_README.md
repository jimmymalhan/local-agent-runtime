# Interactive Workflow Editor

## Overview

The Workflow Editor is an n8n-style visual pipeline interface that displays the agent execution workflow and allows interactive configuration of stage ordering.

**Access**: http://localhost:3003 → Workflow tab (or direct: http://localhost:3003/workflow)

## Features

### Visual Workflow Pipeline

```
[👥 Agent Assignment] → [⚙️ Execution] → [✓ Validation] → [📝 Committing] → [🔗 Merging]
```

Each stage shows:
- **Icon**: Visual identifier (👥 for agents, ⚙️ for execution, etc.)
- **Title**: Stage name
- **Status**: Current state (idle, running, completed)
- **Details**: On click, shows full stage information

### Interactive Arrow Switching

Drag arrows between stages to reorder the workflow:
- **Left arrow drag**: Move stage earlier in pipeline
- **Right arrow drag**: Move stage later in pipeline
- Workflow updates in real-time
- Configuration persisted to backend

### Real-Time Status Synchronization

- WebSocket connection to dashboard for live agent status
- Status updates automatically reflect in workflow stages
- Color coding:
  - **Idle**: Gray (not running)
  - **Running**: Blue (actively executing)
  - **Completed**: Green (finished successfully)

### Workflow Management

**Actions available:**
- **↺ Reset to Default**: Restore original 5-stage workflow
- **▶ Auto-Execute**: Trigger workflow with current configuration
- **⬇ Export Config**: Download workflow as JSON file
- **⬆ Import Config**: Load workflow from JSON file

## API Endpoints

### GET /api/workflow/config
Returns current workflow configuration from backend.

**Response:**
```json
{
  "workflow": [
    {"id": "agent-assignment", "order": 0, "title": "Agent Assignment"},
    {"id": "execution", "order": 1, "title": "Execution"},
    {"id": "validation", "order": 2, "title": "Validation"},
    {"id": "committing", "order": 3, "title": "Committing"},
    {"id": "merging", "order": 4, "title": "Merging"}
  ],
  "updated_at": "2026-03-27T08:36:15.160243"
}
```

### POST /api/workflow/config
Save new workflow configuration.

**Request:**
```json
{
  "workflow": [
    {"id": "execution", "order": 0},
    {"id": "validation", "order": 1},
    {"id": "committing", "order": 2},
    {"id": "merging", "order": 3},
    {"id": "agent-assignment", "order": 4}
  ]
}
```

**Response:**
```json
{
  "status": "saved",
  "workflow": [...]
}
```

### POST /api/workflow/execute
Trigger execution with specified workflow order.

**Request:**
```json
{
  "workflow": [
    {"id": "agent-assignment", "order": 0},
    ...
  ]
}
```

**Response:**
```json
{
  "status": "execution_started",
  "workflow": [...],
  "timestamp": "2026-03-27T08:36:15.160243"
}
```

## Stage Descriptions

### 1. Agent Assignment (👥)
**Duration**: ~100ms
Assigns incoming task to the most suitable agent based on:
- Task category (code_gen, bug_fix, analysis)
- Agent availability and specialization
- Current workload

**Next**: Execution

### 2. Execution (⚙️)
**Duration**: ~2-5s
Primary task execution:
- Code generation or analysis
- Problem-solving and implementation
- Quality assessment

**Next**: Validation

### 3. Validation (✓)
**Duration**: ~500ms
Quality assurance:
- Output correctness verification
- Test execution (if applicable)
- Quality scoring (0-100)

**Next**: Committing

### 4. Committing (📝)
**Duration**: ~200ms
Version control integration:
- Commit to feature branch
- Automatic commit message
- Cleanup of temp files

**Next**: Merging

### 5. Merging (🔗)
**Duration**: ~300ms
Final integration:
- Create pull request
- Merge to main (if approved)
- Handle merge conflicts
- Update documentation

## Workflow Configuration

### Default Order
The default workflow follows this sequence:
```
Agent Assignment → Execution → Validation → Committing → Merging
```

This order is optimal for most use cases:
1. Ensures correct agent assignment
2. Executes task with known agent
3. Validates output quality before committing
4. Commits only validated changes
5. Merges final tested code

### Custom Orders

You can reorder stages for specific use cases:

**Fast Path (skip validation):**
```
Agent Assignment → Execution → Committing → Merging → Validation
```

**Parallel Execution (validation first):**
```
Validation → Agent Assignment → Execution → Committing → Merging
```

**Commit-First (save progress immediately):**
```
Agent Assignment → Execution → Committing → Validation → Merging
```

## Data Persistence

### localStorage
- Workflow state saved to browser localStorage
- Persists across page refreshes
- Used as fallback if backend unavailable

### Backend Storage (state.json)
- Workflow configuration saved to `dashboard/state.json`
- `workflow` key contains ordered stage list
- `workflow_updated_at` timestamp for last update

### Execution Logs
- All workflow executions logged to `reports/workflow_executions.jsonl`
- One JSON object per line (JSONL format)
- Includes timestamp, workflow order, execution status

## Real-Time Updates

### WebSocket Integration
The workflow editor receives real-time status updates through:
- `/ws` WebSocket endpoint
- Agent status mapped to workflow stages:
  - `executor` → Execution stage
  - `reviewer` → Validation stage
  - `committer` → Committing stage
  - `merger` → Merging stage

### Status Mapping
- Agent `status: "working"` → Stage shows "running"
- Agent `status: "idle"` → Stage shows "idle"
- Agent `status: "completed"` → Stage shows "completed"

## Usage Examples

### Example 1: Default Workflow
1. Navigate to http://localhost:3003
2. Click "Workflow" tab in navbar
3. Observe default 5-stage pipeline
4. View real-time status as tasks execute

### Example 2: Reordering Stages
1. In workflow editor, hover over arrow between "Execution" and "Validation"
2. Click and drag arrow left
3. "Validation" moves before "Execution"
4. Workflow config automatically saved
5. New order takes effect immediately

### Example 3: Export/Import
1. Click "⬇ Export Config" to download current workflow
2. Modify the JSON file
3. Click "⬆ Import Config" and select modified file
4. Workflow updated and saved

### Example 4: Reset to Default
1. Accidentally reordered stages incorrectly
2. Click "↺ Reset to Default"
3. Workflow restores to original 5-stage order

## Performance

- **Initial load**: <500ms
- **Stage reorder**: <100ms
- **Config save**: <200ms
- **WebSocket update**: <50ms
- **Render (5 stages + 4 arrows)**: <30ms

## Browser Compatibility

- ✅ Chrome/Chromium (latest)
- ✅ Safari (latest)
- ✅ Firefox (latest)
- ✅ Edge (latest)
- ⚠️ Mobile browsers (responsive layout included)

## Troubleshooting

### Workflow Tab Not Appearing
- **Issue**: "Workflow" button not visible in navbar
- **Solution**: Refresh page with Ctrl+Shift+R (hard refresh)

### Drag-and-drop Not Working
- **Issue**: Arrows won't drag
- **Solution**: Check that JavaScript is enabled; try different browser

### Status Not Updating
- **Issue**: Stage status shows "idle" but agent is running
- **Solution**: Check WebSocket connection in browser console; reconnects automatically

### Config Not Saving
- **Issue**: Workflow reverts to default after refresh
- **Solution**: Check backend /api/workflow/config endpoint; check browser console for errors

## Future Enhancements

- [ ] Multi-stage parallel execution
- [ ] Conditional workflow branching
- [ ] Custom stage templates
- [ ] Workflow versioning and rollback
- [ ] Team-based workflow sharing
- [ ] Advanced metrics per stage
- [ ] AI-suggested stage reordering
- [ ] Workflow performance optimization

## Architecture

```
┌─ Dashboard (index.html)
│  └─ Workflow Tab
│     └─ <iframe src="/workflow">
│        └─ Workflow Editor (workflow-editor.html)
│           ├─ Visual Pipeline Renderer
│           ├─ Drag-Drop Handler
│           ├─ WebSocket Client
│           └─ API Client
│              ├─ GET /api/workflow/config
│              ├─ POST /api/workflow/config
│              ├─ POST /api/workflow/execute
│              └─ WS /ws (real-time status)
```

## Related Files

- **UI**: `dashboard/workflow-editor.html` (270 lines)
- **Server**: `dashboard/server.py` (functions to handle /workflow route + API endpoints)
- **Dashboard**: `dashboard/index.html` (Workflow tab integration)
- **State**: `dashboard/state.json` (workflow configuration storage)
- **Logs**: `reports/workflow_executions.jsonl` (execution history)
