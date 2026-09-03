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
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
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


def test_orphaned_git_metadata_is_quarantined_with_source_bytes(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    control_root = tmp_path / "OpenMates"
    managed = control_root / ".openmates-agent-worktrees"
    worktree = managed / "agent-old"
    missing_gitdir = control_root / ".git" / "worktrees" / "agent-old"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {missing_gitdir}\n", encoding="utf-8")
    (worktree / "recovery.txt").write_text("preserve me\n", encoding="utf-8")
    recovery_root = tmp_path / ".openmates-worktree-recovery"
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", control_root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "WORKTREE_ORPHAN_RECOVERY_DIR", recovery_root)
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "", ""))

    detected = sessions._missing_managed_worktree_gitdir(worktree)
    destination = sessions._quarantine_orphaned_worktree({"path": str(worktree)})

    assert detected == str(missing_gitdir)
    assert not worktree.exists()
    assert destination.parent == recovery_root
    assert (destination / "recovery.txt").read_text(encoding="utf-8") == "preserve me\n"


def test_refresh_does_not_revive_stale_orphan_from_write_markers(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    control_root = tmp_path / "OpenMates"
    worktree = control_root / ".openmates-agent-worktrees" / "agent-old"
    missing_gitdir = control_root / ".git" / "worktrees" / "agent-old"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {missing_gitdir}\n", encoding="utf-8")
    old = "2026-01-01T00:00:00Z"
    session = {
        "last_active": old,
        "writing": "source.py",
        "worktree": {"path": str(worktree), "last_active": old},
    }
    data = {
        "sessions": {"old": session},
        "edit_leases": {"source.py": {"session_id": "old"}},
    }
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", control_root)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", control_root / ".openmates-agent-worktrees")
    monkeypatch.setattr(sessions, "_candidate_changed_files", lambda *_args: [])
    monkeypatch.setattr(sessions, "_hours_since", lambda _value: 100.0)

    refreshed = sessions._refresh_reconciliation_candidate(
        {"session_id": "old", "path": str(worktree), "metadata": session["worktree"]},
        data,
        "target",
        48,
        set(),
    )

    assert refreshed["classification"] == "orphaned_git_metadata"
    assert refreshed["idle_hours"] == 100.0


def test_safe_reconciliation_records_orphan_quarantine(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps({"sessions": {"old": {"worktree": {"path": "/tmp/agent-old"}}}}),
        encoding="utf-8",
    )
    candidate = {
        "session_id": "old",
        "path": "/tmp/agent-old",
        "path_exists": True,
        "missing_gitdir": "/repo/.git/worktrees/agent-old",
        "idle_hours": 100,
        "changed_files": [],
        "inspection_error": "fatal: not a git repository",
        "metadata": {},
    }
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "target", ""))
    monkeypatch.setattr(sessions, "_discover_worktree_candidates", lambda: [candidate])
    monkeypatch.setattr(sessions, "_refresh_reconciliation_candidate", lambda item, *_args: item)
    monkeypatch.setattr(sessions, "_quarantine_orphaned_worktree", lambda _item: Path("/recovery/agent-old"))
    monkeypatch.setattr(
        sessions,
        "_remove_reconciled_worktree",
        lambda _item: (_ for _ in ()).throw(AssertionError("orphan was deleted instead of quarantined")),
    )

    report = sessions.reconcile_session_worktrees(target_ref="origin/dev", idle_hours=48, apply_safe=True)
    data = json.loads(sessions_file.read_text(encoding="utf-8"))

    assert report["deleted"] == ["old"]
    assert "old" not in data["sessions"]
    manifest = data["worktree_deletion_manifests"][0]
    assert manifest["classification"] == "orphaned_git_metadata"
    assert manifest["recovery_path"] == "/recovery/agent-old"
    assert manifest["checkpoint_ref"] == "refs/openmates/checkpoints/old"


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


