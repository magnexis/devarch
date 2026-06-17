from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from ..analyzers.ancient import find_ancient_files
from ..analyzers.dead_code import find_dead_code
from ..analyzers.duplicates import find_duplicates, similarity_report
from ..analyzers.monsters import find_monsters
from ..analyzers import maintenance
from ..analyzers import recovery
from ..analyzers.ruins import find_empty_directories, find_unused_assets
from ..analyzers.suspicious import find_suspicious
from ..analyzers.todos import find_todos
from ..reports.exporters import export_html, export_json, export_markdown, export_pdf
from ..scanner.core import analyze_repository_root, scan_repository
from ..scanner.discovery import build_reference_map, build_text_index
from ..utils.fs import collect_repository, path_kind, read_text, safe_stat
from ..utils.rich_ui import (
    console,
    health_badge,
    render_artifacts,
    render_bars,
    render_header,
    render_kv,
    render_notice,
)


app = typer.Typer(add_completion=False, help="Excavate technical debt and forgotten artifacts from codebases.")
export_app = typer.Typer(add_completion=False, help="Export excavation reports.")
report_app = typer.Typer(add_completion=False, help="Generate formal excavation reports.")
app.add_typer(export_app, name="export")
app.add_typer(report_app, name="report")


def _command_name(command) -> str:
    return command.name or command.callback.__name__.replace("_", "-")


def _command_help(command) -> str:
    text = (command.help or (command.callback.__doc__ or "")).strip()
    return text or "n/a"


def _iter_commands(app_obj: typer.Typer, prefix: str = "") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for command in app_obj.registered_commands:
        if command.hidden:
            continue
        rows.append((f"{prefix}{_command_name(command)}", _command_help(command)))
    for group in app_obj.registered_groups:
        group_name = group.name or "group"
        rows.extend(_iter_commands(group.typer_instance, prefix=f"{prefix}{group_name} "))
    return rows


def _resolve_target(root: Path, target: Path) -> Path:
    return target if target.is_absolute() else (root / target).resolve()


def _file_context(path: Path, line_number: int | None = None, context: int = 2) -> list[str]:
    try:
        lines = read_text(path).splitlines()
    except OSError:
        return [f"Unable to read {path}"]
    if not lines:
        return ["(empty file)"]
    if line_number is None or line_number < 1 or line_number > len(lines):
        start, end = 1, min(len(lines), 10)
    else:
        start = max(1, line_number - context)
        end = min(len(lines), line_number + context)
    output: list[str] = []
    for index in range(start, end + 1):
        marker = ">>" if line_number == index else "  "
        output.append(f"{marker} {index:>4} | {lines[index - 1]}")
    return output


def _render_help_catalog() -> None:
    rows = _iter_commands(app)
    table = Table(title="Dev Archaeologist Command Catalog", header_style="bold cyan")
    table.add_column("Command", overflow="fold")
    table.add_column("Purpose", overflow="fold")
    for name, help_text in rows:
        table.add_row(name, help_text)
    console.print(table)
    render_notice(
        "For focused excavation use commands like investigate, inspect, trace, evidence, errorcode, and bugmark.",
        style="green",
    )


def _explain_error_text(error_text: str) -> dict[str, str]:
    text = error_text.lower()
    if "module not found" in text or "importerror" in text or "modulenotfounderror" in text:
        return {
            "classification": "Import failure",
            "cause": "A dependency or local module is missing from the runtime path.",
            "fix": "Install the dependency, verify the package name, or update the import path.",
        }
    if "permission denied" in text or "eacces" in text:
        return {
            "classification": "Permission error",
            "cause": "The process does not have access to the requested file or directory.",
            "fix": "Adjust file permissions or run the command with the required access level.",
        }
    if "no such file" in text or "enoent" in text or "file not found" in text:
        return {
            "classification": "Missing file",
            "cause": "The path does not exist or the working directory is incorrect.",
            "fix": "Verify the path, check case sensitivity, and confirm the file was generated.",
        }
    if "timeout" in text or "timed out" in text:
        return {
            "classification": "Timeout",
            "cause": "The operation took longer than the configured limit or stalled on I/O.",
            "fix": "Increase the timeout, reduce workload size, or inspect slow dependencies.",
        }
    if "syntaxerror" in text or "invalid syntax" in text:
        return {
            "classification": "Syntax error",
            "cause": "Python could not parse the file or statement.",
            "fix": "Inspect the reported line and nearby context for unmatched delimiters or typos.",
        }
    if "keyerror" in text:
        return {
            "classification": "Missing key",
            "cause": "The code looked up a dictionary entry that was not present.",
            "fix": "Guard the lookup, provide a default, or validate the input data first.",
        }
    if "indexerror" in text:
        return {
            "classification": "Index error",
            "cause": "A list, tuple, or sequence index was out of range.",
            "fix": "Check collection length before indexing and verify iteration bounds.",
        }
    if "connection refused" in text or "econnrefused" in text:
        return {
            "classification": "Connection failure",
            "cause": "The service was unreachable or not listening on the expected address.",
            "fix": "Confirm the service is running and verify host, port, and firewall settings.",
        }
    if "attributeerror" in text:
        return {
            "classification": "Attribute error",
            "cause": "Code tried to access an attribute that the object does not expose.",
            "fix": "Validate object type and confirm the expected interface before calling it.",
        }
    return {
        "classification": "Unknown error shape",
        "cause": "The provided text does not match a common pattern.",
        "fix": "Paste the full traceback or error code for a more specific excavation.",
    }


def _confidence_text(value: float | None) -> str:
    return f"{value:.0%}" if value is not None else "n/a"


def _scan(path: Path):
    console.print("[cyan]Excavating repository...[/cyan]")
    return analyze_repository_root(path)


def _print_timeline(timeline: dict[str, object]) -> None:
    if not timeline.get("available"):
        render_notice("Git history unavailable.", style="yellow")
        return
    tree = Tree("Repository Timeline")
    tree.add(f"Repository Age: {timeline.get('repository_age_years', 0)} years")
    tree.add(f"Total Commits: {timeline.get('commit_count', 0)}")
    if timeline.get("first_commit"):
        tree.add(f"First Commit: {timeline.get('first_commit')}")
    if timeline.get("last_commit"):
        tree.add(f"Last Commit: {timeline.get('last_commit')}")
    eras = tree.add("Eras")
    for era in timeline.get("eras", []):
        eras.add(f"{era['year']}: {era['title']} ({era['activity']})")
    modified = tree.add("Most Modified Files")
    for name, count in (timeline.get("most_modified_files") or [])[:5]:
        modified.add(f"{name} ({count})")
    console.print(tree)


