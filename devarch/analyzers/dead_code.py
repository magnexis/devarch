from __future__ import annotations

import ast
import re
from pathlib import Path

from ..models import Artifact
from ..utils.fs import path_kind, read_text


PY_IMPORT_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.MULTILINE)
CODE_EXTENSIONS = {".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
def _module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    return ".".join(rel.parts)


def _has_unreachable_code(content: str) -> bool:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False

    terminal_types = (ast.Return, ast.Raise, ast.Break, ast.Continue)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            terminated = False
            for stmt in node.body:
                if terminated:
                    return True
                terminated = isinstance(stmt, terminal_types)
    return False


def find_dead_code(root: Path, files: list[Path], text_cache: dict[Path, str]) -> list[Artifact]:
    artifacts: list[Artifact] = []
    text_files = [path for path in files if path_kind(path) == "text"]

    imported_modules: set[str] = set()
    for path in text_files:
        content = text_cache.get(path, "")
        for match in PY_IMPORT_RE.finditer(content):
            target = match.group(1) or match.group(2)
            if target:
                imported_modules.add(target.lstrip(".").replace(".", "/"))

    for path in text_files:
        content = text_cache.get(path, "")
        module = _module_name(path, root)
        module_path = module.replace(".", "/")
        if path.suffix.lower() == ".py":
            if "tests" in path.parts or path.name.startswith("test_") or path.name == "conftest.py":
                continue
            if path.name in {"__init__.py", "__main__.py"}:
                continue
            if not any(module_path.endswith(name) or name.endswith(module_path) for name in imported_modules):
                if "if __name__ == \"__main__\"" not in content and "if __name__ == '__main__'" not in content:
                    artifacts.append(
                        Artifact(
                            path=path,
                            kind="dead_code_candidate",
                            risk="Medium",
                            detail="Module is not referenced by obvious imports",
                            confidence=0.62,
                        )
                    )

            if _has_unreachable_code(content):
                artifacts.append(
                    Artifact(
                        path=path,
                        kind="unreachable_code",
                        risk="Low",
                        detail="Function body contains statements after a terminal statement",
                        confidence=0.72,
                        )
                    )
        else:
            if path.suffix.lower() not in CODE_EXTENSIONS:
                continue
            if not any(module_path.endswith(name) or name.endswith(module_path) for name in imported_modules):
                artifacts.append(
                    Artifact(
                        path=path,
                        kind="dead_code_candidate",
                        risk="Low",
                        detail="File is not referenced by obvious imports",
                        confidence=0.5,
                    )
                )

    return artifacts