def test_hard_expiry_deletes_inactive_classifications_but_protects_live_work(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    old_unique = managed / "agent-old"
    old_inactive = managed / "agent-inactive"
    recent_active = managed / "agent-recent"
    old_unique.mkdir(parents=True)
    old_inactive.mkdir()
    recent_active.mkdir()
    now = time.time()
    os.utime(old_unique, (now - 73 * 3600, now - 73 * 3600))
    os.utime(old_inactive, (now - 73 * 3600, now - 73 * 3600))
    os.utime(recent_active, (now - 2 * 3600, now - 2 * 3600))
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "old": {"writing": "source.py", "worktree": {"path": str(old_unique), "status": "active"}},
                    "inactive": {"worktree": {"path": str(old_inactive), "status": "active"}},
                    "recent": {"worktree": {"path": str(recent_active), "status": "active"}},
                },
                "deploy_queue": [{"session_id": "old"}, {"session_id": "inactive"}, {"session_id": "recent"}],
                "edit_leases": {"source.py": {"session_id": "old"}, "recent.py": {"session_id": "recent"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "_linked_git_worktrees", lambda: [])
    monkeypatch.setattr(
        sessions,
        "_hard_expiry_record_is_safely_disposable",
        lambda record: (record["session_id"] == "inactive", "unique_changes"),
    )
    removed: list[Path] = []
    monkeypatch.setattr(sessions, "_remove_expired_worktree", lambda item: removed.append(Path(item["path"])))
    deleted_refs: list[str] = []
    monkeypatch.setattr(sessions, "_delete_worktree_checkpoint_ref", lambda sid: deleted_refs.append(sid) or True)

    report = sessions.expire_managed_worktrees(max_age_hours=72, now_timestamp=now)

    assert removed == [old_inactive]
    assert report["deleted"] == ["inactive"]
    assert report["retained"] == ["old", "recent"]
    assert report["protected_live"] == ["old"]
    assert report["protected_unresolved"] == []
    assert deleted_refs == ["inactive"]
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert set(data["sessions"]) == {"old", "recent"}
    assert data["deploy_queue"] == [{"session_id": "old"}, {"session_id": "recent"}]
    assert data["edit_leases"] == {"source.py": {"session_id": "old"}, "recent.py": {"session_id": "recent"}}
    manifest = data["worktree_deletion_manifests"][-1]
    assert manifest["session_id"] == "inactive"
    assert manifest["reason"] == "hard_max_age_72h"
    assert "patch" not in manifest
    assert "content" not in manifest


def test_hard_expiry_uses_created_at_instead_of_refreshed_directory_mtime(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    worktree = managed / "agent-old"
    worktree.mkdir(parents=True)
    now = time.time()
    os.utime(worktree, (now, now))
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps({
            "sessions": {
                "old": {
                    "started": "2020-01-01T00:00:00Z",
                    "worktree": {
                        "path": str(worktree),
                        "created_at": "2020-01-01T00:00:00Z",
                    },
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "_linked_git_worktrees", lambda: [])

    records = sessions._managed_worktree_records()

    assert len(records) == 1
    assert records[0]["path_timestamp"] == sessions._parse_iso("2020-01-01T00:00:00Z").timestamp()


def test_hard_expiry_disposable_check_protects_unique_and_unmerged_work(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    path = tmp_path / "agent-old"
    path.mkdir()
    record = {
        "path": str(path),
        "metadata": {"path": str(path), "base_commit": "base"},
        "session": {"repo_remote": "origin", "repo_branch": "dev"},
    }

    monkeypatch.setattr(sessions, "_candidate_changed_files", lambda *_args: ["source.py"])
    assert sessions._hard_expiry_record_is_safely_disposable(record) == (False, "unique_changes")

    monkeypatch.setattr(sessions, "_candidate_changed_files", lambda *_args: [])
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "ahead\n", ""))
    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda *_args: False)
    assert sessions._hard_expiry_record_is_safely_disposable(record) == (False, "unmerged_head")

    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda *_args: True)
    assert sessions._hard_expiry_record_is_safely_disposable(record) == (True, "reachable_clean_head")


def test_hard_expiry_uses_bounded_container_fallback_for_root_owned_artifacts(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed_root = tmp_path / "managed"
    worktree = managed_root / "agent-old"
    worktree.mkdir(parents=True)
    (worktree / "root-owned-artifact").write_text("artifact", encoding="utf-8")
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed_root)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", tmp_path / "repo")
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (1, "", "not a working tree"))
    monkeypatch.setattr(
        sessions.shutil,
        "rmtree",
        lambda _path: (_ for _ in ()).throw(PermissionError("permission denied")),
    )
    recovered: list[Path] = []

    def recover(path: Path) -> None:
        recovered.append(path)
        (path / "root-owned-artifact").unlink()
        path.rmdir()

    monkeypatch.setattr(sessions, "_remove_expired_worktree_with_container", recover)

    sessions._remove_expired_worktree({"path": str(worktree), "linked": False})

    assert recovered == [worktree]
    assert not worktree.exists()


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


def test_worktree_capacity_does_not_count_reserved_blocks_as_used(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    managed.mkdir()
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", tmp_path)
    monkeypatch.setattr(sessions, "WORKTREE_MAX_COUNT", 200)
    monkeypatch.setattr(sessions, "WORKTREE_MIN_FREE_BYTES", 0)
    monkeypatch.setattr(sessions, "WORKTREE_MAX_DISK_PERCENT", 85)
    monkeypatch.setattr(sessions, "expire_managed_worktrees", lambda **_kwargs: {"deleted": []})
    monkeypatch.setattr(
        sessions.shutil,
        "disk_usage",
        lambda _path: sessions.shutil._ntuple_diskusage(total=100, used=80, free=15),
    )

    sessions._enforce_worktree_creation_capacity()


def test_chat_deduplication_removes_integrated_older_worktree_and_rebinds_latest(monkeypatch):
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "old1": {"opencode_session_id": None, "worktree": {"path": "/tmp/agent-old1"}},
            "new1": {"opencode_session_id": None, "worktree": {"path": "/tmp/agent-new1"}},
        },
        "deploy_queue": [],
        "edit_leases": {},
    }
    candidates = [
        {
            "session_id": "old1",
            "path": "/tmp/agent-old1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 10,
            "changed_files": ["source.py"],
            "metadata": {"merged_commit": "commit-1", "status": "merged"},
        },
        {
            "session_id": "new1",
            "path": "/tmp/agent-new1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 20,
            "changed_files": [],
            "metadata": {"status": "active"},
        },
    ]
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, **_kwargs: (0, "target-commit", ""))
    monkeypatch.setattr(sessions, "_chat_lineage_worktree_candidates", lambda **_kwargs: candidates)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(
        sessions,
        "_classify_worktree_candidate",
        lambda candidate, *_args: {**candidate, "classification": "integrated"},
    )
    monkeypatch.setattr(
        sessions,
        "_refresh_reconciliation_candidate",
        lambda candidate, *_args: {**candidate, "classification": "integrated"},
    )
    removed: list[str] = []
    monkeypatch.setattr(sessions, "_remove_reconciled_worktree", lambda candidate: removed.append(candidate["session_id"]))
    monkeypatch.setattr(sessions, "_worktree_checkpoint_lock", lambda _session_id: nullcontext())
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)

    report = sessions.deduplicate_chat_worktrees(target_ref="origin/dev", apply=True)

    assert removed == ["old1"]
    assert report["deleted"] == ["old1"]
    assert report["checkpointed"] == []
    assert set(data["sessions"]) == {"new1"}
    assert data["sessions"]["new1"]["opencode_session_id"] == "ses_chat"
    assert data["sessions"]["new1"]["opencode_top_level_session_id"] == "ses_chat"
    assert data["worktree_deletion_manifests"][0]["reason_code"] == "duplicate_chat_lineage"


