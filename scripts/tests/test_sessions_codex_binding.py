#!/usr/bin/env python3
"""Codex identity regressions for the shared session coordinator.

Use isolated metadata and never create real worktrees or contact Docker.
Exercise exact task identity, repository separation and concurrent registration.
The existing OpenCode and Zellij paths remain independently supported.
See docs/plans/codex-session-runtime-isolation/plan.yml.
"""

# contract-test-file: tooling
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from scripts import sessions

TASK = "01a07cde-f630-76c3-9a46-66eb7c082d85"
OTHER = "01a07d05-4f27-7111-91fb-9ef6fa875c9b"


def test_disconnected_binding_survives_stale_pruning():
    data = {
        "sessions": {
            "old": {"codex_task_id": TASK, "last_active": "2000-01-01T00:00:00Z"}
        }
    }
    assert sessions._prune_stale(data) == []
    assert "old" in data["sessions"]




def test_codex_identity_does_not_fall_back_to_zellij(monkeypatch):
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", TASK)
    monkeypatch.setenv("ZELLIJ_SESSION_NAME", "shared")
    records = {
        "a": {"codex_task_id": TASK, "codex_host": sessions.socket.gethostname()},
        "b": {"zellij_session": "shared"},
    }
    assert sessions._resolve_session_identity(records) == "a"
    monkeypatch.setenv("CODEX_THREAD_ID", OTHER)
    assert sessions._resolve_session_identity(records) is None


def test_task_lookup_rejects_ambiguity_and_separates_repositories():
    records = {
        "sessions": {
            "a": {"codex_task_id": TASK, "codex_host": "host", "repo_id": "one"},
            "b": {"codex_task_id": TASK, "codex_host": "host", "repo_id": "two"},
        }
    }
    assert (
        sessions.session_for_codex(records, TASK, host="host", repo_id="one")[0] == "a"
    )
    assert sessions.session_for_codex(records, TASK, host="other") is None
    with pytest.raises(RuntimeError, match="multiple"):
        sessions.session_for_codex(records, TASK, host="host")


def test_concurrent_registration_reuses_one_binding(monkeypatch, tmp_path):
    monkeypatch.setattr(sessions, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setattr(sessions, "_prune_stale", lambda data: [])
    monkeypatch.setattr(sessions, "_prune_stale_locks", lambda data: [])
    monkeypatch.setattr(sessions, "_prune_checkpoint_lock_files", lambda data: None)
    record = {
        "repo_id": "openmates",
        "codex_task_id": TASK,
        "codex_host": "host",
        "modified_files": [],
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: sessions.register_session_record(record), range(2))
        )
    assert len({r[0] for r in results}) == 1
    assert sum(r[4] for r in results) == 1
    assert len(json.loads((tmp_path / "sessions.json").read_text())["sessions"]) == 1


def test_invalid_task_id_is_rejected():
    with pytest.raises(ValueError, match="Codex"):
        sessions.session_for_codex({"sessions": {}}, "../other", host="host")


def test_adoption_preserves_worktree_and_requires_explicit_attestation(
    monkeypatch, tmp_path
):
    state_file = tmp_path / "sessions.json"
    worktree = tmp_path / "agent-old"
    worktree.mkdir()
    original = {
        "repo_id": "openmates",
        "opencode_session_id": "ses_historic",
        "task_id": "existing-task",
        "modified_files": ["dirty.py"],
        "worktree": {"path": str(worktree)},
        "hold": "retain",
    }
    state_file.write_text(
        json.dumps({"sessions": {"old": original}, "locks": {}, "edit_leases": {}})
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", state_file)
    with pytest.raises(ValueError, match="stopped"):
        sessions.bind_codex_session(
            "old", TASK, expected_worktree=str(worktree), previous_owner_stopped=False
        )
    result = sessions.bind_codex_session(
        "old", TASK, expected_worktree=str(worktree), previous_owner_stopped=True
    )
    assert result["session_id"] == "old"
    saved = json.loads(state_file.read_text())["sessions"]["old"]
    for key, value in original.items():
        assert saved[key] == value
    again = sessions.bind_codex_session(
        "old", TASK, expected_worktree=str(worktree), previous_owner_stopped=True
    )
    assert again == result
    with pytest.raises(RuntimeError, match="another Codex"):
        sessions.bind_codex_session(
            "old", OTHER, expected_worktree=str(worktree), previous_owner_stopped=True
        )
