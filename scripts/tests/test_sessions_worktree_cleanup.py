#!/usr/bin/env python3
"""Tests for bounded automatic cleanup of stale agent worktrees.

Cleanup may remove only old worktrees with an integration-safe classification.
Safe reconciliation preserves recent, unique, and uncertain work, while the
separate 72-hour hard expiry removes every managed classification. Deletion
manifests intentionally retain metadata but no source or patch content.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_cleanup", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_safe_cleanup_deletes_only_old_integrated_worktrees(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({"sessions": {"old": {}, "recent": {}, "unique": {}}}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(
        sessions,
        "_discover_worktree_candidates",
        lambda: [
            {"session_id": "old", "path": "/tmp/old", "idle_hours": 60, "classification": "integrated", "changed_files": ["a.py"]},
            {"session_id": "recent", "path": "/tmp/recent", "idle_hours": 2, "classification": "integrated", "changed_files": ["b.py"]},
            {"session_id": "unique", "path": "/tmp/unique", "idle_hours": 60, "classification": "unique_stale", "changed_files": ["c.py"]},
        ],
    )
    removed: list[str] = []
    monkeypatch.setattr(sessions, "_remove_reconciled_worktree", lambda item: removed.append(item["session_id"]))
    monkeypatch.setattr(sessions, "_refresh_reconciliation_candidate", lambda item, *_args, **_kwargs: item)

    report = sessions.reconcile_session_worktrees(target_ref="origin/dev", idle_hours=48, apply_safe=True)

    assert removed == ["old"]
    assert report["deleted"] == ["old"]
    assert {item["session_id"] for item in report["unresolved"]} == {"recent", "unique"}
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert "old" not in data["sessions"]
    manifest = data["worktree_deletion_manifests"][0]
    assert manifest["session_id"] == "old"
    assert manifest["reason"] == "integrated"
    assert manifest["changed_file_count"] == 1
    assert "patch" not in manifest
    assert "content" not in manifest


def test_safe_cleanup_revalidates_recent_activity_before_deletion(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({"sessions": {"old": {}}}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(
        sessions,
        "_discover_worktree_candidates",
        lambda: [{"session_id": "old", "path": "/tmp/old", "idle_hours": 60, "classification": "integrated", "changed_files": []}],
    )
    monkeypatch.setattr(
        sessions,
        "_refresh_reconciliation_candidate",
        lambda item, *_args, **_kwargs: {**item, "idle_hours": 0, "classification": "recent_active"},
    )
    monkeypatch.setattr(
        sessions,
        "_remove_reconciled_worktree",
        lambda _item: (_ for _ in ()).throw(AssertionError("recent worktree was removed")),
    )

    report = sessions.reconcile_session_worktrees(target_ref="origin/dev", idle_hours=48, apply_safe=True)

    assert report["deleted"] == []
    assert report["unresolved"][0]["classification"] == "recent_active"


def test_cleanup_prunes_manifests_after_thirty_days(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {},
                "worktree_deletion_manifests": [
                    {"session_id": "expired", "deleted_at": "2026-06-01T00:00:00Z"},
                    {"session_id": "current", "deleted_at": "2026-08-03T00:00:00Z"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_hours_since", lambda value: 1000 if "06-01" in value else 24)
    monkeypatch.setattr(sessions, "_discover_worktree_candidates", lambda: [])

    sessions.reconcile_session_worktrees(target_ref="origin/dev", idle_hours=48, apply_safe=True)

    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert [item["session_id"] for item in data["worktree_deletion_manifests"]] == ["current"]


def test_orphan_activity_fallback_ignores_recent_directory_metadata(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-old"
    worktree.mkdir()
    source = worktree / "AGENTS.md"
    source.write_text("old", encoding="utf-8")
    old_timestamp = 1_700_000_000
    source.touch()
    monkeypatch.setattr(sessions.os.path, "getmtime", lambda _path: old_timestamp)

    last_active = sessions._candidate_last_active({}, {}, worktree, [])

    assert last_active == sessions.datetime.fromtimestamp(old_timestamp, sessions.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_reconciliation_report_persists_unresolved_health_summary(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    report_path = tmp_path / "worktree-reconciliation.json"
    monkeypatch.setattr(sessions, "WORKTREE_RECONCILIATION_REPORT", report_path)
    report = {
        "target_ref": "origin/dev",
        "target_commit": "abc123",
        "apply_safe": True,
        "items": [
            {"session_id": "recent", "classification": "recent_active"},
            {"session_id": "unique", "classification": "unique_stale"},
        ],
        "deleted": [],
        "unresolved": [
            {"session_id": "recent", "classification": "recent_active"},
            {"session_id": "unique", "classification": "unique_stale"},
        ],
    }

    sessions._write_worktree_reconciliation_report(report)

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["status"] == "warning"
    assert saved["counts"] == {"recent_active": 1, "unique_stale": 1}
    assert saved["unresolved_stale"] == 1
    assert saved["deleted"] == 0


def test_reconciliation_started_marker_replaces_stale_health(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    report_path = tmp_path / "worktree-reconciliation.json"
    report_path.write_text('{"status": "ok"}\n', encoding="utf-8")
    monkeypatch.setattr(sessions, "WORKTREE_RECONCILIATION_REPORT", report_path)

    sessions._write_worktree_reconciliation_started("origin/dev")

    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["status"] == "running"
    assert saved["target_ref"] == "origin/dev"


def test_hard_expiry_deletes_every_classification_after_seventy_two_hours(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    old_unique = managed / "agent-old"
    recent_active = managed / "agent-recent"
    old_unique.mkdir(parents=True)
    recent_active.mkdir()
    now = time.time()
    os.utime(old_unique, (now - 73 * 3600, now - 73 * 3600))
    os.utime(recent_active, (now - 2 * 3600, now - 2 * 3600))
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "old": {"writing": "source.py", "worktree": {"path": str(old_unique), "status": "active"}},
                    "recent": {"worktree": {"path": str(recent_active), "status": "active"}},
                },
                "deploy_queue": [{"session_id": "old"}, {"session_id": "recent"}],
                "edit_leases": {"source.py": {"session_id": "old"}, "recent.py": {"session_id": "recent"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "_linked_git_worktrees", lambda: [])
    removed: list[Path] = []
    monkeypatch.setattr(sessions, "_remove_expired_worktree", lambda item: removed.append(Path(item["path"])))
    deleted_refs: list[str] = []
    monkeypatch.setattr(sessions, "_delete_worktree_checkpoint_ref", lambda sid: deleted_refs.append(sid) or True)

    report = sessions.expire_managed_worktrees(max_age_hours=72, now_timestamp=now)

    assert removed == [old_unique]
    assert report["deleted"] == ["old"]
    assert report["retained"] == ["recent"]
    assert deleted_refs == ["old"]
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert set(data["sessions"]) == {"recent"}
    assert data["deploy_queue"] == [{"session_id": "recent"}]
    assert data["edit_leases"] == {"recent.py": {"session_id": "recent"}}
    manifest = data["worktree_deletion_manifests"][-1]
    assert manifest["session_id"] == "old"
    assert manifest["reason"] == "hard_max_age_72h"
    assert "patch" not in manifest
    assert "content" not in manifest


def test_worktree_capacity_refuses_before_creation_when_limits_are_breached(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    managed.mkdir()
    for index in range(3):
        (managed / f"agent-{index}").mkdir()
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "WORKTREE_MAX_COUNT", 3)
    monkeypatch.setattr(sessions, "WORKTREE_MIN_FREE_BYTES", 0)
    monkeypatch.setattr(sessions, "WORKTREE_MAX_DISK_PERCENT", 100)
    monkeypatch.setattr(sessions, "expire_managed_worktrees", lambda **_kwargs: {"deleted": []})

    with pytest.raises(RuntimeError, match="worktree count limit"):
        sessions._enforce_worktree_creation_capacity()
