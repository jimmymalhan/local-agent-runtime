"""Tests for the {{name}} CLI."""
from __future__ import annotations

import pytest
from click.testing import CliRunner

from {{name}}.cli import cli
from {{name}}.core import get_item, process_item, list_items, ItemNotFoundError


# --- Core logic tests ---

def test_list_items_returns_items():
    items = list_items()
    assert len(items) > 0
    assert all("id" in item for item in items)


def test_list_items_limit():
    items = list_items(limit=1)
    assert len(items) == 1


def test_get_item_found():
    item = get_item(1)
    assert item["id"] == 1


def test_get_item_not_found():
    with pytest.raises(ItemNotFoundError):
        get_item(9999)


def test_process_item():
    # Reset state first
    from {{name}} import core
    core._STORE[1]["status"] = "pending"
    result = process_item(1)
    assert "done" in result
    assert core._STORE[1]["status"] == "done"


# --- CLI tests ---

@pytest.fixture
def runner():
    return CliRunner()


def test_cli_list(runner):
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "Items" in result.output


def test_cli_list_limit(runner):
    result = runner.invoke(cli, ["list", "--limit", "1"])
    assert result.exit_code == 0


def test_cli_process_dry_run(runner):
    result = runner.invoke(cli, ["process", "1", "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run" in result.output


def test_cli_process_item(runner):
    result = runner.invoke(cli, ["process", "2"])
    assert result.exit_code == 0


def test_cli_process_not_found(runner):
    result = runner.invoke(cli, ["process", "9999"])
    assert result.exit_code == 1


def test_cli_version(runner):
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
