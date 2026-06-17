# Dev Archaeologist

<p align="center">
  <img src="assets/devarch-logo.png" alt="Dev Archaeologist logo" width="220">
</p>

<p align="center">
  <strong>Developed and released by Magnexis</strong>
</p>

<p align="center">
  <em>Software archaeology and repository intelligence from Magnexis<img src="assets/magnexis-logo.png" alt="Magnexis logo" width="35"></em>
</p>


<p align="center">
  <a href="#install"><img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-blue.svg"></a>
  <a href="#license"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-green.svg"></a>
  <a href="#use"><img alt="CLI" src="https://img.shields.io/badge/CLI-devarch-8A6A3A.svg"></a>
  <a href="#project-overview"><img alt="Magnexis" src="https://img.shields.io/badge/Brand-Magnexis-1F1F1F.svg"></a>
  <a href="#release-artifacts"><img alt="Build sdist" src="https://img.shields.io/badge/Build-sdist%20%2B%20wheel-5E4B35.svg"></a>
  <a href="#release-artifacts"><img alt="Release zip" src="https://img.shields.io/badge/Build-release%20zip-444444.svg"></a>
  <a href="#release-artifacts"><img alt="Release manifest" src="https://img.shields.io/badge/Build-manifest%20%2B%20checksums-B8894D.svg"></a>
  <a href="#project-overview"><img alt="Version" src="https://img.shields.io/badge/Version-0.2.0-444444.svg"></a>
</p>

Dev Archaeologist is a Magnexis-built Python CLI for excavating hidden technical debt, structural decay, and forgotten implementation artifacts in software repositories.

It treats every codebase like an archaeological dig site and helps you answer questions like:

- What code is ancient and likely abandoned?
- Where is the repository accumulating risk?
- Which files are structural weak points?
- What can be safely removed, refactored, or archived?
- How is the project evolving over time?

## Project Overview

The tool scans a repository and turns the results into a rich, terminal-first excavation report.

It can surface:

- dead code
- ancient files
- TODO, FIXME, HACK, BUG, TEMP, and XXX markers
- duplicated logic
- unused assets and empty directories
- suspicious backup-style filenames
- oversized, complex "monster" files
- dependency hotspots and fragile chains
- architectural drift and release readiness issues
- remediation suggestions with estimated effort

The design goals are:

- strong terminal UX
- modular analyzers
- readable artifact reports
- release-friendly packaging
- future plugin support

## Magnexis Brand

Dev Archaeologist is presented as part of the Magnexis tooling line.

Brand cues used in this repository:

- the archaeological emblem in the project logo
- the Magnexis name treatment in the README header
- the Magnexis mark used as a small brand seal
- a dedicated brand badge in the top badge row
- consistent earth-toned release and CLI styling

## Installation

Install from PyPI:

```bash
pip install devarch
```

Install with optional extras:

```bash
pip install devarch[extended]
pip install devarch[release]
pip install devarch[test]
```

The `release` extra is useful if you want to build local distributions.

## Quick Start

Run a full excavation over the current directory:

```bash
devarch scan .
```

List every available command:

```bash
devarch help
```

Generate a markdown report:

```bash
devarch export markdown
```

Generate a PDF report:

```bash
devarch report pdf
```

## Release Artifacts

Dev Archaeologist includes a repeatable release build flow for local packaging and CI artifact generation.

Build the release bundle locally:

```bash
pip install .[release]
python scripts/build_release.py
```

This produces the following artifacts in `dist/`:

- `*.whl` for Python wheel distribution
- `*.tar.gz` for source distribution
- `*-release.zip` for a bundled release archive
- `release-manifest.json` for artifact metadata
- `SHA256SUMS.txt` for checksum verification

The zip bundle is convenient for sharing the release set as a single downloadable package.

## Command Reference

### Core excavation

```bash
devarch scan .
devarch help
devarch ancient .
devarch dead-code .
devarch todos .
devarch duplicates .
devarch monsters .
devarch ruins .
devarch suspicious .
devarch inspect src/app.py
devarch trace auth
devarch evidence auth
devarch bugmark src/app.py --line 128
devarch errorcode "ModuleNotFoundError: No module named 'rich'"
```

### Repository intelligence

```bash
devarch dependencies .
devarch genealogy .
devarch civilizations .
devarch debt .
devarch timeline .
devarch personality .
devarch forecast .
devarch explore .
devarch investigate .
devarch weaknesses .
devarch quake .
devarch architecture .
devarch contributors .
devarch mutations .
devarch map .
devarch survival .
devarch notes .
```

### Forensic helpers

```bash
devarch investigate .
devarch inspect src/app.py
devarch trace auth
devarch evidence auth
devarch bugmark src/app.py --line 128
devarch errorcode "ModuleNotFoundError: No module named 'rich'"
```

### Recovery and maintenance

```bash
devarch plan .
devarch delete-check src/legacy_auth.py
devarch refactor .
devarch routes .
devarch configs .
devarch migrations .
devarch deps .
devarch drift .
devarch pr-report .
devarch status .
devarch baseline .
devarch regressions .
devarch budget .
devarch release-check .
devarch ownership .
devarch dependency-health .
devarch cleanup .
devarch standards .
devarch history .
devarch recommend .
devarch prescribe .
devarch repair-plan .
```

### Reporting

```bash
devarch export json
devarch export markdown
devarch export html
devarch report markdown
devarch report html
devarch report pdf
```

## Output Philosophy

Each finding is designed to be actionable instead of just descriptive.

Typical output includes:

- problem
- evidence
- impact
- confidence
- recommended fix
- estimated effort
- risk level

That makes the tool useful not just for audits, but also for cleanup planning, code review, and release preparation.

## Plugin Architecture

Dev Archaeologist exposes a lightweight plugin registry via the `devarch.plugins` entry-point group so future extensions can hook into the excavation pipeline.

Planned extension areas include:

- `devarch-plugin-security`
- `devarch-plugin-ai`
- `devarch-plugin-performance`

## Development

Project layout:

```text
devarch/
├── analyzers/
├── cli/
├── reports/
├── scanner/
├── utils/
└── tests/
```

Useful commands:

```bash
python -m pytest -q
python -m compileall devarch
python scripts/build_release.py
```

## Repository Maintenance

The maintenance engine supports:

- baseline snapshots
- regression detection
- debt budgets
- release readiness checks
- ownership analysis
- dependency health monitoring
- cleanup recommendations
- standards checks
- health history
- remediation prescriptions

## License

MIT
