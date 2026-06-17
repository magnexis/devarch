from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from devarch.cli.main import app


runner = CliRunner()


def test_cli_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Excavate technical debt" in result.stdout


def test_custom_help_and_forensic_commands(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "module.py"
    target.write_text("def run():\n    # TODO: fix this path\n    return 1\n", encoding="utf-8")
    result = runner.invoke(app, ["help"])
    assert result.exit_code == 0
    assert "Command Catalog" in result.stdout
    assert "errorcode" in result.stdout
    assert runner.invoke(app, ["inspect", str(target), str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["trace", "TODO", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["evidence", "module", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["bugmark", str(target), str(tmp_path), "--line", "2"]).exit_code == 0
    error = runner.invoke(app, ["errorcode", "ModuleNotFoundError: No module named 'rich'"])
    assert error.exit_code == 0
    assert "Import failure" in error.stdout


def test_scan_command_on_small_repo(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("# TODO: fix\nprint('hi')\n", encoding="utf-8")
    result = runner.invoke(app, ["scan", str(tmp_path)])
    assert result.exit_code == 0
    assert "Repository Health" in result.stdout
    assert "Remediation Actions" in result.stdout


def test_new_intelligence_commands(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from .core import run\n", encoding="utf-8")
    (tmp_path / "pkg" / "core.py").write_text("from .util import helper\n\ndef run():\n    return helper()\n", encoding="utf-8")
    (tmp_path / "pkg" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    assert runner.invoke(app, ["investigate", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["weaknesses", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["quake", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["architecture", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["contributors", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["mutations", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["map", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["survival", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["notes", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["dependencies", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["personality", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["forecast", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["plan", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["delete-check", "pkg/core.py", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["refactor", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["routes", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["configs", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["migrations", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["deps", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["drift", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["pr-report", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["status", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["baseline", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["regressions", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["budget", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["release-check", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["ownership", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["dependency-health", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["cleanup", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["standards", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["history", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["recommend", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["prescribe", str(tmp_path)]).exit_code == 0
    assert runner.invoke(app, ["repair-plan", str(tmp_path)]).exit_code == 0
    markdown_report = tmp_path / "report.md"
    pdf_report = tmp_path / "report.pdf"
    assert runner.invoke(app, ["report", "markdown", str(tmp_path), "--output", str(markdown_report)]).exit_code == 0
    assert markdown_report.exists()
    assert runner.invoke(app, ["report", "pdf", str(tmp_path), "--output", str(pdf_report)]).exit_code == 0
    assert pdf_report.exists()
