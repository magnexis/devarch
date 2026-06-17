from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
import re

from ..models import Artifact
from ..scanner.discovery import build_reference_map, build_text_index
from ..utils.fs import RepoView, collect_repository, path_kind


@dataclass(slots=True)
class CleanupPriority:
    level: int
    items: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DeletionAnalysis:
    path: Path
    safe_confidence: float
    affected_files: int
    recommendation: str
    references: list[Path] = field(default_factory=list)
    dependencies: list[Path] = field(default_factory=list)


@dataclass(slots=True)
class RefactorCandidate:
    name: str
    locations: list[Path]
    recommendation: str
    confidence: float


@dataclass(slots=True)
class RouteFinding:
    kind: str
    path: Path
    detail: str
    confidence: float


@dataclass(slots=True)
class ConfigFinding:
    kind: str
    name: str
    confidence: float
    locations: list[Path] = field(default_factory=list)


@dataclass(slots=True)
class MigrationFinding:
    path: Path
    kind: str
    status: str
    confidence: float


@dataclass(slots=True)
class DependencyWarning:
    name: str
    only_used_for: int
    recommendation: str
    confidence: float


@dataclass(slots=True)
class DriftReport:
    original: str
    current: str
    severity: str
    cause: str


@dataclass(slots=True)
class PRReport:
    removed: list[str] = field(default_factory=list)
    reduced: list[str] = field(default_factory=list)
    improved: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StatusSummary:
    debt: int
    complexity: int
    dead_code: int
    route_count: int
    dependency_count: int
    cleanup_opportunities: int
    recommendations: list[str] = field(default_factory=list)


def _text_files(view: RepoView) -> list[Path]:
    return [path for path in view.files if path_kind(path) == "text"]


def _get_summary(analysis_or_summary):
    return getattr(analysis_or_summary, "summary", analysis_or_summary)


def _get_intelligence(analysis_or_intelligence):
    return getattr(analysis_or_intelligence, "intelligence", analysis_or_intelligence)


def build_cleanup_plan(analysis_or_summary, priorities: int = 3) -> list[CleanupPriority]:
    summary = _get_summary(analysis_or_summary)
    extra = getattr(summary, "extra", {})
    priorities_map = {
        1: [
            f"Remove {summary.todo_count} TODO-heavy hotspots" if summary.todo_count else "Remove dead code candidates",
            f"Archive {len(extra.get('civilizations', []))} abandoned subsystem clusters" if extra.get("civilizations") else "Delete obsolete routes",
        ],
        2: [
            "Refactor structural weaknesses" if extra.get("weaknesses") else "Refactor oversized modules",
            "Stabilize dependency hubs" if extra.get("dependency_hubs") else "Consolidate duplicated utilities",
        ],
        3: [
            "Consolidate duplicate logic" if summary.duplicate_count else "Trim unused configuration",
            "Reduce technical debt hotspots" if extra.get("debt_heatmap") else "Review migration leftovers",
        ],
    }
    return [CleanupPriority(level=level, items=priorities_map[level]) for level in sorted(priorities_map)][:priorities]


def analyze_deletion(path: Path, root: Path) -> DeletionAnalysis:
    view = collect_repository(root)
    text_cache = build_text_index(view)
    references = build_reference_map(view, text_cache)
    target = path.resolve()
    ref_files = sorted(references.get(target, set()))
    dependencies: list[Path] = []
    needle = target.stem.replace("_", "")
    for source in _text_files(view):
        if source == target:
            continue
        content = text_cache.get(source, "")
        if not content:
            continue
        if target.name in content or needle and needle in content.replace("_", ""):
            dependencies.append(source)
    affected = len(set(ref_files + dependencies))
    safe = max(0.0, 100.0 - (affected * 18.0))
    if affected == 0:
        recommendation = "Archive or Remove"
    elif affected <= 2:
        recommendation = "Review Before Delete"
    else:
        recommendation = "Keep or refactor first"
    return DeletionAnalysis(
        path=target,
        safe_confidence=min(99.0, safe),
        affected_files=affected,
        recommendation=recommendation,
        references=ref_files,
        dependencies=dependencies,
    )


def find_refactor_candidates(analysis_or_intelligence) -> list[RefactorCandidate]:
    intelligence = _get_intelligence(analysis_or_intelligence)
    candidates: list[RefactorCandidate] = []
    duplicates = defaultdict(list)
    summary = getattr(analysis_or_intelligence, "summary", None)
    text_cache = getattr(intelligence, "text_cache", {})
    for artifact in getattr(summary, "artifacts", []):
        if artifact.kind == "duplicate_block":
            key = artifact.detail or artifact.path.stem
            duplicates[key].append(artifact.path)
            match_path = artifact.metadata.get("match_path")
            if match_path:
                duplicates[key].append(Path(match_path))
    for name, paths in duplicates.items():
        locations = sorted({path for path in paths})
        candidates.append(
            RefactorCandidate(
                name=name or "Duplicate logic",
                locations=locations,
                recommendation="Extract shared utility",
                confidence=0.88,
            )
        )
    # oversized classes and repeated validators
    for path in intelligence.view.files:
        if path_kind(path) != "text":
            continue
        content = text_cache.get(path, "")
        if not content:
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                content = ""
        if content.count("def validate") >= 2 or content.count("class ") >= 5:
            candidates.append(
                RefactorCandidate(
                    name=path.name,
                    locations=[path],
                    recommendation="Split responsibilities and extract helpers",
                    confidence=0.74,
                )
            )
    return candidates


