#!/usr/bin/env python3
# contract-test-file: tooling
"""Tests for deterministic OpenMates alpha product-line bumps."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "bump_alpha_version_line.py"


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: dict) -> None:
    write(path, f"{json.dumps(payload, indent=2)}\n")


def make_fixture(root: Path) -> None:
    write_json(
        root / "shared/config/product_version.json",
        {
            "userFacing": "v0.14",
            "cli": {"stableBase": "0.14.0", "stableFloor": "0.14.5", "prereleaseLabel": "alpha"},
            "python": {"stableBase": "0.14.0", "stableFloor": "0.14.5", "prereleaseLabel": "a"},
        },
    )
    for package_path in [
        "package.json",
        "frontend/packages/openmates-cli/package.json",
        "backend/status/frontend/package.json",
    ]:
        write_json(root / package_path, {"name": Path(package_path).parent.name or "openmates", "version": "0.14.0"})
    write_json(
        root / "frontend/packages/ui/package.json",
        {"name": "@repo/ui", "version": "0.14.0", "dependencies": {"katex": "^0.14.0"}},
    )
    write_json(
        root / "backend/status/frontend/package-lock.json",
        {"name": "status", "version": "0.14.0", "packages": {"": {"version": "0.14.0"}}},
    )
    write(root / "packages/openmates-python/pyproject.toml", '[project]\nname = "openmates"\nversion = "0.14.0"\n')
    write(root / "frontend/packages/ui/src/i18n/sources/signup/main.yml", "version_title:\n  en: v0.14\n")
    write(root / "backend/core/docker-compose.selfhost.yml", "image: openmates-api:${OPENMATES_IMAGE_TAG:-v0.14.0}\n")
    write(root / "docs/contributing/guides/git-and-deployment.md", "Current phase: v0.14 and 0.14.N-alpha.0.\n")
    write(root / ".github/workflows/publish-cli.yml", "dev example 0.14.0-alpha.4, main example 0.14.0\n")
    write(root / ".github/workflows/publish-python-sdk.yml", "dev example 0.14.0a4, main example 0.14.0\n")
    write(root / ".github/workflows/publish-selfhost-images.yml", "image tag example v0.14.0-alpha.0\n")
    write(root / "scripts/prepare_cli_publish_version.mjs", "// prereleases on that exact base, e.g. 0.14.0-alpha.N.\n")


def run_script(root: Path, minor: int, check: bool = False) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), "--root", str(root), "--minor", str(minor)]
    if check:
        args.append("--check")
    return subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)


def test_bump_updates_allowed_version_files(tmp_path: Path) -> None:
    make_fixture(tmp_path)

    result = run_script(tmp_path, 15)

    assert result.returncode == 0, result.stderr
    config = json.loads((tmp_path / "shared/config/product_version.json").read_text(encoding="utf-8"))
    assert config == {
        "userFacing": "v0.15",
        "cli": {"stableBase": "0.15.0", "prereleaseLabel": "alpha"},
        "python": {"stableBase": "0.15.0", "prereleaseLabel": "a"},
    }
    assert json.loads((tmp_path / "frontend/packages/openmates-cli/package.json").read_text(encoding="utf-8"))["version"] == "0.15.0"
    assert json.loads((tmp_path / "backend/status/frontend/package-lock.json").read_text(encoding="utf-8"))["packages"][""]["version"] == "0.15.0"
    assert 'version = "0.15.0"' in (tmp_path / "packages/openmates-python/pyproject.toml").read_text(encoding="utf-8")
    assert "v0.15" in (tmp_path / "frontend/packages/ui/src/i18n/sources/signup/main.yml").read_text(encoding="utf-8")
    assert "v0.15.0" in (tmp_path / "backend/core/docker-compose.selfhost.yml").read_text(encoding="utf-8")
    assert "0.15.N-alpha.0" in (tmp_path / "docs/contributing/guides/git-and-deployment.md").read_text(encoding="utf-8")
    assert "0.15.0-alpha.N" in (tmp_path / "scripts/prepare_cli_publish_version.mjs").read_text(encoding="utf-8")
    assert "^0.14.0" in (tmp_path / "frontend/packages/ui/package.json").read_text(encoding="utf-8")
    assert run_script(tmp_path, 15, check=True).returncode == 0


def test_bump_does_not_touch_github_workflow_examples(tmp_path: Path) -> None:
    make_fixture(tmp_path)

    result = run_script(tmp_path, 15)

    assert result.returncode == 0, result.stderr
    assert "0.14.0-alpha.4" in (tmp_path / ".github/workflows/publish-cli.yml").read_text(encoding="utf-8")
    assert "0.14.0a4" in (tmp_path / ".github/workflows/publish-python-sdk.yml").read_text(encoding="utf-8")
    assert "v0.14.0-alpha.0" in (tmp_path / ".github/workflows/publish-selfhost-images.yml").read_text(encoding="utf-8")


def test_bump_audit_fails_on_stale_active_reference(tmp_path: Path) -> None:
    make_fixture(tmp_path)
    write(tmp_path / "frontend/packages/openmates-cli/README.md", "Still says 0.14.0-alpha.9\n")

    result = run_script(tmp_path, 15, check=True)

    assert result.returncode != 0
    assert "Stale active version references remain" in result.stderr
    assert "frontend/packages/openmates-cli/README.md" in result.stderr