def _render_deps(intelligence) -> None:
    render_header("Dependency Archaeology", f"Repository: {intelligence.root}")
    render_kv(
        "Dependency Graph",
        [
            ("Nodes", str(intelligence.graph_node_count)),
            ("Edges", str(intelligence.graph_edge_count)),
            ("Circular Dependencies", str(len(intelligence.dependency_cycles))),
        ],
        border_style="magenta",
    )
    if intelligence.dependency_hubs:
        table = Table(title="Core Dependency Hubs", header_style="bold magenta")
        table.add_column("File", overflow="fold")
        table.add_column("Referenced By", justify="right")
        table.add_column("Depends On", justify="right")
        table.add_column("External", overflow="fold")
        table.add_column("Risk")
        table.add_column("Impact")
        table.add_column("Confidence", justify="right")
        for hub in intelligence.dependency_hubs[:10]:
            table.add_row(
                str(hub.path),
                str(hub.referenced_by),
                str(hub.depends_on),
                ", ".join(hub.external_packages) or "n/a",
                hub.dependency_risk,
                hub.failure_impact,
                f"{hub.confidence:.0%}",
            )
        console.print(table)
    if intelligence.dependency_chains:
        tree = Tree("Dependency Chains")
        for chain in intelligence.dependency_chains[:5]:
            branch = tree.add(Path(chain[0]).name)
            for node in chain[1:]:
                branch = branch.add(Path(node).name)
        console.print(tree)
    if intelligence.dependency_cycles:
        table = Table(title="Circular Dependencies", header_style="bold red")
        table.add_column("Cycle")
        for cycle in intelligence.dependency_cycles[:10]:
            table.add_row(" -> ".join(path.name for path in cycle))
        console.print(table)


def _render_genealogy(intelligence) -> None:
    render_header("Code Family Trees", f"Repository: {intelligence.root}")
    if not intelligence.genealogy:
        render_notice("No strong module family clusters detected.", style="green")
        return
    for family in intelligence.genealogy[:8]:
        tree = Tree(family.name)
        tree.add(str(family.root))
        if family.children:
            children = tree.add("Children")
            for child in family.children:
                children.add(str(child))
        if family.inherited_classes:
            bases = tree.add("Inherited Classes")
            for item in family.inherited_classes[:8]:
                bases.add(item)
        if family.parent_modules:
            parents = tree.add("Parent Modules")
            for parent in family.parent_modules[:5]:
                parents.add(str(parent))
        console.print(tree)


def _render_civilizations(intelligence) -> None:
    render_header("Lost Civilization Detection", f"Repository: {intelligence.root}")
    if not intelligence.civilizations:
        render_notice("No abandoned systems detected.", style="green")
        return
    for civ in intelligence.civilizations[:8]:
        render_kv(
            "Lost Civilization Discovered",
            [
                ("Name", civ.name),
                ("Files", str(len(civ.files))),
                ("Referenced", str(civ.referenced)),
                ("Last Active", f"{civ.last_active_days} days ago"),
                ("Status", civ.status),
                ("Confidence", f"{civ.confidence:.0%}"),
            ],
            border_style="yellow" if civ.status == "Dormant" else "red",
        )


def _render_debt(intelligence) -> None:
    render_header("Technical Debt Heatmap", f"Repository: {intelligence.root}")
    if not intelligence.debt_heatmap:
        render_notice("No debt hotspots detected.", style="green")
        return
    render_bars("Technical Debt Hotspots", [(bucket.bucket, bucket.score) for bucket in intelligence.debt_heatmap[:12]])
    table = Table(title="Hotspot Details")
    table.add_column("Bucket")
    table.add_column("Score", justify="right")
    table.add_column("Label")
    table.add_column("Files", justify="right")
    for bucket in intelligence.debt_heatmap[:12]:
        table.add_row(bucket.bucket, f"{bucket.score:.1f}", bucket.label, str(bucket.files))
    console.print(table)


def _render_personality(intelligence) -> None:
    profile = intelligence.personality
    render_kv(
        "Repository Personality",
        [
            ("Type", profile.type),
            ("Traits", "; ".join(profile.traits)),
            ("Risk", profile.risk),
        ],
        border_style="cyan",
    )


def _render_forecast(intelligence) -> None:
    forecast = intelligence.forecast
    render_kv(
        "Forecast",
        [
            ("Current Health", f"{forecast.current_health}/100"),
            ("Projected 6 Months", f"{forecast.projected_6_months}/100"),
            ("Projected 12 Months", f"{forecast.projected_12_months}/100"),
            ("Reason", forecast.reason),
        ],
        border_style="magenta",
    )


def _render_dna(intelligence) -> None:
    render_kv(
        "DNA Signature",
        [
            ("Signature", ", ".join(intelligence.dna.signature)),
            ("Confidence", f"{intelligence.dna.confidence:.0%}"),
        ],
        border_style="green",
    )


def _render_architecture(intelligence) -> None:
    architecture = intelligence.architecture
    if not architecture:
        render_notice("Architecture classification unavailable.", style="yellow")
        return
    render_kv(
        "Architecture Classification",
        [
            ("Primary", architecture.primary),
            ("Secondary", architecture.secondary),
            ("Confidence", f"{architecture.confidence:.0%}"),
        ],
        border_style="cyan",
    )


def _render_investigation(intelligence) -> None:
    render_header("Code Crime Scene Investigation", f"Repository: {intelligence.root}")
    if intelligence.incidents:
        for incident in intelligence.incidents:
            render_kv(
                "Investigation Report",
                [
                    ("Incident", incident.incident),
                    ("Date", incident.date),
                    ("Impact", incident.impact),
                    ("Outcome", incident.outcome),
                    ("Risk", incident.risk),
                ],
                border_style="red" if incident.risk in {"High", "Critical"} else "yellow",
            )
            if incident.evidence:
                table = Table(title="Evidence", header_style="bold red")
                table.add_column("Evidence", overflow="fold")
                for item in incident.evidence:
                    table.add_row(item)
                console.print(table)
    else:
        render_notice("No incident cluster detected.", style="green")
    _render_architecture(intelligence)
    _render_weaknesses(intelligence)
    _render_observations(intelligence)


def _render_weaknesses(intelligence) -> None:
    render_header("Structural Weakness Detection", f"Repository: {intelligence.root}")
    if not intelligence.weaknesses:
        render_notice("No critical structural weaknesses detected.", style="green")
        return
    table = Table(title="Critical Structural Weaknesses", header_style="bold red")
    table.add_column("Location", overflow="fold")
    table.add_column("Referenced By", justify="right")
    table.add_column("Failure Impact")
    table.add_column("Recovery Difficulty")
    table.add_column("Confidence", justify="right")
    for weakness in intelligence.weaknesses[:12]:
        table.add_row(
            str(weakness.path),
            str(weakness.referenced_by),
            weakness.failure_impact,
            weakness.recovery_difficulty,
            f"{weakness.confidence:.0%}",
        )
    console.print(table)


def _render_quake(intelligence, target: str | None = None) -> None:
    simulation = intelligence.quake_simulation
    render_header("Earthquake Simulation", f"Repository: {intelligence.root}")
    if not simulation:
        render_notice("No simulation target available.", style="yellow")
        return
    if target and target not in {simulation.target.name, str(simulation.target)}:
        render_notice(
            f"Using default target {simulation.target.name}; no separate quake model was built for {target}.",
            style="yellow",
        )
    render_kv(
        "Earthquake Simulation",
        [
            ("Removing", str(simulation.target)),
            ("Projected Damage", str(simulation.projected_damage)),
            ("Subsystems Lost", str(simulation.subsystems_lost)),
            ("Severity", simulation.severity),
        ],
        border_style="red",
    )
    if simulation.affected_files:
        table = Table(title="Affected Files")
        table.add_column("File", overflow="fold")
        for path in simulation.affected_files:
            table.add_row(str(path))
        console.print(table)


