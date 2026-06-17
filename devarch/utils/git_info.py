from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess


@dataclass(slots=True)
class GitSummary:
    available: bool
    commit_count: int = 0
    repository_age_days: int = 0
    first_commit: datetime | None = None
    last_commit: datetime | None = None
    most_modified_files: list[tuple[str, int]] = None  # type: ignore[assignment]


def _run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def collect_git_summary(root: Path) -> GitSummary:
    log_format = "%ct"
    commit_count_raw = _run_git(root, "rev-list", "--count", "HEAD")
    if commit_count_raw is None:
        return GitSummary(available=False, most_modified_files=[])

    first_commit_raw = _run_git(root, "log", "--reverse", "--format=%ct", "HEAD")
    last_commit_raw = _run_git(root, "log", "-1", "--format=%ct", "HEAD")
    stats_raw = _run_git(root, "log", "--name-only", "--pretty=format:")

    first_commit = datetime.fromtimestamp(int(first_commit_raw.splitlines()[0]), tz=timezone.utc) if first_commit_raw else None
    last_commit = datetime.fromtimestamp(int(last_commit_raw.splitlines()[0]), tz=timezone.utc) if last_commit_raw else None
    repository_age_days = 0
    if first_commit and last_commit:
        repository_age_days = max((last_commit - first_commit).days, 0)

    file_counts: dict[str, int] = {}
    if stats_raw:
        for line in stats_raw.splitlines():
            if line.strip():
                file_counts[line.strip()] = file_counts.get(line.strip(), 0) + 1

    most_modified_files = sorted(file_counts.items(), key=lambda item: item[1], reverse=True)[:10]

    return GitSummary(
        available=True,
        commit_count=int(commit_count_raw),
        repository_age_days=repository_age_days,
        first_commit=first_commit,
        last_commit=last_commit,
        most_modified_files=most_modified_files,
    )

