#!/usr/bin/env python3
# contract-test-file: tooling
"""
Freshness test for the generated Rust migration status document.

The committed document must equal the generator output for the current
config/sdk-capabilities.json, config/cli-command-catalog.json and shared Worker
unit sources. Refresh with `python3 scripts/generate_rust_migration_status.py`.

Architecture: docs/architecture/platforms/rust-migration-status.md
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "scripts" / "generate_rust_migration_status.py"


def doc_assert(_claim_id: str) -> None:
    """Hardcoded marker helper for documentation claims."""


def load_generator():
    spec = importlib.util.spec_from_file_location("openmates_rust_migration_status", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rust_migration_status_is_fresh() -> None:
    doc_assert("arch-platforms-rust-migration-status-fresh")
    generator = load_generator()
    committed = (PROJECT_ROOT / generator.OUTPUT).read_text(encoding="utf-8")
    assert committed == generator.render(), (
        "docs/architecture/platforms/rust-migration-status.md is stale; "
        "run python3 scripts/generate_rust_migration_status.py"
    )


def test_rust_migration_status_is_deterministic() -> None:
    generator = load_generator()
    assert generator.render() == generator.render()


def test_headline_metrics_are_side_by_side() -> None:
    generator = load_generator()
    metrics = generator.sdk_metrics(generator.load_json(generator.SDK_CAPABILITIES))
    assert {m["language"] for m in metrics} == {"rust", "npm", "python"}
    for metric in metrics:
        assert metric["implemented"] <= metric["api"] <= metric["total"]
