#!/usr/bin/env python3
"""Selection contracts for automatic integration of forgotten checkpoints.

Automatic integration is opt-out but remains exact-patch, grace-period, and
normal-deploy-gate constrained. Legacy worktrees never become implicit inputs.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_auto_integration", SESSIONS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def eligible_data() -> dict:
    return {
        "sessions": {
            "abcd": {
                "mode": "bug",
                "task": "repair forgotten changes",
                "auto_integration_policy": "enabled",
                "binding_mode": "worktree_routed",
                "modified_files": ["frontend/packages/ui/src/safe.ts"],
                "worktree": {
                    "path": "/repo/agent-abcd",
                    "status": "active",
                },
                "workspace_state": "checkpointed",
                "auto_integration": {
                    "status": "eligible",
                    "patch_id": "patch-1",
                    "checkpoint_commit": "commit-1",
                    "checkpoint_ref": "refs/openmates/checkpoints/abcd",
                    "files": ["frontend/packages/ui/src/safe.ts"],
                    "eligible_after": "2026-08-06T16:00:00Z",
                },
            }
        },
        "edit_leases": {},
        "deploy_queue": [],
    }


def test_activate_session_worktree_invalidates_eligible_checkpoint(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    data["sessions"]["abcd"]["opencode_session_id"] = "ses-parent"
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "locks")

    result = sessions.activate_session_worktree("ses-parent")

    assert result["status"] == "active"
    assert data["sessions"]["abcd"]["workspace_state"] == "changes_pending"
    assert data["sessions"]["abcd"]["worktree"]["status"] == "active"
    assert data["sessions"]["abcd"]["auto_integration"]["status"] == "changes_pending"
    assert data["sessions"]["abcd"]["auto_integration"]["block_reason"] == "live_turn_started"


def test_claim_rechecks_presence_and_invalidates_candidate(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_auto_integration_presence_is_live", lambda _session: True)
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "locks")

    assert sessions._claim_auto_integration({
        "session_id": "abcd",
        "patch_id": "patch-1",
        "checkpoint_commit": "commit-1",
    }) is False
    assert data["sessions"]["abcd"]["workspace_state"] == "changes_pending"
    assert data["sessions"]["abcd"]["auto_integration"]["status"] == "changes_pending"
    assert data["sessions"]["abcd"]["auto_integration"]["block_reason"] == "live_turn_started"


def test_only_current_checkpoint_past_grace_is_selected(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_checkpoint_ref_matches", lambda _session_id, _auto: True)
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: ["frontend/packages/ui/src/safe.ts"])
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch-1")

    selected = sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z")

    assert [item["session_id"] for item in selected] == ["abcd"]


def test_candidate_inspection_failure_does_not_abort_later_candidate(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    broken = data["sessions"].pop("abcd")
    healthy = {
        **broken,
        "worktree": {**broken["worktree"], "path": "/repo/agent-healthy"},
        "auto_integration": {
            **broken["auto_integration"],
            "checkpoint_ref": "refs/openmates/checkpoints/healthy",
        },
    }
    data["sessions"] = {"broken": broken, "healthy": healthy}
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_checkpoint_ref_matches", lambda _session_id, _auto: True)
    monkeypatch.setattr(sessions, "_auto_integration_presence_is_live", lambda _session: False)

    def deploy_files(session, _exclude):
        if session["worktree"]["path"].endswith("agent-abcd"):
            raise RuntimeError("missing git metadata")
        return ["frontend/packages/ui/src/safe.ts"]

    monkeypatch.setattr(sessions, "_session_deploy_files", deploy_files)
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch-1")

    selected = sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z")

    assert [item["session_id"] for item in selected] == ["healthy"]
    assert data["sessions"]["broken"]["auto_integration"]["status"] == "recovery_needed"
    assert "candidate_inspection_failed" in data["sessions"]["broken"]["auto_integration"]["block_reason"]


def test_changed_patch_hold_sensitive_path_and_live_lease_are_blocked(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_checkpoint_ref_matches", lambda _session_id, _auto: True)
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: ["frontend/packages/ui/src/safe.ts"])
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "changed")
    assert sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z") == []

    data = eligible_data()
    data["sessions"]["abcd"]["auto_integration"]["hold"] = True
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    assert sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z") == []

    data = eligible_data()
    data["sessions"]["abcd"]["auto_integration"]["files"] = ["backend/core/directus/migrations/unsafe.sql"]
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    assert sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z") == []

    data = eligible_data()
    data["edit_leases"]["frontend/packages/ui/src/safe.ts"] = {"session_id": "abcd"}
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    assert sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z") == []


def test_legacy_and_high_risk_checkpoints_are_durably_blocked(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    data["sessions"]["abcd"]["auto_integration_policy"] = "legacy"
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))

    assert sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z") == []
    assert data["sessions"]["abcd"]["auto_integration"]["block_reason"] == "legacy_or_unapproved_session"

    data = eligible_data()
    sensitive = "apple/OpenMates/OpenMates.entitlements"
    data["sessions"]["abcd"]["modified_files"] = [sensitive]
    data["sessions"]["abcd"]["auto_integration"]["files"] = [sensitive]
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_checkpoint_ref_matches", lambda _session_id, _auto: True)
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: [sensitive])

    assert sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z") == []
    assert data["sessions"]["abcd"]["auto_integration"]["status"] == "blocked"
    assert data["sessions"]["abcd"]["workspace_state"] == "recovery_needed"


def test_worker_invokes_normal_deploy_without_gate_waivers(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    commands: list[list[str]] = []

    def runner(command: list[str]) -> tuple[int, str, str]:
        commands.append(command)
        data["sessions"]["abcd"]["auto_integration"]["status"] = "integrated"
        return 0, "deployed", ""

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(
        sessions,
        "select_auto_integration_candidates",
        lambda **_kwargs: [{
            "session_id": "abcd",
            "task": "repair forgotten changes",
            "patch_id": "patch-1",
            "checkpoint_commit": "commit-1",
            "files": ["frontend/packages/ui/src/safe.ts"],
        }],
    )
    monkeypatch.setattr(sessions, "_claim_auto_integration", lambda _candidate: True)
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch-1")
    monkeypatch.setattr(sessions, "_delete_worktree_checkpoint_ref", lambda _session_id, **_kwargs: True)
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", Path("/tmp/openmates-test-checkpoint-locks"))

    result = sessions.auto_integrate_checkpoints(
        runner=runner,
        now="2026-08-06T17:00:00Z",
    )

    assert result["integrated"] == ["abcd"]
    command = commands[0]
    assert command[:4] == [sys.executable, "scripts/sessions.py", "deploy", "--session"]
    assert "--no-verify" not in command
    assert "--skip-tests" not in command
    assert command[-2:] == ["--expected-checkpoint-commit", "commit-1"]
    assert data["sessions"]["abcd"]["workspace_state"] == "integrated"


def test_worker_preserves_newer_checkpoint_created_during_deploy(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    deleted: list[str] = []

    def runner(_command: list[str]) -> tuple[int, str, str]:
        data["sessions"]["abcd"]["auto_integration"].update(
            {"patch_id": "patch-2", "checkpoint_commit": "commit-2", "status": "eligible"}
        )
        return 0, "deployed old checkpoint", ""

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "locks")
    monkeypatch.setattr(
        sessions,
        "select_auto_integration_candidates",
        lambda **_kwargs: [{
            "session_id": "abcd",
            "task": "repair forgotten changes",
            "patch_id": "patch-1",
            "checkpoint_commit": "commit-1",
            "files": ["frontend/packages/ui/src/safe.ts"],
        }],
    )
    monkeypatch.setattr(sessions, "_claim_auto_integration", lambda _candidate: True)
    monkeypatch.setattr(
        sessions,
        "_delete_worktree_checkpoint_ref",
        lambda session_id, **_kwargs: deleted.append(session_id),
    )

    result = sessions.auto_integrate_checkpoints(runner=runner, now="2026-08-06T17:00:00Z")

    assert result["integrated"] == []
    assert result["blocked"] == [{"session_id": "abcd", "reason": "checkpoint_changed_during_deploy"}]
    assert data["sessions"]["abcd"]["auto_integration"]["checkpoint_commit"] == "commit-2"
    assert deleted == []


def test_completion_preserves_pending_state_when_source_changes(monkeypatch, tmp_path: Path) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    data["sessions"]["abcd"]["auto_integration"]["status"] = "integrated"
    deleted: list[str] = []
    candidate = {
        "session_id": "abcd",
        "patch_id": "patch-1",
        "checkpoint_commit": "commit-1",
        "files": ["frontend/packages/ui/src/safe.ts"],
    }
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "WORKTREE_CHECKPOINT_LOCKS_DIR", tmp_path / "locks")
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch-2")
    monkeypatch.setattr(
        sessions,
        "_delete_worktree_checkpoint_ref",
        lambda session_id, **_kwargs: deleted.append(session_id) or True,
    )

    assert sessions._complete_auto_integration(candidate) is False
    assert data["sessions"]["abcd"]["workspace_state"] == "changes_pending"
    assert data["sessions"]["abcd"]["auto_integration"]["block_reason"] == "source_changed_during_deploy"
    assert deleted == []


def test_unknown_presence_holds_candidate(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    data["sessions"]["abcd"]["opencode_session_id"] = "ses-parent"

    class BrokenPresenceStore:
        def snapshot(self):
            raise OSError("presence unavailable")

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_mutate_sessions", lambda callback: callback(data))
    monkeypatch.setattr(sessions, "_opencode_presence_store", lambda: BrokenPresenceStore())
    monkeypatch.setattr(sessions, "_checkpoint_ref_matches", lambda _session_id, _auto: True)

    assert sessions.select_auto_integration_candidates(now="2026-08-06T17:00:00Z") == []
    assert data["sessions"]["abcd"]["auto_integration"]["block_reason"] == "live_presence"
    assert data["sessions"]["abcd"]["workspace_state"] == "held"


def test_idle_worker_retries_unchanged_patch_after_transient_failure(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    session = data["sessions"]["abcd"]
    session["opencode_session_id"] = "ses-parent"
    session["last_active"] = "2026-08-06T15:00:00Z"
    session["auto_integration"].update({"status": "blocked", "block_reason": "temporary deploy failure"})
    retried: list[tuple[str, str]] = []
    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_auto_integration_presence_is_live", lambda _session: False)
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: ["frontend/packages/ui/src/safe.ts"])
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch-1")
    monkeypatch.setattr(
        sessions,
        "checkpoint_session_worktree",
        lambda opencode_id, *, event: retried.append((opencode_id, event)) or {"status": "eligible"},
    )

    result = sessions.checkpoint_idle_sessions(now="2026-08-06T17:00:00Z")

    assert result == [{"status": "eligible"}]
    assert retried == [("ses-parent", "idle")]


def test_idle_worker_isolates_checkpoint_failure_and_continues(monkeypatch) -> None:
    sessions = load_sessions_module()
    data = eligible_data()
    data["sessions"] = {
        "broken": {
            **data["sessions"]["abcd"],
            "opencode_session_id": "ses-broken",
            "last_active": "2026-08-06T15:00:00Z",
        },
        "healthy": {
            **data["sessions"]["abcd"],
            "opencode_session_id": "ses-healthy",
            "last_active": "2026-08-06T15:00:00Z",
        },
    }
    data["sessions"]["broken"]["auto_integration"] = {
        "status": "blocked",
        "block_reason": "checkpoint_failed:ignored path",
    }
    data["sessions"]["healthy"]["auto_integration"] = {
        "status": "blocked",
        "block_reason": "temporary failure",
    }
    calls: list[str] = []

    def checkpoint(opencode_id: str, *, event: str) -> dict:
        calls.append(opencode_id)
        if opencode_id == "ses-broken":
            raise RuntimeError("ignored deploy path")
        return {"session_id": "healthy", "status": "eligible"}

    monkeypatch.setattr(sessions, "_load_sessions", lambda: data)
    monkeypatch.setattr(sessions, "_auto_integration_presence_is_live", lambda _session: False)
    monkeypatch.setattr(sessions, "_session_deploy_files", lambda _session, _exclude: ["safe.py"])
    monkeypatch.setattr(sessions, "_worktree_patch_id", lambda _metadata, _files: "patch-1")
    monkeypatch.setattr(sessions, "checkpoint_session_worktree", checkpoint)

    result = sessions.checkpoint_idle_sessions(now="2026-08-06T17:00:00Z")

    assert calls == ["ses-broken", "ses-healthy"]
    assert result == [
        {"session_id": "broken", "status": "blocked", "reason": "ignored deploy path"},
        {"session_id": "healthy", "status": "eligible"},
    ]