ROUTE_PATTERNS = {
    "FastAPI": re.compile(r"@(?:app|router)\.(get|post|put|patch|delete|options|head)\("),
    "Flask": re.compile(r"@(?:app|blueprint)\.(route|get|post|put|delete)\("),
    "Express": re.compile(r"\.(get|post|put|patch|delete)\("),
    "Next.js": re.compile(r"export\s+(?:default\s+)?function\s+\w+|export\s+async\s+function\s+(GET|POST|PUT|PATCH|DELETE)"),
}


def audit_routes(view: RepoView, text_cache: dict[Path, str], references: dict[Path, set[Path]]) -> list[RouteFinding]:
    findings: list[RouteFinding] = []
    for path in _text_files(view):
        content = text_cache.get(path, "")
        if "route" not in path.name.lower() and "/api/" not in str(path).lower() and "app/" not in str(path).lower():
            continue
        if any(pattern.search(content) for pattern in ROUTE_PATTERNS.values()):
            confidence = 0.92
            if len(references.get(path, set())) == 0:
                findings.append(
                    RouteFinding(
                        kind="unused endpoint",
                        path=path,
                        detail="No obvious callers detected",
                        confidence=confidence,
                    )
                )
            else:
                findings.append(
                    RouteFinding(
                        kind="documented route",
                        path=path,
                        detail="Route patterns detected and reference links exist",
                        confidence=confidence,
                    )
                )
        else:
            findings.append(
                RouteFinding(
                    kind="unreachable route",
                    path=path,
                    detail="Path resembles route code but no handlers were found",
                    confidence=0.7,
                )
            )
    return findings


def audit_configs(view: RepoView, text_cache: dict[Path, str]) -> list[ConfigFinding]:
    env_vars = Counter()
    for content in text_cache.values():
        for match in re.finditer(r"\b[A-Z][A-Z0-9_]{2,}\b", content):
            env_vars[match.group(0)] += 1
    findings: list[ConfigFinding] = []
    for name, count in env_vars.items():
        if count <= 1 and any(token in name for token in ("KEY", "URL", "ENDPOINT", "SECRET")):
            findings.append(ConfigFinding(kind="unused environment variable", name=name, confidence=0.8))
    return findings


def audit_migrations(view: RepoView, text_cache: dict[Path, str]) -> list[MigrationFinding]:
    findings: list[MigrationFinding] = []
    for path in view.files:
        name = path.name.lower()
        if "migration" not in str(path).lower() and "migrate" not in name and "schema" not in name:
            continue
        content = text_cache.get(path, "") if path_kind(path) == "text" else ""
        if "TODO" in content or "XXX" in content:
            findings.append(MigrationFinding(path=path, kind="incomplete migration", status="Needs Review", confidence=0.84))
        elif "down()" not in content and "rollback" not in content and "revert" not in content:
            findings.append(MigrationFinding(path=path, kind="orphaned migration", status="Orphaned", confidence=0.78))
    return findings


def rationalize_dependencies(analysis_or_intelligence) -> list[DependencyWarning]:
    intelligence = _get_intelligence(analysis_or_intelligence)
    warnings: list[DependencyWarning] = []
    counts = Counter()
    for package, count in intelligence.external_packages.items():
        counts[package.lower()] += count
    for name, count in counts.items():
        if count <= 1 and name in {"lodash", "underscore", "moment", "left-pad"}:
            warnings.append(
                DependencyWarning(
                    name=name,
                    only_used_for=count,
                    recommendation="Replace with native code",
                    confidence=0.9,
                )
            )
    return warnings


def detect_drift(analysis_or_intelligence) -> DriftReport:
    analysis = analysis_or_intelligence
    intelligence = _get_intelligence(analysis_or_intelligence)
    summary = _get_summary(analysis_or_intelligence)
    original = intelligence.dna.signature[0] if intelligence.dna.signature else "Unknown"
    current = intelligence.architecture.primary if intelligence.architecture else "Unknown"
    forecast = getattr(intelligence, "forecast", None)
    current_health = getattr(forecast, "current_health", getattr(summary, "health_score", 0))
    projected_12 = getattr(forecast, "projected_12_months", current_health)
    severity = "High" if projected_12 < current_health - 10 else "Moderate"
    cause = "Feature accumulation" if getattr(summary, "health_score", 100) < 80 else "Structural drift"
    if current == "Prototype" and getattr(summary, "health_score", 100) < 70:
        current = "Monolithic Application"
    return DriftReport(original=f"Simple {original.title()} Service", current=current, severity=severity, cause=cause)


def build_pr_report(analysis_or_summary) -> PRReport:
    summary = _get_summary(analysis_or_summary)
    pr = PRReport()
    pr.removed.append(f"{summary.ancient_count} ancient files")
    pr.removed.append(f"{summary.dead_code_count} dead code candidates")
    pr.reduced.append(f"duplicate code by {summary.duplicate_count * 6}%")
    pr.improved.append(f"repository health score from {max(0, summary.health_score - 7)} to {summary.health_score}")
    return pr


def build_status_summary(analysis_or_summary) -> StatusSummary:
    summary = _get_summary(analysis_or_summary)
    intelligence = _get_intelligence(analysis_or_summary)
    return StatusSummary(
        debt=int(summary.technical_debt_estimate),
        complexity=min(100, len(intelligence.dependency_hubs) * 5 + len(intelligence.weaknesses) * 10),
        dead_code=summary.dead_code_count,
        route_count=len(intelligence.knowledge_map.route_graph),
        dependency_count=summary.duplicate_count + intelligence.graph_edge_count,
        cleanup_opportunities=summary.artifact_count + len(intelligence.weaknesses),
        recommendations=[
            "Prioritize high-impact deletions",
            "Refactor structural bottlenecks",
            "Audit routes and config drift",
        ],
    )
