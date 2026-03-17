# Claude/Codex Sessions + Local Agent Actions Plan

## Goal

- `claude` and `codex` run **local agents** (Ollama)
- Each spins up its **own session first** (Claude-style or Codex-style)
- Then uses local agents to perform actions when the user requests work
- Real-time feedback, iterate before done

## Phases

### Phase 1: Plan ✓
- [x] Document plan
- [x] Add to state/todo.md

### Phase 2: Restore claude/codex → local agents ✓
- [x] Restore script: `scripts/restore_local_agent_claude_codex.sh`
- [x] Claude uses `start_claude_compatible.sh`, Codex uses `start_codex_compatible.sh`
- [x] SESSION_PERSONA=claude|codex|local for branding

### Phase 3: Session-first flow ✓
- [x] Session startup: show persona welcome before first action
- [x] Claude session: "Claude (local) — session ready"
- [x] Codex session: "Codex (local) — session ready"
- [x] Plain task → /pipeline (local agents perform)

### Phase 4: Test + feedback (user run)
- [ ] Run `claude` and `codex` in separate terminals
- [ ] Same action in both: `/pipeline "list files in scripts/"`
- [ ] Use `/feedback <text>` in each session to record feedback
- [ ] Feedback saved to `state/feedback-sessions.md`

### Phase 5: Iterate
- [ ] Review `state/feedback-sessions.md`
- [ ] Adjust welcome, prompts, or flow per feedback
- [ ] Re-test until user approves
