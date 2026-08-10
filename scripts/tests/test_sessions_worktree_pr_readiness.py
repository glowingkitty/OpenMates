#!/usr/bin/env python3
"""Tests for the dev-to-main worktree readiness gate.

Recent work may be explicitly excluded from a release. Unknown, stale, blocked,
or orphaned state remains a hard stop until reconciliation resolves it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_pr_readiness", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_readiness_allows_explicit_recent_exclusion(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(
        sessions,
        "reconcile_session_worktrees",
        lambda **_kwargs: {
            "target_ref": "origin/dev",
            "target_commit": "abc123",
            "items": [{"session_id": "live", "classification": "recent_active"}],
            "unresolved": [],
            "deleted": [],
        },
    )
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"deploy_queue": []})

    report = sessions.worktree_release_readiness(target_ref="origin/dev", excluded_active={"live"})

    assert report["ready"] is True
    assert report["excluded_active"] == ["live"]


def test_readiness_blocks_unresolved_and_blocked_deploys(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(
        sessions,
        "reconcile_session_worktrees",
        lambda **_kwargs: {
            "target_ref": "origin/dev",
            "target_commit": "abc123",
            "items": [{"session_id": "stale", "classification": "unique_stale"}],
            "unresolved": [{"session_id": "stale", "classification": "unique_stale"}],
            "deleted": [],
        },
    )
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"deploy_queue": [{"id": "deploy-old", "status": "blocked"}]})

    report = sessions.worktree_release_readiness(target_ref="origin/dev", excluded_active=set())

    assert report["ready"] is False
    assert report["blocking_worktrees"] == ["stale"]
    assert report["blocked_deploys"] == ["deploy-old"]
