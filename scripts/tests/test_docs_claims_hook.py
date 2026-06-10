#!/usr/bin/env python3
"""
Regression tests for non-blocking docs impact hook behavior.

The hook is a reminder system, not an edit blocker. It should surface connected
docs and tests whenever documentation or assertion files change, then exit zero
so agents can continue working.

Architecture: docs/specs/docs-claims-enforcement-cleanup/spec.yml
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "docs_claims_impact.py"
HOOK_PATH = PROJECT_ROOT / ".claude" / "hooks" / "docs-claims-impact.sh"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_docs_claims_impact", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_docs_path_reports_linked_assertion_file(tmp_path):
    docs = tmp_path / "docs"
    write(
        docs / "user-guide" / "sharing.md",
        "---\nstatus: active\ndoc_type: how-to\naudience:\n  - everyday-users\nlast_verified: 2026-06-10\nclaims:\n  - id: share-link\n    type: e2e\n    file: tests/share.spec.ts\n    assertion: share-link\n---\n# Sharing\n",
    )
    write(tmp_path / "tests" / "share.spec.ts", "docAssert('share-link', () => {});\n")
    module = load_module()

    impact = module.analyze_paths(["docs/user-guide/sharing.md"], docs_root=docs, repo_root=tmp_path)

    assert impact["changed_docs"] == ["docs/user-guide/sharing.md"]
    assert impact["affected_tests"] == ["tests/share.spec.ts"]
    assert impact["claim_ids"] == ["share-link"]
    assert impact["blocking"] is False


def test_test_path_reports_affected_docs(tmp_path):
    docs = tmp_path / "docs"
    write(
        docs / "architecture" / "sync.md",
        "---\nstatus: active\ndoc_type: explanation\naudience:\n  - contributors\nlast_verified: 2026-06-10\nclaims:\n  - id: sync-contract\n    type: backend\n    file: backend/tests/test_sync.py\n    assertion: sync-contract\n---\n# Sync\n",
    )
    write(tmp_path / "backend" / "tests" / "test_sync.py", 'doc_assert("sync-contract")\n')
    module = load_module()

    impact = module.analyze_paths(["backend/tests/test_sync.py"], docs_root=docs, repo_root=tmp_path)

    assert impact["changed_tests"] == ["backend/tests/test_sync.py"]
    assert impact["affected_docs"] == ["docs/architecture/sync.md"]
    assert impact["claim_ids"] == ["sync-contract"]


def test_shell_hook_is_non_blocking_for_docs_changes():
    payload = {
        "cwd": str(PROJECT_ROOT),
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(PROJECT_ROOT / "docs" / "user-guide" / "sharing.md")},
    }

    result = subprocess.run(
        ["bash", str(HOOK_PATH)],
        cwd=PROJECT_ROOT,
        input=json.dumps(payload),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert "docs impact" in (result.stdout + result.stderr).lower()