def _render_map(intelligence) -> None:
    render_header("Repository Knowledge Map", f"Repository: {intelligence.root}")
    tree = Tree("Core")
    for item in intelligence.knowledge_map.core:
        tree.add(item)
    if intelligence.knowledge_map.dependency_graph:
        deps = tree.add("Dependency Graph")
        for dep in intelligence.knowledge_map.dependency_graph[:8]:
            deps.add(dep)
    api = tree.add("API")
    for item in intelligence.knowledge_map.route_graph[:5]:
        api.add(item)
    services = tree.add("Services")
    for item in intelligence.knowledge_map.service_graph[:5]:
        services.add(item)
    architecture = tree.add("Architecture")
    for item in intelligence.knowledge_map.architecture_graph:
        architecture.add(item)
    console.print(tree)


def _render_contributors(intelligence) -> None:
    render_header("Developer Behavior Analysis", f"Repository: {intelligence.root}")
    if not intelligence.contributors:
        render_notice("No contributor data available.", style="yellow")
        return
    table = Table(title="Repository Custodians", header_style="bold cyan")
    table.add_column("Area")
    table.add_column("Owner")
    table.add_column("Maintenance")
    table.add_column("Abandoned")
    for item in intelligence.contributors[:20]:
        table.add_row(item.area, item.owner, item.maintenance_owner, item.abandoned_owner)
    console.print(table)


def _render_mutations(intelligence) -> None:
    render_header("Evolutionary Mutation Tracking", f"Repository: {intelligence.root}")
    if not intelligence.mutations:
        render_notice("No major mutation detected.", style="green")
        return
    for mutation in intelligence.mutations:
        render_kv(
            "Mutation Detected",
            [
                ("Project Type", mutation.project_type),
                ("Became", mutation.became),
                ("Date", mutation.date),
                ("Impact", mutation.impact),
            ],
            border_style="magenta",
        )


def _render_containment_zones(intelligence) -> None:
    render_header("Complexity Containment Zones", f"Repository: {intelligence.root}")
    if not intelligence.containment_zones:
        render_notice("No containment zones detected.", style="green")
        return
    table = Table(title="Containment Zones", header_style="bold yellow")
    table.add_column("Location", overflow="fold")
    table.add_column("Complexity", justify="right")
    table.add_column("Spread Rate")
    table.add_column("Recommendation")
    for zone in intelligence.containment_zones[:12]:
        table.add_row(zone.location, str(zone.complexity), zone.spread_rate, zone.recommendation)
    console.print(table)


def _render_survival(intelligence) -> None:
    render_header("Project Survival Score", f"Repository: {intelligence.root}")
    survival = intelligence.survival
    if not survival:
        render_notice("Survival score unavailable.", style="yellow")
        return
    render_kv(
        "Survival Score",
        [
            ("Score", f"{survival.score}/100"),
            ("Risk", survival.risk),
            ("Single Point Failure", survival.single_point_failure),
            ("Maintainability", str(survival.maintainability)),
            ("Recoverability", str(survival.recoverability)),
            ("Onboarding Difficulty", str(survival.onboarding_difficulty)),
            ("Bus Factor", str(survival.bus_factor)),
        ],
        border_style="green" if survival.score >= 70 else "red",
    )


def _render_observations(intelligence) -> None:
    render_header("AI-Assisted Archaeological Notes", f"Repository: {intelligence.root}")
    if not intelligence.observations:
        render_notice("No observations generated.", style="yellow")
        return
    for note in intelligence.observations[:8]:
        panel_text = note.observation
        if note.evidence:
            panel_text += "\n\nEvidence:\n" + "\n".join(f"- {item}" for item in note.evidence)
        console.print(Panel(panel_text, border_style="cyan"))


def _render_inspect(root: Path, target: Path) -> None:
    resolved = _resolve_target(root, target)
    if not resolved.exists():
        raise typer.BadParameter(f"Target does not exist: {target}")
    analysis = _scan(root)
    text_cache = analysis.intelligence.text_cache
    references = analysis.intelligence.references
    dependencies = analysis.intelligence.dependencies
    file_text = text_cache.get(resolved) or read_text(resolved)
    lines = file_text.splitlines()
    todos = [finding for finding in find_todos([resolved])]
    render_header("Deep Inspection", f"Target: {resolved}")
    render_kv(
        "Artifact Profile",
        [
            ("Kind", path_kind(resolved)),
            ("Size", f"{safe_stat(resolved)} bytes"),
            ("Lines", str(len(lines))),
            ("Referenced By", str(len(references.get(resolved, set())))),
            ("Depends On", str(len(dependencies.get(resolved, set())))),
            ("TODO Markers", str(len(todos))),
        ],
        border_style="cyan",
    )
    if todos:
        table = Table(title="Embedded Notes", header_style="bold red")
        table.add_column("Severity")
        table.add_column("Line")
        table.add_column("Comment", overflow="fold")
        for finding in todos[:10]:
            table.add_row(finding.severity, str(finding.line), finding.comment)
        console.print(table)
    if len(lines) > 0:
        preview = _file_context(resolved, 1, context=4)
        console.print(Panel("\n".join(preview), title="File Preview", border_style="blue"))
    if references.get(resolved):
        table = Table(title="Inbound References", header_style="bold magenta")
        table.add_column("File", overflow="fold")
        for item in sorted(references.get(resolved, set()))[:15]:
            table.add_row(str(item))
        console.print(table)


def _render_trace(root: Path, target: str) -> None:
    analysis = _scan(root)
    view = analysis.intelligence.view
    text_cache = analysis.intelligence.text_cache
    references = analysis.intelligence.references
    dependencies = analysis.intelligence.dependencies
    resolved = _resolve_target(root, Path(target))
    render_header("Trace Excavation", f"Repository: {view.root}")
    if resolved.exists():
        table = Table(title="Dependency Trace", header_style="bold magenta")
        table.add_column("Direction")
        table.add_column("File", overflow="fold")
        for item in sorted(references.get(resolved, set()))[:20]:
            table.add_row("Referenced By", str(item))
        for item in sorted(dependencies.get(resolved, set()))[:20]:
            table.add_row("Depends On", str(item))
        console.print(table)
        return
    hits: list[tuple[Path, int, str]] = []
    needle = target.lower()
    for path, content in text_cache.items():
        for index, line in enumerate(content.splitlines(), start=1):
            if needle in line.lower():
                hits.append((path, index, line.strip()))
                if len(hits) >= 30:
                    break
        if len(hits) >= 30:
            break
    if not hits:
        render_notice(f"No trace evidence found for {escape(target)}.", style="yellow")
        return
    table = Table(title="Symbol Trace", header_style="bold cyan")
    table.add_column("File", overflow="fold")
    table.add_column("Line", justify="right")
    table.add_column("Match", overflow="fold")
    for path, line_number, line in hits:
        table.add_row(str(path), str(line_number), line)
    console.print(table)