def test_chat_deduplication_checkpoints_unique_older_work_before_removal(monkeypatch):
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "old1": {"worktree": {"path": "/tmp/agent-old1", "base_commit": "base"}},
            "new1": {"worktree": {"path": "/tmp/agent-new1"}},
        },
        "deploy_queue": [],
        "edit_leases": {},
    }
    candidates = [
        {
            "session_id": "old1",
            "path": "/tmp/agent-old1",
            "head": "base",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 10,
            "changed_files": ["source.py"],
            "metadata": {"path": "/tmp/agent-old1", "base_commit": "base"},
        },
        {
            "session_id": "new1",
            "path": "/tmp/agent-new1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 20,
            "changed_files": [],
            "metadata": {"status": "active"},
        },
    ]
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, **_kwargs: (0, "target-commit", ""))
    monkeypatch.setattr(sessions, "_chat_lineage_worktree_candidates", lambda **_kwargs: candidates)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(
        sessions,
        "_classify_worktree_candidate",
        lambda candidate, *_args: {**candidate, "classification": "unique_stale"},
    )
    monkeypatch.setattr(
        sessions,
        "_refresh_reconciliation_candidate",
        lambda candidate, *_args: {**candidate, "classification": "unique_stale"},
    )
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda *_args: "patch-1")
    checkpoints: list[str] = []
    monkeypatch.setattr(
        sessions,
        "_create_worktree_checkpoint_commit",
        lambda session_id, *_args: checkpoints.append(session_id) or "checkpoint-1",
    )
    monkeypatch.setattr(sessions, "_remove_reconciled_worktree", lambda _candidate: None)
    monkeypatch.setattr(sessions, "_worktree_checkpoint_lock", lambda _session_id: nullcontext())
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)

    report = sessions.deduplicate_chat_worktrees(target_ref="origin/dev", apply=True)

    assert checkpoints == ["old1"]
    assert report["deleted"] == ["old1"]
    assert report["checkpointed"] == [
        {
            "session_id": "old1",
            "checkpoint_ref": "refs/openmates/checkpoints/old1",
            "checkpoint_commit": "checkpoint-1",
        }
    ]


