"""CLI adapter for rendering profiling charts using rich."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def render_univariate_chart(chart_payload: dict[str, Any]) -> None:
    """Render a univariate horizontal bar chart to the terminal."""
    col = chart_payload["column"]
    ctype = chart_payload["type"]
    data = chart_payload["data"]

    if ctype == "empty":
        console.print(f"[yellow]Column '{col}' is empty or contains only nulls.[/yellow]")
        return

    title = f"Profiling Chart: {col} ({ctype})"

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column("Label", justify="right", style="cyan")
    table.add_column("Count", justify="right", style="green")
    table.add_column("Bar", justify="left")

    if not data:
        console.print(f"[yellow]No data to display for column '{col}'.[/yellow]")
        return

    max_count = max(count for _, count in data)
    max_bar_width = 40  # Max characters for the bar

    for label, count in data:
        bar_len = int((count / max_count) * max_bar_width) if max_count > 0 else 0
        bar = "█" * bar_len
        table.add_row(label, str(count), bar)

    console.print(Panel(table, title=title, expand=False))