def _render_evidence(root: Path, target: str) -> None:
    analysis = _scan(root)
    text_cache = analysis.intelligence.text_cache
    references = analysis.intelligence.references
    resolved = _resolve_target(root, Path(target))
    render_header("Evidence File", f"Repository: {analysis.intelligence.view.root}")
    if resolved.exists():
        lines = (text_cache.get(resolved) or read_text(resolved)).splitlines()
        snippets = _file_context(resolved, 1, context=5)
        render_kv(
            "Evidence Summary",
            [
                ("Target", str(resolved)),
                ("Referenced By", str(len(references.get(resolved, set())))),
                ("Evidence Lines", str(len(lines))),
                ("Confidence", "High" if len(references.get(resolved, set())) else "Moderate"),
            ],
            border_style="yellow",
        )
        console.print(Panel("\n".join(snippets), title="Evidence Snapshot", border_style="yellow"))
        return
    trace_hits: list[tuple[Path, int, str]] = []
    needle = target.lower()
    for path, content in text_cache.items():
        for index, line in enumerate(content.splitlines(), start=1):
            if needle in line.lower():
                trace_hits.append((path, index, line.strip()))
                if len(trace_hits) >= 15:
                    break
        if len(trace_hits) >= 15:
            break
    if not trace_hits:
        render_notice(f"No evidence located for {escape(target)}.", style="yellow")
        return
    table = Table(title="Evidence Trail", header_style="bold yellow")
    table.add_column("File", overflow="fold")
    table.add_column("Line", justify="right")
    table.add_column("Snippet", overflow="fold")
    for path, line_number, line in trace_hits:
        table.add_row(str(path), str(line_number), line)
    console.print(table)


def _render_bugmark(root: Path, target: Path, line: int | None, note: str | None) -> None:
    resolved = _resolve_target(root, target)
    if not resolved.exists():
        raise typer.BadParameter(f"Target does not exist: {target}")
    detected_line = line
    if detected_line is None:
        try:
            for index, content_line in enumerate(read_text(resolved).splitlines(), start=1):
                lowered = content_line.lower()
                if any(marker in lowered for marker in ("todo", "fixme", "hack", "bug", "temp", "xxx")):
                    detected_line = index
                    break
        except OSError:
            detected_line = None
    context = _file_context(resolved, detected_line, context=3)
    title = "Bug Marker"
    if note:
        title = f"Bug Marker - {note}"
    render_kv(
        "Bugmark",
        [
            ("File", str(resolved)),
            ("Line", str(detected_line or "auto")),
            ("Note", note or "n/a"),
            ("Status", "Highlighted" if detected_line else "Review"),
        ],
        border_style="red",
    )
    console.print(Panel("\n".join(context), title=title, border_style="red"))


def _render_cleanup_plan(analysis) -> None:
    summary = analysis.summary
    plan = recovery.build_cleanup_plan(analysis)
    render_header("Repository Cleanup Plan", f"Repository: {summary.root}")
    if not plan:
        render_notice("No cleanup priorities identified.", style="green")
        return
    for item in plan:
        panel = Panel(
            "\n".join(f"- {line}" for line in item.items),
            title=f"Priority {item.level}",
            border_style="red" if item.level == 1 else "yellow" if item.level == 2 else "green",
        )
        console.print(panel)


def _render_delete_check(root: Path, target: str) -> None:
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    analysis = recovery.analyze_deletion(candidate, root)
    render_kv(
        "Deletion Confidence",
        [
            ("Safe", f"{analysis.safe_confidence:.0f}%"),
            ("Files Affected", str(analysis.affected_files)),
            ("Recommendation", analysis.recommendation),
        ],
        border_style="yellow" if analysis.safe_confidence < 80 else "green",
    )
    if analysis.references or analysis.dependencies:
        table = Table(title="Impact Radius", header_style="bold yellow")
        table.add_column("Type")
        table.add_column("File", overflow="fold")
        for path in analysis.references:
            table.add_row("Reference", str(path))
        for path in analysis.dependencies:
            table.add_row("Dependency", str(path))
        console.print(table)


def _render_refactor_candidates(analysis) -> None:
    candidates = recovery.find_refactor_candidates(analysis)
    render_header("Refactor Opportunities", f"Repository: {analysis.summary.root}")
    if not candidates:
        render_notice("No strong refactor candidates found.", style="green")
        return
    for candidate in candidates:
        render_kv(
            "Refactor Candidate",
            [
                ("Function", candidate.name),
                ("Found In", "\n".join(f"- {path}" for path in candidate.locations)),
                ("Recommendation", candidate.recommendation),
                ("Confidence", f"{candidate.confidence:.0%}"),
            ],
            border_style="magenta",
        )


def _render_routes(analysis) -> None:
    findings = recovery.audit_routes(analysis.intelligence.view, analysis.intelligence.text_cache, analysis.intelligence.references)
    render_header("Route Auditing", f"Repository: {analysis.summary.root}")
    if not findings:
        render_notice("No route-like files detected.", style="green")
        return
    table = Table(title="Route Findings", header_style="bold cyan")
    table.add_column("Kind")
    table.add_column("File", overflow="fold")
    table.add_column("Detail", overflow="fold")
    table.add_column("Confidence", justify="right")
    for finding in findings:
        table.add_row(finding.kind, str(finding.path), finding.detail, f"{finding.confidence:.0%}")
    console.print(table)


def _render_configs(analysis) -> None:
    findings = recovery.audit_configs(analysis.intelligence.view, analysis.intelligence.text_cache)
    render_header("Configuration Auditing", f"Repository: {analysis.summary.root}")
    if not findings:
        render_notice("No stale configuration detected.", style="green")
        return
    table = Table(title="Configuration Findings", header_style="bold yellow")
    table.add_column("Kind")
    table.add_column("Name")
    table.add_column("Locations", overflow="fold")
    table.add_column("Confidence", justify="right")
    for finding in findings:
        table.add_row(finding.kind, finding.name, ", ".join(str(path) for path in finding.locations) or "n/a", f"{finding.confidence:.0%}")
    console.print(table)


def _render_migrations(analysis) -> None:
    findings = recovery.audit_migrations(analysis.intelligence.view, analysis.intelligence.text_cache)
    render_header("Migration Auditing", f"Repository: {analysis.summary.root}")
    if not findings:
        render_notice("No migration issues detected.", style="green")
        return
    table = Table(title="Migration Findings", header_style="bold red")
    table.add_column("Path", overflow="fold")
    table.add_column("Kind")
    table.add_column("Status")
    table.add_column("Confidence", justify="right")
    for finding in findings:
        table.add_row(str(finding.path), finding.kind, finding.status, f"{finding.confidence:.0%}")
    console.print(table)


