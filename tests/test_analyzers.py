from __future__ import annotations

from pathlib import Path

from devarch.analyzers.ancient import find_ancient_files
from devarch.analyzers.dead_code import find_dead_code
from devarch.analyzers.duplicates import find_duplicates
from devarch.analyzers.health import calculate_health
from devarch.analyzers.monsters import find_monsters
from devarch.analyzers.ruins import find_empty_directories, find_unused_assets
from devarch.analyzers.suspicious import find_suspicious
from devarch.analyzers.todos import find_todos


def test_todo_detection(tmp_path: Path) -> None:
    file = tmp_path / "app.py"
    file.write_text("x = 1\n# TODO: refactor this\n", encoding="utf-8")
    findings = find_todos([file])
    assert len(findings) == 1
    assert findings[0].severity == "MEDIUM"


def test_suspicious_detection(tmp_path: Path) -> None:
    file = tmp_path / "report_final_copy.py"
    file.write_text("print('x')\n", encoding="utf-8")
    artifacts = find_suspicious([file])
    assert len(artifacts) == 1
    assert artifacts[0].confidence and artifacts[0].confidence >= 0.7


def test_health_scoring_moves_with_debt() -> None:
    good = calculate_health(
        total_files=10,
        dead_code_count=0,
        duplicate_count=0,
        ancient_count=0,
        todo_count=0,
        monster_count=0,
        ruin_count=0,
        suspicious_count=0,
    )
    bad = calculate_health(
        total_files=10,
        dead_code_count=8,
        duplicate_count=5,
        ancient_count=4,
        todo_count=20,
        monster_count=3,
        ruin_count=4,
        suspicious_count=5,
    )
    assert good.score > bad.score
    assert bad.score < 60


def test_duplicate_detection(tmp_path: Path) -> None:
    left = tmp_path / "a.py"
    right = tmp_path / "b.py"
    block = "\n".join(f"line {i}" for i in range(20))
    left.write_text(block, encoding="utf-8")
    right.write_text(block, encoding="utf-8")
    artifacts = find_duplicates([left, right], {left: block, right: block})
    assert artifacts


def test_monster_detection(tmp_path: Path) -> None:
    file = tmp_path / "monster.py"
    file.write_text("\n".join("if x: pass" for _ in range(900)), encoding="utf-8")
    artifacts = find_monsters([file])
    assert artifacts


def test_dead_code_detection(tmp_path: Path) -> None:
    root = tmp_path
    app = root / "app.py"
    other = root / "unused.py"
    app.write_text("import os\nprint('hi')\n", encoding="utf-8")
    other.write_text("def x():\n    return 1\n", encoding="utf-8")
    text_cache = {app: app.read_text(encoding="utf-8"), other: other.read_text(encoding="utf-8")}
    artifacts = find_dead_code(root, [app, other], text_cache)
    assert artifacts


def test_ancient_and_ruins(tmp_path: Path) -> None:
    old = tmp_path / "legacy.py"
    old.write_text("print('old')\n", encoding="utf-8")
    empty_dir = tmp_path / "old_dir"
    empty_dir.mkdir()
    references = {}
    ancient = find_ancient_files([old], references, threshold_days=0)
    ruins = find_empty_directories([empty_dir], [old]) + find_unused_assets([old], {})
    assert ancient
    assert ruins

