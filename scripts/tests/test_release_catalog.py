#!/usr/bin/env python3
"""
Regression tests for the tag-backed milestone release catalog.

The fixtures use synthetic release metadata so validation and note rendering stay
deterministic without querying GitHub, registries, or maintainer credentials.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

_catalog = importlib.import_module("release_catalog")
ReleaseCatalogError = _catalog.ReleaseCatalogError
render_release_notes = _catalog.render_release_notes
validate_catalog = _catalog.validate_catalog


def valid_catalog() -> dict:
    return {
        "schema_version": 1,
        "milestones": [
            {
                "tag": "v0.10.0-alpha",
                "commit": "a" * 40,
                "title": "v0.10 Alpha: apps, sharing, and payments",
                "prerelease": True,
                "historical_backfill": True,
                "original_release_window": "May 2026",
                "release_notes": "## Highlights\n- A detailed user-facing capability.",
                "artifacts": {
                    "npm": {"version": "0.10.0-alpha.5", "git_head": "a" * 40},
                    "pypi": {"status": "unavailable"},
                    "ghcr": {"status": "unavailable"},
                },
            }
        ],
    }


def test_valid_catalog_renders_only_supported_channels() -> None:
    milestone = validate_catalog(valid_catalog())[0]

    notes = render_release_notes(milestone)

    assert "Historical backfill" in notes
    assert "## Highlights" in notes
    assert "A detailed user-facing capability." in notes
    assert "npm install -g openmates@0.10.0-alpha.5" in notes
    assert "unavailable" not in notes
    assert "Apple" not in notes
    assert "VS Code" not in notes


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tag", "release-0.10", "tag"),
        ("commit", "a" * 39, "commit"),
        ("commit", "main", "commit"),
    ],
)
def test_catalog_rejects_non_immutable_release_identity(field: str, value: str, message: str) -> None:
    catalog = valid_catalog()
    catalog["milestones"][0][field] = value

    with pytest.raises(ReleaseCatalogError, match=message):
        validate_catalog(catalog)


def test_catalog_rejects_duplicate_tags() -> None:
    catalog = valid_catalog()
    catalog["milestones"].append(dict(catalog["milestones"][0]))

    with pytest.raises(ReleaseCatalogError, match="duplicate"):
        validate_catalog(catalog)


def test_catalog_rejects_contradictory_unavailable_artifact() -> None:
    catalog = valid_catalog()
    catalog["milestones"][0]["artifacts"]["pypi"] = {"status": "unavailable", "version": "0.10.0"}

    with pytest.raises(ReleaseCatalogError, match="unavailable"):
        validate_catalog(catalog)


def test_catalog_requires_ghcr_source_revision_to_match_milestone() -> None:
    catalog = valid_catalog()
    catalog["milestones"][0]["artifacts"]["ghcr"] = {
        "tag": "v0.10.0",
        "digest": "sha256:" + "b" * 64,
        "revision": "b" * 40,
    }

    with pytest.raises(ReleaseCatalogError, match="revision"):
        validate_catalog(catalog)


def test_draft_command_requires_an_annotated_tag() -> None:
    milestone = validate_catalog(valid_catalog())[0]

    command = _catalog.build_draft_command(milestone, Path("/tmp/release.md"))

    assert command[:3] == ["gh", "release", "create"]
    assert "--verify-tag" in command
    assert "--draft" in command
    assert "--prerelease" in command
    assert command[command.index("--target") + 1] == "a" * 40


def test_existing_draft_uses_update_command() -> None:
    milestone = validate_catalog(valid_catalog())[0]

    command = _catalog.build_update_command(milestone, Path("/tmp/release.md"))

    assert command[:3] == ["gh", "release", "edit"]
    assert "--draft" in command
    assert "--prerelease" in command
    assert command[command.index("--target") + 1] == "a" * 40
