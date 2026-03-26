"""{{name}} CLI entry point."""
from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from .core import process_item, list_items, ItemNotFoundError

console = Console()


@click.group()
@click.version_option()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """{{name}} — a production-ready CLI tool."""
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


@cli.command("list")
@click.option("--limit", "-n", default=10, show_default=True, help="Max items to show.")
@click.pass_context
def list_cmd(ctx: click.Context, limit: int) -> None:
    """List all items."""
    items = list_items(limit=limit)
    if not items:
        console.print("[yellow]No items found.[/yellow]")
        return

    table = Table(title="Items", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="dim", width=6)
    table.add_column("Name")
    table.add_column("Status")

    for item in items:
        table.add_row(str(item["id"]), item["name"], item["status"])

    console.print(table)


@cli.command("process")
@click.argument("item_id", type=int)
@click.option("--dry-run", is_flag=True, help="Show what would happen without doing it.")
@click.pass_context
def process_cmd(ctx: click.Context, item_id: int, dry_run: bool) -> None:
    """Process a single item by ID."""
    verbose = ctx.obj.get("verbose", False)

    if dry_run:
        console.print(f"[dim]Dry run: would process item {item_id}[/dim]")
        return

    try:
        result = process_item(item_id, verbose=verbose)
        console.print(f"[green]Processed item {item_id}: {result}[/green]")
    except ItemNotFoundError:
        console.print(f"[red]Error:[/red] Item {item_id} not found.", err=True)
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]Unexpected error:[/red] {exc}", err=True)
        if verbose:
            console.print_exception()
        sys.exit(2)


def main() -> None:
    """Package entry point."""
    cli(obj={})
