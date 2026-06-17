from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from pathspec import PathSpec  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal environments
    class PathSpec:  # type: ignore[no-redef]
        def __init__(self, patterns: list[str]) -> None:
            self.patterns = patterns

        @classmethod
        def from_lines(cls, _style: str, lines: list[str]) -> "PathSpec":
            return cls(lines)

        def match_file(self, rel_path: str) -> bool:
            candidate = rel_path.replace("\\", "/")
            for pattern in self.patterns:
                pattern = pattern.strip()
                if not pattern:
                    continue
                normalized = pattern.replace("\\", "/")
                if normalized.endswith("/"):
                    prefix = normalized[:-1]
                    if candidate == prefix or candidate.startswith(f"{prefix}/"):
                        return True
                elif candidate == normalized or candidate.endswith(f"/{normalized}"):
                    return True
            return False


DEFAULT_IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
}

DEFAULT_IGNORE_FILES = {
    "devarch-report.md",
    "devarch-report.markdown",
    "devarch-report.html",
    "devarch-report.json",
    "devarch-report.pdf",
}

TEXT_EXTENSIONS = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".css",
    ".html",
    ".sh",
    ".bat",
    ".ps1",
    ".mjs",
    ".cjs",
    ".sql",
}

ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".bmp",
    ".mp3",
    ".mp4",
    ".mov",
    ".webm",
    ".wav",
    ".pdf",
    ".zip",
}


@dataclass(slots=True)
class RepoView:
    root: Path
    files: list[Path]
    directories: list[Path]
    ignore_spec: PathSpec | None


def read_gitignore(root: Path) -> PathSpec | None:
    patterns: list[str] = []
    gitignore = root / ".gitignore"
    if gitignore.exists():
        patterns.extend(
            line.strip()
            for line in gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    patterns.extend(f"{name}/" for name in DEFAULT_IGNORE_DIRS)
    patterns.extend(DEFAULT_IGNORE_FILES)
    return PathSpec.from_lines("gitwildmatch", patterns) if patterns else None


def is_ignored(path: Path, root: Path, ignore_spec: PathSpec | None) -> bool:
    rel = path.relative_to(root).as_posix()
    if ignore_spec and ignore_spec.match_file(rel):
        return True
    return False


def collect_repository(root: Path) -> RepoView:
    root = root.resolve()
    ignore_spec = read_gitignore(root)
    files: list[Path] = []
    directories: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            if path == root:
                continue
            if is_ignored(path, root, ignore_spec):
                directories.append(path)
            continue
        if is_ignored(path, root, ignore_spec):
            continue
        files.append(path)
    return RepoView(root=root, files=files, directories=directories, ignore_spec=ignore_spec)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def safe_stat(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def path_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if suffix in ASSET_EXTENSIONS:
        return "asset"
    return "binary"
