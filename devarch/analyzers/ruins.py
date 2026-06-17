from __future__ import annotations

from pathlib import Path
import re

from ..models import Artifact
from ..utils.fs import ASSET_EXTENSIONS, path_kind, read_text


def find_empty_directories(directories: list[Path], files: list[Path]) -> list[Artifact]:
    file_set = set(files)
    artifacts: list[Artifact] = []
    for directory in directories:
        if directory.exists() and not any(child for child in directory.iterdir() if child not in file_set):
            artifacts.append(
                Artifact(
                    path=directory,
                    kind="empty_directory",
                    risk="Low",
                    detail="Empty directory",
                    confidence=1.0,
                )
            )
    return artifacts


def find_unused_assets(files: list[Path], text_cache: dict[Path, str]) -> list[Artifact]:
    assets = [path for path in files if path.suffix.lower() in ASSET_EXTENSIONS]
    if not assets:
        return []
    combined = "\n".join(text_cache.values()).lower()
    artifacts: list[Artifact] = []
    for asset in assets:
        if asset.name.lower() not in combined and asset.stem.lower() not in combined:
            artifacts.append(
                Artifact(
                    path=asset,
                    kind="unused_asset",
                    risk="Medium",
                    detail="No obvious textual references",
                    confidence=0.72,
                )
            )
    return artifacts

