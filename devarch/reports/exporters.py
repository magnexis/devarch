from __future__ import annotations

import json
from pathlib import Path

from ..models import ScanSummary


def _confidence_text(value: float | None) -> str:
    return f"{value:.0%}" if value is not None else "n/a"


def _load_maintenance(root: Path) -> dict[str, object]:
    state_dir = root / ".devarch"
    baseline_path = state_dir / "baseline.json"
    history_path = state_dir / "history.jsonl"
    data: dict[str, object] = {"baseline": None, "history_entries": 0}
    if baseline_path.exists():
        try:
            data["baseline"] = json.loads(baseline_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data["baseline"] = None
    if history_path.exists():
        data["history_entries"] = sum(1 for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip())
    return data


def summary_to_dict(summary: ScanSummary) -> dict[str, object]:
    return {
        "root": str(summary.root),
        "scanned_at": summary.scanned_at.isoformat(),
        "total_files": summary.total_files,
        "artifact_count": summary.artifact_count,
        "ancient_count": summary.ancient_count,
        "todo_count": summary.todo_count,
        "duplicate_count": summary.duplicate_count,
        "dead_code_count": summary.dead_code_count,
        "monster_count": summary.monster_count,
        "ruin_count": summary.ruin_count,
        "suspicious_count": summary.suspicious_count,
        "technical_debt_estimate": summary.technical_debt_estimate,
        "health_score": summary.health_score,
        "health_status": summary.health_status,
        "warnings": summary.warnings,
        "timeline": summary.timeline,
        "extra": summary.extra,
        "maintenance": _load_maintenance(summary.root),
        "artifacts": [
            {
                "path": str(item.path),
                "kind": item.kind,
                "risk": item.risk,
                "score": item.score,
                "age_days": item.age_days,
                "size_bytes": item.size_bytes,
                "line_number": item.line_number,
                "detail": item.detail,
                "confidence": item.confidence,
                "metadata": item.metadata,
            }
            for item in summary.artifacts
        ],
    }


def export_json(summary: ScanSummary, destination: Path) -> Path:
    destination.write_text(json.dumps(summary_to_dict(summary), indent=2), encoding="utf-8")
    return destination


def export_markdown(summary: ScanSummary, destination: Path) -> Path:
    data = summary_to_dict(summary)
    dna = ", ".join(summary.extra.get("dna", {}).get("signature", [])) or "n/a"
    personality = summary.extra.get("personality", {}).get("type", "n/a")
    architecture = summary.extra.get("architecture", {})
    survival = summary.extra.get("survival", {})
    forecast = summary.extra.get("forecast", {})
    maintenance = data.get("maintenance", {})
    baseline = maintenance.get("baseline") or {}
    lines = [
        "# Dev Archaeologist Excavation Report",
        "",
        f"- Root: `{data['root']}`",
        f"- Scanned at: `{data['scanned_at']}`",
        f"- Health: **{summary.health_score}/100** ({summary.health_status})",
        f"- Technical debt estimate: `{summary.technical_debt_estimate:.1f}`",
        f"- DNA signature: `{dna}`",
        f"- Personality: `{personality}`",
        f"- Architecture: `{architecture.get('primary', 'n/a')} / {architecture.get('secondary', 'n/a')}`",
        f"- Survival score: `{survival.get('score', 'n/a')}`",
        f"- Forecast 6 months: `{forecast.get('projected_6_months', 'n/a')}`",
        f"- Forecast 12 months: `{forecast.get('projected_12_months', 'n/a')}`",
        f"- Baseline health: `{baseline.get('health_score', 'n/a')}`",
        f"- Maintenance history entries: `{maintenance.get('history_entries', 0)}`",
        "",
        "## Metrics",
        "",
        f"- Total files: {summary.total_files}",
        f"- Artifacts: {summary.artifact_count}",
        f"- Ancient files: {summary.ancient_count}",
        f"- TODOs: {summary.todo_count}",
        f"- Duplicates: {summary.duplicate_count}",
        f"- Dead code candidates: {summary.dead_code_count}",
        f"- Monster files: {summary.monster_count}",
        f"- Ruins: {summary.ruin_count}",
        f"- Suspicious files: {summary.suspicious_count}",
        "",
        "## Warnings",
        "",
    ]
    lines.extend(f"- {warning}" for warning in (summary.warnings or ["None"]))
    lines.extend(["", "## Intelligence", ""])
    lines.append(f"- Dependency hubs: {len(summary.extra.get('dependency_hubs', []))}")
    lines.append(f"- Civilizations: {len(summary.extra.get('civilizations', []))}")
    lines.append(f"- Heatmap buckets: {len(summary.extra.get('debt_heatmap', []))}")
    lines.append(f"- Structural weaknesses: {len(summary.extra.get('weaknesses', []))}")
    lines.append(f"- Investigations: {len(summary.extra.get('investigation', []))}")
    lines.append(f"- Containment zones: {len(summary.extra.get('containment_zones', []))}")
    lines.append(f"- Remediation findings: {len(summary.extra.get('remediation', []))}")
    lines.extend(["", "## Artifacts", ""])
    for artifact in summary.artifacts:
        lines.extend(
            [
                f"### {artifact.kind}",
                f"- Path: `{artifact.path}`",
                f"- Risk: {artifact.risk}",
                f"- Confidence: {_confidence_text(artifact.confidence)}",
                f"- Detail: {artifact.detail or 'n/a'}",
            ]
        )
        if artifact.age_days is not None:
            lines.append(f"- Age: {artifact.age_days} days")
        if artifact.line_number is not None:
            lines.append(f"- Line: {artifact.line_number}")
        lines.append("")
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def export_html(summary: ScanSummary, destination: Path) -> Path:
    rows = "\n".join(
        f"<tr><td>{artifact.path}</td><td>{artifact.kind}</td><td>{artifact.risk}</td><td>{_confidence_text(artifact.confidence)}</td><td>{artifact.detail}</td></tr>"
        for artifact in summary.artifacts
    )
    warnings = "".join(f"<li>{warning}</li>" for warning in (summary.warnings or ["None"]))
    dna = ", ".join(summary.extra.get("dna", {}).get("signature", [])) or "n/a"
    personality = summary.extra.get("personality", {}).get("type", "n/a")
    architecture = summary.extra.get("architecture", {})
    survival = summary.extra.get("survival", {})
    forecast = summary.extra.get("forecast", {})
    maintenance = summary_to_dict(summary).get("maintenance", {})
    baseline = maintenance.get("baseline") or {}
    heatmap = "".join(
        f"<tr><td>{item['bucket']}</td><td>{item['score']}</td><td>{item['label']}</td><td>{item['files']}</td></tr>"
        for item in summary.extra.get("debt_heatmap", [])
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Dev Archaeologist Report</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0b1020; color: #e5eefc; }}
.card {{ background: #111a33; border: 1px solid #22305f; border-radius: 16px; padding: 1rem 1.25rem; margin-bottom: 1rem; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ border-bottom: 1px solid #22305f; padding: .55rem; text-align: left; vertical-align: top; }}
th {{ color: #9dd3ff; }}
.score {{ font-size: 2rem; font-weight: 700; }}
</style>
</head>
<body>
<div class="card"><div class="score">{summary.health_score}/100</div><div>{summary.health_status}</div></div>
<div class="card"><strong>DNA</strong><div>{dna}</div></div>
<div class="card"><strong>Personality</strong><div>{personality}</div></div>
<div class="card"><strong>Architecture</strong><div>{architecture.get('primary', 'n/a')} / {architecture.get('secondary', 'n/a')}</div></div>
<div class="card"><strong>Survival</strong><div>{survival.get('score', 'n/a')}/100</div></div>
<div class="card"><strong>Forecast</strong><div>6 months: {forecast.get('projected_6_months', 'n/a')} | 12 months: {forecast.get('projected_12_months', 'n/a')}</div></div>
<div class="card"><strong>Baseline</strong><div>{baseline.get('health_score', 'n/a')} | History entries: {maintenance.get('history_entries', 0)}</div></div>
<div class="card"><strong>Remediation</strong><div>{len(summary.extra.get('remediation', []))} findings</div></div>
<div class="card"><strong>Warnings</strong><ul>{warnings}</ul></div>
<div class="card"><strong>Heatmap</strong><table><thead><tr><th>Bucket</th><th>Score</th><th>Label</th><th>Files</th></tr></thead><tbody>{heatmap}</tbody></table></div>
<div class="card"><strong>Artifacts</strong><table><thead><tr><th>Path</th><th>Kind</th><th>Risk</th><th>Confidence</th><th>Detail</th></tr></thead><tbody>{rows}</tbody></table></div>
</body>
</html>"""
    destination.write_text(html, encoding="utf-8")
    return destination


def export_pdf(summary: ScanSummary, destination: Path) -> Path:
    def escape_pdf(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    def build_page(lines: list[str], top: int = 760) -> str:
        commands = ["BT", "/F1 11 Tf", f"40 {top} Td"]
        first = True
        for line in lines:
            safe = escape_pdf(line[:120])
            if first:
                commands.append(f"({safe}) Tj")
                first = False
            else:
                commands.append(f"0 -14 Td ({safe}) Tj")
        commands.append("ET")
        return "\n".join(commands)

    chunks: list[list[str]] = []
    header = [
        "Dev Archaeologist Excavation Report",
        f"Root: {summary.root}",
        f"Health: {summary.health_score}/100 ({summary.health_status})",
        f"Debt estimate: {summary.technical_debt_estimate:.1f}",
        f"DNA: {', '.join(summary.extra.get('dna', {}).get('signature', [])) or 'n/a'}",
        f"Personality: {summary.extra.get('personality', {}).get('type', 'n/a')}",
        f"Architecture: {summary.extra.get('architecture', {}).get('primary', 'n/a')} / {summary.extra.get('architecture', {}).get('secondary', 'n/a')}",
        f"Survival: {summary.extra.get('survival', {}).get('score', 'n/a')}/100",
        f"Forecast 12 months: {summary.extra.get('forecast', {}).get('projected_12_months', 'n/a')}",
        f"Baseline health: {(summary_to_dict(summary).get('maintenance', {}).get('baseline') or {}).get('health_score', 'n/a')}",
        f"Remediation findings: {len(summary.extra.get('remediation', []))}",
        "Warnings:",
    ]
    body = [f"- {warning}" for warning in (summary.warnings or ["None"])]
    body.extend(["Artifacts:"])
    body.extend(
        f"- {artifact.kind}: {artifact.path} ({artifact.risk}, {_confidence_text(artifact.confidence)})"
        for artifact in summary.artifacts[:50]
    )
    lines = header + body
    while lines:
        chunks.append(lines[:40])
        lines = lines[40:]

    objects: list[bytes] = []
    page_objects: list[int] = []

    def add_object(body: str) -> int:
        objects.append(body.encode("utf-8"))
        return len(objects)

    catalog_id = add_object("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add_object("<< /Type /Pages /Kids [] /Count 0 >>")
    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    for chunk in chunks:
        content = build_page(chunk)
        content_id = add_object(f"<< /Length {len(content.encode('utf-8'))} >>\nstream\n{content}\nendstream")
        page_id = add_object(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> >>"
        )
        page_objects.append(page_id)

    kids = " ".join(f"{page} 0 R" for page in page_objects)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_objects)} >>".encode("utf-8")
    objects[catalog_id - 1] = b"<< /Type /Catalog /Pages 2 0 R >>"

    pdf_bytes = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf_bytes))
        pdf_bytes.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf_bytes.extend(body)
        pdf_bytes.extend(b"\nendobj\n")
    xref_offset = len(pdf_bytes)
    pdf_bytes.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf_bytes.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf_bytes.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf_bytes.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    destination.write_bytes(pdf_bytes)
    return destination
