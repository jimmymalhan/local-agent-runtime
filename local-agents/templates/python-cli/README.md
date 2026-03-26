# {{name}}

Python CLI tool built with Click and Rich.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```bash
# List items
{{name}} list
{{name}} list --limit 5

# Process an item
{{name}} process 1
{{name}} process 1 --dry-run

# Verbose mode
{{name}} --verbose process 2
```

## Development

```bash
# Run tests
pytest

# Lint
ruff check .

# Type check
mypy src/
```

## Project structure

```
src/{{name}}/
  __init__.py    # Package metadata
  cli.py         # Click commands
  core.py        # Business logic
tests/
  test_cli.py    # CLI and core tests
pyproject.toml   # Package config, dependencies, tooling
```
