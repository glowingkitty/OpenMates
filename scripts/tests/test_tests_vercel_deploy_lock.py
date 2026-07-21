#!/usr/bin/env python3
"""Regression tests for tests.py releasing Vercel deploy locks."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TESTS_PATH = PROJECT_ROOT / "scripts" / "tests.py"


def load_tests_module():
    spec = importlib.util.spec_from_file_location("openmates_tests_control", TESTS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_sessions_file(path: Path, commit_sha: str) -> None:
    path.write_text(
        json.dumps(
            {
                "locks": {
                    "docker_rebuild": {"status": "NONE"},
                    "vercel_deploy": {
                        "status": "IN_PROGRESS",
                        "claimed_by": "89c2",
                        "commit_sha": commit_sha,
                        "since": "2026-07-21T10:00:00Z",
                        "last_updated": "2026-07-21T10:00:00Z",
                    },
                },
                "sessions": {},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_release_vercel_deploy_lock_for_matching_commit(monkeypatch, tmp_path):
    tests_control = load_tests_module()
    sessions_file = tmp_path / "sessions.json"
    write_sessions_file(sessions_file, "abcdef123456")
    monkeypatch.setattr(tests_control, "SESSIONS_FILE", sessions_file)

    assert tests_control.release_vercel_deploy_lock_for_commit("abcdef1") is True

    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["locks"]["vercel_deploy"]["status"] == "NONE"
    assert data["locks"]["vercel_deploy"]["released_commit_sha"] == "abcdef123456"


def test_release_vercel_deploy_lock_keeps_mismatched_commit(monkeypatch, tmp_path):
    tests_control = load_tests_module()
    sessions_file = tmp_path / "sessions.json"
    write_sessions_file(sessions_file, "abcdef123456")
    monkeypatch.setattr(tests_control, "SESSIONS_FILE", sessions_file)

    assert tests_control.release_vercel_deploy_lock_for_commit("123456abcdef") is False

    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["locks"]["vercel_deploy"]["status"] == "IN_PROGRESS"
