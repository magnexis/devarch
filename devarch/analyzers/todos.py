from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path

from ..models import Artifact
from ..utils.fs import path_kind, read_text


TODO_PATTERNS = {
    "CRITICAL": re.compile(r"\b(?:FIXME|BUG)\b", re.IGNORECASE),
    "HIGH": re.compile(r"\b(?:HACK|XXX)\b", re.IGNORECASE),
    "MEDIUM": re.compile(r"\b(?:TODO)\b", re.IGNORECASE),
    "LOW": re.compile(r"\b(?:TEMP)\b", re.IGNORECASE),
}


@dataclass(slots=True)
class TodoFinding:
    file: Path
    line: int
    severity: str
    comment: str


def find_todos(files: list[Path]) -> list[TodoFinding]:
    findings: list[TodoFinding] = []
    for path in files:
        if path_kind(path) != "text":
            continue
        content = read_text(path)
        for line_no, line in enumerate(content.splitlines(), start=1):
            for severity, pattern in TODO_PATTERNS.items():
                if pattern.search(line):
                    findings.append(
                        TodoFinding(
                            file=path,
                            line=line_no,
                            severity=severity,
                            comment=line.strip(),
                        )
                    )
                    break
    return findings


def todos_to_artifacts(findings: list[TodoFinding]) -> list[Artifact]:
    return [
        Artifact(
            path=finding.file,
            kind="todo",
            risk=finding.severity,
            line_number=finding.line,
            detail=finding.comment,
            confidence=1.0,
        )
        for finding in findings
    ]

