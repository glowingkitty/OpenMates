#!/usr/bin/env python3
"""Regression tests for the OpenCode control-plane deployment boundary.

Ordinary product sessions must never deploy the traffic controller that routes
all other chats. Codex-owned control-plane work is committed outside the product
session deploy path, so the canonical sessions.py gate rejects these files for
every OpenCode product session rather than trusting a prompt-level capability.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_PATH = PROJECT_ROOT / "scripts" / "sessions.py"


def load_sessions_module():
    spec = importlib.util.spec_from_file_location("openmates_sessions_control_plane_guard", SESSIONS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "path",
    [
        "scripts/sessions.py",
        "scripts/start-opencode-server.sh",
        "scripts/server-restart.sh",
        "scripts/opencode_permission_watcher.py",
        "scripts/opencode_credential_migration.py",
        "scripts/opencode_runtime_release.py",
        "scripts/sync_opencode_runtime_hook.py",
        "scripts/patches/opencode-v1.17.20-productive-recompaction.patch",
        ".opencode/plugins/openmates-hooks.js",
        ".opencode/agents/code-reviewer.md",
        "opencode.json",
        "backend/engineering_control_plane/coordination.py",
    ],
)
def test_protected_control_plane_paths_are_classified(path: str) -> None:
    sessions = load_sessions_module()

    assert sessions.is_protected_control_plane_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "frontend/packages/ui/src/components/Button.svelte",
        "backend/apps/ai/tasks/ask_skill_task.py",
        "docs/plans/chat-settings-redesign/plan.yml",
        "scripts/tests/test_user_tasks_scheduler.py",
    ],
)
def test_product_paths_remain_deployable(path: str) -> None:
    sessions = load_sessions_module()

    assert not sessions.is_protected_control_plane_path(path)


def test_product_session_deploy_rejects_protected_manifest() -> None:
    sessions = load_sessions_module()

    with pytest.raises(RuntimeError, match="CONTROL-PLANE DEPLOY BLOCKED"):
        sessions.validate_product_session_deploy_paths(
            ["frontend/packages/ui/src/components/Button.svelte", "scripts/sessions.py"]
        )


def test_codex_unbound_session_may_deploy_control_plane_recovery(monkeypatch) -> None:
    sessions = load_sessions_module()
    monkeypatch.setenv("CODEX_SESSION_ID", "codex-session")
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)

    sessions.validate_product_session_deploy_paths(
        ["scripts/sessions.py", ".opencode/plugins/openmates-hooks.js"],
        session={"opencode_session_id": None, "opencode_top_level_session_id": None},
    )


def test_codex_may_deploy_reviewed_opencode_bound_control_plane_recovery(monkeypatch) -> None:
    sessions = load_sessions_module()
    monkeypatch.setenv("CODEX_SESSION_ID", "codex-session")
    monkeypatch.delenv("OPENCODE_SESSION_ID", raising=False)

    sessions.validate_product_session_deploy_paths(
        ["scripts/sessions.py"],
        session={"opencode_session_id": "ses_bound"},
    )


def test_opencode_runtime_cannot_use_codex_control_plane_allowance(monkeypatch) -> None:
    sessions = load_sessions_module()
    monkeypatch.setenv("CODEX_SESSION_ID", "codex-session")
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_current")

    with pytest.raises(RuntimeError, match="CONTROL-PLANE DEPLOY BLOCKED"):
        sessions.validate_product_session_deploy_paths(
            ["scripts/sessions.py"],
            session={"opencode_session_id": None, "opencode_top_level_session_id": None},
        )


def test_product_session_deploy_allows_unprotected_manifest() -> None:
    sessions = load_sessions_module()

    sessions.validate_product_session_deploy_paths(
        ["frontend/packages/ui/src/components/Button.svelte", "backend/apps/ai/tasks/ask_skill_task.py"]
    )
