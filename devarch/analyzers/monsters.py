from __future__ import annotations

from dataclasses import dataclass
import ast
from pathlib import Path

from ..models import Artifact
from ..utils.fs import path_kind, read_text


def complexity_from_text(content: str) -> int:
    score = 1
    for token in ("if ", "elif ", "for ", "while ", " and ", " or ", "case ", "except ", "?", "match "):
        score += content.count(token)
    return score


def dependency_count(content: str) -> int:
    count = 0
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("import ") or line.startswith("from "):
            count += 1
        if line.startswith("require(") or "import " in line:
            count += 1
    return count


def find_monsters(
    files: list[Path],
    max_lines: int = 800,
    complexity_threshold: int = 35,
    dependency_threshold: int = 25,
) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for path in files:
        if path_kind(path) != "text":
            continue
        content = read_text(path)
        lines = content.count("\n") + 1
        complexity = complexity_from_text(content)
        deps = dependency_count(content)
        if lines >= max_lines or complexity >= complexity_threshold or deps >= dependency_threshold:
            threat = "Severe" if lines >= max_lines * 2 or complexity >= complexity_threshold * 2 or deps >= dependency_threshold * 2 else "High"
            details = []
            if lines >= max_lines:
                details.append(f"lines={lines}")
            if complexity >= complexity_threshold:
                details.append(f"complexity={complexity}")
            if deps >= dependency_threshold:
                details.append(f"dependencies={deps}")
            artifacts.append(
                Artifact(
                    path=path,
                    kind="monster_file",
                    risk=threat,
                    detail=", ".join(details),
                    confidence=0.9,
                    metadata={"lines": lines, "complexity": complexity, "dependencies": deps},
                )
            )
    return artifacts
