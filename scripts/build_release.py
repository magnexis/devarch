from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True, exist_ok=True)

    subprocess.run([sys.executable, "-m", "build"], cwd=ROOT, check=True)

    artifacts = sorted(
        path for path in DIST.iterdir() if path.is_file() and path.suffix in {".whl", ".gz"}
    )
    manifest = {
        "project": "devarch",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": [
            {
                "name": artifact.name,
                "size_bytes": artifact.stat().st_size,
                "sha256": _sha256(artifact),
            }
            for artifact in artifacts
        ],
    }

    manifest_path = DIST / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    checksum_lines = [
        f"{entry['sha256']}  {entry['name']}"
        for entry in manifest["artifacts"]
    ]
    (DIST / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    bundle_path = DIST / f"{manifest['project']}-{manifest['artifacts'][0]['name'].split('-')[1]}-release.zip"
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for artifact in artifacts:
            archive.write(artifact, arcname=artifact.name)
    bundle_entry = {
        "name": bundle_path.name,
        "size_bytes": bundle_path.stat().st_size,
        "sha256": _sha256(bundle_path),
    }
    manifest["artifacts"].append(bundle_entry)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    checksum_lines.append(f"{bundle_entry['sha256']}  {bundle_entry['name']}")
    (DIST / "SHA256SUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    print("Release artifacts created:")
    for entry in manifest["artifacts"]:
        print(f"- {entry['name']} ({entry['size_bytes']} bytes)")
    print(f"- {manifest_path.name}")
    print("- SHA256SUMS.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
