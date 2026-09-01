#!/usr/bin/env python3
"""Regression tests for the sessions.py Vercel build-machine deploy gate."""

# contract-test-file: tooling

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def allow_control_plane_deploy_protocol(monkeypatch, sessions) -> None:
    monkeypatch.setattr(sessions, "_fetch_origin_dev_commit", lambda: "origin-dev")
    monkeypatch.setattr(sessions, "_enforce_control_plane_deploy_protocol_compatible", lambda _origin_ref: None)


def test_vercel_build_machine_gate_allows_standard_fixed(monkeypatch):
    sessions = load_sessions_module()

    monkeypatch.setattr(sessions, "_get_vercel_token_for_deploy_gate", lambda: "token")
    monkeypatch.setattr(sessions, "_load_web_app_vercel_project_config", lambda: ("team", "project"))
    monkeypatch.setattr(
        sessions,
        "_fetch_vercel_project_settings",
        lambda _token, _team, _project: {
            "nodeVersion": "24.x",
            "resourceConfig": {
                "buildMachineType": "standard",
                "buildMachineSelection": "fixed",
            }
        },
    )

    sessions._enforce_vercel_standard_build_machine()


def test_vercel_build_machine_gate_blocks_turbo_elastic(monkeypatch):
    sessions = load_sessions_module()

    monkeypatch.setattr(sessions, "_get_vercel_token_for_deploy_gate", lambda: "token")
    monkeypatch.setattr(sessions, "_load_web_app_vercel_project_config", lambda: ("team", "project"))
    monkeypatch.setattr(
        sessions,
        "_fetch_vercel_project_settings",
        lambda _token, _team, _project: {
            "nodeVersion": "24.x",
            "resourceConfig": {
                "buildMachineType": "turbo",
                "buildMachineSelection": "elastic",
            }
        },
    )

    with pytest.raises(RuntimeError, match="standard/fixed"):
        sessions._enforce_vercel_standard_build_machine()


def test_vercel_build_machine_gate_requires_token(monkeypatch):
    sessions = load_sessions_module()

    monkeypatch.setattr(sessions, "_get_vercel_token_for_deploy_gate", lambda: "")

    with pytest.raises(RuntimeError, match="VERCEL_TOKEN is required"):
        sessions._enforce_vercel_standard_build_machine()


def test_vercel_deploy_gate_blocks_node20_runtime(monkeypatch):
    sessions = load_sessions_module()

    monkeypatch.setattr(sessions, "_get_vercel_token_for_deploy_gate", lambda: "token")
    monkeypatch.setattr(sessions, "_load_web_app_vercel_project_config", lambda: ("team", "project"))
    monkeypatch.setattr(
        sessions,
        "_fetch_vercel_project_settings",
        lambda _token, _team, _project: {
            "nodeVersion": "20.x",
            "resourceConfig": {
                "buildMachineType": "standard",
                "buildMachineSelection": "fixed",
            },
        },
    )

    with pytest.raises(RuntimeError, match="Node.js version must be 24.x"):
        sessions._enforce_vercel_standard_build_machine()


def test_debug_vercel_starts_bug_session_with_complete_args(monkeypatch):
    sessions = load_sessions_module()
    captured = {}

    def fake_start(args):
        captured["start_args"] = args

    def fake_run_cmd(cmd, cwd=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return 0, "vercel logs\n", ""

    monkeypatch.setattr(sessions, "cmd_start", fake_start)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)

    sessions.cmd_debug_vercel(argparse.Namespace(opencode_session="oc-session"))

    start_args = captured["start_args"]
    assert start_args.mode == "bug"
    assert start_args.task == "debug Vercel deployment failure"
    assert start_args.tags == "debug"
    assert start_args.vercel is False
    assert start_args.error_since == 7
    assert start_args.opencode_session == "oc-session"
    assert captured["cmd"] == [
        sys.executable,
        str(sessions.PROJECT_ROOT / "backend" / "scripts" / "debug_vercel.py"),
    ]


def test_vercel_deploy_lock_blocks_active_other_session(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {
      "status": "IN_PROGRESS",
      "claimed_by": "other",
      "commit_sha": "abcdef123456",
      "since": "2026-07-21T10:00:00Z",
      "last_updated": "2026-07-21T10:00:00Z"
    }
  },
  "sessions": {}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 10)

    with pytest.raises(RuntimeError, match="vercel_deploy lock held by other"):
        sessions._acquire_session_lock(
            "vercel_deploy",
            "current",
            commit_sha="123456abcdef",
            phase="pushing_commit",
        )


