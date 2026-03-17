# UI Standards

## Production-Grade Desktop-First Design
- **Layout**: Wide desktop layout (1200px+), side panels, split views
- **Spacing**: Consistent, deliberate, premium (16px base unit)
- **Hierarchy**: Clear visual priority, obvious next steps
- **Motion**: Smooth transitions, no jarring jumps, purposeful animations
- **States**: Loading, empty, success, error, retry, partial failure, stale data

## Non-Technical Language
Replace:
- ❌ "API endpoint" → ✅ "Request"
- ❌ "Orchestration" → ✅ "Process" or "Flow"
- ❌ "Verifier agent" → ✅ "Analysis"
- ❌ "Rollback" → ✅ "Undo" or "Revert"
- ❌ "Async queue" → ✅ "Background task"
- ❌ "State machine" → ✅ "Status"

## User Journeys (End-to-End Workflows)
Every page must show:
1. **What this does** - one sentence describing the purpose
2. **Why it matters** - business value or outcome
3. **What action to take** - obvious next button or input

Example structure:
```
What: Submit a diagnosis request for your system failure
Why: Get root cause analysis, fix plan, and recovery steps
Action: [Submit Incident] button in form
```

## Required UI States
- **Loading**: Spinner + progress message ("Analyzing incident...")
- **Empty**: Helpful message + example input
- **Success**: Confirmation + next steps
- **Error**: Clear message + recovery path
- **Validation**: Real-time feedback on input
- **Permission Denied**: Explanation + escalation path
- **Retry**: "Retry" button + backoff countdown
- **Audit History**: Timestamp + user + action performed
- **Last Updated**: Show recency of data
- **Stale Data**: Warning if older than threshold

## Desktop-Specific Patterns
- Side panels for navigation (not hamburger)
- Split views (input on left, results on right)
- Comparison tables (before/after states)
- Timeline views (sequence of events)
- Admin controls (operator actions, not hidden)
- Review queues (prioritized work list)
- Status dashboard (at-a-glance health)

## Accessible and Polished
- Keyboard navigation (Tab, Enter, Escape)
- ARIA labels for screen readers
- Sufficient color contrast (WCAG AA minimum)
- Focus indicators visible
- Error messages linked to fields
- Obvious button states (hover, active, disabled)

## Business User Focus
- Show data in business terms (not JSON)
- Use consistent terminology
- Provide context before actions
- Explain why something failed in business language
- Show estimated time to completion
- Display recent activity/history

## Example Workflows (Show in UI)
1. **Request Intake**: Form → Submit → Confirmation
2. **Processing**: Start → Progress bar → Stages → Complete
3. **Review**: Results → Sections (Cause, Fix, Tests) → Approve/Reject
4. **Recovery**: Failure → Error explanation → Retry button → Success
5. **Audit**: Action → History list → Details → User + timestamp

## Component States
Every interactive element must have:
- Normal state
- Hover state
- Active/pressed state
- Disabled state
- Loading state
- Error state

## Not to Show on Screen
- ❌ JSON responses
- ❌ Stack traces
- ❌ Internal IDs (trace IDs ok, backend IDs hidden)
- ❌ Code snippets
- ❌ Technical terms without explanation
- ❌ Multiple errors at once (prioritize top issue)

## Testing UI Locally
```bash
npm start
# Open http://localhost:3000
# Test:
# 1. Form submission with valid input
# 2. Form validation with invalid input
# 3. Loading state appears and disappears
# 4. Results display correctly
# 5. Error case with network failure
# 6. Success confirmation and next steps
```

## Responsive Breakpoints
- Desktop: 1200px+ (primary, wide layout)
- Tablet: 768px-1199px (side panel → collapse to tabs)
- Mobile: <768px (NOT supported, show "desktop only" message)

## Color and Typography
- Color: Semantic (primary action, success, error, warning)
- Typography: 16px base, 1.5 line height, max 80ch width
- Contrast: WCAG AA minimum (4.5:1 for text)

## Loading and Progress
- Show spinner + message
- Estimate time to completion
- Show stages (Router → Retriever → Skeptic → Verifier)
- Allow cancel if safe
- Show detailed progress on hover

## Error Messages
Format: [Icon] [Problem] [Why] [Action]

Example:
```
⚠️ Network error
The API was unreachable
Retrying in 2 seconds... [Retry Now]
```

## Mobile Message
Display on screens <768px:
```
This tool is optimized for desktop and laptop.
Please use a larger screen or rotate your device.
```
