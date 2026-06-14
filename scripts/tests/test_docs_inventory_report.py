#!/usr/bin/env python3
"""
Regression tests for documentation inventory and cleanup reporting.

The inventory report is the deterministic input for docs cleanup agents. It
does not decide how to rewrite prose; it exposes objective folder, link, status,
claim, and cloud/self-host boundary facts.

Architecture: docs/specs/docs-claims-enforcement-cleanup/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "docs_inventory.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_docs_inventory", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_inventory_reports_folder_counts_links_and_cleanup_candidates(tmp_path):
    docs = tmp_path / "docs"
    write(
        docs / "architecture" / "platforms" / "web-app.md",
        "---\nstatus: active\ndoc_type: explanation\naudience:\n  - contributors\nlast_verified: 2026-06-10\nclaims:\n  - id: manual-web\n    type: manual\n    reason: fixture\n---\n# Web\n[Core](../core/security.md)\n",
    )
    write(docs / "architecture" / "core" / "security.md", "---\nstatus: active\n---\n# Security\n")
    write(docs / "architecture" / "orphan.md", "# Orphan\n")
    write(docs / "architecture" / "future.md", "---\nstatus: planned\n---\n# Future\n")
    module = load_module()

    report = module.build_inventory(docs)

    assert report["totals"]["markdown_docs"] == 4
    assert report["totals"]["active_docs"] == 2
    assert report["folders"]["architecture/platforms"]["docs"] == 1
    assert "docs/architecture/orphan.md" in report["cleanup_candidates"]["orphan_docs"]
    assert "docs/architecture/future.md" in report["cleanup_candidates"]["invalid_status_docs"]
    assert report["links"]["internal_markdown_links"] == 1


def test_inventory_flags_self_hosting_cloud_payment_language(tmp_path):
    docs = tmp_path / "docs"
    write(
        docs / "self-hosting" / "setup.md",
        "---\nstatus: active\n---\n# Setup\nConfigure Stripe billing for your self-hosted server.\n",
    )
    module = load_module()

    report = module.build_inventory(docs)

    assert "docs/self-hosting/setup.md" in report["cleanup_candidates"]["self_hosting_cloud_payment_docs"]


def test_inventory_tracks_target_structure_presence(tmp_path):
    docs = tmp_path / "docs"
    write(docs / "architecture" / "platforms" / "README.md", "# Platforms\n")
    write(docs / "user-guide" / "billing" / "README.md", "# Billing\n")
    module = load_module()

    report = module.build_inventory(docs)

    assert report["target_structure"]["architecture/platforms"] is True
    assert report["target_structure"]["user-guide/billing"] is True