def test_vercel_deploy_lock_allows_same_session_same_commit_refresh(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {
      "status": "IN_PROGRESS",
      "claimed_by": "current",
      "commit_sha": "abcdef123456",
      "since": "2026-07-21T10:00:00Z",
      "last_updated": "2026-07-21T10:00:00Z"
    }
  },
  "sessions": {}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 10)

    acquired = sessions._acquire_session_lock(
        "vercel_deploy",
        "current",
        commit_sha="abcdef123456",
        phase="pushing_commit",
    )

    assert acquired is False


def test_vercel_deploy_lock_clears_stale_commit_for_same_session_precommit(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {
      "status": "IN_PROGRESS",
      "claimed_by": "current",
      "commit_sha": "oldcommit123",
      "phase": "pushing_commit",
      "since": "2026-07-21T10:00:00Z",
      "last_updated": "2026-07-21T10:00:00Z"
    }
  },
  "sessions": {}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 10)

    acquired = sessions._acquire_session_lock(
        "vercel_deploy",
        "current",
        phase="preparing_commit",
    )

    assert acquired is False
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    lock = data["locks"]["vercel_deploy"]
    assert "commit_sha" not in lock
    assert lock["phase"] == "preparing_commit"


def test_wait_lock_returns_immediately_when_available(monkeypatch, tmp_path, capsys):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        '{"locks":{"docker_rebuild":{"status":"NONE"},"vercel_deploy":{"status":"NONE"}},"sessions":{}}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)

    sessions.cmd_wait_lock(argparse.Namespace(type="vercel", session="current", timeout=0, poll=1))

    assert "Lock 'vercel_deploy' is available" in capsys.readouterr().out


def test_wait_lock_times_out_for_active_other_session(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {
      "status": "IN_PROGRESS",
      "claimed_by": "other",
      "commit_sha": "abcdef123456",
      "phase": "pushing_commit",
      "since": "2026-07-21T10:00:00Z",
      "last_updated": "2026-07-21T10:00:00Z"
    }
  },
  "sessions": {}
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 10)

    with pytest.raises(SystemExit) as exc:
        sessions.cmd_wait_lock(argparse.Namespace(type="vercel", session="current", timeout=0, poll=1))

    assert exc.value.code == 1


def test_wait_lock_follow_tracks_owner_transition_and_signals_ready(monkeypatch, tmp_path, capsys):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        json.dumps({
            "locks": {"docker_rebuild": {"status": "NONE"}, "vercel_deploy": {"status": "NONE"}},
            "sessions": {"current": {"task": "resume after lock"}},
        }) + "\n",
        encoding="utf-8",
    )
    snapshots = iter([
        {"claimed_by": "first", "phase": "building"},
        {"claimed_by": "second", "phase": "verifying"},
        {},
    ])
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_active_lock_snapshot", lambda _lock_type: next(snapshots))
    monkeypatch.setattr(sessions.time, "sleep", lambda _seconds: None)

    sessions.cmd_wait_lock(argparse.Namespace(type="docker", session="current", timeout=None, poll=1, follow=True))

    output = capsys.readouterr().out
    assert "held by first" in output
    assert "held by second" in output
    assert '"signal": "OPENMATES_WAIT_READY"' in output
    stored = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert "resource_wait" not in stored["sessions"]["current"]


