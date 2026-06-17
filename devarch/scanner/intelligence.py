from __future__ import annotations

import ast
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Iterable

from ..analyzers.ancient import find_ancient_files
from ..analyzers.dead_code import find_dead_code
from ..analyzers.duplicates import find_duplicates, similarity_report
from ..analyzers.health import calculate_health
from ..analyzers.monsters import find_monsters
from ..analyzers.ruins import find_empty_directories, find_unused_assets
from ..analyzers.suspicious import find_suspicious
from ..analyzers.todos import find_todos, todos_to_artifacts
from ..models import Artifact, ScanSummary
from ..utils.fs import RepoView, collect_repository, path_kind
from ..utils.git_info import GitSummary, collect_git_summary
from .discovery import build_reference_map, build_text_index


PY_IMPORT_RE = re.compile(r"^\s*from\s+([\w.]+)(?:\s+import|\s*$)|^\s*import\s+([\w.]+)", re.MULTILINE)
JS_IMPORT_RE = re.compile(r"""(?m)^\s*import\s+.*?\s+from\s+['"]([^'"]+)['"]|require\(['"]([^'"]+)['"]\)""")
RELATIVE_PREFIX_RE = re.compile(r"^(\.+)(.*)$")


@dataclass(slots=True)
class DependencyHub:
    path: Path
    referenced_by: int
    depends_on: int
    external_packages: list[str] = field(default_factory=list)
    dependency_risk: str = "Low"
    failure_impact: str = "Moderate"
    confidence: float = 0.0


@dataclass(slots=True)
class FamilyTree:
    name: str
    root: Path
    children: list[Path] = field(default_factory=list)
    parent_modules: list[Path] = field(default_factory=list)
    inherited_classes: list[str] = field(default_factory=list)
    major_chains: list[list[Path]] = field(default_factory=list)


@dataclass(slots=True)
class CivilizationCluster:
    name: str
    files: list[Path]
    referenced: int
    last_active_days: int
    status: str
    confidence: float


@dataclass(slots=True)
class HeatmapBucket:
    bucket: str
    score: float
    label: str
    files: int


@dataclass(slots=True)
class PersonalityProfile:
    type: str
    traits: list[str]
    risk: str


@dataclass(slots=True)
class ForecastProfile:
    current_health: int
    projected_6_months: int
    projected_12_months: int
    reason: str


@dataclass(slots=True)
class DNAProfile:
    signature: list[str]
    confidence: float


@dataclass(slots=True)
class TimelineEra:
    year: int
    title: str
    activity: int


@dataclass(slots=True)
class InvestigationIncident:
    incident: str
    date: str
    impact: str
    outcome: str
    risk: str
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StructuralWeakness:
    path: Path
    referenced_by: int
    failure_impact: str
    recovery_difficulty: str
    confidence: float


@dataclass(slots=True)
class EarthquakeSimulation:
    target: Path
    projected_damage: int
    subsystems_lost: int
    severity: str
    affected_files: list[Path] = field(default_factory=list)


@dataclass(slots=True)
class ArchitectureClassification:
    primary: str
    secondary: str
    confidence: float


@dataclass(slots=True)
class ContributorOwnership:
    area: str
    owner: str
    maintenance_owner: str
    abandoned_owner: str


@dataclass(slots=True)
class MutationEvent:
    project_type: str
    became: str
    date: str
    impact: str


@dataclass(slots=True)
class KnowledgeMap:
    core: list[str] = field(default_factory=list)
    dependency_graph: list[str] = field(default_factory=list)
    route_graph: list[str] = field(default_factory=list)
    service_graph: list[str] = field(default_factory=list)
    architecture_graph: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContainmentZone:
    location: str
    complexity: int
    spread_rate: str
    recommendation: str


@dataclass(slots=True)
class SurvivalProfile:
    score: int
    risk: str
    single_point_failure: str
    maintainability: int
    recoverability: int
    onboarding_difficulty: int
    bus_factor: int


@dataclass(slots=True)
class ForensicObservation:
    observation: str
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RepositoryIntelligence:
    root: Path
    view: RepoView
    text_cache: dict[Path, str]
    references: dict[Path, set[Path]]
    dependencies: dict[Path, set[Path]]
    reverse_dependencies: dict[Path, set[Path]]
    external_packages: Counter[str]
    dependency_hubs: list[DependencyHub]
    dependency_cycles: list[list[Path]]
    dependency_chains: list[list[Path]]
    genealogy: list[FamilyTree]
    civilizations: list[CivilizationCluster]
    debt_heatmap: list[HeatmapBucket]
    personality: PersonalityProfile
    forecast: ForecastProfile
    dna: DNAProfile
    timeline_eras: list[TimelineEra]
    ownership: dict[Path, str]
    file_last_active_days: dict[Path, int]
    artifact_confidence: dict[str, float]
    graph_node_count: int
    graph_edge_count: int
    incidents: list[InvestigationIncident] = field(default_factory=list)
    weaknesses: list[StructuralWeakness] = field(default_factory=list)
    quake_simulation: EarthquakeSimulation | None = None
    architecture: ArchitectureClassification | None = None
    contributors: list[ContributorOwnership] = field(default_factory=list)
    mutations: list[MutationEvent] = field(default_factory=list)
    knowledge_map: KnowledgeMap = field(default_factory=KnowledgeMap)
    containment_zones: list[ContainmentZone] = field(default_factory=list)
    survival: SurvivalProfile | None = None
    observations: list[ForensicObservation] = field(default_factory=list)


@dataclass(slots=True)
class RepositoryAnalysis:
    summary: ScanSummary
    intelligence: RepositoryIntelligence


