from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from devarch.scanner.core import analyze_repository_root


def _make_repo(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("from .auth import login\n", encoding="utf-8")
    (tmp_path / "src" / "auth.py").write_text("from .session import Session\n\nclass Auth:\n    pass\n", encoding="utf-8")
    (tmp_path / "src" / "session.py").write_text("class Session:\n    pass\n", encoding="utf-8")
    old = tmp_path / "src" / "legacy_auth.py"
    old.write_text("# TODO: remove\nclass LegacyAuth:\n    pass\n", encoding="utf-8")
    ancient_ts = (datetime.now(timezone.utc) - timedelta(days=800)).timestamp()
    os.utime(old, (ancient_ts, ancient_ts))


def test_repository_intelligence_builds_graph(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    analysis = analyze_repository_root(tmp_path)
    intelligence = analysis.intelligence
    assert intelligence.graph_node_count >= 4
    assert intelligence.dna.signature
    assert "PYTHON" in intelligence.dna.signature
    assert intelligence.dependency_hubs
    assert intelligence.architecture is not None
    assert intelligence.survival is not None
    assert intelligence.knowledge_map.core
    assert intelligence.observations
    assert intelligence.forecast.projected_12_months <= intelligence.forecast.current_health


def test_civilizations_and_genealogy(tmp_path: Path) -> None:
    _make_repo(tmp_path)
    analysis = analyze_repository_root(tmp_path)
    intelligence = analysis.intelligence
    assert intelligence.civilizations or intelligence.genealogy
    assert isinstance(intelligence.personality.type, str)
    assert intelligence.incidents
    assert intelligence.weaknesses or intelligence.quake_simulation is not None
