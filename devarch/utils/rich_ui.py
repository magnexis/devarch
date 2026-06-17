from __future__ import annotations

from typing import Iterable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..models import Artifact, ScanSummary


console = Console()


def fmt_days(days: int | None) -> str:
    if days is None:
        return "n/a"
    if days < 30:
        return f"{days} days"
    years = days / 365
    return f"{years:.1f} years"


def health_badge(score: int) -> str:
    if score >= 85:
        return "Healthy"
    if score >= 65:
        return "Worn"
    if score >= 45:
        return "Unearthed Debt"
    return "Critical"


def render_header(title: str, subtitle: str | None = None) -> None:
    text = Text(title, style="bold cyan")
    if subtitle:
        text.append(f"\n{subtitle}", style="dim")
    console.print(Panel(text, border_style="cyan"))


def render_metric_grid(summary: ScanSummary) -> None:
    table = Table.grid(expand=True)
    table.add_column()
    table.add_column()
    table.add_column()
    table.add_row(
        f"[bold]Artifacts[/bold]\n{summary.artifact_count}",
        f"[bold]Ancient[/bold]\n{summary.ancient_count}",
        f"[bold]Health[/bold]\n{summary.health_score}/100",
    )
    table.add_row(
        f"[bold]TODOs[/bold]\n{summary.todo_count}",
        f"[bold]Duplicates[/bold]\n{summary.duplicate_count}",
        f"[bold]Debt[/bold]\n{summary.technical_debt_estimate:.1f}",
    )
    console.print(Panel(table, title="Excavation Summary", border_style="green"))


def render_artifacts(title: str, artifacts: Iterable[Artifact]) -> None:
    table = Table(title=title, show_lines=False, header_style="bold magenta")
    table.add_column("File", overflow="fold")
    table.add_column("Age", style="yellow", no_wrap=True)
    table.add_column("Size", style="cyan", no_wrap=True)
    table.add_column("Risk", style="red", no_wrap=True)
    table.add_column("Confidence", style="green", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    count = 0
    for artifact in artifacts:
        count += 1
        table.add_row(
            str(artifact.path),
            f"{artifact.age_days} days" if artifact.age_days is not None else "n/a",
            f"{artifact.size_bytes} B" if artifact.size_bytes is not None else "n/a",
            artifact.risk,
            f"{artifact.confidence:.0%}" if artifact.confidence is not None else "n/a",
            artifact.detail or artifact.kind,
        )
    if count:
        console.print(table)
    else:
        console.print(Panel("No artifacts found.", border_style="green"))


def render_notice(message: str, style: str = "yellow") -> None:
    console.print(Panel(message, border_style=style))


def render_kv(title: str, rows: list[tuple[str, str]], border_style: str = "cyan") -> None:
    table = Table.grid(expand=True)
    table.add_column(justify="left")
    table.add_column(justify="left")
    for label, value in rows:
        table.add_row(f"[bold]{label}[/bold]", value)
    console.print(Panel(table, title=title, border_style=border_style))


def render_bars(title: str, rows: list[tuple[str, float]]) -> None:
    table = Table(title=title, header_style="bold magenta")
    table.add_column("Bucket", overflow="fold")
    table.add_column("Score", justify="right")
    table.add_column("Bar", overflow="fold")
    max_score = max((score for _, score in rows), default=0.0) or 1.0
    for label, score in rows:
        width = max(1, int((score / max_score) * 20))
        table.add_row(label, f"{score:.1f}", "#" * width)
    console.print(table)
