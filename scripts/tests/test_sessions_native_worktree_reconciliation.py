#!/usr/bin/env python3
"""Reconciliation tests for native source and disposable integration worktrees.

Integration checkouts are reproducible from their source patch and dev base, so
stale instances may be removed. Native source worktrees retain the conservative
unique-content policy used by existing sessions.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_native_reconciliation", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_inventory_distinguishes_source_and_integration_worktrees(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    source = managed / "agent-abcd"
    integration = managed / "integration-abcd-123456789abc"
    source.mkdir(parents=True)
    integration.mkdir()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "abcd": {
                        "binding_mode": "native",
                        "worktree": {"path": str(source), "base_commit": "base", "status": "active"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(
        sessions,
        "_linked_git_worktrees",
        lambda: [
            {"path": str(source), "head": "source-head"},
            {"path": str(integration), "head": "integration-head", "detached": "true"},
        ],
    )
    monkeypatch.setattr(sessions, "_candidate_changed_files", lambda *_args: ["changed.py"])
    monkeypatch.setattr(sessions, "_candidate_last_active", lambda *_args: "2026-01-01T00:00:00Z")
    monkeypatch.setattr(sessions, "_hours_since", lambda _value: 100)

    candidates = sessions._discover_worktree_candidates()

    by_kind = {candidate["worktree_kind"]: candidate for candidate in candidates}
    assert by_kind["source"]["session_id"] == "abcd"
    assert by_kind["source"]["binding_mode"] == "native"
    assert by_kind["integration"]["session_id"] == "integration-abcd-123456789abc"


def test_stale_integration_is_disposable_but_source_changes_remain_unique(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    integration = managed / "integration-abcd-123456789abc"
    source = managed / "agent-abcd"
    integration.mkdir(parents=True)
    source.mkdir()
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)

    integration_result = sessions._classify_worktree_candidate(
        {
            "session_id": integration.name,
            "path": str(integration),
            "worktree_kind": "integration",
            "idle_hours": 100,
            "changed_files": ["staged.py"],
            "metadata": {},
        },
        "target",
        48,
        approved_obsolete=set(),
    )
    monkeypatch.setattr(sessions, "_worktree_target_files_match", lambda *_args: False)
    source_result = sessions._classify_worktree_candidate(
        {
            "session_id": "abcd",
            "path": str(source),
            "worktree_kind": "source",
            "idle_hours": 100,
            "changed_files": ["unique.py"],
            "metadata": {},
        },
        "target",
        48,
        approved_obsolete=set(),
    )

    assert integration_result["classification"] == "disposable_integration"
    assert source_result["classification"] == "unique_stale"
