from __future__ import annotations

from pathlib import Path

from ..models import ScanSummary
from .intelligence import RepositoryAnalysis, analyze_repository


def scan_repository(root: Path) -> ScanSummary:
    return analyze_repository(root).summary


def analyze_repository_root(root: Path) -> RepositoryAnalysis:
    return analyze_repository(root)