def _render_dependency_rationalization(analysis) -> None:
    warnings = recovery.rationalize_dependencies(analysis)
    render_header("Dependency Rationalization", f"Repository: {analysis.summary.root}")
    if not warnings:
        render_notice("No dependency rationalization warnings found.", style="green")
        return
    table = Table(title="Dependency Warnings", header_style="bold red")
    table.add_column("Package")
    table.add_column("Used For", justify="right")
    table.add_column("Recommendation", overflow="fold")
    table.add_column("Confidence", justify="right")
    for warning in warnings:
        table.add_row(warning.name, str(warning.only_used_for), warning.recommendation, f"{warning.confidence:.0%}")
    console.print(table)


def _render_drift(analysis) -> None:
    drift = recovery.detect_drift(analysis)
    render_kv(
        "Architecture Drift",
        [
            ("Original", drift.original),
            ("Current", drift.current),
            ("Drift Severity", drift.severity),
            ("Primary Cause", drift.cause),
        ],
        border_style="magenta",
    )


def _render_pr_report(analysis) -> None:
    pr = recovery.build_pr_report(analysis)
    render_header("Automated Pull Request Notes", f"Repository: {analysis.summary.root}")
    table = Table(title="Technical Debt Changes", header_style="bold green")
    table.add_column("Section")
    table.add_column("Items", overflow="fold")
    if pr.removed:
        table.add_row("Removed", "\n".join(f"- {item}" for item in pr.removed))
    if pr.reduced:
        table.add_row("Reduced", "\n".join(f"- {item}" for item in pr.reduced))
    if pr.improved:
        table.add_row("Improved", "\n".join(f"- {item}" for item in pr.improved))
    console.print(table)


def _render_status(analysis) -> None:
    status = recovery.build_status_summary(analysis)
    render_header("Repository Maintenance Dashboard", f"Repository: {analysis.summary.root}")
    render_kv(
        "Maintenance Status",
        [
            ("Debt", str(status.debt)),
            ("Complexity", str(status.complexity)),
            ("Dead Code", str(status.dead_code)),
            ("Route Count", str(status.route_count)),
            ("Dependency Count", str(status.dependency_count)),
            ("Cleanup Opportunities", str(status.cleanup_opportunities)),
        ],
        border_style="cyan",
    )
    if status.recommendations:
        console.print(Panel("\n".join(f"- {item}" for item in status.recommendations), title="Recommendations", border_style="cyan"))
    baseline = maintenance.load_baseline(analysis.summary.root)
    if baseline:
        render_kv(
            "Baseline Context",
            [
                ("Captured", baseline.captured_at),
                ("Baseline Health", f"{baseline.health_score}/100"),
                ("Baseline Complexity", str(baseline.complexity_score)),
            ],
            border_style="green",
        )
    history = maintenance.history_points(analysis.summary.root)
    if history:
        render_notice(f"Maintenance history entries tracked: {len(history)}", style="cyan")


def _render_baseline(analysis) -> None:
    snapshot = maintenance.save_baseline(analysis)
    render_kv(
        "Baseline Snapshot",
        [
            ("Captured", snapshot.captured_at),
            ("Files", str(snapshot.file_count)),
            ("Dependencies", str(snapshot.dependency_count)),
            ("Complexity", str(snapshot.complexity_score)),
            ("Dead Code", str(snapshot.dead_code_count)),
            ("Duplicates", str(snapshot.duplicate_code_count)),
            ("Routes", str(snapshot.route_count)),
            ("Health", f"{snapshot.health_score}/100"),
        ],
        border_style="green",
    )


def _render_regressions(analysis) -> None:
    current = maintenance.build_snapshot(analysis)
    baseline = maintenance.load_baseline(analysis.summary.root)
    render_header("Regression Detection", f"Repository: {analysis.summary.root}")
    if baseline is None:
        render_notice("No baseline found. Run `devarch baseline .` first.", style="yellow")
        return
    report = maintenance.compare_to_baseline(current, baseline)
    render_kv(
        "Regression Report",
        [
            ("Complexity", f"{baseline.complexity_score} -> {current.complexity_score} ({report.complexity_delta:+.1f}%)"),
            ("Dead Code", f"{baseline.dead_code_count} -> {current.dead_code_count} ({report.dead_code_delta:+d})"),
            ("Duplicate Logic", f"{baseline.duplicate_code_count} -> {current.duplicate_code_count} ({report.duplicate_delta:+d})"),
            ("Health Score", f"{baseline.health_score} -> {current.health_score} ({report.health_delta:+d})"),
            ("Status", report.status),
        ],
        border_style="red" if report.status == "Regressed" else "green",
    )
    maintenance.append_history(analysis, label="regression-check")


def _load_budget_config(path: Path, config: Optional[Path]) -> maintenance.BudgetLimits:
    return maintenance.read_budget_limits(path, config=config)


def _render_budget(analysis, config: Optional[Path] = None) -> None:
    current = maintenance.build_snapshot(analysis)
    limits = _load_budget_config(analysis.summary.root, config)
    result = maintenance.evaluate_budget(current, limits)
    render_header("Technical Debt Budget", f"Repository: {analysis.summary.root}")
    rows = [
        ("Dead Files", f"{current.dead_code_count} / {limits.max_dead_files}"),
        ("Complexity", f"{current.complexity_score} / {limits.max_complexity}"),
        ("Duplicate Blocks", f"{current.duplicate_code_count} / {limits.max_duplicate_blocks}"),
        ("TODOs", f"{current.todo_count} / {limits.max_todos}"),
        ("Routes", f"{current.route_count} / {limits.max_routes}"),
        ("Dependencies", f"{current.dependency_count} / {limits.max_dependencies}"),
        ("Health", f"{current.health_score} / {limits.min_health_score}"),
        ("Status", result.status),
    ]
    render_kv("Technical Debt Budget", rows, border_style="yellow" if result.exceeded else "green")
    if result.exceeded:
        table = Table(title="Budget Exceeded", header_style="bold red")
        table.add_column("Metric")
        table.add_column("Current", justify="right")
        table.add_column("Limit", justify="right")
        for label, value, limit in result.exceeded:
            table.add_row(label, str(value), str(limit))
        console.print(table)


def _render_release_check(analysis, config: Optional[Path] = None) -> None:
    baseline = maintenance.load_baseline(analysis.summary.root)
    limits = _load_budget_config(analysis.summary.root, config)
    report = maintenance.release_check(analysis, baseline=baseline, limits=limits)
    render_header("Release Readiness", f"Repository: {analysis.summary.root}")
    render_kv(
        "Release Readiness",
        [
            ("Score", f"{report.score}/100"),
            ("Status", report.status),
            ("Warnings", str(len(report.warnings))),
        ],
        border_style="green" if report.status == "Ready" else "yellow",
    )
    if report.warnings:
        console.print(Panel("\n".join(f"- {item}" for item in report.warnings[:10]), title="Warnings", border_style="yellow"))
    if report.blockers:
        console.print(Panel("\n".join(f"- {item}" for item in report.blockers), title="Blockers", border_style="red"))
    maintenance.append_history(analysis, label="release-check")


