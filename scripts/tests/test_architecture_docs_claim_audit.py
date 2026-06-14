#!/usr/bin/env python3
"""
Regression tests for architecture documentation claim coverage audits.

The architecture audit is the completion gate for the architecture-docs claim
coverage spec: every kept active architecture doc must have source-linked,
hardcoded claims or an explicit narrow exception.

Architecture: docs/specs/architecture-docs-claim-coverage/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "docs_architecture_claim_audit.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_docs_architecture_claim_audit", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_audit_reports_weak_architecture_claim_profiles(tmp_path):
    docs = tmp_path / "docs"
    write(
        docs / "architecture" / "weak.md",
        "---\n"
        "status: active\n"
        "doc_type: architecture\n"
        "audience:\n"
        "  - contributors\n"
        "last_verified: 2026-06-11\n"
        "claims: []\n"
        "---\n"
        "# Weak\n\n"
        "This doc mentions code but has no source link.\n",
    )
    write(
        docs / "architecture" / "strong.md",
        "---\n"
        "status: active\n"
        "doc_type: architecture\n"
        "audience:\n"
        "  - contributors\n"
        "last_verified: 2026-06-11\n"
        "claims:\n"
        "  - id: strong-static\n"
        "    type: static\n"
        "    file: scripts/tests/test_architecture_static_claims.py\n"
        "    assertion: strong-static\n"
        "  - id: strong-behavior\n"
        "    type: backend\n"
        "    file: backend/tests/test_strong.py\n"
        "    assertion: strong-behavior\n"
        "  - id: strong-code-anchor\n"
        "    type: static\n"
        "    file: scripts/tests/test_architecture_static_claims.py\n"
        "    assertion: strong-code-anchor\n"
        "---\n"
        "# Strong\n\n"
        "See [service.py](../../backend/service.py) and `run_service`.\n",
    )
    module = load_module()

    report = module.build_architecture_claim_report(docs_root=docs, repo_root=tmp_path)

    assert report["totals"]["architecture_docs_total"] == 2
    assert report["totals"]["active_architecture_docs"] == 2
    assert report["totals"]["active_architecture_docs_with_claims"] == 1
    assert "docs/architecture/weak.md" in report["failures"]["missing_claims"]
    assert "docs/architecture/weak.md" in report["failures"]["missing_source_links"]
    assert report["next_docs_area_recommendation"]


def test_index_docs_can_use_narrow_manual_exception(tmp_path):
    docs = tmp_path / "docs"
    write(
        docs / "architecture" / "README.md",
        "---\n"
        "status: active\n"
        "doc_type: index\n"
        "audience:\n"
        "  - contributors\n"
        "last_verified: 2026-06-11\n"
        "claims:\n"
        "  - id: architecture-index-manual\n"
        "    type: manual\n"
        "    reason: Small index page; link validation covers its targets.\n"
        "---\n"
        "# Architecture\n\n"
        "- [Core](core/security.md)\n",
    )
    module = load_module()

    report = module.build_architecture_claim_report(docs_root=docs, repo_root=tmp_path)

    assert report["failures"]["weak_claim_profiles"] == []
    assert report["totals"]["manual_exceptions"] == 1
