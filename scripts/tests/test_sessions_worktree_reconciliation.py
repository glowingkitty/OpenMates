#!/usr/bin/env python3
"""Tests for report-only worktree discovery and classification.

The reconciliation report joins session metadata with Git-linked and physical
worktrees. Report-only operation must never mutate repository or session state.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_reconciliation", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_classification_prefers_recorded_reachable_deploy(monkeypatch):
    sessions = load_sessions_module()
    candidate = {
        "session_id": "abcd",
        "path": "/tmp/agent-abcd",
        "idle_hours": 60,
        "changed_files": ["scripts/sessions.py"],
        "metadata": {
            "status": "merged",
            "root_applied_patch_id": "patch-1",
            "merged_commit": "commit-1",
        },
    }
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata: "patch-1")
    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda commit, target: (commit, target) == ("commit-1", "origin/dev"))

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete=set())

    assert result["classification"] == "integrated"
    assert result["reason_code"] == "recorded_patch_reachable"


def test_report_only_reconciliation_does_not_remove_worktrees(monkeypatch):
    sessions = load_sessions_module()
    candidate = {
        "session_id": "orphan",
        "path": "/tmp/agent-orphan",
        "idle_hours": 72,
        "changed_files": ["old.py"],
        "classification": "superseded",
    }
    monkeypatch.setattr(sessions, "_discover_worktree_candidates", lambda: [candidate])
    monkeypatch.setattr(
        sessions,
        "_remove_reconciled_worktree",
        lambda _item: (_ for _ in ()).throw(AssertionError("report-only mutated state")),
    )

    report = sessions.reconcile_session_worktrees(target_ref="origin/dev", idle_hours=48, apply_safe=False)

    assert report["target_ref"] == "origin/dev"
    assert report["deleted"] == []
    assert report["items"][0]["classification"] == "superseded"


def test_review_approved_obsolete_work_is_not_classified_when_recent(monkeypatch):
    sessions = load_sessions_module()
    candidate = {
        "session_id": "recent",
        "path": "/tmp/agent-recent",
        "idle_hours": 4,
        "changed_files": ["new.py"],
        "metadata": {},
    }
    monkeypatch.setattr(sessions, "_worktree_target_files_match", lambda _candidate, _target: False)

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete={"recent"})

    assert result["classification"] == "recent_active"


def test_inspection_error_is_never_safe_deletable():
    sessions = load_sessions_module()
    candidate = {
        "session_id": "broken",
        "path": "/tmp/agent-broken",
        "idle_hours": 100,
        "changed_files": [],
        "inspection_error": "invalid base",
        "head": "reachable",
        "metadata": {},
    }

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete=set())

    assert result["classification"] == "malformed"
    assert result["reason_code"] == "inspection_failed"


def test_review_approved_old_inspection_error_is_superseded():
    sessions = load_sessions_module()
    candidate = {
        "session_id": "broken",
        "path": "/tmp/agent-broken",
        "idle_hours": 100,
        "changed_files": [],
        "inspection_error": "missing worktree metadata",
        "metadata": {},
    }

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete={"broken"})

    assert result["classification"] == "superseded"
    assert result["reason_code"] == "review_approved_obsolete"


def test_remove_unlinked_reviewed_worktree_uses_contained_directory_cleanup(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    worktree = managed / "agent-broken"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "_run_cmd", lambda _cmd: (1, "", "not a working tree"))
    removed: list[Path] = []
    monkeypatch.setattr(sessions.shutil, "rmtree", lambda path: removed.append(Path(path)))

    sessions._remove_reconciled_worktree({"path": str(worktree), "linked": False})

    assert removed == [worktree]


def test_reconciliation_only_filter_limits_immediate_review_scope(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(
        sessions,
        "_discover_worktree_candidates",
        lambda: [
            {"session_id": "selected", "path": "/tmp/agent-selected", "idle_hours": 0, "classification": "superseded"},
            {"session_id": "other", "path": "/tmp/agent-other", "idle_hours": 0, "classification": "integrated"},
        ],
    )

    report = sessions.reconcile_session_worktrees(
        target_ref="origin/dev",
        idle_hours=0,
        apply_safe=False,
        only_session_ids={"selected"},
    )

    assert [item["session_id"] for item in report["items"]] == ["selected"]