def _render_ownership(analysis) -> None:
    findings = maintenance.ownership_report(analysis)
    render_header("Ownership Analysis", f"Repository: {analysis.summary.root}")
    if not findings:
        render_notice("No obvious ownership gaps detected.", style="green")
        return
    table = Table(title="Ownership Warnings", header_style="bold yellow")
    table.add_column("Module")
    table.add_column("Last Significant Activity", justify="right")
    table.add_column("Primary Maintainer")
    table.add_column("Status")
    for item in findings:
        table.add_row(item.module, f"{item.last_significant_activity_days} days", item.primary_maintainer, item.status)
    console.print(table)


def _render_dependency_health(analysis) -> None:
    alerts = maintenance.dependency_health_report(analysis)
    render_header("Dependency Lifecycle Monitoring", f"Repository: {analysis.summary.root}")
    if not alerts:
        render_notice("No dependency alerts found.", style="green")
        return
    table = Table(title="Dependency Alerts", header_style="bold red")
    table.add_column("Package")
    table.add_column("Status")
    table.add_column("Used By", justify="right")
    table.add_column("Recommendation", overflow="fold")
    for item in alerts:
        table.add_row(item.package, item.status, str(item.used_by), item.recommendation)
    console.print(table)


def _render_cleanup_queue(analysis) -> None:
    queue = maintenance.cleanup_candidates(analysis)
    render_header("Cleanup Candidates", f"Repository: {analysis.summary.root}")
    if not queue:
        render_notice("No cleanup queue available.", style="green")
        return
    table = Table(title="Top Cleanup Opportunities", header_style="bold green")
    table.add_column("#", justify="right")
    table.add_column("Opportunity", overflow="fold")
    for index, item in enumerate(queue[:10], start=1):
        table.add_row(str(index), item)
    console.print(table)


def _render_standards(analysis) -> None:
    report = maintenance.standards_report(analysis)
    render_header("Repository Standards Enforcement", f"Repository: {analysis.summary.root}")
    render_kv(
        "Standards Report",
        [
            ("Naming", f"{report.naming}%"),
            ("Documentation", f"{report.documentation}%"),
            ("Consistency", f"{report.consistency}%"),
            ("Test Coverage", f"{report.test_coverage}%"),
        ],
        border_style="cyan",
    )
    if report.notes:
        console.print(Panel("\n".join(f"- {item}" for item in report.notes), title="Notes", border_style="yellow"))


def _render_history(analysis) -> None:
    points = maintenance.history_points(analysis.summary.root)
    render_header("Repository Health History", f"Repository: {analysis.summary.root}")
    if not points:
        render_notice("No maintenance history recorded yet.", style="yellow")
        return
    table = Table(title="Health History", header_style="bold cyan")
    table.add_column("Captured At")
    table.add_column("Health", justify="right")
    table.add_column("Complexity", justify="right")
    table.add_column("Dead Code", justify="right")
    table.add_column("Duplicates", justify="right")
    table.add_column("Label")
    for point in points[-10:]:
        table.add_row(point.captured_at, str(point.health_score), str(point.complexity_score), str(point.dead_code_count), str(point.duplicate_code_count), point.label)
    console.print(table)


def _render_recommendations(analysis) -> None:
    items = maintenance.recommendation_items(analysis)
    render_header("Automatic Recommendations", f"Repository: {analysis.summary.root}")
    if not items:
        render_notice("No actionable recommendations available.", style="green")
        return
    for index, item in enumerate(items, start=1):
        render_kv(
            f"Recommendation #{index}",
            [
                ("Action", item.title),
                ("Current", item.current),
                ("Target", item.target),
                ("Potential Reduction", item.potential_reduction),
            ],
            border_style="magenta",
        )


def _render_prescription(analysis) -> None:
    prescription = maintenance.prescribe_repository(analysis)
    render_header("Repository Prescription", f"Repository: {analysis.summary.root}")
    render_kv(
        "Immediate Actions",
        [
            ("Actions", "\n".join(f"- {item}" for item in prescription.immediate_actions) or "n/a"),
            ("Estimated Time", f"{prescription.estimated_time_minutes // 60} hours {prescription.estimated_time_minutes % 60} minutes"),
            ("Expected Health Increase", f"+{prescription.expected_health_increase} points"),
        ],
        border_style="green",
    )
    if prescription.findings:
        table = Table(title="Remediation Prescriptions", header_style="bold magenta")
        table.add_column("Problem", overflow="fold")
        table.add_column("Fix", overflow="fold")
        table.add_column("Effort", justify="right")
        table.add_column("Risk")
        table.add_column("Confidence", justify="right")
        for finding in prescription.findings:
            table.add_row(finding.problem, finding.recommended_fix, finding.estimated_effort, finding.risk_level, f"{finding.confidence:.0%}")
        console.print(table)


def _render_repair_plan(analysis) -> None:
    plan = maintenance.repair_plan(analysis)
    render_header("Repository Repair Mode", f"Repository: {analysis.summary.root}")
    if not plan:
        render_notice("No repair plan available.", style="green")
        return
    for week in plan:
        render_kv(
            f"Week {week.week}",
            [
                ("Focus", week.focus),
                ("Actions", "\n".join(f"- {item}" for item in week.actions)),
                ("Expected Health", week.expected_health),
            ],
            border_style="cyan",
        )


def _render_scan_summary(analysis) -> None:
    summary = analysis.summary
    intelligence = analysis.intelligence
    render_header("Dev Archaeologist", f"Repository: {summary.root}")
    render_kv(
        "Excavation Summary",
        [
            ("Artifacts", str(summary.artifact_count)),
            ("Ancient", str(summary.ancient_count)),
            ("TODOs", str(summary.todo_count)),
            ("Duplicates", str(summary.duplicate_count)),
            ("Health", f"{summary.health_score}/100"),
            ("Status", summary.health_status),
            ("Badge", health_badge(summary.health_score)),
        ],
        border_style="green",
    )
    render_notice(
        f"Repository Health: {summary.health_score}/100 | Status: {summary.health_status} | Badge: {health_badge(summary.health_score)}",
        style="cyan",
    )
    _print_timeline(summary.timeline)
    _render_dna(intelligence)
    confidence = summary.extra.get("artifact_confidence", {})
    render_kv(
        "Artifact Confidence",
        [
            ("Dead Code", f"{confidence.get('dead_code', 0):.0%}" if confidence.get("dead_code") is not None else "n/a"),
            ("Ancient File", f"{confidence.get('ancient_file', 0):.0%}" if confidence.get("ancient_file") is not None else "n/a"),
            ("Duplicate Logic", f"{confidence.get('duplicate_block', 0):.0%}" if confidence.get("duplicate_block") is not None else "n/a"),
        ],
        border_style="green",
    )
    _render_personality(intelligence)
    _render_forecast(intelligence)
    render_artifacts("Excavated Artifacts", summary.artifacts[:25])
    remediation = summary.extra.get("remediation", [])
    if remediation:
        table = Table(title="Remediation Actions", header_style="bold magenta")
        table.add_column("Problem", overflow="fold")
        table.add_column("Impact")
        table.add_column("Fix", overflow="fold")
        table.add_column("Effort", justify="right")
        table.add_column("Risk")
        for item in remediation[:12]:
            table.add_row(item["problem"], item["impact"], item["recommended_fix"], item["estimated_effort"], item["risk_level"])
        console.print(table)
    if summary.warnings:
        render_notice("\n".join(f"- {warning}" for warning in summary.warnings), style="yellow")


