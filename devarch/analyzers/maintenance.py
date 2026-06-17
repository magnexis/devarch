from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import re
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None  # type: ignore[assignment]

from ..scanner.intelligence import RepositoryAnalysis


STATE_DIR_NAME = ".devarch"
BASELINE_FILE = "baseline.json"
HISTORY_FILE = "history.jsonl"
BUDGET_FILE_CANDIDATES = ("budget.json", "budget.toml", "budget.yml", "budget.yaml")


@dataclass(slots=True)
class MaintenanceSnapshot:
    captured_at: str
    root: str
    file_count: int
    dependency_count: int
    complexity_score: int
    dead_code_count: int
    duplicate_code_count: int
    route_count: int
    todo_count: int
    health_score: int
    technical_debt: float


@dataclass(slots=True)
class RegressionReport:
    baseline: MaintenanceSnapshot
    current: MaintenanceSnapshot
    complexity_delta: float
    dead_code_delta: int
    duplicate_delta: int
    health_delta: int
    status: str


@dataclass(slots=True)
class BudgetLimits:
    max_dead_files: int = 10
    max_complexity: int = 80
    max_duplicate_blocks: int = 25
    max_todos: int = 50
    max_routes: int = 100
    max_dependencies: int = 150
    min_health_score: int = 70


@dataclass(slots=True)
class BudgetCheck:
    limits: BudgetLimits
    exceeded: list[tuple[str, int, int]] = field(default_factory=list)
    status: str = "Passing"


@dataclass(slots=True)
class ReleaseCheck:
    score: int
    status: str
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    budget: BudgetCheck | None = None
    regression: RegressionReport | None = None


@dataclass(slots=True)
class OwnershipFinding:
    module: str
    last_significant_activity_days: int
    primary_maintainer: str
    status: str


@dataclass(slots=True)
class DependencyAlert:
    package: str
    status: str
    recommendation: str
    confidence: float
    used_by: int


@dataclass(slots=True)
class StandardsReport:
    naming: int
    documentation: int
    consistency: int
    test_coverage: int
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HistoryPoint:
    captured_at: str
    health_score: int
    complexity_score: int
    dead_code_count: int
    duplicate_code_count: int
    label: str


@dataclass(slots=True)
class RecommendationItem:
    title: str
    current: str
    target: str
    potential_reduction: str


@dataclass(slots=True)
class RemediationFinding:
    problem: str
    evidence: list[str]
    impact: str
    confidence: float
    recommended_fix: str
    estimated_effort: str
    risk_level: str
    root_cause: str
    likely_consequences: str
    alternative_solution: str
    implementation_difficulty: str
    location: str


@dataclass(slots=True)
class PrescriptionPlan:
    findings: list[RemediationFinding] = field(default_factory=list)
    immediate_actions: list[str] = field(default_factory=list)
    estimated_time_minutes: int = 0
    expected_health_increase: int = 0


@dataclass(slots=True)
class RepairWeek:
    week: int
    focus: str
    actions: list[str] = field(default_factory=list)
    expected_health: str = ""


def _state_dir(root: Path) -> Path:
    return root / STATE_DIR_NAME


def _baseline_path(root: Path) -> Path:
    return _state_dir(root) / BASELINE_FILE


def _history_path(root: Path) -> Path:
    return _state_dir(root) / HISTORY_FILE


def _default_budget_path(root: Path) -> Path | None:
    state_dir = _state_dir(root)
    for name in BUDGET_FILE_CANDIDATES:
        candidate = state_dir / name
        if candidate.exists():
            return candidate
    return None


def _ensure_state_dir(root: Path) -> Path:
    state_dir = _state_dir(root)
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir


def _serialise(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _serialise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialise(item) for item in value]
    if hasattr(value, "__dict__"):
        return _serialise(value.__dict__)
    return value


def _snapshot_from_analysis(analysis: RepositoryAnalysis) -> MaintenanceSnapshot:
    summary = analysis.summary
    intelligence = analysis.intelligence
    return MaintenanceSnapshot(
        captured_at=datetime.now(timezone.utc).isoformat(),
        root=str(summary.root),
        file_count=summary.total_files,
        dependency_count=analysis.intelligence.graph_edge_count,
        complexity_score=min(100, len(intelligence.dependency_hubs) * 5 + len(intelligence.weaknesses) * 10),
        dead_code_count=summary.dead_code_count,
        duplicate_code_count=summary.duplicate_count,
        route_count=len(intelligence.knowledge_map.route_graph),
        todo_count=summary.todo_count,
        health_score=summary.health_score,
        technical_debt=summary.technical_debt_estimate,
    )


