from __future__ import annotations

from pathlib import Path

from ..models import Artifact


SUSPICIOUS_MARKERS = (
    "old",
    "backup",
    "copy",
    "final",
    "final2",
    "new",
    "temp",
    "legacy",
    "archive",
)


def find_suspicious(files: list[Path]) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for path in files:
        lowered = path.name.lower()
        hits = [marker for marker in SUSPICIOUS_MARKERS if marker in lowered]
        if not hits:
            continue
        confidence = min(0.6 + 0.1 * len(hits), 0.99)
        artifacts.append(
            Artifact(
                path=path,
                kind="suspicious",
                risk="Medium" if len(hits) == 1 else "High",
                detail=f"Matched markers: {', '.join(hits)}",
                confidence=confidence,
            )
        )
    return artifacts

