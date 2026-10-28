#!/usr/bin/env python3
"""Tests for bounded automatic cleanup of stale agent worktrees.

Cleanup may remove only old worktrees with an integration-safe classification.
Safe reconciliation preserves recent, unique, and uncertain work, while the
separate four-day default expiry archives unique changes before removing idle
worktrees. Deletion manifests retain metadata and archive paths, not source.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import fcntl
import json
import os
import subprocess
import sys
import tarfile
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
    import tempfile
    module._test_expiry_directory = tempfile.TemporaryDirectory(prefix="openmates-expiry-test-")
    module.WORKTREE_EXPIRY_LOCK_FILE = Path(module._test_expiry_directory.name) / "expiry.lock"
    # Expiry unit tests own a synthetic runtime; dedicated tests below exercise
    # the real probes without consulting host services during filesystem tests.
    module._expiry_worktree_has_runtime_references = lambda _path: False
    module._expiry_codex_thread_is_live = lambda _session: False
    module._queue_coordinated_worktree_cleanup = lambda: False
    return module


def test_safe_cleanup_default_retains_integrated_work_under_four_days(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "dev-head", ""))
    monkeypatch.setattr(sessions, "_discover_worktree_candidates", lambda: [
        {"session_id": "old", "path": "/tmp/old", "idle_hours": 120, "classification": "integrated"},
        {"session_id": "recent", "path": "/tmp/recent", "idle_hours": 72, "classification": "integrated"},
    ])

    report = sessions.reconcile_session_worktrees()

    assert {item["session_id"]: item["classification"] for item in report["items"]} == {
        "old": "integrated", "recent": "recent_active",
    }
    assert report["deleted"] == []


def test_cleanup_and_reconciliation_delegate_before_inventory_after_disk_cutover(monkeypatch):
    sessions = load_sessions_module()
    calls = []
    monkeypatch.setattr(sessions, "_queue_coordinated_worktree_cleanup", lambda: calls.append(True) or True)
    monkeypatch.setattr(sessions, "_run_cmd", lambda *a, **k: pytest.fail("independent cleanup inventory"))
    report = sessions.reconcile_session_worktrees(apply_safe=True)
    assert report["queued"] and report["deleted"] == []
    expiry = sessions.expire_managed_worktrees.__wrapped__(max_age_hours=96)
    assert expiry["queued"] and expiry["retained"] == []
    assert len(calls) == 2


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
    os.utime(old_unique, (now - 169 * 3600, now - 169 * 3600))
    os.utime(old_inactive, (now - 169 * 3600, now - 169 * 3600))
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
                "edit_leases": {"source.py": {"session_id": "old", "since": sessions._now_iso()}, "recent.py": {"session_id": "recent"}},
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
    monkeypatch.setattr(sessions, "_archive_expired_worktree", lambda _item: str(tmp_path / "recovery.tar.gz"))
    deleted_refs: list[str] = []
    monkeypatch.setattr(sessions, "_delete_worktree_checkpoint_ref", lambda sid: deleted_refs.append(sid) or True)

    report = sessions.expire_managed_worktrees(max_age_hours=168, now_timestamp=now)

    assert removed == [old_inactive]
    assert report["deleted"] == ["inactive"]
    assert report["retained"] == ["old", "recent"]
    assert report["protected_live"] == ["old"]
    assert report["protected_unresolved"] == []
    assert deleted_refs == ["inactive"]
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert set(data["sessions"]) == {"old", "recent"}
    assert data["deploy_queue"] == [{"session_id": "old"}, {"session_id": "recent"}]
    assert data["edit_leases"]["source.py"]["session_id"] == "old"
    assert data["edit_leases"]["recent.py"] == {"session_id": "recent"}
    manifest = data["worktree_deletion_manifests"][-1]
    assert manifest["session_id"] == "inactive"
    assert manifest["reason"] == "hard_max_age_168h"
    assert "patch" not in manifest
    assert "content" not in manifest
    assert manifest["recovery_archive"] == ""


def test_hard_expiry_defaults_to_four_inactive_days_and_protects_recent_merged_work(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    now = time.time()
    managed = tmp_path / "worktrees"
    records = []
    session_data = {}
    for session_id, age_hours, status, session_idle, worktree_idle in (
        ("old", 120, "active", 120, 120),
        ("recent", 72, "active", 72, 72),
        ("merged-recent", 120, "merged", 120, 1),
        ("ended-recent", 120, "ended", 1, 120),
    ):
        path = managed / f"agent-{session_id}"
        path.mkdir(parents=True)
        session = {
            "last_active": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - session_idle * 3600)),
            "worktree": {
                "path": str(path),
                "status": status,
                "last_active": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - worktree_idle * 3600)),
            },
        }
        session_data[session_id] = session
        records.append({
            "session_id": session_id,
            "path": str(path),
            "path_timestamp": now - age_hours * 3600,
            "session": session,
            "metadata": session["worktree"],
        })
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({"sessions": session_data}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_managed_worktree_records", lambda: records)
    monkeypatch.setattr(sessions, "_hard_expiry_record_is_safely_disposable", lambda _record: (True, "reachable_clean_head"))
    removed = []
    monkeypatch.setattr(sessions, "_remove_expired_worktree", lambda record: removed.append(record["session_id"]))
    monkeypatch.setattr(sessions, "_delete_worktree_checkpoint_ref", lambda _session_id: True)

    report = sessions.expire_managed_worktrees(now_timestamp=now)

    assert removed == ["old"]
    assert report["deleted"] == ["old"]
    assert report["max_age_hours"] == 96
    assert set(report["retained"]) == {"recent", "merged-recent", "ended-recent"}
    assert set(report["protected_live"]) == {"merged-recent", "ended-recent"}
    assert set(json.loads(sessions_file.read_text())["sessions"]) == {"recent", "merged-recent", "ended-recent"}


def test_hard_expiry_rejects_age_below_four_days(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_managed_worktree_records", lambda: pytest.fail("must reject before discovery"))

    with pytest.raises(ValueError, match="below the configured hard lifetime"):
        sessions.expire_managed_worktrees(max_age_hours=95)


def test_seven_day_expiry_ignores_stale_lifecycle_and_task_bindings(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    now = time.time()
    old_timestamp = now - 8 * 24 * 3600
    stale_activity = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(old_timestamp))
    recent_activity = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
    managed = tmp_path / "worktrees"
    records = []
    session_data = {}
    for session_id, status, last_active in (
        ("merged", "merged", stale_activity),
        ("stale-task", "active", stale_activity),
        ("recent-task", "active", recent_activity),
        ("dirty", "merged", stale_activity),
    ):
        path = managed / f"agent-{session_id}"
        path.mkdir(parents=True)
        session = {
            "codex_task_id": "task-id",
            "last_active": last_active,
            "lifecycle": {"version": sessions.WORKSPACE_LIFECYCLE_VERSION},
            "worktree": {"path": str(path), "status": status},
        }
        session_data[session_id] = session
        records.append({
            "session_id": session_id,
            "path": str(path),
            "path_timestamp": old_timestamp,
            "session": session,
            "metadata": session["worktree"],
        })
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({"sessions": session_data}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_managed_worktree_records", lambda: records)
    monkeypatch.setattr(
        sessions,
        "_hard_expiry_record_is_safely_disposable",
        lambda record: (record["session_id"] != "dirty", "unique_changes"),
    )
    removed = []
    monkeypatch.setattr(sessions, "_remove_expired_worktree", lambda record: removed.append(record["session_id"]))
    monkeypatch.setattr(sessions, "_archive_expired_worktree", lambda _record: str(tmp_path / "recovery.tar.gz"))
    monkeypatch.setattr(sessions, "_verify_expired_worktree_archive_snapshot", lambda *_args: None)
    monkeypatch.setattr(sessions, "_delete_worktree_checkpoint_ref", lambda _session_id: True)
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "", ""))

    report = sessions.expire_managed_worktrees(max_age_hours=168, now_timestamp=now)

    assert sorted(removed) == ["dirty", "merged", "stale-task"]
    assert report["deleted"] == ["dirty", "merged", "stale-task"]
    assert report["protected_live"] == ["recent-task"]
    assert report["protected_unresolved"] == []


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
    monkeypatch.setattr(sessions, "_expiry_ignored_roots", lambda _path: [])
    monkeypatch.setattr(sessions, "_run_cmd", lambda *_args, **_kwargs: (0, "ahead\n", ""))
    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda *_args: False)
    assert sessions._hard_expiry_record_is_safely_disposable(record) == (False, "unmerged_head")

    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda *_args: True)
    assert sessions._hard_expiry_record_is_safely_disposable(record) == (True, "reachable_clean_head")


def test_hard_expiry_detects_ignored_only_user_data(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    path = tmp_path / "agent-old"
    path.mkdir()
    record = {"path": str(path), "metadata": {}, "session": {}}
    monkeypatch.setattr(sessions, "_candidate_changed_files", lambda *_args: [])
    monkeypatch.setattr(sessions, "_expiry_ignored_roots", lambda _path: ["node_modules", "private.env"])

    assert sessions._hard_expiry_record_is_safely_disposable(record) == (False, "unique_ignored_files")


def test_hard_expiry_archives_tracked_untracked_and_head_before_removal(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    path = managed / "agent-old"
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "tracked.txt").write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=path, check=True)
    (path / "tracked.txt").write_text("staged\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=path, check=True)
    (path / "tracked.txt").write_text("after\n", encoding="utf-8")
    (path / "new.txt").write_text("keep me\n", encoding="utf-8")
    os.link(path / "new.txt", path / "hardlink.txt")
    (path / "link.txt").symlink_to("new.txt")
    (path / ".gitignore").write_text("node_modules/\nprivate.env\n", encoding="utf-8")
    (path / "node_modules").mkdir()
    (path / "node_modules" / "generated.bin").write_bytes(b"reproducible")
    (path / "private.env").write_text("valuable\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", path)
    monkeypatch.setattr(sessions, "WORKTREE_EXPIRY_ARCHIVE_DIR", tmp_path / "recovery")
    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda *_args: True)

    archive = Path(sessions._archive_expired_worktree({"session_id": "old", "path": str(path)}))

    assert archive.stat().st_mode & 0o777 == 0o600
    with tarfile.open(archive, "r:gz") as saved:
        names = set(saved.getnames())
        assert names == {"manifest.json", "staged.patch", "working.patch", "untracked/.gitignore", "untracked/new.txt", "untracked/hardlink.txt", "untracked/link.txt", "untracked/private.env"}
        manifest = json.load(saved.extractfile("manifest.json"))
        assert b"staged" in saved.extractfile("staged.patch").read()
        assert b"after" in saved.extractfile("working.patch").read()
        assert saved.extractfile("untracked/new.txt").read() == b"keep me\n"
        for name in ("untracked/new.txt", "untracked/hardlink.txt"):
            assert saved.getmember(name).isfile()
            assert not saved.getmember(name).islnk()
            assert saved.extractfile(name).read() == b"keep me\n"
        assert saved.getmember("untracked/link.txt").linkname == "new.txt"
        assert saved.extractfile("untracked/private.env").read() == b"valuable\n"
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True, check=True).stdout.strip() == manifest["head"]
    sessions._verify_expired_worktree_archive_snapshot({"path": str(path)}, str(archive))
    second_archive = Path(sessions._archive_expired_worktree({"session_id": "old", "path": str(path)}))
    assert second_archive != archive
    assert archive.exists()


def test_hard_expiry_archive_failure_preserves_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    path = managed / "agent-old"
    path.mkdir(parents=True)
    old = time.time() - 8 * 24 * 3600
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "_linked_git_worktrees", lambda: [])
    monkeypatch.setattr(sessions, "_hard_expiry_record_is_safely_disposable", lambda _record: (False, "unique_changes"))
    monkeypatch.setattr(sessions, "_archive_expired_worktree", lambda _record: (_ for _ in ()).throw(RuntimeError("archive failed")))
    monkeypatch.setattr(sessions, "_remove_expired_worktree", lambda _record: pytest.fail("must not remove"))
    os.utime(path, (old, old))

    report = sessions.expire_managed_worktrees(max_age_hours=168)

    assert path.exists()
    assert report["deleted"] == []
    assert report["failures"][0]["session_id"] == "old"


@pytest.mark.parametrize("failure", ["archive_size", "free_space"])
def test_recovery_archive_allocation_is_bounded_before_writing(monkeypatch, tmp_path, failure):
    sessions = load_sessions_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "unique-proof").write_text("preserve")
    monkeypatch.setattr(sessions, "is_valid_managed_worktree_path", lambda _p: True)
    monkeypatch.setattr(sessions, "_expiry_archive_snapshot", lambda _p: ("head", b"", b"", []))
    monkeypatch.setattr(sessions, "WORKTREE_EXPIRY_ARCHIVE_DIR", tmp_path / "recovery")
    if failure == "archive_size":
        monkeypatch.setattr(sessions, "WORKTREE_EXPIRY_MAX_ARCHIVE_BYTES", 100)
    else:
        from collections import namedtuple
        usage = namedtuple("Usage", "total used free")
        monkeypatch.setattr(sessions.shutil, "disk_usage", lambda _p: usage(1000, 900, 100))
    with pytest.raises(RuntimeError, match="worktree retained"):
        sessions._archive_expired_worktree({"path": str(source), "session_id": "source"})
    assert (source / "unique-proof").read_text() == "preserve"
    assert not (tmp_path / "recovery").exists()


def test_hard_expiry_serializes_other_process_and_releases_lock(tmp_path):
    lock_path = tmp_path / "expiry.lock"
    ready = tmp_path / "ready"
    done = tmp_path / "done"
    script = """
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('expiry_child', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.WORKTREE_EXPIRY_LOCK_FILE = pathlib.Path(sys.argv[2])
module._managed_worktree_records = lambda: []
pathlib.Path(sys.argv[3]).write_text('ready')
module.expire_managed_worktrees(max_age_hours=168)
module._managed_worktree_records = lambda: (_ for _ in ()).throw(RuntimeError('intentional'))
try:
    module.expire_managed_worktrees(max_age_hours=168)
except RuntimeError:
    pass
module._managed_worktree_records = lambda: []
module.expire_managed_worktrees(max_age_hours=168)
pathlib.Path(sys.argv[4]).write_text('done')
"""
    with lock_path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        child = subprocess.Popen(
            [sys.executable, "-c", script, str(SESSIONS_PATH), str(lock_path), str(ready), str(done)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert ready.exists()
            time.sleep(0.15)
            assert child.poll() is None
            assert not done.exists()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    stdout, stderr = child.communicate(timeout=5)
    assert child.returncode == 0, (stdout, stderr)
    assert done.exists()


@pytest.mark.parametrize("child_old,child_removal_fails", [(False, False), (True, True)])
def test_hard_expiry_keeps_parent_when_nested_worktree_survives(
    monkeypatch, tmp_path, child_old, child_removal_fails
):
    sessions = load_sessions_module()
    parent = tmp_path / "worktrees" / "agent-parent"
    child = parent / "agent-child"
    child.mkdir(parents=True)
    now = time.time()
    records = [
        {"session_id": "parent", "path": str(parent), "path_timestamp": now - 9 * 24 * 3600, "session": {}, "metadata": {}},
        {"session_id": "child", "path": str(child), "path_timestamp": now - (9 * 24 * 3600 if child_old else 3600), "session": {}, "metadata": {}},
    ]
    monkeypatch.setattr(sessions, "_managed_worktree_records", lambda: records)
    monkeypatch.setattr(sessions, "_hard_expiry_record_is_safely_disposable", lambda _record: (True, "reachable_clean_head"))
    removed = []

    def remove(record):
        removed.append(record["session_id"])
        if child_removal_fails:
            raise RuntimeError("child cleanup failed")

    monkeypatch.setattr(sessions, "_remove_expired_worktree", remove)

    report = sessions.expire_managed_worktrees(max_age_hours=168, now_timestamp=now)

    assert removed == (["child"] if child_old else [])
    assert report["deleted"] == []
    assert any(item["session_id"] == "parent" and item["reason"] == "nested_worktree_retained" for item in report["protected_unresolved"])


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
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)

    result = sessions.ensure_session_worktree("abcd")

    assert result["status"] == "active"
    assert result["merged_commit"] == "abc123456789"


def test_ensure_rejects_missing_merged_worktree(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    missing = tmp_path / "managed" / "agent-abcd"
    data = {"sessions": {"abcd": {"worktree": {"path": str(missing), "status": "merged"}}}}
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)

    with pytest.raises(RuntimeError, match="invalid or missing managed worktree"):
        sessions.ensure_session_worktree("abcd")




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


@pytest.mark.parametrize("guard", ["none", "recent_activity", "valid_lease", "process", "codex"])
def test_hard_expiry_stale_write_marker_requires_current_liveness(monkeypatch, tmp_path, guard):
    sessions = load_sessions_module()
    now = time.time()
    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 200 * 3600))
    session = {"writing": "source.py", "last_active": stale, "worktree": {"path": str(tmp_path)}}
    data = {"sessions": {"old": session}, "edit_leases": {"source.py": {"session_id": "old", "since": stale}}}
    if guard == "recent_activity":
        session["last_active"] = sessions._now_iso()
    if guard == "valid_lease":
        data["edit_leases"]["source.py"]["since"] = sessions._now_iso()
    monkeypatch.setattr(sessions, "_expiry_worktree_has_runtime_references", lambda _p: guard == "process")
    monkeypatch.setattr(sessions, "_expiry_codex_thread_is_live", lambda _s: guard == "codex")
    assert sessions._hard_expiry_record_is_live(
        {"session_id": "old", "path": str(tmp_path)}, data, now_timestamp=now, idle_hours=96,
    ) is (guard != "none")


def _real_runtime_probe():
    spec = importlib.util.spec_from_file_location("sessions_runtime_probe", SESSIONS_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_expiry_runtime_probe_preserves_process_cwd(monkeypatch, tmp_path):
    sessions = _real_runtime_probe()
    monkeypatch.setattr(sessions, "_run_cmd", lambda *a, **kw: (0, "", ""))
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], cwd=tmp_path)
    try:
        assert sessions._expiry_worktree_has_runtime_references(tmp_path)
    finally:
        child.terminate()
        child.wait(timeout=10)


@pytest.mark.parametrize("docker_result", ["mounted", "parent_mounted", "unmounted", "unavailable", "invalid"])
def test_expiry_runtime_probe_checks_container_mounts_and_fails_closed(monkeypatch, tmp_path, docker_result):
    sessions = _real_runtime_probe()
    proc = tmp_path / "empty-proc"
    proc.mkdir()
    real_iterdir = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", lambda p: real_iterdir(proc if p == Path("/proc") else p))
    source = tmp_path / "worktree"
    source.mkdir()
    mount_source = str(source.parent if docker_result == "parent_mounted" else source)
    def run(cmd, **kwargs):
        if cmd[:2] == ["docker", "ps"]:
            if docker_result == "unavailable":
                return 1, "", "unavailable"
            return 0, "container", ""
        if docker_result == "invalid":
            return 0, "invalid json", ""
        mounts = [] if docker_result == "unmounted" else [{"Source": mount_source}]
        return 0, json.dumps([{"Mounts": mounts}]), ""
    monkeypatch.setattr(sessions, "_run_cmd", run)
    assert sessions._expiry_worktree_has_runtime_references(source) is (docker_result != "unmounted")


def test_expiry_runtime_probe_preserves_uninspectable_process(monkeypatch, tmp_path):
    sessions = _real_runtime_probe()
    real_iterdir = Path.iterdir
    def iterdir(path):
        if path == Path('/proc'):
            raise PermissionError('process inventory unavailable')
        return real_iterdir(path)
    monkeypatch.setattr(Path, 'iterdir', iterdir)
    assert sessions._expiry_worktree_has_runtime_references(tmp_path)


@pytest.mark.parametrize('status,age,complete,expected', [
    ('active', 0, True, True),
    ('idle', 0, True, False),
    ('notLoaded', 0, True, False),
    ('idle', 300, True, True),
    ('idle', 0, False, True),
    ('unknown', 0, True, True),
])
def test_expiry_codex_presence_requires_fresh_complete_idle_inventory(monkeypatch, tmp_path, status, age, complete, expected):
    sessions = _real_runtime_probe()
    from scripts import codex_task_adapter
    state = tmp_path / 'adapter.json'
    state.write_text(json.dumps({'presence': {
        'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - age)),
        'complete': complete, 'connection': 'connected',
        'threads': {'bound-thread': {'status': status}},
    }}))
    monkeypatch.setattr(codex_task_adapter, 'adapter_path', lambda _root: state)
    assert sessions._expiry_codex_thread_is_live({'codex_thread_id': 'bound-thread'}) is expected


@pytest.mark.parametrize('outcome', ['reference', 'none', 'denied', 'error', 'reused'])
def test_expiry_privileged_probe_requires_elected_owner_and_stable_process(monkeypatch, tmp_path, outcome):
    sessions = _real_runtime_probe()
    from scripts import disk_coordinator
    monkeypatch.setattr(disk_coordinator, 'configured', lambda _root: object())
    monkeypatch.setattr(disk_coordinator, 'owner_check', lambda _owner: outcome != 'denied')
    real_read_text = Path.read_text
    monkeypatch.setattr(Path, 'read_text', lambda p, *a, **kw: (
        '123 (test) ' + ' '.join(['S'] * 19 + ['42'])
        if p == Path('/proc/123/stat') else real_read_text(p, *a, **kw)
    ))
    calls = []
    expected = [str(tmp_path / 'worktree' / 'source.py')] if outcome == 'reference' else []
    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:2] == ['docker', 'inspect']:
            return 0, 'sha256:' + 'a' * 64, ''
        assert kwargs['timeout'] == 30
        assert '--read-only' in cmd and '--pull=never' in cmd
        assert cmd[cmd.index('--network') + 1] == 'none'
        assert cmd[cmd.index('--cap-drop') + 1] == 'ALL'
        assert cmd[cmd.index('--cap-add') + 1] == 'SYS_PTRACE'
        assert cmd[cmd.index('--security-opt') + 1] == 'no-new-privileges'
        assert 'apparmor=unconfined' in cmd
        assert cmd[cmd.index('--mount') + 1] == 'type=bind,source=/proc,target=/host-proc,readonly'
        assert cmd[-1] == '123'
        if outcome == 'error':
            return 1, '', 'denied'
        return 0, json.dumps({'start': '99' if outcome == 'reused' else '42', 'references': expected}), ''
    monkeypatch.setattr(sessions, '_run_cmd', run)
    result = sessions._expiry_privileged_process_references(123)
    if outcome in {'reference', 'none'}:
        assert result == expected
    else:
        assert result is None
    if outcome == 'denied':
        assert calls == []
