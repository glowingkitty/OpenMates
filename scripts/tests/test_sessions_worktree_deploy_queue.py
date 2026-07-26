#!/usr/bin/env python3
"""Tests for visible blocked deploy fallback metadata.

The record is stored in sessions.json so blocked worktree deploys remain
visible until a human resolves the root integration conflict and retries.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_worktree_deploy_queue", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_enqueue_deploy_records_visible_blocked_metadata(monkeypatch, tmp_path):
    sessions = load_sessions_module()
    sessions_file = tmp_path / "sessions.json"
    sessions_file.write_text(json.dumps({"locks": {}, "sessions": {}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(sessions, "SESSIONS_FILE", sessions_file)
    monkeypatch.setattr(sessions, "_now_iso", lambda: "2026-07-26T00:00:00Z")

    item = sessions.enqueue_worktree_deploy("abcd", "fix: thing", "patch123", reason="lock busy")

    assert item["session_id"] == "abcd"
    assert item["status"] == "blocked"
    assert item["title"] == "fix: thing"
    assert item["patch_id"] == "patch123"
    assert item["reason"] == "lock busy"
    assert "rerun sessions.py deploy" in item["next_action"]
    data = json.loads(sessions_file.read_text(encoding="utf-8"))
    assert data["deploy_queue"] == [item]
