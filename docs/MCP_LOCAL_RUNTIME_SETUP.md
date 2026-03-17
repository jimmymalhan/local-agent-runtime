# MCP Local Runtime Setup

This MCP server is an opt-in path for the local agent pipeline (Ollama). Use it only when you explicitly want the local runtime. Cursor should not automatically call it for ordinary Codex, Claude, or Cursor implementation work.

## Install

```bash
cd /Users/jimmymalhan/Doc/local-agent-runtime/mcp-local-runtime
pip install "mcp[cli]"
# or: uv add "mcp[cli]" && uv sync
```

## Add to Cursor

1. Open **Cursor Settings** → **Features** → **MCP** (or **Cursor Settings** → **MCP**)
2. Add a new server:

| Field | Value |
|-------|-------|
| Name | `local-runtime` |
| Command | `python3` |
| Args | `server.py` |
| Cwd | `/Users/jimmymalhan/Doc/local-agent-runtime/mcp-local-runtime` |

**Direct run test:**
```bash
cd /Users/jimmymalhan/Doc/local-agent-runtime/mcp-local-runtime
python3 server.py
# Should print "Server started (stdio mode - will wait for input)"
```

Or add to your Cursor MCP config (e.g. `~/.cursor/mcp.json` or project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "local-runtime": {
      "command": "uv",
      "args": ["run", "mcp", "run", "server.py"],
      "cwd": "/Users/jimmymalhan/Doc/local-agent-runtime/mcp-local-runtime"
    }
  }
}
```

## Usage

When you explicitly choose the local runtime, call the `run_local_pipeline` tool. The local agents (Ollama + local_team_run.py) run the task and review auto-runs at the end.

## Verify

In Cursor, you should see `run_local_pipeline` under MCP tools for the `local-runtime` server.
