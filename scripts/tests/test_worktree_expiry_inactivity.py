#!/usr/bin/env python3
"""Tests for inactivity-based worktree expiry, archive retention and recovery hints."""

# contract-test-file: tooling

from __future__ import annotations

import json
import os
import time

import pytest

from test_sessions_worktree_cleanup import load_sessions_module


def _iso(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _setup(monkeypatch, tmp_path, *, chat_age_hours: float | None, activity_age_hours: float = 30):
    sessions = load_sessions_module()
    now = time.time()
    projects = tmp_path / "projects"
    (projects / "slug").mkdir(parents=True)
    if chat_age_hours is not None:
        transcript = projects / "slug" / "chat-1.jsonl"
        transcript.write_text("{}\n")
        os.utime(transcript, (now - chat_age_hours * 3600,) * 2)
    monkeypatch.setenv("OPENMATES_CLAUDE_PROJECTS_DIR", str(projects))
    path = tmp_path / "worktrees" / "agent-x"
    path.mkdir(parents=True)
    stamp = _iso(now - activity_age_hours * 3600)
    session = {"agent_task_id": "chat-1", "last_active": stamp, "worktree": {"path": str(path), "last_active": stamp}}
    record = {"session_id": "x", "path": str(path), "path_timestamp": now - 40 * 3600,
              "session": session, "metadata": session["worktree"]}
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({"sessions": {"x": session}}), encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_managed_worktree_records", lambda: [record])
    monkeypatch.setattr(sessions, "_hard_expiry_record_is_safely_disposable", lambda _r: (False, "unique_changes"))
    archived, removed = [], []
    monkeypatch.setattr(sessions, "_archive_expired_worktree", lambda r: archived.append(r["session_id"]) or str(tmp_path / "a.tar.gz"))
    monkeypatch.setattr(sessions, "_verify_expired_worktree_archive_snapshot", lambda *_a: None)
    monkeypatch.setattr(sessions, "_remove_expired_worktree", lambda r: removed.append(r["session_id"]))
    monkeypatch.setattr(sessions, "_delete_worktree_checkpoint_ref", lambda _s: True)
    return sessions, now, archived, removed


def test_recent_chat_transcript_retains_worktree(monkeypatch, tmp_path):
    sessions, now, archived, removed = _setup(monkeypatch, tmp_path, chat_age_hours=2)
    report = sessions.expire_managed_worktrees(max_age_hours=24, now_timestamp=now)
    assert removed == [] and archived == []
    assert report["protected_live"] == ["x"]


def test_recent_subagent_transcript_retains_worktree(monkeypatch, tmp_path):
    sessions, now, archived, removed = _setup(monkeypatch, tmp_path, chat_age_hours=100)
    sub = tmp_path / "projects" / "slug" / "chat-1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a.jsonl").write_text("{}\n")
    report = sessions.expire_managed_worktrees(max_age_hours=24, now_timestamp=now)
    assert removed == [] and report["protected_live"] == ["x"]


@pytest.mark.parametrize("chat_age", [None, 50])
def test_all_signals_inactive_archives_then_expires(monkeypatch, tmp_path, chat_age):
    sessions, now, archived, removed = _setup(monkeypatch, tmp_path, chat_age_hours=chat_age)
    report = sessions.expire_managed_worktrees(max_age_hours=24, now_timestamp=now)
    assert archived == ["x"] and removed == ["x"]
    assert report["deleted"] == ["x"]
    manifest = json.loads(sessions.SESSIONS_FILE.read_text())["worktree_deletion_manifests"][-1]
    assert manifest["recovery_archive"].endswith("a.tar.gz")
    assert manifest["agent_task_id"] == "chat-1"


def test_dry_run_changes_nothing(monkeypatch, tmp_path):
    sessions, now, archived, removed = _setup(monkeypatch, tmp_path, chat_age_hours=None)
    report = sessions.expire_managed_worktrees(max_age_hours=24, now_timestamp=now, dry_run=True)
    assert report["would_delete"] == ["x"] and report["archive_required"] == ["x"]
    assert archived == [] and removed == [] and report["deleted"] == []


def test_floor_rejects_23_hours(monkeypatch):
    sessions = load_sessions_module()
    monkeypatch.setattr(sessions, "_managed_worktree_records", lambda: pytest.fail("must reject first"))
    with pytest.raises(ValueError, match="minimum inactivity window"):
        sessions.expire_managed_worktrees(max_age_hours=23)


def test_archives_older_than_retention_are_pruned_and_manifest_marked(monkeypatch, tmp_path):
    sessions, now, _archived, _removed = _setup(monkeypatch, tmp_path, chat_age_hours=2)
    archive_dir = sessions.WORKTREE_EXPIRY_ARCHIVE_DIR
    archive_dir.mkdir(parents=True)
    old, new, other = archive_dir / "old.tar.gz", archive_dir / "new.tar.gz", archive_dir / "keep.txt"
    for item, age in ((old, 8 * 24), (new, 6 * 24), (other, 30 * 24)):
        item.write_text("x")
        os.utime(item, (now - age * 3600,) * 2)
    outside = tmp_path / "target.tar.gz"
    outside.write_text("x")
    os.utime(outside, (now - 30 * 24 * 3600,) * 2)
    (archive_dir / "link.tar.gz").symlink_to(outside)
    data = json.loads(sessions.SESSIONS_FILE.read_text())
    data["worktree_deletion_manifests"] = [{"session_id": "gone", "recovery_archive": str(old),
                                           "deleted_at": sessions._now_iso()}]
    sessions.SESSIONS_FILE.write_text(json.dumps(data))
    report = sessions.expire_managed_worktrees(max_age_hours=24, now_timestamp=now)
    assert report["pruned_archives"] == ["old.tar.gz"]
    assert not old.exists() and new.exists() and other.exists() and outside.exists()
    stored = json.loads(sessions.SESSIONS_FILE.read_text())["worktree_deletion_manifests"][0]
    assert stored["recovery_archive_pruned_at"]


def test_unknown_session_error_names_recovery_archive(tmp_path):
    sessions = load_sessions_module()
    archive = tmp_path / "gone.tar.gz"
    archive.write_text("x")
    data = {"sessions": {}, "worktree_deletion_manifests": [
        {"session_id": "abcd", "recovery_archive": str(archive), "deleted_at": sessions._now_iso()}]}
    with pytest.raises(RuntimeError, match=r"recovery archive .*gone\.tar\.gz.*deleted automatically on"):
        sessions._resolve_session_id(data, session_id="abcd")


def test_head_bundle_preserves_unmerged_commits(tmp_path):
    import subprocess
    from scripts import worktree_expiry_policy as policy

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org"}
    def run(*a):
        return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, env=env)
    run("init", "-q", "-b", "dev")
    (repo / "f").write_text("1")
    run("add", "f")
    run("commit", "-qm", "base")
    run("checkout", "-qb", "work")
    (repo / "f").write_text("2")
    run("commit", "-qam", "unmerged")
    bundle = policy.head_bundle(repo, "dev", 10_000_000)
    assert bundle.startswith(b"# v")
