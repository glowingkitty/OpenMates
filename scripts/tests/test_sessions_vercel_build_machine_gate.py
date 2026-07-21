#!/usr/bin/env python3
"""Regression tests for the sessions.py Vercel build-machine deploy gate."""

from __future__ import annotations

import argparse
import importlib.util
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
            phase="awaiting_vercel_or_e2e",
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
        phase="awaiting_vercel_or_e2e",
    )

    assert acquired is False