def test_chat_deduplication_blocks_partially_removed_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    old_path = tmp_path / "agent-old1"
    old_path.mkdir()
    (old_path / ".git").write_text("gitdir: /removed/worktree\n", encoding="utf-8")
    data = {
        "sessions": {
            "old1": {"worktree": {"path": str(old_path), "base_commit": "base"}},
            "new1": {"worktree": {"path": "/tmp/agent-new1"}},
        },
        "deploy_queue": [],
        "edit_leases": {},
    }
    candidates = [
        {
            "session_id": "old1",
            "path": str(old_path),
            "head": "",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 10,
            "changed_files": [],
            "inspection_error": "invalid gitdir",
            "metadata": {"path": str(old_path), "base_commit": "base"},
        },
        {
            "session_id": "new1",
            "path": "/tmp/agent-new1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 20,
            "changed_files": [],
            "metadata": {"status": "active"},
        },
    ]

    def run_command(command, **_kwargs):
        if command[:3] == ["git", "rev-parse", "origin/dev"]:
            return 0, "target-commit", ""
        if command[:3] == ["git", "rev-parse", "--verify"]:
            return 0, "checkpoint-1", ""
        raise AssertionError(command)

    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "_chat_lineage_worktree_candidates", lambda **_kwargs: candidates)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(
        sessions,
        "_classify_worktree_candidate",
        lambda candidate, *_args: {**candidate, "classification": "malformed"},
    )
    monkeypatch.setattr(
        sessions,
        "_refresh_reconciliation_candidate",
        lambda candidate, *_args: {**candidate, "classification": "malformed"},
    )
    monkeypatch.setattr(sessions, "_worktree_checkpoint_lock", lambda _session_id: nullcontext())
    removed: list[str] = []
    monkeypatch.setattr(sessions, "_remove_reconciled_worktree", lambda candidate: removed.append(candidate["session_id"]))

    report = sessions.deduplicate_chat_worktrees(target_ref="origin/dev", apply=True)

    assert removed == []
    assert report["deleted"] == []
    assert report["checkpointed"] == []
    assert report["blocked"] == [{"session_id": "old1", "reason": "invalid_or_missing_worktree"}]


def test_checkpoint_ref_refuses_unverified_session_id_reuse(monkeypatch):
    sessions = load_sessions_module()
    checkpoint_ref = sessions._worktree_checkpoint_ref("abcd")
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "old-checkpoint", ""))
    monkeypatch.setattr(
        sessions,
        "_load_sessions",
        lambda: {"sessions": {"abcd": {"auto_integration": {"checkpoint_commit": "different"}}}},
    )

    with pytest.raises(RuntimeError, match="unverified provenance"):
        sessions._checkpoint_ref_expected_commit("abcd", checkpoint_ref, "new-checkpoint")