def _git_run(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _python_module_key(root: Path, path: Path) -> str:
    return ".".join(path.relative_to(root).with_suffix("").parts)


def _package_keys(root: Path, path: Path) -> set[str]:
    key = _python_module_key(root, path)
    parts = key.split(".")
    keys = {key, key.replace(".", "/"), path.name, path.stem}
    for index in range(1, len(parts)):
        prefix = ".".join(parts[:index])
        keys.add(prefix)
        keys.add(prefix.replace(".", "/"))
    return {item for item in keys if item}


def _resolve_relative_module(source: Path, target: str, root: Path) -> str | None:
    match = RELATIVE_PREFIX_RE.match(target)
    if not match:
        return None
    dots, remainder = match.groups()
    package_parts = list(source.relative_to(root).parts[:-1])
    for _ in range(max(len(dots) - 1, 0)):
        if package_parts:
            package_parts.pop()
    if remainder:
        package_parts.extend([part for part in remainder.split(".") if part])
    return ".".join(package_parts)


def _extract_python_dependencies(path: Path, content: str, root: Path) -> tuple[set[str], set[str], dict[str, list[str]]]:
    internal: set[str] = set()
    external: set[str] = set()
    class_bases: dict[str, list[str]] = defaultdict(list)
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return internal, external, class_bases

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name
                if name:
                    internal.add(name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_name = "." * node.level + node.module if node.level else node.module
            else:
                module_name = "." * node.level
            if module_name.startswith("."):
                resolved = _resolve_relative_module(path, module_name, root)
                if resolved:
                    internal.add(resolved)
            elif module_name:
                internal.add(module_name)
        elif isinstance(node, ast.ClassDef):
            base_names: list[str] = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.append(base.id)
                elif isinstance(base, ast.Attribute):
                    parts = []
                    current = base
                    while isinstance(current, ast.Attribute):
                        parts.append(current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        parts.append(current.id)
                    base_names.append(".".join(reversed(parts)))
            if base_names:
                class_bases[node.name].extend(base_names)

    imported_modules = set()
    for item in internal:
        imported_modules.add(item.split(".")[0])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.name.split(".")[0]
                if name and name not in sys.stdlib_module_names:
                    external.add(name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top and top not in sys.stdlib_module_names and top not in imported_modules:
                    external.add(top)
    return internal, external, class_bases


def _extract_js_dependencies(content: str) -> tuple[set[str], set[str]]:
    internal: set[str] = set()
    external: set[str] = set()
    for match in JS_IMPORT_RE.finditer(content):
        target = match.group(1) or match.group(2)
        if not target:
            continue
        if target.startswith(".") or target.startswith("/"):
            internal.add(target)
        else:
            external.add(target.split("/")[0])
    return internal, external


def _build_module_index(view: RepoView) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in view.files:
        if path_kind(path) != "text":
            continue
        stem = path.stem
        rel = path.relative_to(view.root).with_suffix("")
        dotted = ".".join(rel.parts)
        slash = rel.as_posix()
        index[dotted] = path
        index[slash] = path
        index[stem] = path
        if path.name == "__init__.py":
            index[".".join(rel.parent.parts)] = path
            index[rel.parent.as_posix()] = path
    return index


def _resolve_target(source: Path, target: str, root: Path, module_index: dict[str, Path]) -> Path | None:
    raw = target.strip()
    if not raw:
        return None
    if raw.startswith("."):
        relative = _resolve_relative_module(source, raw, root)
        if relative:
            candidate = module_index.get(relative) or module_index.get(relative.replace(".", "/"))
            if candidate:
                return candidate
            for suffix in ("", ".py", ".js", ".ts", ".tsx", ".jsx", ".md"):
                possible = root / relative.replace(".", "/")
                if suffix and not str(possible).endswith(suffix):
                    possible = possible.with_suffix(suffix)
                if possible.exists():
                    return possible.resolve()
        return None
    cleaned = raw.split(" as ", 1)[0].strip()
    cleaned = cleaned.replace("/", ".")
    if cleaned in module_index:
        return module_index[cleaned]
    parts = cleaned.split(".")
    for index in range(len(parts), 0, -1):
        prefix = ".".join(parts[:index])
        if prefix in module_index:
            return module_index[prefix]
    for suffix in (".py", ".js", ".ts", ".tsx", ".jsx", ".md", "/__init__.py"):
        candidate = root / cleaned.replace(".", "/")
        if suffix == "/__init__.py":
            possible = candidate / "__init__.py"
        else:
            possible = candidate.with_suffix(suffix) if candidate.suffix == "" else candidate
        if possible.exists():
            return possible.resolve()
    return None


def _git_last_active_days(root: Path, path: Path, use_git: bool = True) -> int:
    raw = _git_run(root, "log", "-1", "--format=%ct", "--", str(path.relative_to(root))) if use_git else None
    if not raw:
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return 0
        return max((datetime.now(timezone.utc) - modified).days, 0)
    timestamp = int(raw.splitlines()[0])
    return max((datetime.now(timezone.utc) - datetime.fromtimestamp(timestamp, tz=timezone.utc)).days, 0)


def _git_last_author(root: Path, path: Path) -> str:
    raw = _git_run(root, "log", "-1", "--format=%an", "--", str(path.relative_to(root)))
    return raw or "unknown"


def _cycle_dfs(start: Path, graph: dict[Path, set[Path]]) -> list[list[Path]]:
    cycles: list[list[Path]] = []
    stack: list[Path] = []
    seen: set[Path] = set()

    def visit(node: Path) -> None:
        if node in stack:
            index = stack.index(node)
            cycle = stack[index:] + [node]
            if len(cycle) > 2:
                cycles.append(cycle)
            return
        if node in seen:
            return
        seen.add(node)
        stack.append(node)
        for child in graph.get(node, set()):
            visit(child)
        stack.pop()

    visit(start)
    return cycles


def _dependency_cycles(graph: dict[Path, set[Path]]) -> list[list[Path]]:
    cycles: list[list[Path]] = []
    for node in graph:
        cycles.extend(_cycle_dfs(node, graph))
    deduped: list[list[Path]] = []
    seen: set[tuple[str, ...]] = set()
    for cycle in cycles:
        names = tuple(str(path) for path in cycle)
        signature = tuple(sorted(names))
        if signature not in seen:
            seen.add(signature)
            deduped.append(cycle)
    return deduped


def _reachable_count(start: Path, graph: dict[Path, set[Path]]) -> int:
    visited: set[Path] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for child in graph.get(node, set()):
            if child not in visited and child != start:
                visited.add(child)
                stack.append(child)
    return len(visited)


def _longest_chain(start: Path, graph: dict[Path, set[Path]], limit: int = 8) -> list[Path]:
    best: list[Path] = [start]

    def visit(node: Path, chain: list[Path], seen: set[Path]) -> None:
        nonlocal best
        if len(chain) > len(best):
            best = chain[:]
        if len(chain) >= limit:
            return
        for child in graph.get(node, set()):
            if child in seen:
                continue
            visit(child, chain + [child], seen | {child})

    visit(start, [start], {start})
    return best


def _cluster_name(paths: list[Path]) -> str:
    lowered = " ".join(path.name.lower() for path in paths)
    if "auth" in lowered:
        return "Legacy Authentication System"
    if "payment" in lowered or "billing" in lowered:
        return "Abandoned Payment Flow"
    if "admin" in lowered:
        return "Forgotten Admin Panel"
    if "api" in lowered or "v1" in lowered or "v2" in lowered:
        return "Legacy API Version"
    return "Lost Subsystem"


def _group_by_top_level(paths: Iterable[Path], root: Path) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for path in paths:
        rel = path.relative_to(root)
        group = rel.parts[0] if rel.parts else rel.parent.name
        groups[group].append(path)
    return groups


def _repository_dna(view: RepoView, text_cache: dict[Path, str], health_score: int) -> DNAProfile:
    signature: list[str] = []
    joined = "\n".join(text_cache.values()).lower()
    names = " ".join(path.name.lower() for path in view.files)
    if "fastapi" in joined or "fastapi" in names:
        signature.append("FASTAPI")
    if "django" in joined or "django" in names:
        signature.append("DJANGO")
    if "flask" in joined or "flask" in names:
        signature.append("FLASK")
    if "postgres" in joined or "psycopg" in joined or "sqlalchemy" in joined:
        signature.append("POSTGRES")
    if any(path.suffix.lower() in {".ts", ".tsx"} for path in view.files):
        signature.append("TYPESCRIPT")
    if any(path.suffix.lower() == ".py" for path in view.files):
        signature.append("PYTHON")
    if any("test" in path.parts for path in view.files):
        signature.append("TEST_HEAVY")
    if any(path.suffix.lower() in {".md", ".rst"} for path in view.files):
        signature.append("DOCUMENTED")
    if len(view.files) < 20:
        signature.append("COMPACT")
    else:
        signature.append("MODULAR" if len({path.parent for path in view.files}) > 6 else "MONOLITHIC")
    signature.append("HIGH_MAINTAINABILITY" if health_score >= 80 else "MEDIUM_MAINTAINABILITY" if health_score >= 60 else "LOW_MAINTAINABILITY")
    signature.append("LOW_COMPLEXITY" if health_score >= 85 else "MEDIUM_COMPLEXITY" if health_score >= 60 else "HIGH_COMPLEXITY")
    confidence = min(0.99, 0.65 + (health_score / 300))
    return DNAProfile(signature=signature, confidence=round(confidence, 2))


def _architecture_classification(view: RepoView, intelligence: "RepositoryIntelligence | None" = None) -> ArchitectureClassification:
    top_level = {path.relative_to(view.root).parts[0] for path in view.files if path.relative_to(view.root).parts}
    joined = " ".join(sorted(top_level)).lower()
    if any(token in joined for token in ("service", "worker", "queue")):
        primary = "Service Oriented"
    elif any(token in joined for token in ("controller", "view", "model", "route", "api")):
        primary = "Layered Monolith"
    elif len(top_level) >= 8 and sum(1 for path in view.files if path.suffix.lower() in {".py", ".ts", ".tsx"}) > 20:
        primary = "Modular Monolith"
    else:
        primary = "Prototype"

    if intelligence and intelligence.dependency_cycles:
        secondary = "Event Driven"
    elif any(path.name.startswith("test_") for path in view.files):
        secondary = "Domain Driven Design"
    elif any("service" in part.lower() for part in top_level):
        secondary = "Service Oriented"
    else:
        secondary = "Layered"
    confidence = 0.82 if primary != "Prototype" else 0.68
    return ArchitectureClassification(primary=primary, secondary=secondary, confidence=confidence)


def _contributors(root: Path, ownership: dict[Path, str], dependencies: dict[Path, set[Path]]) -> list[ContributorOwnership]:
    by_area: dict[str, Counter[str]] = defaultdict(Counter)
    for path, owner in ownership.items():
        area = path.relative_to(root).parts[0] if path.relative_to(root).parts else path.stem
        by_area[area][owner] += 1
    contributors: list[ContributorOwnership] = []
    for area, counts in sorted(by_area.items()):
        owner, _ = counts.most_common(1)[0]
        maintenance_owner = owner if owner != "unknown" else "unknown"
        abandoned_owner = "unknown" if counts.get("unknown", 0) else owner
        contributors.append(
            ContributorOwnership(
                area=area,
                owner=owner,
                maintenance_owner=maintenance_owner,
                abandoned_owner=abandoned_owner,
            )
        )
    return contributors


def _mutations(root: Path, view: RepoView, git_summary: GitSummary) -> list[MutationEvent]:
    if not git_summary.available:
        heuristics: list[MutationEvent] = []
        names = " ".join(path.name.lower() for path in view.files)
        if "legacy" in names or "migration" in names:
            heuristics.append(
                MutationEvent(
                    project_type="CLI",
                    became="Hybrid / Transitional System",
                    date=datetime.now(timezone.utc).strftime("%Y-%m"),
                    impact="Medium",
                )
            )
        return heuristics

    raw = _git_run(root, "log", "--reverse", "--format=%ad", "--date=format:%Y-%m", "--name-only")
    if not raw:
        return []
    wave_counts: Counter[str] = Counter()
    for line in raw.splitlines():
        if re.match(r"^\d{4}-\d{2}$", line.strip()):
            wave_counts[line.strip()] += 1
    if not wave_counts:
        return []
    year_month, count = wave_counts.most_common(1)[0]
    impact = "High" if count >= 20 else "Medium"
    return [
        MutationEvent(
            project_type="CLI",
            became="Web Platform" if count >= 20 else "Growing Platform",
            date=year_month,
            impact=impact,
        )
    ]


def _knowledge_map(view: RepoView, dependency_hubs: list[DependencyHub], architecture: ArchitectureClassification) -> KnowledgeMap:
    core = sorted({path.relative_to(view.root).parts[0] for path in view.files if path.relative_to(view.root).parts})[:8]
    dep_graph = [f"{hub.path.name} -> {hub.depends_on} deps" for hub in dependency_hubs[:10]]
    route_graph = [f"{path.name}" for path in view.files if "route" in path.name.lower() or "api" in path.name.lower()]
    service_graph = [f"{path.name}" for path in view.files if "service" in path.name.lower() or "worker" in path.name.lower()]
    architecture_graph = [f"{architecture.primary} -> {architecture.secondary}"]
    return KnowledgeMap(
        core=core,
        dependency_graph=dep_graph,
        route_graph=route_graph,
        service_graph=service_graph,
        architecture_graph=architecture_graph,
    )


def _containment_zones(view: RepoView, text_cache: dict[Path, str], dependencies: dict[Path, set[Path]], reverse_dependencies: dict[Path, set[Path]], artifacts: list[Artifact]) -> list[ContainmentZone]:
    zones: list[ContainmentZone] = []
    grouped = _group_by_top_level(view.files, view.root)
    monster_paths = {artifact.path for artifact in artifacts if artifact.kind == "monster_file"}
    duplicate_paths = {artifact.path for artifact in artifacts if artifact.kind == "duplicate_block"}
    for location, paths in grouped.items():
        complexity = 0
        complexity += sum(text_cache.get(path, "").count("if ") + text_cache.get(path, "").count("for ") + text_cache.get(path, "").count("while ") for path in paths)
        complexity += sum(len(dependencies.get(path, set())) + len(reverse_dependencies.get(path, set())) for path in paths)
        complexity += sum(2 for path in paths if path in monster_paths)
        complexity += sum(1 for path in paths if path in duplicate_paths)
        if complexity == 0:
            continue
        if complexity >= 40:
            spread = "Increasing"
            rec = "Immediate Refactor"
        elif complexity >= 20:
            spread = "Moderate"
            rec = "Contain and simplify"
        else:
            spread = "Stable"
            rec = "Monitor"
        zones.append(
            ContainmentZone(
                location=location,
                complexity=min(100, complexity),
                spread_rate=spread,
                recommendation=rec,
            )
        )
    return sorted(zones, key=lambda item: item.complexity, reverse=True)


def _survival_score(summary: ScanSummary, intelligence: "RepositoryIntelligence", contributors: list[ContributorOwnership]) -> SurvivalProfile:
    maintainability = max(0, min(100, summary.health_score))
    recoverability = max(0, min(100, 100 - len(intelligence.dependency_cycles) * 8 - len(intelligence.civilizations) * 6 - len(intelligence.weaknesses) * 4))
    onboarding = max(0, min(100, len(intelligence.weaknesses) * 10 + len(intelligence.dependency_hubs) * 2 + (100 - summary.health_score) // 2))
    bus_factor = max(1, min(5, len({item.owner for item in contributors if item.owner != "unknown"})))
    score = round((maintainability * 0.4 + recoverability * 0.25 + (100 - onboarding) * 0.2 + bus_factor * 5 * 0.15))
    if score >= 80:
        risk = "Low"
    elif score >= 60:
        risk = "Moderate"
    elif score >= 40:
        risk = "High"
    else:
        risk = "Critical"
    single_point = intelligence.weaknesses[0].path.name if intelligence.weaknesses else (intelligence.dependency_hubs[0].path.name if intelligence.dependency_hubs else "Unknown")
    return SurvivalProfile(
        score=score,
        risk=risk,
        single_point_failure=single_point,
        maintainability=maintainability,
        recoverability=recoverability,
        onboarding_difficulty=onboarding,
        bus_factor=bus_factor,
    )


def _observations(
    intelligence: "RepositoryIntelligence",
    architecture: ArchitectureClassification,
    investigations: list[InvestigationIncident],
    weaknesses: list[StructuralWeakness],
    civilizations: list[CivilizationCluster],
) -> list[ForensicObservation]:
    notes: list[ForensicObservation] = []
    if civilizations:
        notes.append(
            ForensicObservation(
                observation=f"The repository contains {len(civilizations)} partially abandoned system cluster(s).",
                evidence=[civ.name for civ in civilizations[:3]],
            )
        )
    if weaknesses:
        notes.append(
            ForensicObservation(
                observation=f"{len(weaknesses)} structural bottleneck(s) concentrate failure risk in a few modules.",
                evidence=[str(item.path) for item in weaknesses[:3]],
            )
        )
    if investigations:
        notes.append(
            ForensicObservation(
                observation="Evidence suggests a migration or refactor has occurred without fully retiring the old path.",
                evidence=[incident.incident for incident in investigations[:2]],
            )
        )
    notes.append(
        ForensicObservation(
            observation=f"The repository most closely resembles a {architecture.primary.lower()}.",
            evidence=[architecture.secondary, f"confidence={architecture.confidence:.0%}"],
        )
    )
    if intelligence.dependency_cycles:
        notes.append(
            ForensicObservation(
                observation="Cyclic dependencies indicate architectural pressure and constrained change paths.",
                evidence=[f"cycles={len(intelligence.dependency_cycles)}"],
            )
        )
    return notes


def _classify_personality(
    *,
    health_score: int,
    commit_count: int,
    file_count: int,
    monster_count: int,
    duplicate_count: int,
    ancient_count: int,
    dependency_cycles: int,
    external_packages: int,
) -> PersonalityProfile:
    if file_count <= 15 and commit_count < 20:
        return PersonalityProfile(type="Prototype", traits=["Small surface area", "Fast-moving changes", "Minimal bureaucracy"], risk="Volatile")
    if ancient_count and dependency_cycles and monster_count:
        return PersonalityProfile(type="Fortress", traits=["Defensive layers", "Legacy defenses", "High inertia"], risk="Accumulated complexity")
    if external_packages > 20 and file_count > 50 and health_score >= 70:
        return PersonalityProfile(type="Enterprise", traits=["Structured layering", "Many integrations", "Policy driven"], risk="Integration drag")
    if monster_count > 0 and duplicate_count > 0 and health_score < 75:
        return PersonalityProfile(type="Startup", traits=["Rapid experimentation", "High feature growth", "Moderate organization"], risk="Accumulating technical debt")
    if commit_count > 100 and file_count > 80 and health_score >= 75:
        return PersonalityProfile(type="Scientist", traits=["Iterative exploration", "Measured evolution", "Strong evidence trail"], risk="Analysis overhead")
    if file_count > 50 and dependency_cycles == 0 and external_packages < 12:
        return PersonalityProfile(type="Architect", traits=["Clear boundaries", "Intentional structure", "Stable modules"], risk="Rigid change paths")
    if commit_count > 60 and file_count > 40:
        return PersonalityProfile(type="Explorer", traits=["Rapid experimentation", "High feature growth", "Moderate organization"], risk="Moderate technical debt")
    return PersonalityProfile(type="Research Lab", traits=["Experimental paths", "Multiple branches of thought", "Evolving structure"], risk="Discovery overhead")


def _forecast(health_score: int, dependency_cycles: int, monster_count: int, duplicate_count: int, ancient_count: int) -> ForecastProfile:
    drift = dependency_cycles * 3 + monster_count * 4 + duplicate_count * 2 + ancient_count
    projected_6 = max(0, min(100, health_score - drift - 4))
    projected_12 = max(0, min(100, health_score - drift - 10))
    if drift:
        reason = "Increasing dependency growth and structural debt"
    else:
        reason = "Stable graph and limited debt signals"
    return ForecastProfile(
        current_health=health_score,
        projected_6_months=projected_6,
        projected_12_months=projected_12,
        reason=reason,
    )


def _timeline_eras(root: Path) -> list[TimelineEra]:
    raw = _git_run(root, "log", "--reverse", "--format=%ad", "--date=format:%Y")
    if not raw:
        return []
    counts: Counter[int] = Counter()
    for line in raw.splitlines():
        if line.strip().isdigit():
            counts[int(line.strip())] += 1
    if not counts:
        return []
    eras: list[TimelineEra] = []
    for year, activity in sorted(counts.items()):
        if activity <= 4:
            title = "Foundation Era"
        elif activity <= 15:
            title = "Expansion Era"
        elif activity <= 30:
            title = "Growth Era"
        else:
            title = "Feature Explosion Era"
        eras.append(TimelineEra(year=year, title=title, activity=activity))
    if len(eras) >= 2 and eras[-1].activity <= 6:
        eras[-1].title = "Maintenance Era"
    return eras


def _dependency_heatmap(
    view: RepoView,
    text_cache: dict[Path, str],
    dependencies: dict[Path, set[Path]],
    reverse_dependencies: dict[Path, set[Path]],
    artifacts: list[Artifact],
) -> list[HeatmapBucket]:
    groups = _group_by_top_level(view.files, view.root)
    by_path_artifacts = defaultdict(list)
    for artifact in artifacts:
        by_path_artifacts[artifact.path].append(artifact)

    buckets: list[HeatmapBucket] = []
    for group, paths in groups.items():
        todo_density = sum(text_cache.get(path, "").count("TODO") + text_cache.get(path, "").count("FIXME") for path in paths)
        monster_weight = sum(1 for path in paths for artifact in by_path_artifacts.get(path, []) if artifact.kind == "monster_file")
        ancient_weight = sum(1 for path in paths for artifact in by_path_artifacts.get(path, []) if artifact.kind == "ancient_file")
        duplicate_weight = sum(1 for path in paths for artifact in by_path_artifacts.get(path, []) if artifact.kind == "duplicate_block")
        incoming = sum(len(reverse_dependencies.get(path, set())) for path in paths)
        outgoing = sum(len(dependencies.get(path, set())) for path in paths)
        score = todo_density * 0.7 + monster_weight * 3 + ancient_weight * 2 + duplicate_weight * 2 + incoming * 0.4 + outgoing * 0.25
        if score >= 20:
            label = "Severe"
        elif score >= 12:
            label = "High"
        elif score >= 6:
            label = "Moderate"
        else:
            label = "Light"
        buckets.append(HeatmapBucket(bucket=group, score=round(score, 1), label=label, files=len(paths)))
    return sorted(buckets, key=lambda item: item.score, reverse=True)


def _family_trees(
    view: RepoView,
    root: Path,
    reverse_dependencies: dict[Path, set[Path]],
    dependencies: dict[Path, set[Path]],
    class_bases: dict[Path, dict[str, list[str]]],
) -> list[FamilyTree]:
    trees: list[FamilyTree] = []
    grouped = _group_by_top_level(view.files, root)
    for group, paths in grouped.items():
        if len(paths) < 2:
            continue
        ordered = sorted(paths, key=lambda path: (len(reverse_dependencies.get(path, set())), len(dependencies.get(path, set()))), reverse=True)
        main = ordered[0]
        inherited: list[str] = []
        for mapping in class_bases.values():
            for class_name, bases in mapping.items():
                for base in bases:
                    inherited.append(f"{class_name} -> {base}")
        trees.append(
            FamilyTree(
                name=f"{group.title()} Family",
                root=main,
                children=ordered[1:5],
                parent_modules=sorted(list(reverse_dependencies.get(main, set())), key=lambda p: str(p))[:5],
                inherited_classes=inherited[:10],
                major_chains=[],
            )
        )
    return trees


def _civilizations(
    view: RepoView,
    root: Path,
    reverse_dependencies: dict[Path, set[Path]],
    file_last_active_days: dict[Path, int],
) -> list[CivilizationCluster]:
    clusters: list[CivilizationCluster] = []
    grouped = _group_by_top_level(view.files, root)
    for group, paths in grouped.items():
        referenced = sum(1 for path in paths if reverse_dependencies.get(path))
        last_active = max((file_last_active_days.get(path, 0) for path in paths), default=0)
        if len(paths) < 3 or last_active < 120:
            continue
        extinct = referenced == 0 and last_active >= 365
        dormant = referenced <= max(1, len(paths) // 4) and last_active >= 180
        if not (extinct or dormant):
            continue
        name = _cluster_name(paths)
        status = "Extinct" if extinct else "Dormant"
        confidence = 0.88 if extinct else 0.76
        clusters.append(
            CivilizationCluster(
                name=name,
                files=sorted(paths),
                referenced=referenced,
                last_active_days=last_active,
                status=status,
                confidence=confidence,
            )
        )
    return sorted(clusters, key=lambda item: (item.last_active_days, item.referenced), reverse=True)


def _dependency_hubs(
    view: RepoView,
    dependencies: dict[Path, set[Path]],
    reverse_dependencies: dict[Path, set[Path]],
    external_packages: dict[Path, set[str]],
) -> list[DependencyHub]:
    hubs: list[DependencyHub] = []
    for path in view.files:
        if path_kind(path) == "binary":
            continue
        referenced_by = len(reverse_dependencies.get(path, set()))
        depends_on = len(dependencies.get(path, set()))
        ext = sorted(external_packages.get(path, set()))
        if referenced_by >= 5 or depends_on >= 8 or ext:
            impact = "Critical" if referenced_by >= 20 or depends_on >= 15 else "High" if referenced_by >= 8 or depends_on >= 10 else "Moderate"
            risk = "High" if referenced_by >= 10 or depends_on >= 10 else "Medium"
            hubs.append(
                DependencyHub(
                    path=path,
                    referenced_by=referenced_by,
                    depends_on=depends_on,
                    external_packages=ext[:8],
                    dependency_risk=risk,
                    failure_impact=impact,
                    confidence=min(0.99, 0.6 + referenced_by * 0.015 + depends_on * 0.01),
                )
            )
    return sorted(hubs, key=lambda item: (item.referenced_by, item.depends_on), reverse=True)


def _dependency_chains(dependencies: dict[Path, set[Path]], hubs: list[DependencyHub]) -> list[list[Path]]:
    chains: list[list[Path]] = []
    for hub in hubs[:10]:
        chain = _longest_chain(hub.path, dependencies)
        if len(chain) > 1:
            chains.append(chain)
    return chains


def _structural_weaknesses(view: RepoView, dependencies: dict[Path, set[Path]], reverse_dependencies: dict[Path, set[Path]], dependency_hubs: list[DependencyHub]) -> list[StructuralWeakness]:
    weaknesses: list[StructuralWeakness] = []
    for hub in dependency_hubs[:12]:
        if hub.referenced_by >= 8 and (hub.depends_on <= 2 or not dependencies.get(hub.path)):
            difficulty = "High" if hub.depends_on > 0 else "Medium"
            impact = "Severe" if hub.referenced_by >= 20 else "High"
            weaknesses.append(
                StructuralWeakness(
                    path=hub.path,
                    referenced_by=hub.referenced_by,
                    failure_impact=impact,
                    recovery_difficulty=difficulty,
                    confidence=min(0.99, hub.confidence + 0.1),
                )
            )

    for path, dependents in sorted(reverse_dependencies.items(), key=lambda item: len(item[1]), reverse=True):
        if len(dependents) >= 25 and path not in {weak.path for weak in weaknesses}:
            weaknesses.append(
                StructuralWeakness(
                    path=path,
                    referenced_by=len(dependents),
                    failure_impact="Severe" if len(dependents) >= 50 else "High",
                    recovery_difficulty="High",
                    confidence=0.9,
                )
            )
    return weaknesses[:10]


def _quake_simulation(
    view: RepoView,
    dependencies: dict[Path, set[Path]],
    reverse_dependencies: dict[Path, set[Path]],
    target: str | None = None,
) -> EarthquakeSimulation | None:
    module_index = _build_module_index(view)
    selected: Path | None = None
    if target:
        selected = module_index.get(target) or module_index.get(target.replace("/", "."))
        if not selected:
            for path in view.files:
                if path.name == target or str(path).endswith(target):
                    selected = path
                    break
    if selected is None:
        if reverse_dependencies:
            selected = max(reverse_dependencies.items(), key=lambda item: len(item[1]))[0]
        elif dependencies:
            selected = max(dependencies.items(), key=lambda item: len(item[1]))[0]
        else:
            return None

    affected: set[Path] = set()
    stack = [selected]
    while stack:
        node = stack.pop()
        for child in reverse_dependencies.get(node, set()):
            if child not in affected:
                affected.add(child)
                stack.append(child)

    subsystem_count = len({path.relative_to(view.root).parts[0] for path in affected if path.relative_to(view.root).parts})
    severity = "Catastrophic" if len(affected) >= 25 else "Severe" if len(affected) >= 10 else "High" if len(affected) >= 4 else "Moderate"
    return EarthquakeSimulation(
        target=selected,
        projected_damage=len(affected),
        subsystems_lost=subsystem_count,
        severity=severity,
        affected_files=sorted(affected)[:30],
    )


def _investigation_incidents(
    view: RepoView,
    text_cache: dict[Path, str],
    dependencies: dict[Path, set[Path]],
    reverse_dependencies: dict[Path, set[Path]],
    git_summary: GitSummary,
) -> list[InvestigationIncident]:
    evidence: list[str] = []
    dangerous_patterns = {
        "eval(": "unsafe dynamic evaluation",
        "exec(": "runtime code execution",
        "pickle.load": "unsafe deserialization",
        "yaml.load": "unsafe YAML loading",
        "shell=True": "shell injection surface",
        "os.system(": "shell execution",
        "subprocess.Popen": "process spawning",
    }
    for path, content in text_cache.items():
        for needle, description in dangerous_patterns.items():
            if needle in content:
                evidence.append(f"{path.name}: {description}")
    file_explosion = sorted(
        (
            (group, len(paths))
            for group, paths in _group_by_top_level(view.files, view.root).items()
            if len(paths) >= 8
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    if file_explosion:
        evidence.append(f"File explosion in {file_explosion[0][0]} ({file_explosion[0][1]} files)")
    migration_names = [path for path in view.files if any(token in path.name.lower() for token in ("migration", "refactor", "legacy", "v2", "v3"))]
    if migration_names:
        evidence.append(f"{len(migration_names)} migration/refactor-era files detected")

    if not evidence:
        return [
            InvestigationIncident(
                incident="Repository Baseline",
                date=git_summary.last_commit.date().isoformat() if git_summary.last_commit else datetime.now(timezone.utc).date().isoformat(),
                impact=f"{len(view.files)} files scanned",
                outcome="No obvious incident cluster detected",
                risk="Low",
                evidence=["No dangerous patterns observed in source files"],
            )
        ]

    if git_summary.available and git_summary.last_commit:
        incident_date = git_summary.last_commit.date().isoformat()
    else:
        incident_date = datetime.now(timezone.utc).date().isoformat()

    impact = f"{max(1, len(evidence))} indicators found"
    if migration_names and file_explosion:
        outcome = "Legacy system partially abandoned"
        risk = "High"
        incident = "Authentication Refactor" if any("auth" in path.name.lower() for path in migration_names) else "Structural Migration"
    elif evidence:
        outcome = "Suspicious architectural change patterns detected"
        risk = "Medium"
        incident = "Incident Cluster"
    else:
        outcome = "Repository appears stable"
        risk = "Low"
        incident = "Baseline"
    return [
        InvestigationIncident(
            incident=incident,
            date=incident_date,
            impact=impact,
            outcome=outcome,
            risk=risk,
            evidence=evidence[:8],
        )
    ]


def build_repository_intelligence(
    root: Path,
    *,
    view: RepoView | None = None,
    text_cache: dict[Path, str] | None = None,
    artifacts: list[Artifact] | None = None,
    health_score: int | None = None,
    git_summary: GitSummary | None = None,
) -> RepositoryIntelligence:
    view = view or collect_repository(root)
    text_cache = text_cache or build_text_index(view)
    references = build_reference_map(view, text_cache)
    git_summary = git_summary or collect_git_summary(root)

    module_index = _build_module_index(view)
    dependencies: dict[Path, set[Path]] = defaultdict(set)
    reverse_dependencies: dict[Path, set[Path]] = defaultdict(set)
    external_packages: dict[Path, set[str]] = defaultdict(set)
    ownership: dict[Path, str] = {}
    file_last_active_days: dict[Path, int] = {}
    class_bases_by_path: dict[Path, dict[str, list[str]]] = {}

    for path in view.files:
        if path_kind(path) != "text":
            continue
        content = text_cache.get(path, "")
        if path.suffix.lower() == ".py":
            internal, external, class_bases = _extract_python_dependencies(path, content, root)
            class_bases_by_path[path] = class_bases
            for dep in internal:
                resolved = _resolve_target(path, dep, root, module_index)
                if resolved and resolved != path:
                    dependencies[path].add(resolved)
                    reverse_dependencies[resolved].add(path)
            external_packages[path].update(external)
        elif path.suffix.lower() in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
            internal, external = _extract_js_dependencies(content)
            for dep in internal:
                resolved = _resolve_target(path, dep, root, module_index)
                if resolved and resolved != path:
                    dependencies[path].add(resolved)
                    reverse_dependencies[resolved].add(path)
            external_packages[path].update(external)
        else:
            for match in PY_IMPORT_RE.finditer(content):
                target = match.group(1) or match.group(2)
                if not target:
                    continue
                resolved = _resolve_target(path, target, root, module_index)
                if resolved and resolved != path:
                    dependencies[path].add(resolved)
                    reverse_dependencies[resolved].add(path)

        if git_summary.available:
            ownership[path] = _git_last_author(root, path)
            file_last_active_days[path] = _git_last_active_days(root, path, use_git=True)
        else:
            ownership[path] = "unknown"
            file_last_active_days[path] = _git_last_active_days(root, path, use_git=False)

    all_artifacts = artifacts or []
    if not all_artifacts:
        todos = find_todos(view.files)
        todo_artifacts = todos_to_artifacts(todos)
        ancient = find_ancient_files(view.files, build_reference_map(view, text_cache))
        dead_code = find_dead_code(view.root, view.files, text_cache)
        duplicates = find_duplicates(view.files, text_cache)
        monsters = find_monsters(view.files)
        ruins = find_empty_directories(view.directories, view.files) + find_unused_assets(view.files, text_cache)
        suspicious = find_suspicious(view.files)
        all_artifacts = [*todo_artifacts, *ancient, *dead_code, *duplicates, *monsters, *ruins, *suspicious]

    artifact_confidence = {
        "dead_code": round(sum(item.confidence or 0 for item in all_artifacts if item.kind in {"dead_code_candidate", "unreachable_code"}) / max(1, sum(1 for item in all_artifacts if item.kind in {"dead_code_candidate", "unreachable_code"})), 2),
        "ancient_file": round(sum(item.confidence or 0 for item in all_artifacts if item.kind == "ancient_file") / max(1, sum(1 for item in all_artifacts if item.kind == "ancient_file")), 2),
        "duplicate_block": round(sum(item.confidence or 0 for item in all_artifacts if item.kind == "duplicate_block") / max(1, sum(1 for item in all_artifacts if item.kind == "duplicate_block")), 2),
    }

    health_score = health_score if health_score is not None else 0
    dependency_hubs = _dependency_hubs(view, dependencies, reverse_dependencies, external_packages)
    dependency_cycles = _dependency_cycles(dependencies)
    dependency_chains = _dependency_chains(dependencies, dependency_hubs)
    genealogy = _family_trees(view, root, reverse_dependencies, dependencies, class_bases_by_path)
    civilizations = _civilizations(view, root, reverse_dependencies, file_last_active_days)
    debt_heatmap = _dependency_heatmap(view, text_cache, dependencies, reverse_dependencies, all_artifacts)
    weaknesses = _structural_weaknesses(view, dependencies, reverse_dependencies, dependency_hubs)
    architecture = _architecture_classification(view)
    personality = _classify_personality(
        health_score=health_score,
        commit_count=git_summary.commit_count,
        file_count=len(view.files),
        monster_count=sum(1 for artifact in all_artifacts if artifact.kind == "monster_file"),
        duplicate_count=sum(1 for artifact in all_artifacts if artifact.kind == "duplicate_block"),
        ancient_count=sum(1 for artifact in all_artifacts if artifact.kind == "ancient_file"),
        dependency_cycles=len(dependency_cycles),
        external_packages=sum(len(values) for values in external_packages.values()),
    )
    forecast = _forecast(
        health_score=health_score,
        dependency_cycles=len(dependency_cycles),
        monster_count=sum(1 for artifact in all_artifacts if artifact.kind == "monster_file"),
        duplicate_count=sum(1 for artifact in all_artifacts if artifact.kind == "duplicate_block"),
        ancient_count=sum(1 for artifact in all_artifacts if artifact.kind == "ancient_file"),
    )
    dna = _repository_dna(view, text_cache, health_score)
    timeline_eras = _timeline_eras(root)
    graph_node_count = len(view.files)
    graph_edge_count = sum(len(values) for values in dependencies.values())
    contributors = _contributors(root, ownership, dependencies)
    quake_simulation = _quake_simulation(view, dependencies, reverse_dependencies)
    mutations = _mutations(root, view, git_summary)
    survival = _survival_score(
        ScanSummary(
            root=root,
            scanned_at=datetime.now(timezone.utc),
            total_files=len(view.files),
            artifact_count=len(all_artifacts),
            ancient_count=sum(1 for item in all_artifacts if item.kind == "ancient_file"),
            todo_count=sum(1 for item in all_artifacts if item.kind == "todo"),
            duplicate_count=sum(1 for item in all_artifacts if item.kind == "duplicate_block"),
            dead_code_count=sum(1 for item in all_artifacts if item.kind in {"dead_code_candidate", "unreachable_code"}),
            monster_count=sum(1 for item in all_artifacts if item.kind == "monster_file"),
            ruin_count=sum(1 for item in all_artifacts if item.kind in {"empty_directory", "unused_asset"}),
            suspicious_count=sum(1 for item in all_artifacts if item.kind == "suspicious"),
            technical_debt_estimate=0.0,
            health_score=health_score,
            health_status="",
        ),
        intelligence=RepositoryIntelligence(
            root=root,
            view=view,
            text_cache=text_cache,
            references=references,
            dependencies=dependencies,
            reverse_dependencies=reverse_dependencies,
            external_packages=Counter(),
            dependency_hubs=dependency_hubs,
            dependency_cycles=dependency_cycles,
            dependency_chains=dependency_chains,
            genealogy=genealogy,
            civilizations=civilizations,
            debt_heatmap=debt_heatmap,
            personality=personality,
            forecast=forecast,
            dna=dna,
            timeline_eras=timeline_eras,
            ownership=ownership,
            file_last_active_days=file_last_active_days,
            artifact_confidence=artifact_confidence,
            graph_node_count=graph_node_count,
            graph_edge_count=graph_edge_count,
            weaknesses=weaknesses,
            architecture=architecture,
        ),
        contributors=contributors,
    )
    knowledge_map = _knowledge_map(view, dependency_hubs, architecture)
    investigations = _investigation_incidents(view, text_cache, dependencies, reverse_dependencies, git_summary)
    observations = _observations(
        RepositoryIntelligence(
            root=root,
            view=view,
            text_cache=text_cache,
            references=references,
            dependencies=dependencies,
            reverse_dependencies=reverse_dependencies,
            external_packages=Counter(),
            dependency_hubs=dependency_hubs,
            dependency_cycles=dependency_cycles,
            dependency_chains=dependency_chains,
            genealogy=genealogy,
            civilizations=civilizations,
            debt_heatmap=debt_heatmap,
            personality=personality,
            forecast=forecast,
            dna=dna,
            timeline_eras=timeline_eras,
            ownership=ownership,
            file_last_active_days=file_last_active_days,
            artifact_confidence=artifact_confidence,
            graph_node_count=graph_node_count,
            graph_edge_count=graph_edge_count,
            weaknesses=weaknesses,
            architecture=architecture,
            contributors=contributors,
            survival=survival,
        ),
        architecture,
        investigations,
        weaknesses,
        civilizations,
    )

    external_package_counts = Counter()
    for packages in external_packages.values():
        external_package_counts.update(packages)

    return RepositoryIntelligence(
        root=root,
        view=view,
        text_cache=text_cache,
        references=references,
        dependencies=dependencies,
        reverse_dependencies=reverse_dependencies,
        external_packages=external_package_counts,
        dependency_hubs=dependency_hubs,
        dependency_cycles=dependency_cycles,
        dependency_chains=dependency_chains,
        genealogy=genealogy,
        civilizations=civilizations,
        debt_heatmap=debt_heatmap,
        personality=personality,
        forecast=forecast,
        dna=dna,
        timeline_eras=timeline_eras,
        ownership=ownership,
        file_last_active_days=file_last_active_days,
        artifact_confidence=artifact_confidence,
        graph_node_count=graph_node_count,
        graph_edge_count=graph_edge_count,
        incidents=investigations,
        weaknesses=weaknesses,
        quake_simulation=quake_simulation,
        architecture=architecture,
        contributors=contributors,
        mutations=mutations,
        knowledge_map=knowledge_map,
        containment_zones=_containment_zones(view, text_cache, dependencies, reverse_dependencies, all_artifacts),
        survival=survival,
        observations=observations,
    )


def analyze_repository(root: Path) -> RepositoryAnalysis:
    view = collect_repository(root)
    text_cache = build_text_index(view)
    references = build_reference_map(view, text_cache)

    todos = find_todos(view.files)
    todo_artifacts = todos_to_artifacts(todos)
    ancient = find_ancient_files(view.files, references)
    dead_code = find_dead_code(view.root, view.files, text_cache)
    duplicates = find_duplicates(view.files, text_cache)
    monsters = find_monsters(view.files)
    ruins = find_empty_directories(view.directories, view.files) + find_unused_assets(view.files, text_cache)
    suspicious = find_suspicious(view.files)

    artifacts: list[Artifact] = []
    artifacts.extend(todo_artifacts)
    artifacts.extend(ancient)
    artifacts.extend(dead_code)
    artifacts.extend(duplicates)
    artifacts.extend(monsters)
    artifacts.extend(ruins)
    artifacts.extend(suspicious)

    health = calculate_health(
        total_files=len(view.files),
        dead_code_count=len(dead_code),
        duplicate_count=len(duplicates),
        ancient_count=len(ancient),
        todo_count=len(todo_artifacts),
        monster_count=len(monsters),
        ruin_count=len(ruins),
        suspicious_count=len(suspicious),
    )

    warnings = list(health.warnings)
    if not artifacts:
        warnings.append("No major artifacts detected")
    if not view.files:
        warnings.append("Repository appears empty")

    git_summary = collect_git_summary(root)
    intelligence = build_repository_intelligence(root, view=view, text_cache=text_cache, artifacts=artifacts, health_score=health.score, git_summary=git_summary)
    from ..analyzers import maintenance

    remediation_findings = maintenance.remediation_findings(RepositoryAnalysis(summary=ScanSummary(
        root=view.root,
        scanned_at=datetime.now(timezone.utc),
        total_files=len(view.files),
        artifact_count=len(artifacts),
        ancient_count=len(ancient),
        todo_count=len(todo_artifacts),
        duplicate_count=len(duplicates),
        dead_code_count=len(dead_code),
        monster_count=len(monsters),
        ruin_count=len(ruins),
        suspicious_count=len(suspicious),
        technical_debt_estimate=health.debt_estimate,
        health_score=health.score,
        health_status=health.status,
    ), intelligence=intelligence))
    summary = ScanSummary(
        root=view.root,
        scanned_at=datetime.now(timezone.utc),
        total_files=len(view.files),
        artifact_count=len(artifacts),
        ancient_count=len(ancient),
        todo_count=len(todo_artifacts),
        duplicate_count=len(duplicates),
        dead_code_count=len(dead_code),
        monster_count=len(monsters),
        ruin_count=len(ruins),
        suspicious_count=len(suspicious),
        technical_debt_estimate=health.debt_estimate,
        health_score=health.score,
        health_status=health.status,
        warnings=warnings,
        artifacts=artifacts,
        timeline={
            "available": bool(git_summary.available),
            "commit_count": git_summary.commit_count,
            "repository_age_days": git_summary.repository_age_days,
            "repository_age_years": round(git_summary.repository_age_days / 365, 1) if git_summary.repository_age_days else 0,
            "first_commit": git_summary.first_commit.isoformat() if git_summary.first_commit else None,
            "last_commit": git_summary.last_commit.isoformat() if git_summary.last_commit else None,
            "most_modified_files": git_summary.most_modified_files,
            "eras": [{"year": era.year, "title": era.title, "activity": era.activity} for era in intelligence.timeline_eras],
        },
        extra={
            "similarity_pairs": similarity_report(view.files, text_cache),
            "dna": {"signature": intelligence.dna.signature, "confidence": intelligence.dna.confidence},
            "personality": {"type": intelligence.personality.type, "traits": intelligence.personality.traits, "risk": intelligence.personality.risk},
            "artifact_confidence": intelligence.artifact_confidence,
            "architecture": {
                "primary": intelligence.architecture.primary if intelligence.architecture else "Prototype",
                "secondary": intelligence.architecture.secondary if intelligence.architecture else "Layered",
                "confidence": intelligence.architecture.confidence if intelligence.architecture else 0.68,
            },
            "forecast": {
                "current_health": intelligence.forecast.current_health,
                "projected_6_months": intelligence.forecast.projected_6_months,
                "projected_12_months": intelligence.forecast.projected_12_months,
                "reason": intelligence.forecast.reason,
            },
            "investigation": [
                {
                    "incident": incident.incident,
                    "date": incident.date,
                    "impact": incident.impact,
                    "outcome": incident.outcome,
                    "risk": incident.risk,
                    "evidence": incident.evidence,
                }
                for incident in intelligence.incidents
            ],
            "weaknesses": [
                {
                    "path": str(item.path),
                    "referenced_by": item.referenced_by,
                    "failure_impact": item.failure_impact,
                    "recovery_difficulty": item.recovery_difficulty,
                    "confidence": item.confidence,
                }
                for item in intelligence.weaknesses
            ],
            "quake": None
            if intelligence.quake_simulation is None
            else {
                "target": str(intelligence.quake_simulation.target),
                "projected_damage": intelligence.quake_simulation.projected_damage,
                "subsystems_lost": intelligence.quake_simulation.subsystems_lost,
                "severity": intelligence.quake_simulation.severity,
                "affected_files": [str(path) for path in intelligence.quake_simulation.affected_files],
            },
            "dependency_hubs": [
                {
                    "path": str(hub.path),
                    "referenced_by": hub.referenced_by,
                    "depends_on": hub.depends_on,
                    "external_packages": hub.external_packages,
                    "dependency_risk": hub.dependency_risk,
                    "failure_impact": hub.failure_impact,
                    "confidence": hub.confidence,
                }
                for hub in intelligence.dependency_hubs
            ],
            "civilizations": [
                {
                    "name": civ.name,
                    "files": [str(path) for path in civ.files],
                    "referenced": civ.referenced,
                    "last_active_days": civ.last_active_days,
                    "status": civ.status,
                    "confidence": civ.confidence,
                }
                for civ in intelligence.civilizations
            ],
            "contributors": [
                {
                    "area": item.area,
                    "owner": item.owner,
                    "maintenance_owner": item.maintenance_owner,
                    "abandoned_owner": item.abandoned_owner,
                }
                for item in intelligence.contributors
            ],
            "mutations": [
                {
                    "project_type": item.project_type,
                    "became": item.became,
                    "date": item.date,
                    "impact": item.impact,
                }
                for item in intelligence.mutations
            ],
            "knowledge_map": {
                "core": intelligence.knowledge_map.core,
                "dependency_graph": intelligence.knowledge_map.dependency_graph,
                "route_graph": intelligence.knowledge_map.route_graph,
                "service_graph": intelligence.knowledge_map.service_graph,
                "architecture_graph": intelligence.knowledge_map.architecture_graph,
            },
            "containment_zones": [
                {
                    "location": item.location,
                    "complexity": item.complexity,
                    "spread_rate": item.spread_rate,
                    "recommendation": item.recommendation,
                }
                for item in intelligence.containment_zones
            ],
            "survival": {
                "score": intelligence.survival.score if intelligence.survival else 0,
                "risk": intelligence.survival.risk if intelligence.survival else "Unknown",
                "single_point_failure": intelligence.survival.single_point_failure if intelligence.survival else "Unknown",
                "maintainability": intelligence.survival.maintainability if intelligence.survival else 0,
                "recoverability": intelligence.survival.recoverability if intelligence.survival else 0,
                "onboarding_difficulty": intelligence.survival.onboarding_difficulty if intelligence.survival else 0,
                "bus_factor": intelligence.survival.bus_factor if intelligence.survival else 0,
            },
            "observations": [
                {
                    "observation": item.observation,
                    "evidence": item.evidence,
                }
                for item in intelligence.observations
            ],
            "debt_heatmap": [
                {
                    "bucket": bucket.bucket,
                    "score": bucket.score,
                    "label": bucket.label,
                    "files": bucket.files,
                }
                for bucket in intelligence.debt_heatmap
            ],
            "graph": {
                "nodes": intelligence.graph_node_count,
                "edges": intelligence.graph_edge_count,
            },
            "remediation": [
                {
                    "problem": item.problem,
                    "evidence": item.evidence,
                    "impact": item.impact,
                    "confidence": item.confidence,
                    "recommended_fix": item.recommended_fix,
                    "estimated_effort": item.estimated_effort,
                    "risk_level": item.risk_level,
                    "root_cause": item.root_cause,
                    "likely_consequences": item.likely_consequences,
                    "alternative_solution": item.alternative_solution,
                    "implementation_difficulty": item.implementation_difficulty,
                    "location": item.location,
                }
                for item in remediation_findings[:100]
            ],
        },
    )
    return RepositoryAnalysis(summary=summary, intelligence=intelligence)
