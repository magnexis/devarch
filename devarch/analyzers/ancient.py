from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..models import Artifact
from ..utils.fs import path_kind, safe_stat


@dataclass(slots=True)
class AncientStats:
    total: int
    unreferenced: int


def file_age_days(path: Path) -> int:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return max((datetime.now(timezone.utc) - modified).days, 0)


def find_ancient_files(
    files: list[Path],
    references: dict[Path, set[Path]],
    threshold_days: int = 365,
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for path in files:
        if path_kind(path) == "binary":
            continue
        age = file_age_days(path)
        referenced = path in references and bool(references[path])
        if age >= threshold_days or (age >= 180 and not referenced):
            risk = "High" if age >= 730 or not referenced else "Medium"
            status = "Unreferenced" if not referenced else "Referenced"
            artifacts.append(
                Artifact(
                    path=path,
                    kind="ancient_file",
                    risk=risk,
                    age_days=age,
                    size_bytes=safe_stat(path),
                    detail=status,
                    confidence=0.84 if not referenced else 0.7,
                )
            )
    return artifacts

