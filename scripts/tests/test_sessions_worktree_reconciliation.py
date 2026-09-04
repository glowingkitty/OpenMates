#!/usr/bin/env python3
"""Tests for report-only worktree discovery and classification.

The reconciliation report joins session metadata with Git-linked and physical
worktrees. Report-only operation must never mutate repository or session state.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from argparse import Namespace
from pathlib import Path

import pytest


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


def test_missing_registered_worktree_is_retirable_after_idle_threshold(tmp_path):
    sessions = load_sessions_module()
    candidate = {
        "session_id": "missing",
        "path": str(tmp_path / "agent-missing"),
        "path_exists": False,
        "idle_hours": 100,
        "changed_files": [],
        "metadata": {},
    }

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete=set())

    assert result["classification"] == "missing_worktree"
    assert result["reason_code"] == "registered_path_missing"


def test_missing_git_admin_is_recoverable_not_generic_malformed(tmp_path):
    sessions = load_sessions_module()
    candidate = {
        "session_id": "orphan",
        "path": str(tmp_path / "agent-orphan"),
        "path_exists": True,
        "missing_gitdir": "/repo/.git/worktrees/agent-orphan",
        "idle_hours": 100,
        "changed_files": [],
        "inspection_error": "fatal: not a git repository",
        "metadata": {},
    }

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete=set())

    assert result["classification"] == "orphaned_git_metadata"
    assert result["reason_code"] == "git_admin_missing"


def test_dirty_integration_worktree_is_never_disposable():
    sessions = load_sessions_module()
    candidate = {
        "session_id": "integration-dirty",
        "path": "/tmp/integration-dirty-123456789abc",
        "worktree_kind": "integration",
        "idle_hours": 100,
        "changed_files": ["scripts/sessions.py"],
        "metadata": {},
    }

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete=set())

    assert result["classification"] == "unique_stale"
    assert result["reason_code"] == "integration_has_changes"


def test_integration_inspection_error_is_never_disposable():
    sessions = load_sessions_module()
    candidate = {
        "session_id": "integration-broken",
        "path": "/tmp/integration-broken-123456789abc",
        "worktree_kind": "integration",
        "idle_hours": 100,
        "changed_files": [],
        "inspection_error": "cannot inspect index",
        "metadata": {},
    }

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete=set())

    assert result["classification"] == "malformed"
    assert result["reason_code"] == "inspection_failed"


def test_duplicate_comparison_includes_git_file_mode(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-mode"
    worktree.mkdir()
    script = worktree / "tool.sh"
    script.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    script.chmod(0o755)
    candidate = {"path": str(worktree), "changed_files": ["tool.sh"]}
    monkeypatch.setattr(sessions, "_target_file_bytes", lambda _target, _path: script.read_bytes())
    monkeypatch.setattr(sessions, "_target_file_mode", lambda _target, _path: "100644")

    assert not sessions._worktree_target_files_match(candidate, "origin/dev")


def test_duplicate_comparison_distinguishes_symlink_from_regular_file(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    worktree = tmp_path / "agent-link"
    worktree.mkdir()
    regular_file = worktree / "linked-config"
    regular_file.write_text("config.yml", encoding="utf-8")
    candidate = {"path": str(worktree), "changed_files": ["linked-config"]}
    monkeypatch.setattr(sessions, "_target_file_bytes", lambda _target, _path: b"config.yml")
    monkeypatch.setattr(sessions, "_target_file_mode", lambda _target, _path: "120000")

    assert not sessions._worktree_target_files_match(candidate, "origin/dev")


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

    def remove(path):
        removed.append(Path(path))
        Path(path).rmdir()

    monkeypatch.setattr(sessions.shutil, "rmtree", remove)

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


def test_discovery_only_scope_skips_diff_inspection_for_unselected_worktrees(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    managed = tmp_path / "worktrees"
    selected = managed / "agent-selected"
    other = managed / "agent-other"
    selected.mkdir(parents=True)
    other.mkdir()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps(
            {
                "sessions": {
                    "selected": {"worktree": {"path": str(selected), "status": "active"}},
                    "other": {"worktree": {"path": str(other), "status": "active"}},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "AGENT_WORKTREES_DIR", managed)
    monkeypatch.setattr(sessions, "PROJECT_ROOT", selected)
    monkeypatch.setattr(sessions, "CONTROL_PLANE_ROOT", tmp_path / "control-plane")
    monkeypatch.setattr(sessions, "_linked_git_worktrees", lambda: [])
    inspected: list[Path] = []
    monkeypatch.setattr(
        sessions,
        "_candidate_changed_files",
        lambda path, _metadata: inspected.append(Path(path)) or [],
    )

    candidates = sessions._discover_worktree_candidates(only_session_ids={"selected"})

    assert [item["session_id"] for item in candidates] == ["selected"]
    assert candidates[0]["session"]["worktree"] == {"path": str(selected), "status": "active"}
    assert inspected == [selected]


def test_merged_candidate_compares_changed_files_to_recorded_merge_commit(monkeypatch):
    sessions = load_sessions_module()
    candidate = {
        "session_id": "merged",
        "path": "/tmp/agent-merged",
        "idle_hours": 100,
        "changed_files": ["source.py"],
        "metadata": {"merged_commit": "merge-commit", "status": "merged"},
    }
    monkeypatch.setattr(sessions, "_git_is_ancestor", lambda commit, target: (commit, target) == ("merge-commit", "origin/dev"))
    monkeypatch.setattr(
        sessions,
        "_worktree_target_files_match",
        lambda _candidate, target: target == "merge-commit",
    )

    result = sessions._classify_worktree_candidate(candidate, "origin/dev", 48, approved_obsolete=set())

    assert result["classification"] == "integrated"
    assert result["reason_code"] == "merged_file_states_reachable"


def test_related_test_discovery_prunes_managed_worktree_copies(tmp_path):
    sessions = load_sessions_module()
    source_test = tmp_path / "scripts" / "test_storage_guard.py"
    worktree_test = tmp_path / ".openmates-agent-worktrees" / "agent-old" / "scripts" / "test_storage_guard_copy.py"
    source_test.parent.mkdir(parents=True)
    worktree_test.parent.mkdir(parents=True)
    source_test.write_text("def test_storage_guard(): pass\n", encoding="utf-8")
    worktree_test.write_text("def test_storage_guard_copy(): pass\n", encoding="utf-8")

    report = sessions._find_tests_for_file("scripts/storage_guard.py", checkout_root=tmp_path)

    assert report["unit_tests"] == ["scripts/test_storage_guard.py"]


def test_python_test_discovery_prefers_exact_sibling_over_global_stem_matches(tmp_path):
    sessions = load_sessions_module()
    source = tmp_path / "backend" / "engineering_control_plane" / "api.py"
    exact = source.parent / "tests" / "test_api.py"
    unrelated = tmp_path / "backend" / "tests" / "test_api_key_scopes.py"
    source.parent.mkdir(parents=True)
    exact.parent.mkdir(parents=True)
    unrelated.parent.mkdir(parents=True)
    source.write_text("pass\n", encoding="utf-8")
    exact.write_text("def test_api(): pass\n", encoding="utf-8")
    unrelated.write_text("def test_api_key_scopes(): pass\n", encoding="utf-8")

    report = sessions._find_tests_for_file(
        "backend/engineering_control_plane/api.py",
        checkout_root=tmp_path,
    )

    assert report["unit_tests"] == ["backend/engineering_control_plane/tests/test_api.py"]


def test_python_test_discovery_honors_bounded_source_test_directive(tmp_path):
    sessions = load_sessions_module()
    source = tmp_path / "backend" / "engineering_control_plane" / "coordination_repository.py"
    contract_test = source.parent / "tests" / "test_coordination.py"
    source.parent.mkdir(parents=True)
    contract_test.parent.mkdir(parents=True)
    source.write_text(
        "# test-file: backend/engineering_control_plane/tests/test_coordination.py\n",
        encoding="utf-8",
    )
    contract_test.write_text("def test_coordination(): pass\n", encoding="utf-8")

    report = sessions._find_tests_for_file(
        "backend/engineering_control_plane/coordination_repository.py",
        checkout_root=tmp_path,
    )

    assert report["unit_tests"] == ["backend/engineering_control_plane/tests/test_coordination.py"]


def test_cli_refuses_lower_idle_threshold_without_only_scope(monkeypatch, capsys):
    sessions = load_sessions_module()
    monkeypatch.setattr(
        sessions,
        "reconcile_session_worktrees",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unsafe reconciliation started")),
    )

    with pytest.raises(SystemExit) as exc_info:
        sessions.cmd_worktree(
            Namespace(
                worktree_action="reconcile",
                target="origin/dev",
                idle_hours=0,
                apply_safe=True,
                approve_obsolete=["selected"],
                only=[],
                format="text",
            )
        )

    assert exc_info.value.code == 2
    assert "--only" in capsys.readouterr().err


def test_legacy_cleanup_refuses_lower_idle_threshold(monkeypatch, capsys):
    sessions = load_sessions_module()
    monkeypatch.setattr(
        sessions,
        "cleanup_session_worktrees",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unsafe cleanup started")),
    )

    with pytest.raises(SystemExit) as exc_info:
        sessions.cmd_worktree(Namespace(worktree_action="cleanup", idle_hours=0))

    assert exc_info.value.code == 2
    assert "below 48" in capsys.readouterr().err


def test_duplicate_chat_plan_keeps_only_most_recent_source_worktree():
    sessions = load_sessions_module()
    candidates = [
        {
            "session_id": "old1",
            "path": "/tmp/agent-old1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 10,
        },
        {
            "session_id": "new1",
            "path": "/tmp/agent-new1",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 20,
        },
        {
            "session_id": "other",
            "path": "/tmp/agent-other",
            "worktree_kind": "source",
            "chat_lineage": "ses_other",
            "lineage_created_ms": 5,
        },
    ]

    plan = sessions._plan_duplicate_chat_worktrees(candidates)

    assert plan["duplicate_chat_count"] == 1
    assert plan["retained"] == ["new1"]
    assert plan["remove"] == ["old1"]


def test_duplicate_chat_plan_never_groups_unknown_or_integration_worktrees():
    sessions = load_sessions_module()
    candidates = [
        {
            "session_id": "known",
            "path": "/tmp/agent-known",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 10,
        },
        {
            "session_id": "integration-known",
            "path": "/tmp/integration-known-123",
            "worktree_kind": "integration",
            "chat_lineage": "ses_chat",
            "lineage_created_ms": 20,
        },
        {
            "session_id": "unknown",
            "path": "/tmp/agent-unknown",
            "worktree_kind": "source",
            "chat_lineage": "",
            "lineage_created_ms": 30,
        },
    ]

    plan = sessions._plan_duplicate_chat_worktrees(candidates)

    assert plan["duplicate_chat_count"] == 0
    assert plan["retained"] == []
    assert plan["remove"] == []
    assert plan["lineage_unknown"] == ["unknown"]
    assert plan["integration_excluded"] == ["integration-known"]


def test_duplicate_chat_plan_keeps_newest_worktree_over_older_bound_event():
    sessions = load_sessions_module()
    candidates = [
        {
            "session_id": "bound",
            "path": "/tmp/agent-bound",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_bound": True,
            "lineage_created_ms": 10,
        },
        {
            "session_id": "newer-unbound",
            "path": "/tmp/agent-newer",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_bound": False,
            "lineage_created_ms": 20,
        },
    ]

    plan = sessions._plan_duplicate_chat_worktrees(candidates)

    assert plan["retained"] == ["newer-unbound"]
    assert plan["remove"] == ["bound"]


def test_duplicate_chat_plan_excludes_newer_invalid_path_from_authoritative_selection():
    sessions = load_sessions_module()
    candidates = [
        {
            "session_id": "valid",
            "path": "/tmp/agent-valid",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_path_valid": True,
            "lineage_created_ms": 10,
        },
        {
            "session_id": "invalid-newer",
            "path": "/tmp/missing",
            "worktree_kind": "source",
            "chat_lineage": "ses_chat",
            "lineage_path_valid": False,
            "lineage_created_ms": 20,
        },
    ]

    plan = sessions._plan_duplicate_chat_worktrees(candidates)

    assert plan["duplicate_chat_count"] == 0
    assert plan["authoritative"] == {"ses_chat": "valid"}
    assert plan["remove"] == []
    assert plan["invalid_path_excluded"] == ["invalid-newer"]


def test_legacy_lineage_reconstruction_uses_top_level_chat_and_latest_creation(tmp_path):
    sessions = load_sessions_module()
    database = tmp_path / "opencode.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE session (id TEXT, parent_id TEXT)")
    connection.execute("CREATE TABLE part (session_id TEXT, time_created INTEGER, data TEXT)")
    connection.executemany(
        "INSERT INTO session VALUES (?, ?)",
        [("ses_parent", None), ("ses_child", "ses_parent")],
    )
    first = {
        "type": "tool",
        "state": {
            "output": "== SESSION abcd ==\n  Worktree: /repo/.openmates-agent-worktrees/agent-abcd\n",
        },
    }
    latest = {
        "type": "tool",
        "state": {
            "output": "== SESSION ef12 ==\n  Worktree: /repo/.openmates-agent-worktrees/agent-ef12\n",
        },
    }
    connection.executemany(
        "INSERT INTO part VALUES (?, ?, ?)",
        [("ses_child", 10, json.dumps(first)), ("ses_parent", 20, json.dumps(latest))],
    )
    connection.commit()
    connection.close()

    lineage = sessions._legacy_worktree_chat_lineage(database)

    assert lineage["abcd"] == {"chat_lineage": "ses_parent", "lineage_created_ms": 10}
    assert lineage["ef12"] == {"chat_lineage": "ses_parent", "lineage_created_ms": 20}


def test_obsolete_approval_requires_matching_only_scope(monkeypatch, capsys):
    sessions = load_sessions_module()
    monkeypatch.setattr(
        sessions,
        "reconcile_session_worktrees",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("unscoped approval started")),
    )
    args = Namespace(
        worktree_action="reconcile",
        idle_hours=48,
        only=[],
        approve_obsolete=["broken"],
        target="origin/dev",
        apply_safe=True,
        format="text",
    )

    with pytest.raises(SystemExit) as exc_info:
        sessions.cmd_worktree(args)

    assert exc_info.value.code == 2
    assert "--only broken" in capsys.readouterr().err
