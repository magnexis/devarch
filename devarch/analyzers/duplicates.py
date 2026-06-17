from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re

from ..models import Artifact
from ..utils.fs import path_kind, read_text


def normalize_text(text: str) -> str:
    text = re.sub(r"\"\"\".*?\"\"\"|'''.*?'''", "", text, flags=re.S)
    text = re.sub(r"#.*$", "", text, flags=re.M)
    text = re.sub(r"//.*$", "", text, flags=re.M)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b\d+\b", "0", text)
    return text.strip().lower()


def tokenize_blocks(text: str, block_size: int = 12) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) <= block_size:
        return ["\n".join(lines)] if lines else []
    blocks: list[str] = []
    for index in range(0, len(lines) - block_size + 1):
        blocks.append("\n".join(lines[index : index + block_size]))
    return blocks


def find_duplicates(files: list[Path], text_cache: dict[Path, str]) -> list[Artifact]:
    signatures: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        if path_kind(path) != "text":
            continue
        content = normalize_text(text_cache.get(path, ""))
        if not content:
            continue
        for block in tokenize_blocks(content):
            if len(block.split()) < 10:
                continue
            signatures[block].append(path)

    artifacts: list[Artifact] = []
    seen: set[tuple[Path, Path, str]] = set()
    for block, paths in signatures.items():
        if len(paths) < 2:
            continue
        for idx, left in enumerate(paths):
            for right in paths[idx + 1 :]:
                pair = tuple(sorted((left, right))) + (block,)
                if pair in seen:
                    continue
                seen.add(pair)
                artifacts.append(
                    Artifact(
                        path=left,
                        kind="duplicate_block",
                        risk="Medium",
                        detail=f"Similar to {right}",
                        score=0.85,
                        confidence=0.85,
                        metadata={"match_path": str(right)},
                    )
                )
    return artifacts


def similarity_report(files: list[Path], text_cache: dict[Path, str]) -> list[dict[str, object]]:
    normalized: dict[Path, set[str]] = {}
    for path in files:
        if path_kind(path) != "text":
            continue
        tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]+", normalize_text(text_cache.get(path, ""))))
        if tokens:
            normalized[path] = tokens

    report: list[dict[str, object]] = []
    paths = list(normalized)
    for idx, left in enumerate(paths):
        for right in paths[idx + 1 :]:
            a = normalized[left]
            b = normalized[right]
            if not a or not b:
                continue
            intersection = len(a & b)
            union = len(a | b)
            if not union:
                continue
            similarity = round((intersection / union) * 100, 1)
            if similarity >= 65:
                report.append(
                    {
                        "left": str(left),
                        "right": str(right),
                        "similarity": similarity,
                    }
                )
    return sorted(report, key=lambda item: item["similarity"], reverse=True)

