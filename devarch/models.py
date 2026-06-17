from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Artifact:
    path: Path
    kind: str
    risk: str
    score: float = 0.0
    age_days: int | None = None
    size_bytes: int | None = None
    line_number: int | None = None
    detail: str = ""
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScanSummary:
    root: Path
    scanned_at: datetime
    total_files: int
    artifact_count: int
    ancient_count: int
    todo_count: int
    duplicate_count: int
    dead_code_count: int
    monster_count: int
    ruin_count: int
    suspicious_count: int
    technical_debt_estimate: float
    health_score: int
    health_status: str
    warnings: list[str] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    timeline: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