def test_checkpoint_ref_accepts_prior_failed_deploy_checkpoint(monkeypatch):
    sessions = load_sessions_module()
    checkpoint_ref = sessions._worktree_checkpoint_ref("abcd")

    def run_command(command, **_kwargs):
        if command[:3] == ["git", "rev-parse", "--verify"]:
            return 0, "old-checkpoint", ""
        if command[:4] == ["git", "show", "-s", "--format=%s"]:
            return 0, "checkpoint: preserve session abcd", ""
        raise AssertionError(command)

    monkeypatch.setattr(sessions, "_run_cmd", run_command)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: {"sessions": {"abcd": {}}})

    assert sessions._checkpoint_ref_expected_commit("abcd", checkpoint_ref, "new-checkpoint") == "old-checkpoint"


def test_ensure_reactivates_valid_merged_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "managed" / "agent-abcd"
    worktree.mkdir(parents=True)
    data = {
        "sessions": {
            "abcd": {
                "worktree": {
                    "path": str(worktree),
                    "status": "merged",
                    "merged_commit": "abc123456789",
                    "base_commit": "base123",
                }
            }
        }
    }
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(sessions, "link_shared_worktree_resources", lambda _path: [".env"])

    result = sessions.ensure_session_worktree("abcd")

    assert result["status"] == "active"
    assert result["merged_commit"] == "abc123456789"


def test_ensure_rejects_missing_merged_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    missing = tmp_path / "managed" / "agent-abcd"
    data = {"sessions": {"abcd": {"worktree": {"path": str(missing), "status": "merged"}}}}
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))

    with pytest.raises(RuntimeError, match="invalid or missing managed worktree"):
        sessions.ensure_session_worktree("abcd")