def build_snapshot(analysis: RepositoryAnalysis) -> MaintenanceSnapshot:
    return _snapshot_from_analysis(analysis)


def save_baseline(analysis: RepositoryAnalysis) -> MaintenanceSnapshot:
    snapshot = _snapshot_from_analysis(analysis)
    state_dir = _ensure_state_dir(analysis.summary.root)
    _baseline_path(analysis.summary.root).write_text(
        json.dumps(_serialise(asdict(snapshot)), indent=2),
        encoding="utf-8",
    )
    _history_path(analysis.summary.root).open("a", encoding="utf-8").write(json.dumps({"kind": "baseline", **_serialise(asdict(snapshot))}) + "\n")
    return snapshot


def load_baseline(root: Path) -> MaintenanceSnapshot | None:
    path = _baseline_path(root)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return MaintenanceSnapshot(**data)


def load_history(root: Path) -> list[HistoryPoint]:
    path = _history_path(root)
    if not path.exists():
        return []
    history: list[HistoryPoint] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        history.append(
            HistoryPoint(
                captured_at=raw["captured_at"],
                health_score=raw["health_score"],
                complexity_score=raw["complexity_score"],
                dead_code_count=raw["dead_code_count"],
                duplicate_code_count=raw["duplicate_code_count"],
                label=raw.get("kind", "snapshot"),
            )
        )
    return history


