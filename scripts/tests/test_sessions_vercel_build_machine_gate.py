#!/usr/bin/env python3
"""Regression tests for the sessions.py Vercel build-machine deploy gate."""

from __future__ import annotations

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