def test_chat_deduplication_blocks_fresh_inspection_failure(monkeypatch):
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "old1": {"worktree": {"path": "/tmp/agent-old1"}},
            "new1": {"worktree": {"path": "/tmp/agent-new1"}},
        },
        "deploy_queue": [],
        "edit_leases": {},
    }
    candidates = [
        {
            "session_id": "old1",
            "path": "/tmp/agent-old1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 10,
            "changed_files": [],
            "metadata": {},
        },
        {
            "session_id": "new1",
            "path": "/tmp/agent-new1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 20,
            "changed_files": [],
            "metadata": {},
        },
    ]
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "target-commit", ""))
    monkeypatch.setattr(sessions, "_chat_lineage_worktree_candidates", lambda **_kwargs: candidates)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_worktree_checkpoint_lock", lambda _session_id: nullcontext())
    monkeypatch.setattr(sessions, "_existing_direct_managed_worktree", lambda _path: True)
    monkeypatch.setattr(
        sessions,
        "_refresh_reconciliation_candidate",
        lambda candidate, *_args: {**candidate, "classification": "malformed", "inspection_error": "unreadable"},
    )
    monkeypatch.setattr(
        sessions,
        "_checkpoint_duplicate_worktree",
        lambda *_args: (_ for _ in ()).throw(AssertionError("malformed worktree was checkpointed")),
    )
    monkeypatch.setattr(
        sessions,
        "_remove_reconciled_worktree",
        lambda *_args: (_ for _ in ()).throw(AssertionError("malformed worktree was removed")),
    )

    report = sessions.deduplicate_chat_worktrees(target_ref="origin/dev", apply=True)

    assert report["deleted"] == []
    assert report["blocked"] == [{"session_id": "old1", "reason": "inspection_failed"}]
    assert "old1" in data["sessions"]
    assert data.get("worktree_deletion_manifests", []) == []


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _deployed_source_fixture(tmp_path: Path) -> tuple[Path, Path, str, str]:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test")
    (source / "deployed.txt").write_text("base\n", encoding="utf-8")
    (source / "remaining.txt").write_text("base\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "base")
    base = _git(source, "rev-parse", "HEAD")
    (source / "deployed.txt").write_text("deployed\n", encoding="utf-8")
    _git(source, "commit", "-am", "deployed")
    deployed = _git(source, "rev-parse", "HEAD")
    integration = tmp_path / "integration"
    _git(tmp_path, "clone", str(source), str(integration))
    _git(source, "reset", "--hard", base)
    (source / "deployed.txt").write_text("deployed\n", encoding="utf-8")
    return source, integration, base, deployed


def test_deploy_sync_advances_fully_deployed_source_head(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    source, integration, base, deployed = _deployed_source_fixture(tmp_path)
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda *_args: "patch-1")

    warning = sessions._sync_deployed_files_to_source(
        {"path": str(source), "base_commit": base},
        integration,
        ["deployed.txt"],
        ["deployed.txt"],
        "patch-1",
    )

    assert warning == ""
    assert _git(source, "rev-parse", "HEAD") == deployed
    assert _git(source, "status", "--porcelain") == ""


def test_deploy_sync_preserves_source_edits_made_during_integration(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    source, integration, base, deployed = _deployed_source_fixture(tmp_path)
    (source / "deployed.txt").write_text("later edit\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda *_args: "later-patch")

    warning = sessions._sync_deployed_files_to_source(
        {"path": str(source), "base_commit": base},
        integration,
        ["deployed.txt"],
        ["deployed.txt"],
        "original-patch",
    )

    assert warning == "Source worktree changed during deploy; deployed files were not synchronized."
    assert _git(source, "rev-parse", "HEAD") == base
    assert (source / "deployed.txt").read_text(encoding="utf-8") == "later edit\n"
    assert _git(source, "status", "--porcelain") == "M deployed.txt"


def test_deploy_sync_preserves_unselected_post_checkpoint_work(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    source, integration, base, deployed = _deployed_source_fixture(tmp_path)
    (source / "remaining.txt").write_text("post-checkpoint\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda *_args: "original-patch")

    warning = sessions._sync_deployed_files_to_source(
        {"path": str(source), "base_commit": base},
        integration,
        ["deployed.txt"],
        ["deployed.txt"],
        "original-patch",
    )

    assert warning == ""
    assert _git(source, "rev-parse", "HEAD") == deployed
    assert (source / "remaining.txt").read_text(encoding="utf-8") == "post-checkpoint\n"
    assert _git(source, "status", "--porcelain").splitlines() == ["M remaining.txt"]


def test_deploy_sync_advances_and_preserves_unselected_untracked_work(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    source, integration, base, deployed = _deployed_source_fixture(tmp_path)
    (source / "new-note.txt").write_text("keep me\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda *_args: "original-patch")

    warning = sessions._sync_deployed_files_to_source(
        {"path": str(source), "base_commit": base},
        integration,
        ["deployed.txt"],
        ["deployed.txt"],
        "original-patch",
    )

    assert warning == ""
    assert _git(source, "rev-parse", "HEAD") == deployed
    assert (source / "new-note.txt").read_text(encoding="utf-8") == "keep me\n"


def test_deploy_sync_retains_old_head_when_upstream_changed_remaining_path(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    source, integration, base, deployed = _deployed_source_fixture(tmp_path)
    (integration / "remaining.txt").write_text("upstream\n", encoding="utf-8")
    _git(integration, "add", "remaining.txt")
    _git(integration, "commit", "-m", "upstream remaining")
    deployed_with_overlap = _git(integration, "rev-parse", "HEAD")
    (source / "remaining.txt").write_text("local\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda *_args: "selected-patch")

    warning = sessions._sync_deployed_files_to_source(
        {"path": str(source), "base_commit": base},
        integration,
        ["deployed.txt"],
        ["deployed.txt"],
        "selected-patch",
    )

    assert warning == ""
    assert deployed_with_overlap != deployed
    assert _git(source, "rev-parse", "HEAD") == base
    assert (source / "remaining.txt").read_text(encoding="utf-8") == "local\n"


def test_deploy_sync_removes_clean_path_deleted_upstream(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    source, integration, base, _deployed = _deployed_source_fixture(tmp_path)
    (source / "obsolete.txt").write_text("old\n", encoding="utf-8")
    _git(source, "add", "obsolete.txt")
    _git(source, "commit", "-m", "add obsolete")
    source_base = _git(source, "rev-parse", "HEAD")
    _git(integration, "fetch", str(source), source_base)
    _git(integration, "reset", "--hard", source_base)
    (integration / "deployed.txt").write_text("deployed again\n", encoding="utf-8")
    (integration / "obsolete.txt").unlink()
    _git(integration, "add", "-A")
    _git(integration, "commit", "-m", "deploy and delete obsolete")
    deployed = _git(integration, "rev-parse", "HEAD")
    _git(source, "fetch", str(integration), deployed)
    (source / "deployed.txt").write_text("deployed again\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda *_args: "selected-patch")

    warning = sessions._sync_deployed_files_to_source(
        {"path": str(source), "base_commit": source_base},
        integration,
        ["deployed.txt"],
        ["deployed.txt"],
        "selected-patch",
    )

    assert warning == ""
    assert _git(source, "rev-parse", "HEAD") == deployed
    assert not (source / "obsolete.txt").exists()
    assert _git(source, "status", "--porcelain") == ""


def test_deploy_sync_never_captures_or_rewrites_unselected_staged_work(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    source, integration, base, _deployed = _deployed_source_fixture(tmp_path)
    (source / "remaining.txt").write_text("operator work\n", encoding="utf-8")
    _git(source, "add", "remaining.txt")
    index_before = _git(source, "write-tree")
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda *_args: "selected-patch")

    warning = sessions._sync_deployed_files_to_source(
        {"path": str(source), "base_commit": base},
        integration,
        ["deployed.txt"],
        ["deployed.txt"],
        "selected-patch",
    )

    assert warning == ""
    assert _git(source, "rev-parse", "HEAD") == base
    assert _git(source, "write-tree") == index_before
    assert (source / "remaining.txt").read_text(encoding="utf-8") == "operator work\n"
    assert _git(source, "status", "--porcelain").splitlines() == ["M deployed.txt", "M  remaining.txt"]


def test_chat_deduplication_blocks_lease_acquired_after_discovery(monkeypatch):
    sessions = load_sessions_module()
    data = {
        "sessions": {
            "old1": {"worktree": {"path": "/tmp/agent-old1"}},
            "new1": {"worktree": {"path": "/tmp/agent-new1"}},
        },
        "deploy_queue": [],
        "edit_leases": {},
    }
    candidates = [
        {
            "session_id": "old1",
            "path": "/tmp/agent-old1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 10,
            "changed_files": [],
            "metadata": {},
        },
        {
            "session_id": "new1",
            "path": "/tmp/agent-new1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 20,
            "changed_files": [],
            "metadata": {},
        },
    ]
    monkeypatch.setattr(sessions, "_run_cmd", lambda command, **_kwargs: (0, "target-commit", ""))
    monkeypatch.setattr(sessions, "_chat_lineage_worktree_candidates", lambda **_kwargs: candidates)
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)

    mutation_count = 0
    lock_held = False

    @contextmanager
    def checkpoint_lock(_session_id):
        nonlocal lock_held
        assert not lock_held
        lock_held = True
        try:
            yield
        finally:
            lock_held = False

    def mutate(callback):
        nonlocal mutation_count
        if callback.__name__ != "remove_duplicate":
            assert not lock_held
            return callback(data)
        assert lock_held
        mutation_count += 1
        if mutation_count == 1:
            data["edit_leases"]["source.py"] = {"session_id": "old1"}
        return callback(data)

    monkeypatch.setattr(sessions, "_mutate_sessions", mutate)
    monkeypatch.setattr(sessions, "_worktree_checkpoint_lock", checkpoint_lock)
    monkeypatch.setattr(
        sessions,
        "_remove_reconciled_worktree",
        lambda _candidate: (_ for _ in ()).throw(AssertionError("leased worktree was removed")),
    )

    report = sessions.deduplicate_chat_worktrees(target_ref="origin/dev", apply=True)

    assert report["deleted"] == []
    assert report["blocked"] == [{"session_id": "old1", "reason": "live_edit"}]
    assert "old1" in data["sessions"]