def append_history(analysis: RepositoryAnalysis, label: str = "snapshot") -> MaintenanceSnapshot:
    snapshot = _snapshot_from_analysis(analysis)
    _ensure_state_dir(analysis.summary.root)
    with _history_path(analysis.summary.root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": label, **_serialise(asdict(snapshot))}) + "\n")
    return snapshot


def compare_to_baseline(current: MaintenanceSnapshot, baseline: MaintenanceSnapshot) -> RegressionReport:
    complexity_delta = ((current.complexity_score - baseline.complexity_score) / baseline.complexity_score * 100) if baseline.complexity_score else 0.0
    dead_code_delta = current.dead_code_count - baseline.dead_code_count
    duplicate_delta = current.duplicate_code_count - baseline.duplicate_code_count
    health_delta = current.health_score - baseline.health_score
    status = "Improved"
    if health_delta < 0 or dead_code_delta > 0 or duplicate_delta > 0 or complexity_delta > 0:
        status = "Regressed"
    return RegressionReport(
        baseline=baseline,
        current=current,
        complexity_delta=round(complexity_delta, 1),
        dead_code_delta=dead_code_delta,
        duplicate_delta=duplicate_delta,
        health_delta=health_delta,
        status=status,
    )


def read_budget_limits(root: Path, config: Path | None = None) -> BudgetLimits:
    candidate = config or _default_budget_path(root)
    if not candidate or not candidate.exists():
        return BudgetLimits()
    suffix = candidate.suffix.lower()
    data: dict[str, Any]
    if suffix == ".json":
        data = json.loads(candidate.read_text(encoding="utf-8"))
    elif suffix == ".toml" and tomllib is not None:
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
    elif suffix in {".yml", ".yaml"}:
        data = {}
        for line in candidate.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if re.fullmatch(r"-?\d+", value):
                data[key] = int(value)
            elif re.fullmatch(r"-?\d+\.\d+", value):
                data[key] = float(value)
            else:
                data[key] = value
    else:
        return BudgetLimits()
    allowed = {field.name for field in BudgetLimits.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    return BudgetLimits(**{key: data[key] for key in data if key in allowed})


def evaluate_budget(current: MaintenanceSnapshot, limits: BudgetLimits) -> BudgetCheck:
    exceeded: list[tuple[str, int, int]] = []
    checks = {
        "Dead Files": (current.dead_code_count, limits.max_dead_files),
        "Complexity": (current.complexity_score, limits.max_complexity),
        "Duplicate Blocks": (current.duplicate_code_count, limits.max_duplicate_blocks),
        "TODOs": (current.todo_count, limits.max_todos),
        "Routes": (current.route_count, limits.max_routes),
        "Dependencies": (current.dependency_count, limits.max_dependencies),
    }
    for label, (value, limit) in checks.items():
        if value > limit:
            exceeded.append((label, value, limit))
    status = "Passing" if not exceeded and current.health_score >= limits.min_health_score else "Failing"
    return BudgetCheck(limits=limits, exceeded=exceeded, status=status)


def ownership_report(analysis: RepositoryAnalysis) -> list[OwnershipFinding]:
    findings: list[OwnershipFinding] = []
    intelligence = analysis.intelligence
    for item in intelligence.contributors:
        related_days = [
            intelligence.file_last_active_days.get(path, 0)
            for path in intelligence.view.files
            if (path.relative_to(intelligence.root).parts and path.relative_to(intelligence.root).parts[0] == item.area)
        ]
        last_activity = max(related_days, default=0)
        if item.owner == "unknown" or last_activity >= 365:
            findings.append(
                OwnershipFinding(
                    module=item.area,
                    last_significant_activity_days=last_activity,
                    primary_maintainer=item.owner if item.owner != "unknown" else "Unknown",
                    status="Unowned" if item.owner == "unknown" else "Stale",
                )
            )
    return findings


def _declared_dependencies(root: Path) -> set[str]:
    declared: set[str] = set()
    pyproject = root / "pyproject.toml"
    if pyproject.exists() and tomllib is not None:
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        project = data.get("project", {})
        for item in project.get("dependencies", []):
            name = re.split(r"[<>=~!\[]", str(item), 1)[0].strip()
            if name:
                declared.add(name.lower())
    for candidate in root.rglob("requirements*.txt"):
        for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-r"):
                continue
            name = re.split(r"[<>=~!\[]", line, 1)[0].strip()
            if name:
                declared.add(name.lower())
    return declared


def dependency_health_report(analysis: RepositoryAnalysis) -> list[DependencyAlert]:
    root = analysis.summary.root
    intelligence = analysis.intelligence
    declared = _declared_dependencies(root)
    imported = {package.lower() for package in intelligence.external_packages}
    local_modules = {
        path.stem.lower()
        for path in intelligence.view.files
        if path.suffix.lower() in {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
    }
    local_modules.update(
        part.lower()
        for path in intelligence.view.files
        for part in path.parts[:1]
        if part and part.lower() not in {root.name.lower()}
    )
    local_modules.update({"version", "cli", "reports", "scanner", "intelligence", "discovery", "maintenance", "recovery", "models", "utils", "analyzers", "plugins"})
    alerts: list[DependencyAlert] = []
    for package in sorted(declared):
        used_by = intelligence.external_packages.get(package, intelligence.external_packages.get(package.lower(), 0))
        if package not in imported or used_by == 0:
            alerts.append(
                DependencyAlert(
                    package=package,
                    status="Unused",
                    recommendation="Remove or replace",
                    confidence=0.9,
                    used_by=used_by,
                )
            )
    for package, count in intelligence.external_packages.items():
        normalized = package.lower()
        if normalized in local_modules or normalized in declared:
            continue
        if count <= 1:
            alerts.append(
                DependencyAlert(
                    package=normalized,
                    status="Untracked",
                    recommendation="Document or pin the dependency",
                    confidence=0.72,
                    used_by=count,
                )
            )
    return alerts


def standards_report(analysis: RepositoryAnalysis) -> StandardsReport:
    view = analysis.intelligence.view
    text_cache = analysis.intelligence.text_cache
    python_files = [path for path in view.files if path.suffix.lower() == ".py"]
    readable_docs = [path for path in view.files if path.suffix.lower() in {".md", ".rst"} or path.name.lower().startswith("readme")]
    snake_case = sum(1 for path in view.files if re.fullmatch(r"[a-z0-9_./-]+", path.name.lower()) and "__" not in path.name)
    docs_with_docstring = 0
    for path in python_files:
        content = text_cache.get(path, "")
        if '"""' in content or "'''" in content:
            docs_with_docstring += 1
    naming = int(round((snake_case / max(1, len(view.files))) * 100))
    documentation = int(round(min(1.0, (len(readable_docs) + docs_with_docstring) / max(1, len(view.files))) * 100))
    consistent_dirs = sum(1 for directory in view.directories if directory.name == directory.name.lower())
    consistency = int(round((consistent_dirs / max(1, len(view.directories))) * 100)) if view.directories else 100
    test_coverage = int(round((sum(1 for path in view.files if "test" in path.name.lower()) / max(1, len(view.files))) * 100))
    notes: list[str] = []
    if documentation < 70:
        notes.append("Documentation coverage could be improved")
    if naming < 80:
        notes.append("File naming is inconsistent")
    if consistency < 80:
        notes.append("Folder naming is inconsistent")
    if test_coverage < 15:
        notes.append("Test footprint is light")
    return StandardsReport(
        naming=naming,
        documentation=documentation,
        consistency=consistency,
        test_coverage=test_coverage,
        notes=notes,
    )


def history_points(root: Path, current: MaintenanceSnapshot | None = None) -> list[HistoryPoint]:
    points = load_history(root)
    if current is not None:
        points = [*points, HistoryPoint(
            captured_at=current.captured_at,
            health_score=current.health_score,
            complexity_score=current.complexity_score,
            dead_code_count=current.dead_code_count,
            duplicate_code_count=current.duplicate_code_count,
            label="current",
        )]
    return points


def cleanup_candidates(analysis: RepositoryAnalysis) -> list[str]:
    from . import recovery

    plan = recovery.build_cleanup_plan(analysis)
    queue: list[str] = []
    for item in plan:
        for line in item.items:
            queue.append(line)
    return queue


def recommendation_items(analysis: RepositoryAnalysis) -> list[RecommendationItem]:
    current = _snapshot_from_analysis(analysis)
    items: list[RecommendationItem] = []
    dependency_alerts = dependency_health_report(analysis)
    if dependency_alerts:
        unused = sum(1 for item in dependency_alerts if item.status == "Unused")
        items.append(
            RecommendationItem(
                title="Reduce dependency count",
                current=f"{len(dependency_alerts)} risky packages",
                target=f"Remove {unused} unused dependencies",
                potential_reduction=f"{min(100, unused * 5)}% smaller dependency surface",
            )
        )
    if current.dead_code_count:
        items.append(
            RecommendationItem(
                title="Lower dead code count",
                current=f"{current.dead_code_count} dead files",
                target="Move toward zero",
                potential_reduction="Fewer stale execution paths",
            )
        )
    if current.complexity_score >= 70:
        items.append(
            RecommendationItem(
                title="Reduce complexity hotspots",
                current=f"Complexity score {current.complexity_score}/100",
                target="Drop below 60",
                potential_reduction="Lower maintenance burden",
            )
        )
    return items[:5]


def _risk_from_artifact(kind: str, impact: str) -> str:
    if impact in {"Critical", "Severe"}:
        return "High"
    if kind in {"monster_file", "dead_code_candidate", "unreachable_code"}:
        return "Medium"
    return "Low"


def _effort_from_artifact(kind: str, size: int | None = None) -> str:
    if kind in {"dead_code_candidate", "unused_asset", "empty_directory", "suspicious"}:
        return "2-10 minutes"
    if kind in {"todo", "ancient_file"}:
        return "15-30 minutes"
    if kind in {"duplicate_block"}:
        return "30-90 minutes"
    if kind in {"monster_file"}:
        return "2-4 hours"
    if size and size > 2000:
        return "4+ hours"
    return "30 minutes"


def _make_finding(
    *,
    problem: str,
    evidence: list[str],
    impact: str,
    confidence: float,
    recommended_fix: str,
    estimated_effort: str,
    risk_level: str,
    root_cause: str,
    likely_consequences: str,
    alternative_solution: str,
    implementation_difficulty: str,
    location: str,
) -> RemediationFinding:
    return RemediationFinding(
        problem=problem,
        evidence=evidence,
        impact=impact,
        confidence=confidence,
        recommended_fix=recommended_fix,
        estimated_effort=estimated_effort,
        risk_level=risk_level,
        root_cause=root_cause,
        likely_consequences=likely_consequences,
        alternative_solution=alternative_solution,
        implementation_difficulty=implementation_difficulty,
        location=location,
    )


def remediation_findings(analysis: RepositoryAnalysis) -> list[RemediationFinding]:
    findings: list[RemediationFinding] = []
    summary = analysis.summary
    intelligence = analysis.intelligence
    covered_locations: set[str] = set()

    def add_finding(item: RemediationFinding) -> None:
        findings.append(item)
        if item.location:
            covered_locations.add(item.location)

    for artifact in summary.artifacts:
        kind = artifact.kind
        risk = _risk_from_artifact(kind, artifact.risk)
        evidence = [str(artifact.path)]
        if artifact.detail:
            evidence.append(artifact.detail)
        if kind == "dead_code_candidate":
            add_finding(
                _make_finding(
                    problem=f"Dead code detected in {artifact.path.name}",
                    evidence=evidence,
                    impact=artifact.risk or "Low",
                    confidence=artifact.confidence or 0.85,
                    recommended_fix="Remove the file or unreachable block",
                    estimated_effort=_effort_from_artifact(kind, artifact.size_bytes),
                    risk_level=risk,
                    root_cause="Unused logic accumulated over time",
                    likely_consequences="Continued maintenance overhead and false dependency signals",
                    alternative_solution="Archive the file first if you need a rollback window",
                    implementation_difficulty="Easy",
                    location=str(artifact.path),
                )
            )
        elif kind == "ancient_file":
            add_finding(
                _make_finding(
                    problem=f"Ancient file appears abandoned: {artifact.path.name}",
                    evidence=evidence,
                    impact=artifact.risk or "Moderate",
                    confidence=artifact.confidence or 0.82,
                    recommended_fix="Archive or remove after confirming no runtime references",
                    estimated_effort=_effort_from_artifact(kind, artifact.size_bytes),
                    risk_level=risk,
                    root_cause="File has drifted out of active development",
                    likely_consequences="Stale behavior, confusing ownership, unnecessary cognitive load",
                    alternative_solution="Move to an archive folder with a deprecation note",
                    implementation_difficulty="Easy",
                    location=str(artifact.path),
                )
            )
        elif kind == "duplicate_block":
            add_finding(
                _make_finding(
                    problem=f"Duplicated logic detected in {artifact.path.name}",
                    evidence=evidence,
                    impact="Medium",
                    confidence=artifact.confidence or 0.84,
                    recommended_fix="Extract shared utility or shared module",
                    estimated_effort=_effort_from_artifact(kind, artifact.size_bytes),
                    risk_level="Medium",
                    root_cause="Copy-paste reuse instead of shared abstraction",
                    likely_consequences="Bug fixes will need to be repeated in multiple places",
                    alternative_solution="Document the duplication if extraction would be too invasive",
                    implementation_difficulty="Moderate",
                    location=str(artifact.path),
                )
            )
        elif kind == "monster_file":
            add_finding(
                _make_finding(
                    problem=f"Oversized or complex file detected: {artifact.path.name}",
                    evidence=[str(artifact.path), artifact.detail or "High complexity surface"],
                    impact="High",
                    confidence=artifact.confidence or 0.9,
                    recommended_fix="Split responsibilities into smaller modules",
                    estimated_effort=_effort_from_artifact(kind, artifact.size_bytes),
                    risk_level="High",
                    root_cause="Feature accumulation without module boundaries",
                    likely_consequences="Change risk and review burden will stay high",
                    alternative_solution="Add internal helper modules before a full split",
                    implementation_difficulty="Hard",
                    location=str(artifact.path),
                )
            )
        elif kind in {"todo", "fixme", "hack", "bug", "temp", "xxx"}:
            add_finding(
                _make_finding(
                    problem=f"Outstanding developer note in {artifact.path.name}",
                    evidence=evidence,
                    impact="Low",
                    confidence=artifact.confidence or 0.75,
                    recommended_fix="Resolve the note or convert it into a tracked issue",
                    estimated_effort=_effort_from_artifact(kind, artifact.size_bytes),
                    risk_level="Low",
                    root_cause="Work was paused before the change was completed",
                    likely_consequences="Deferred cleanup will compound over time",
                    alternative_solution="Keep as a documented follow-up with owner and deadline",
                    implementation_difficulty="Easy",
                    location=str(artifact.path),
                )
            )
        elif kind in {"unused_asset", "empty_directory"}:
            add_finding(
                _make_finding(
                    problem=f"Unused structure or asset: {artifact.path.name}",
                    evidence=evidence,
                    impact="Low",
                    confidence=artifact.confidence or 0.8,
                    recommended_fix="Delete if truly unused or document a future use",
                    estimated_effort=_effort_from_artifact(kind, artifact.size_bytes),
                    risk_level="Low",
                    root_cause="Repository drift and old build outputs",
                    likely_consequences="Clutter and confusion for future maintainers",
                    alternative_solution="Move to an archive folder temporarily",
                    implementation_difficulty="Easy",
                    location=str(artifact.path),
                )
            )
        elif kind == "suspicious":
            add_finding(
                _make_finding(
                    problem=f"Suspicious backup-style file detected: {artifact.path.name}",
                    evidence=evidence,
                    impact="Low",
                    confidence=artifact.confidence or 0.86,
                    recommended_fix="Rename, archive, or remove after verifying intent",
                    estimated_effort=_effort_from_artifact(kind, artifact.size_bytes),
                    risk_level="Low",
                    root_cause="Temporary file naming conventions were never cleaned up",
                    likely_consequences="Potential confusion and accidental reuse of stale code",
                    alternative_solution="Label the file clearly if it must remain",
                    implementation_difficulty="Easy",
                    location=str(artifact.path),
                )
            )
        else:
            add_finding(
                _make_finding(
                    problem=f"Review artifact: {artifact.path.name} ({artifact.kind})",
                    evidence=evidence,
                    impact=artifact.risk or "Moderate",
                    confidence=artifact.confidence or 0.7,
                    recommended_fix="Review and either keep, archive, or remove based on ownership",
                    estimated_effort=_effort_from_artifact(kind, artifact.size_bytes),
                    risk_level=risk,
                    root_cause="Artifact was discovered during repository excavation",
                    likely_consequences="Unreviewed files may continue to accumulate technical debt",
                    alternative_solution="Document why the artifact is intentionally kept",
                    implementation_difficulty="Easy",
                    location=str(artifact.path),
                )
            )

    # Ensure non-artifact findings are also represented with remediation guidance.

    for weakness in intelligence.weaknesses:
        add_finding(
            _make_finding(
                problem=f"Structural weakness in {weakness.path.name}",
                evidence=[str(weakness.path), f"Referenced by {weakness.referenced_by} files"],
                impact=weakness.failure_impact,
                confidence=weakness.confidence,
                recommended_fix="Decouple the module and reduce fan-in",
                estimated_effort="1-4 hours",
                risk_level="High" if weakness.failure_impact in {"Critical", "Severe"} else "Medium",
                root_cause="Too many modules depend on a single implementation",
                likely_consequences="Change propagation and fragile deployments",
                alternative_solution="Wrap the API before a deeper refactor",
                implementation_difficulty="Hard",
                location=str(weakness.path),
            )
        )

    for alert in dependency_health_report(analysis):
        add_finding(
            _make_finding(
                problem=f"Dependency issue: {alert.package}",
                evidence=[alert.status, f"Used by {alert.used_by} files"],
                impact="Moderate" if alert.used_by else "Low",
                confidence=alert.confidence,
                recommended_fix=alert.recommendation,
                estimated_effort="10-30 minutes",
                risk_level="Medium" if alert.status == "Untracked" else "Low",
                root_cause="Dependency lifecycle has drifted from the codebase",
                likely_consequences="Unnecessary package surface and upgrade burden",
                alternative_solution="Pin and document the package if removal is risky",
                implementation_difficulty="Easy",
                location=alert.package,
            )
        )

    for note in standards_report(analysis).notes:
        add_finding(
            _make_finding(
                problem=note,
                evidence=[summary.root.name],
                impact="Moderate",
                confidence=0.7,
                recommended_fix="Improve naming, docs, or tests in the affected area",
                estimated_effort="15-60 minutes",
                risk_level="Low",
                root_cause="Repository standards have drifted over time",
                likely_consequences="Lower maintainability and onboarding friction",
                alternative_solution="Add a short style guide note for the team",
                implementation_difficulty="Easy",
                location=str(summary.root),
            )
        )

    if intelligence.architecture and intelligence.architecture.primary == "Prototype" and summary.health_score < 85:
        add_finding(
            _make_finding(
                problem="Architecture is still reading as a prototype",
                evidence=[intelligence.architecture.primary, intelligence.architecture.secondary],
                impact="Moderate",
                confidence=intelligence.architecture.confidence,
                recommended_fix="Introduce explicit layers or module boundaries",
                estimated_effort="2-8 hours",
                risk_level="Medium",
                root_cause="Growth outpaced structure",
                likely_consequences="New changes will keep spreading across the codebase",
                alternative_solution="Document the current architecture before refactoring",
                implementation_difficulty="Hard",
                location=str(summary.root),
            )
        )

    return findings


def prescribe_repository(analysis: RepositoryAnalysis) -> PrescriptionPlan:
    findings = remediation_findings(analysis)
    top = sorted(
        findings,
        key=lambda item: (
            {"High": 3, "Medium": 2, "Low": 1}.get(item.risk_level, 1),
            item.confidence,
        ),
        reverse=True,
    )
    immediate_actions: list[str] = []
    estimated_time = 0
    expected_health = 0
    for finding in top[:5]:
        immediate_actions.append(f"{finding.recommended_fix} - {finding.location}")
        if finding.estimated_effort.startswith("2-10"):
            estimated_time += 10
        elif finding.estimated_effort.startswith("15-30"):
            estimated_time += 25
        elif finding.estimated_effort.startswith("30-90"):
            estimated_time += 60
        elif finding.estimated_effort.startswith("1-4"):
            estimated_time += 180
        elif finding.estimated_effort.startswith("2-8"):
            estimated_time += 300
        else:
            estimated_time += 30
        expected_health += 2 if finding.risk_level == "Low" else 3 if finding.risk_level == "Medium" else 4
    return PrescriptionPlan(
        findings=top[:10],
        immediate_actions=immediate_actions[:5],
        estimated_time_minutes=estimated_time,
        expected_health_increase=min(20, expected_health),
    )


def repair_plan(analysis: RepositoryAnalysis) -> list[RepairWeek]:
    findings = prescribe_repository(analysis).findings
    stages = [
        (
            "Week 1",
            "Remove dead code and unused dependencies",
            lambda item: item.problem.lower().startswith(("dead code", "unused", "dependency")),
        ),
        (
            "Week 2",
            "Consolidate duplicate logic and resolve TODOs",
            lambda item: "duplicate" in item.problem.lower() or "todo" in item.problem.lower(),
        ),
        (
            "Week 3",
            "Split oversized modules and reduce structural risk",
            lambda item: "structural" in item.problem.lower() or "architecture" in item.problem.lower() or "monster" in item.problem.lower(),
        ),
        (
            "Week 4",
            "Recover documentation, naming, and ownership",
            lambda item: "documentation" in item.problem.lower() or "naming" in item.problem.lower() or "ownership" in item.problem.lower(),
        ),
    ]
    plan: list[RepairWeek] = []
    for index, (label, focus, matcher) in enumerate(stages, start=1):
        items = [item for item in findings if matcher(item)]
        actions = [f"{item.recommended_fix} ({item.location})" for item in items[:3]]
        if not actions:
            actions = [
                "Re-scan after the previous week of cleanup",
                "Review the highest-risk modules",
            ]
        health_target = min(99, analysis.summary.health_score + index * 4)
        plan.append(
            RepairWeek(
                week=index,
                focus=focus,
                actions=actions,
                expected_health=f"{analysis.summary.health_score} -> {health_target}",
            )
        )
    return plan


def release_check(analysis: RepositoryAnalysis, baseline: MaintenanceSnapshot | None = None, limits: BudgetLimits | None = None) -> ReleaseCheck:
    current = _snapshot_from_analysis(analysis)
    budget = evaluate_budget(current, limits or BudgetLimits())
    regression = compare_to_baseline(current, baseline) if baseline else None
    warnings = list(analysis.summary.warnings)
    blockers: list[str] = []
    if budget.exceeded:
        blockers.extend(f"{label}: {value} / {limit}" for label, value, limit in budget.exceeded)
    if regression and regression.health_delta < 0:
        blockers.append(f"Health dropped {abs(regression.health_delta)} points")
    if current.health_score < 85:
        warnings.append("Health score below release threshold")
    score = current.health_score
    score -= len(blockers) * 5
    score -= max(0, len(warnings) - 3) * 2
    score = max(0, min(100, score))
    status = "Ready" if score >= 85 and not blockers else "Needs Work"
    return ReleaseCheck(score=score, status=status, warnings=warnings, blockers=blockers, budget=budget, regression=regression)