def test_deploy_blocks_before_commit_when_vercel_lock_is_held(monkeypatch, tmp_path, capsys):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {
      "status": "IN_PROGRESS",
      "claimed_by": "other",
      "commit_sha": "abcdef123456",
      "phase": "pushing_commit",
      "since": "2026-07-21T10:00:00Z",
      "last_updated": "2026-07-21T10:00:00Z"
    }
  },
  "sessions": {
    "current": {
      "task": "test deploy lock",
      "modified_files": ["docs/test.md"]
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run_cmd(cmd, cwd=None, timeout=None):
        commands.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_minutes_since", lambda _value: 10)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)

    args = argparse.Namespace(
        session="current",
        exclude=None,
        title="docs: test deploy lock",
        message=None,
        end_session=False,
        no_verify=False,
        use_staged=True,
        skip_tests_reason="unit test",
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
    )

    with pytest.raises(SystemExit) as exc:
        sessions.cmd_deploy(args)

    assert exc.value.code == 1
    assert not any(cmd[:2] == ["git", "commit"] for cmd in commands)
    assert "No commit was created" in capsys.readouterr().err


def test_deploy_releases_vercel_lock_after_successful_push(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {"status": "NONE"}
  },
  "sessions": {
    "current": {
      "task": "test deploy release",
      "modified_files": ["docs/test.md"]
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run_cmd(cmd, cwd=None, timeout=None):
        commands.append(cmd)
        if cmd == ["git", "commit", "-m", "docs: test deploy release"]:
            return 0, "[dev abc123] docs: test deploy release", ""
        if cmd == ["git", "rev-parse", "HEAD"]:
            return 0, "abc123def456", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_validate_staged_deploy_files", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(sessions, "_save_last_deploy_sha", lambda _sha: None)
    allow_control_plane_deploy_protocol(monkeypatch, sessions)

    args = argparse.Namespace(
        session="current",
        exclude=None,
        title="docs: test deploy release",
        message=None,
        end_session=False,
        no_verify=False,
        use_staged=True,
        skip_tests_reason="unit test",
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
    )

    sessions.cmd_deploy(args)

    assert ["git", "push", "origin", "dev"] in commands
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["locks"]["vercel_deploy"]["status"] == "NONE"
    assert data["locks"]["vercel_deploy"]["released_by"] == "current"


def test_deploy_can_start_verification_handoff_after_successful_push(monkeypatch, tmp_path, capsys):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {"status": "NONE"}
  },
  "sessions": {
    "current": {
      "task": "test deploy handoff",
      "modified_files": ["docs/test.md"]
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    started = {}

    def fake_run_cmd(cmd, cwd=None, timeout=None):
        if cmd == ["git", "commit", "-m", "docs: test deploy handoff"]:
            return 0, "[dev abc123] docs: test deploy handoff", ""
        if cmd == ["git", "rev-parse", "HEAD"]:
            return 0, "abc123def456", ""
        return 0, "", ""

    def fake_start(args):
        started["mode"] = args.mode
        started["task"] = args.task

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_validate_staged_deploy_files", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(sessions, "_save_last_deploy_sha", lambda _sha: None)
    monkeypatch.setattr(sessions, "cmd_start", fake_start)
    allow_control_plane_deploy_protocol(monkeypatch, sessions)

    args = argparse.Namespace(
        session="current",
        exclude=None,
        title="docs: test deploy handoff",
        message=None,
        end_session=False,
        no_verify=False,
        use_staged=True,
        skip_tests_reason="unit test",
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
        start_verification_session=True,
    )

    sessions.cmd_deploy(args)

    assert started == {
        "mode": "testing",
        "task": "Verify deploy abc123def from session current",
    }
    output = capsys.readouterr().out
    assert "== VERIFICATION HANDOFF ==" in output
    assert "--expected-commit abc123def456" in output


def test_deployed_commit_handoff_prints_full_sha_and_content_stable_test_command(capsys):
    sessions = load_sessions_module()
    commit = "abcdef1234567890abcdef1234567890abcdef12"

    sessions._print_deployed_commit_handoff(commit)

    output = capsys.readouterr().out
    assert f"Full commit: {commit}" in output
    assert f"--gate-deploy --expected-commit {commit}" in output
    assert "--require-exact-commit" not in output


def test_use_staged_deploy_rejects_untracked_staged_files(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {"status": "NONE"}
  },
  "sessions": {
    "current": {
      "task": "test staged deploy fallback",
      "modified_files": []
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run_cmd(cmd, cwd=None, timeout=None):
        commands.append(cmd)
        if cmd == ["git", "commit", "-m", "docs: staged fallback"]:
            return 0, "[dev abc123] docs: staged fallback", ""
        if cmd == ["git", "rev-parse", "HEAD"]:
            return 0, "abc123def456", ""
        return 0, "", ""

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda *, checkout_root=None: {"docs/test.md"})
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_validate_staged_deploy_files", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(sessions, "_save_last_deploy_sha", lambda _sha: None)

    args = argparse.Namespace(
        session="current",
        exclude=None,
        title="docs: staged fallback",
        message=None,
        end_session=False,
        no_verify=False,
        use_staged=True,
        skip_tests_reason="unit test",
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
    )

    with pytest.raises(SystemExit) as exc:
        sessions.cmd_deploy(args)

    assert exc.value.code == 1
    assert ["git", "commit", "-m", "docs: staged fallback"] not in commands


def test_use_staged_deploy_rechecks_index_before_commit(monkeypatch, tmp_path, capsys):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {"status": "NONE"}
  },
  "sessions": {
    "current": {
      "task": "test staged deploy race",
      "modified_files": ["docs/test.md"]
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []
    staged_snapshots = iter([
        {"docs/test.md"},
        {"docs/test.md"},
        {"frontend/apps/web_app/tests/other.spec.ts"},
    ])

    def fake_run_cmd(cmd, cwd=None, timeout=None):
        commands.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda *, checkout_root=None: next(staged_snapshots))
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    allow_control_plane_deploy_protocol(monkeypatch, sessions)

    args = argparse.Namespace(
        session="current",
        exclude=None,
        title="docs: test deploy race",
        message=None,
        end_session=False,
        no_verify=False,
        use_staged=True,
        skip_tests_reason="unit test",
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
    )

    with pytest.raises(SystemExit) as exc:
        sessions.cmd_deploy(args)

    assert exc.value.code == 1
    assert not any(cmd[:2] == ["git", "commit"] for cmd in commands)
    assert "Staged index changed before commit" in capsys.readouterr().err


def test_deploy_rechecks_auto_staged_index_before_commit(monkeypatch, tmp_path, capsys):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {"status": "NONE"}
  },
  "sessions": {
    "current": {
      "task": "test auto staged deploy race",
      "modified_files": ["docs/test.md"]
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []
    staged_snapshots = iter([
        set(),
        {"frontend/apps/web_app/tests/other.spec.ts"},
    ])

    def fake_run_cmd(cmd, cwd=None, timeout=None):
        commands.append(cmd)
        return 0, "", ""

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: ["docs/test.md"])
    monkeypatch.setattr(sessions, "_get_staged_files", lambda *, checkout_root=None: next(staged_snapshots))
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_pytest_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_embed_registry_validation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_enforce_vercel_standard_build_machine", lambda: None)
    monkeypatch.setattr(sessions, "_wait_and_acquire_session_lock", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sessions, "_release_session_lock", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    allow_control_plane_deploy_protocol(monkeypatch, sessions)

    args = argparse.Namespace(
        session="current",
        exclude=None,
        title="docs: test auto deploy race",
        message=None,
        end_session=False,
        no_verify=False,
        use_staged=False,
        skip_tests_reason="unit test",
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
    )

    with pytest.raises(SystemExit) as exc:
        sessions.cmd_deploy(args)

    assert exc.value.code == 1
    assert any(cmd[:2] in (["git", "add"], ["git", "rm"]) for cmd in commands)
    assert not any(cmd[:2] == ["git", "commit"] for cmd in commands)
    assert "Staged index changed before commit" in capsys.readouterr().err


def test_deploy_blocks_sdk_changes_when_cleartext_gate_fails(monkeypatch, tmp_path, capsys):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(
        """
{
  "locks": {
    "docker_rebuild": {"status": "NONE"},
    "vercel_deploy": {"status": "NONE"}
  },
  "sessions": {
    "current": {
      "task": "test sdk deploy gate",
      "modified_files": ["frontend/packages/openmates-cli/src/sdk.ts"]
    }
  }
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def fake_run_cmd(cmd, cwd=None, timeout=None):
        commands.append(cmd)
        return 0, "", ""

    def fake_sdk_audit(cmd):
        return 1, "", "parity drift"

    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_get_dirty_files", lambda *, checkout_root=None: ["frontend/packages/openmates-cli/src/sdk.ts"])
    monkeypatch.setattr(sessions, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(sessions, "_run_translation_build", lambda: (0, "", ""))
    monkeypatch.setattr(sessions, "_run_translation_validation", lambda: (0, "", ""))
    monkeypatch.setattr(sessions, "_run_test_enforcement_gate", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sessions, "_run_sdk_cleartext_audit", fake_sdk_audit)

    args = argparse.Namespace(
        session="current",
        exclude=None,
        title="test: sdk gate",
        message=None,
        end_session=False,
        no_verify=False,
        use_staged=False,
        skip_tests_reason=None,
        require_parity=False,
        lock_timeout=0,
        lock_poll=1,
    )

    with pytest.raises(SystemExit) as exc:
        sessions.cmd_deploy(args)

    assert exc.value.code == 1
    assert not any(cmd[:2] == ["git", "add"] for cmd in commands)
    assert not any(cmd[:2] == ["git", "commit"] for cmd in commands)
    assert "SDK CLEARTEXT GATE FAILED" in capsys.readouterr().err
