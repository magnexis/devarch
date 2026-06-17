from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from ..models import Artifact
from ..utils.fs import RepoView, collect_repository, path_kind, read_text, safe_stat


IMPORT_RE = re.compile(
    r"""(?mx)
    ^\s*(?:from\s+([\w.\-/]+)\s+import|import\s+([\w.\-/]+))
    """
)

REF_RE = re.compile(r"""(?i)\b([A-Za-z0-9_\-/]+\.(?:py|pyi|js|jsx|ts|tsx|md|json|yml|yaml|html|css|svg|png|jpg|jpeg|gif))\b""")


def build_text_index(view: RepoView) -> dict[Path, str]:
    cache: dict[Path, str] = {}
    for path in view.files:
        if path_kind(path) == "text":
            cache[path] = read_text(path)
    return cache


def normalize_ref(root: Path, ref: str) -> Path | None:
    ref = ref.strip().lstrip(".").replace(".", "/")
    candidate = root / ref
    if candidate.exists():
        return candidate.resolve()
    for suffix in ("", ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".json", ".yml", ".yaml", ".html", ".css"):
        p = (root / f"{ref}{suffix}").resolve()
        if p.exists():
            return p
    for suffix in ("", ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".json", ".yml", ".yaml", ".html", ".css"):
        matches = list(root.rglob(f"{ref}{suffix}"))
        if matches:
            return matches[0].resolve()
    return None


def build_reference_map(view: RepoView, text_index: dict[Path, str]) -> dict[Path, set[Path]]:
    references: dict[Path, set[Path]] = defaultdict(set)
    for source_path, content in text_index.items():
        for match in IMPORT_RE.finditer(content):
            target = match.group(1) or match.group(2)
            if not target:
                continue
            normalized = normalize_ref(view.root, target)
            if normalized:
                references[normalized].add(source_path)
        for match in REF_RE.finditer(content):
            ref_path = normalize_ref(view.root, match.group(1))
            if ref_path:
                references[ref_path].add(source_path)
    return references


def file_age_days(path: Path, git_last_commit_ts: int | None = None) -> int:
    from datetime import datetime, timezone

    if git_last_commit_ts is not None:
        modified = datetime.fromtimestamp(git_last_commit_ts, tz=timezone.utc)
    else:
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    return max((now - modified).days, 0)


def iter_repo_files(root: Path) -> list[Path]:
    return collect_repository(root).files


def artifact(path: Path, kind: str, risk: str, detail: str, **metadata: object) -> Artifact:
    return Artifact(
        path=path,
        kind=kind,
        risk=risk,
        size_bytes=safe_stat(path),
        detail=detail,
        metadata=dict(metadata),
    )
