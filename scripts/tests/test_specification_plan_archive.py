#!/usr/bin/env python3
"""Completed Plan archive eligibility tests.

Architecture: docs/plans/contract-driven-development/plan.yml
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def load_module():
    path = ROOT / "scripts" / "specifications.py"
    spec = importlib.util.spec_from_file_location("openmates_specification_archive", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_plan(root: Path, *, status: str = "verified") -> Path:
    path = root / "feature" / "plan.yml"
    path.parent.mkdir(parents=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "id": "feature",
                "status": status,
                "specification_refs": [{"id": "feature.example", "version": 1, "role": "primary"}],
                "implementation_state": {"subject_commit": "abc1234"},
            }
        ),
        encoding="utf-8",
    )
    old = (datetime.now(UTC) - timedelta(days=31)).timestamp()
    os.utime(path, (old, old))
    return path


def test_archive_moves_only_complete_cooled_specification_linked_plan(tmp_path):
    module = load_module()
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    path = write_plan(active)

    moved = module.archive_plans(active, archive, cooling_days=30, now=datetime.now(UTC))

    assert not path.exists()
    assert moved == [archive / str(datetime.now(UTC).year) / "feature" / "plan.yml"]
    assert moved[0].exists()


def test_archive_does_not_move_draft_plan_or_offer_delete(tmp_path):
    module = load_module()
    active = tmp_path / "active"
    archive = tmp_path / "archive"
    path = write_plan(active, status="draft")

    assert module.archive_plans(active, archive, cooling_days=30, now=datetime.now(UTC)) == []
    assert path.exists()
    assert "delete" not in module.specification_command_names()