def _export_report(fmt: str, path: Path, output: Optional[Path]) -> Path:
    analysis = _scan(path)
    default_names = {
        "json": "devarch-report.json",
        "markdown": "devarch-report.md",
        "html": "devarch-report.html",
        "pdf": "devarch-report.pdf",
    }
    destination = output or path / default_names[fmt]
    if fmt == "json":
        export_json(analysis.summary, destination)
    elif fmt == "markdown":
        export_markdown(analysis.summary, destination)
    elif fmt == "html":
        export_html(analysis.summary, destination)
    elif fmt == "pdf":
        export_pdf(analysis.summary, destination)
    else:
        raise typer.BadParameter(f"Unsupported report format: {fmt}")
    return destination


@app.command()
def scan(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Perform a complete archaeological excavation."""
    _render_scan_summary(_scan(path))


@app.command("help")
def help_command() -> None:
    """Show the full command catalog."""
    _render_help_catalog()


@app.command()
def ancient(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Find ancient, likely abandoned files."""
    view = collect_repository(path)
    text_cache = build_text_index(view)
    references = build_reference_map(view, text_cache)
    artifacts = find_ancient_files(view.files, references)
    render_header("Ancient Excavation", f"Repository: {view.root}")
    if artifacts:
        for artifact in artifacts:
            console.print(
                Panel(
                    f"[bold]File:[/bold]\n{artifact.path}\n\n"
                    f"[bold]Age:[/bold]\n{artifact.age_days} days\n\n"
                    f"[bold]Status:[/bold]\n{artifact.detail}\n\n"
                    f"[bold]Risk:[/bold]\n{artifact.risk}\n\n"
                    f"[bold]Confidence:[/bold]\n{_confidence_text(artifact.confidence)}",
                    title="Ancient Artifact Found",
                    border_style="magenta",
                )
            )
    else:
        render_notice("No ancient artifacts detected.", style="green")


@app.command("dead-code")
def dead_code(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Detect unused modules, unreferenced files, orphaned components, and unreachable code."""
    view = collect_repository(path)
    text_cache = build_text_index(view)
    artifacts = find_dead_code(view.root, view.files, text_cache)
    render_header("Dead Code Excavation", f"Repository: {view.root}")
    render_artifacts("Potentially Safe to Remove", artifacts)


@app.command()
def todos(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Search for TODO, FIXME, HACK, BUG, TEMP, and XXX markers."""
    view = collect_repository(path)
    findings = find_todos(view.files)
    render_header("TODO Excavation", f"Repository: {view.root}")
    if not findings:
        render_notice("No TODO markers found.", style="green")
        return
    table = Table(title="Excavated Notes", header_style="bold red")
    table.add_column("Severity")
    table.add_column("File")
    table.add_column("Line")
    table.add_column("Comment", overflow="fold")
    for finding in findings:
        table.add_row(finding.severity, str(finding.file), str(finding.line), finding.comment)
    console.print(table)


@app.command()
def duplicates(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Identify duplicated functions, copied blocks, and repeated logic."""
    view = collect_repository(path)
    text_cache = build_text_index(view)
    artifacts = find_duplicates(view.files, text_cache)
    pairs = similarity_report(view.files, text_cache)
    render_header("Duplicate Detector", f"Repository: {view.root}")
    render_artifacts("Duplicate Blocks", artifacts)
    if pairs:
        table = Table(title="Similarity Percentages")
        table.add_column("Left")
        table.add_column("Right")
        table.add_column("Similarity")
        for item in pairs[:15]:
            table.add_row(str(item["left"]), str(item["right"]), f'{item["similarity"]}%')
        console.print(table)


@app.command()
def monsters(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Detect files with excessive line count, complexity, or dependency count."""
    view = collect_repository(path)
    artifacts = find_monsters(view.files)
    render_header("Monster File Detection", f"Repository: {view.root}")
    if artifacts:
        for artifact in artifacts:
            console.print(
                Panel(
                    f"[bold]File:[/bold]\n{artifact.path}\n\n"
                    f"[bold]Lines:[/bold]\n{artifact.metadata.get('lines', 'n/a')}\n\n"
                    f"[bold]Complexity:[/bold]\n{artifact.metadata.get('complexity', 'n/a')}\n\n"
                    f"[bold]Threat Level:[/bold]\n{artifact.risk}\n\n"
                    f"[bold]Confidence:[/bold]\n{_confidence_text(artifact.confidence)}",
                    title="Monster Discovered",
                    border_style="red",
                )
            )
    else:
        render_notice("No monster files detected.", style="green")


@app.command()
def ruins(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Find empty folders, abandoned directories, and unused assets."""
    view = collect_repository(path)
    text_cache = build_text_index(view)
    artifacts = find_empty_directories(view.directories, view.files) + find_unused_assets(view.files, text_cache)
    render_header("Ruins Survey", f"Repository: {view.root}")
    render_artifacts("Empty Structures", artifacts)


@app.command()
def suspicious(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Detect suspicious backup-like filenames."""
    view = collect_repository(path)
    artifacts = find_suspicious(view.files)
    render_header("Suspicious Artifact Sweep", f"Repository: {view.root}")
    render_artifacts("Suspicious Files", artifacts)


@app.command()
def investigate(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Perform forensic analysis on the repository."""
    _render_investigation(_scan(path).intelligence)


@app.command()
def inspect(
    target: Path,
    root: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
) -> None:
    """Inspect a specific file or artifact in more detail."""
    _render_inspect(root, target)


@app.command()
def trace(
    target: str,
    root: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
) -> None:
    """Trace references, dependencies, or symbol mentions across the repository."""
    _render_trace(root, target)


@app.command()
def evidence(
    target: str,
    root: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
) -> None:
    """Show direct evidence for a file, symbol, or suspicious string."""
    _render_evidence(root, target)


@app.command()
def bugmark(
    target: Path,
    root: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    line: Optional[int] = typer.Option(None, "--line", "-l", help="Line number to highlight."),
    note: Optional[str] = typer.Option(None, "--note", "-n", help="Optional note for the highlighted bug."),
) -> None:
    """Highlight a suspected bug location without modifying files."""
    _render_bugmark(root, target, line, note)


@app.command("errorcode")
def errorcode(
    error_text: str,
) -> None:
    """Explain a build, runtime, or dependency error in plain language."""
    explanation = _explain_error_text(error_text)
    render_kv(
        "Error Code Excavation",
        [
            ("Input", error_text),
            ("Classification", explanation["classification"]),
            ("Likely Cause", explanation["cause"]),
            ("Recommended Fix", explanation["fix"]),
        ],
        border_style="red",
    )


@app.command()
def weaknesses(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Identify single points of failure and fragile dependency chains."""
    _render_weaknesses(_scan(path).intelligence)


@app.command()
def quake(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    target: Optional[str] = typer.Option(None, "--target", "-t", help="Target file or module to simulate removing."),
) -> None:
    """Simulate the breakage radius of deleting a file, class, or module."""
    _render_quake(_scan(path).intelligence, target=target)


@app.command()
def architecture(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Identify the repository's architectural pattern."""
    _render_architecture(_scan(path).intelligence)


@app.command()
def contributors(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Analyze feature ownership and maintenance custodians."""
    _render_contributors(_scan(path).intelligence)


@app.command()
def mutations(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Track major repository transformations."""
    _render_mutations(_scan(path).intelligence)


@app.command()
def map(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate the repository knowledge map."""
    _render_map(_scan(path).intelligence)


@app.command()
def survival(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Estimate maintainability, recoverability, and bus factor."""
    _render_survival(_scan(path).intelligence)


@app.command()
def notes(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate AI-assisted archaeological notes."""
    _render_observations(_scan(path).intelligence)


@app.command()
def dependencies(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Analyze internal imports, external packages, cycles, and dependency hubs."""
    _render_deps(_scan(path).intelligence)


@app.command()
def genealogy(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Discover parent modules, child modules, and inherited classes."""
    _render_genealogy(_scan(path).intelligence)


@app.command()
def civilizations(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Detect abandoned clusters of code that look like lost systems."""
    _render_civilizations(_scan(path).intelligence)


@app.command()
def debt(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate a repository-wide debt heatmap."""
    _render_debt(_scan(path).intelligence)


@app.command()
def timeline(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Summarize repository growth and activity by Git era."""
    analysis = _scan(path)
    render_header("Repository Evolution Timeline", f"Repository: {analysis.summary.root}")
    _print_timeline(analysis.summary.timeline)


@app.command()
def personality(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Classify the repository's working style."""
    _render_personality(_scan(path).intelligence)


@app.command()
def forecast(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Predict likely maintenance trajectory."""
    _render_forecast(_scan(path).intelligence)


@app.command()
def plan(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate a prioritized cleanup roadmap."""
    _render_cleanup_plan(_scan(path))


@app.command("delete-check")
def delete_check(
    target: str,
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
) -> None:
    """Analyze whether a file is safe to remove."""
    _render_delete_check(path, target)


@app.command()
def refactor(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Detect duplicate logic and oversized classes."""
    _render_refactor_candidates(_scan(path))


@app.command()
def routes(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Audit routes for unused, unreachable, or undocumented endpoints."""
    _render_routes(_scan(path))


@app.command()
def configs(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Detect stale environment variables and conflicting config."""
    _render_configs(_scan(path))


@app.command()
def migrations(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Inspect migrations for orphaned or incomplete states."""
    _render_migrations(_scan(path))


@app.command("deps")
def deps(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Detect duplicate packages and oversized dependency chains."""
    _render_dependency_rationalization(_scan(path))


@app.command()
def drift(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Compare current architecture against repository history."""
    _render_drift(_scan(path))


@app.command("pr-report")
def pr_report(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate pull request notes for maintenance changes."""
    _render_pr_report(_scan(path))


@app.command()
def status(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Show a single-command repository maintenance dashboard."""
    _render_status(_scan(path))


@app.command()
def baseline(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Create and store a repository snapshot baseline."""
    _render_baseline(_scan(path))


@app.command()
def regressions(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Identify health regressions since the last baseline."""
    _render_regressions(_scan(path))


@app.command()
def budget(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Optional budget configuration file."),
) -> None:
    """Evaluate the repository against technical debt budgets."""
    _render_budget(_scan(path), config=config)


@app.command("release-check")
def release_check(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Optional budget configuration file."),
) -> None:
    """Evaluate release readiness across debt, config, routes, and migrations."""
    _render_release_check(_scan(path), config=config)


@app.command()
def ownership(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Identify unowned modules and stale code areas."""
    _render_ownership(_scan(path))


@app.command("dependency-health")
def dependency_health(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Track unused and untracked dependencies."""
    _render_dependency_health(_scan(path))


@app.command()
def cleanup(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate a prioritized cleanup queue."""
    _render_cleanup_queue(_scan(path))


@app.command()
def standards(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Check naming, documentation, and consistency standards."""
    _render_standards(_scan(path))


@app.command()
def history(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Track repository health over time."""
    _render_history(_scan(path))


@app.command()
def recommend(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate practical maintenance recommendations."""
    _render_recommendations(_scan(path))


@app.command()
def prescribe(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate a repository-wide remediation prescription."""
    _render_prescription(_scan(path))


@app.command("repair-plan")
def repair_plan(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Generate a step-by-step repository recovery strategy."""
    _render_repair_plan(_scan(path))


@app.command()
def explore(path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True)) -> None:
    """Launch a lightweight live excavation dashboard."""
    analysis = _scan(path)

    def render_dashboard() -> Panel:
        summary = analysis.summary
        lines = [
            f"Repository: {summary.root}",
            f"Health: {summary.health_score}/100 ({summary.health_status})",
            f"Artifacts: {summary.artifact_count}",
            f"DNA: {', '.join(analysis.intelligence.dna.signature)}",
            f"Personality: {analysis.intelligence.personality.type}",
            "",
            "Actions:",
            "- 1: Refresh dashboard",
            "- 2: Show dependency hubs",
            "- 3: Show civilizations",
            "- 4: Show debt heatmap",
            "- q: Quit",
        ]
        return Panel("\n".join(lines), title="Interactive Excavation", border_style="cyan")

    with Live(render_dashboard(), console=console, refresh_per_second=4) as live:
        while True:
            choice = typer.prompt("Choose action", default="1")
            if choice.lower() == "q":
                break
            if choice == "1":
                live.update(render_dashboard())
            elif choice == "2":
                _render_deps(analysis.intelligence)
            elif choice == "3":
                _render_civilizations(analysis.intelligence)
            elif choice == "4":
                _render_debt(analysis.intelligence)
            else:
                render_notice("Unknown action.", style="yellow")


@export_app.command("json")
def export_json_cmd(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    destination = _export_report("json", path, output)
    console.print(f"Exported JSON report to {destination}")


@export_app.command("markdown")
def export_markdown_cmd(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    destination = _export_report("markdown", path, output)
    console.print(f"Exported Markdown report to {destination}")


@export_app.command("html")
def export_html_cmd(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    destination = _export_report("html", path, output)
    console.print(f"Exported HTML report to {destination}")


@report_app.command("json")
def report_json_cmd(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    destination = _export_report("json", path, output)
    console.print(f"Generated JSON report at {destination}")


@report_app.command("markdown")
def report_markdown_cmd(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    destination = _export_report("markdown", path, output)
    console.print(f"Generated Markdown report at {destination}")


@report_app.command("html")
def report_html_cmd(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    destination = _export_report("html", path, output)
    console.print(f"Generated HTML report at {destination}")


@report_app.command("pdf")
def report_pdf_cmd(
    path: Path = typer.Argument(Path("."), exists=True, file_okay=False, dir_okay=True, resolve_path=True),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file path."),
) -> None:
    destination = _export_report("pdf", path, output)
    console.print(f"Generated PDF report at {destination}")
