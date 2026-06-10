#!/usr/bin/env python3
"""
Regression tests for deterministic documentation Markdown link validation.

These tests keep broken docs links out of the repository without requiring a
browser, Playwright, or the public docs web app. The validator is intentionally
static so hooks, CI, and local agents can run it cheaply.

Architecture: docs/specs/docs-claims-enforcement-cleanup/spec.yml
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "docs_markdown_links.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openmates_docs_markdown_links", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_relative_markdown_links_must_resolve(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "source.md").write_text(
        "[Existing](./target.md)\n[Missing](./missing.md)\n",
        encoding="utf-8",
    )
    (docs / "target.md").write_text("# Target\n", encoding="utf-8")
    module = load_module()

    findings = module.validate_markdown_links(docs)

    assert [finding.target for finding in findings] == ["./missing.md"]
    assert findings[0].source == docs / "source.md"
    assert "replace, update, remove, fold, or delete" in findings[0].message


def test_docs_specs_links_are_validated_as_git_files(tmp_path):
    docs = tmp_path / "docs"
    (docs / "architecture").mkdir(parents=True)
    (docs / "specs" / "example").mkdir(parents=True)
    (docs / "architecture" / "index.md").write_text(
        "[Spec](../specs/example/spec.yml)\n[Missing spec](../specs/missing/spec.yml)\n",
        encoding="utf-8",
    )
    (docs / "specs" / "example" / "spec.yml").write_text("id: example\n", encoding="utf-8")
    module = load_module()

    findings = module.validate_markdown_links(docs)

    assert [finding.target for finding in findings] == ["../specs/missing/spec.yml"]


def test_external_links_are_not_checked_by_static_validator(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "source.md").write_text(
        "[External](https://example.com/missing.md)\n[Mail](mailto:test@example.com)\n",
        encoding="utf-8",
    )
    module = load_module()

    assert module.validate_markdown_links(docs) == []
