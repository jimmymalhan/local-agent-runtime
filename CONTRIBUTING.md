# Contributing to Nexus

## Getting Started

```bash
git clone https://github.com/jimmymalhan/local-agent-runtime
cd local-agent-runtime
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 dashboard/server.py --port 3001
```

## How to Contribute

### Reporting Bugs
Open an issue with:
- What you did
- What you expected
- What happened (paste the error or dashboard screenshot)

### Adding an Agent

1. Create `agents/your_agent.py` with a `run_task(task: dict) -> dict` function
2. Register it in `agents/nexus_inference.py` under the routing table
3. Add an entry to the agent catalog in `README.md`
4. Test it: add a task to `projects.json` with `"agent": "your_agent"` and run the daemon

### Modifying the Dashboard

The dashboard is a single-page app in `dashboard/index.html` (React + inline JS).
Run the server and refresh the browser — no build step needed.

### Submitting a PR

1. Fork the repo and create a branch: `feature/your-feature` or `fix/your-bug`
2. Make your changes — keep commits small and focused
3. Verify the dashboard still loads at `http://localhost:3001`
4. Open a PR against `main` with a clear description

### Code Style

- Python: follow PEP 8, use `black` for formatting if you like
- Keep agent files self-contained — one file per agent
- No hardcoded paths — use `pathlib.Path(__file__).parent` relative paths

## Questions

Open a GitHub Discussion or drop a message in the repo issues.
