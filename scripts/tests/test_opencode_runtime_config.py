#!/usr/bin/env python3
# contract-test-file: tooling
"""Contracts for the OpenCode runtime configuration shipped by OpenMates.

Primary agents must not lose their tools because they crossed an arbitrary
number of useful operations. Task state and progress-aware orchestration own
continuation and loop diagnostics; the OpenCode `steps` option remains available
upstream but is intentionally absent from the deployed OpenMates configuration.
"""

from __future__ import annotations

import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_primary_agents_have_no_fixed_step_limit() -> None:
    config = json.loads((PROJECT_ROOT / "opencode.json").read_text(encoding="utf-8"))

    limited = {
        name: agent["steps"]
        for name, agent in config.get("agent", {}).items()
        if isinstance(agent, dict) and "steps" in agent
    }

    assert limited == {}


def test_primary_agents_use_openmates_tasks_instead_of_native_todos() -> None:
    config = json.loads((PROJECT_ROOT / "opencode.json").read_text(encoding="utf-8"))

    permission = config.get("permission", {})
    assert permission.get("todowrite") == "deny"
    assert permission.get("todoread") == "deny"
    assert permission.get("task", "allow") == "allow"
    assert permission.get("openmates_task") == "allow"
    assert config["agent"]["plan"]["permission"]["todowrite"] == "deny"
    assert config["agent"]["plan"]["permission"]["task"] == "allow"


def test_launcher_accepts_explicit_shared_project_and_runtime_paths() -> None:
    launcher = (PROJECT_ROOT / "scripts/start-opencode-server.sh").read_text(encoding="utf-8")

    assert 'SOURCE_CHECKOUT="${OPENCODE_PROJECT_ROOT:-' in launcher
    assert 'RUNTIME_CHECKOUT="${OPENCODE_RUNTIME_CHECKOUT:-' in launcher


def test_launcher_uses_agent_skills_without_claude_skill_compatibility() -> None:
    launcher = (PROJECT_ROOT / "scripts/start-opencode-server.sh").read_text(encoding="utf-8")

    assert "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1" in launcher


def test_runtime_patch_bounds_provider_retries_and_persists_terminal_errors() -> None:
    patch = (
        PROJECT_ROOT / "scripts/patches/opencode-v1.17.20-bounded-provider-retries.patch"
    ).read_text(encoding="utf-8")

    assert "RETRY_MAX_RETRIES = 5" in patch
    assert "RETRY_MAX_NOT_FOUND_RETRIES = 1" in patch
    assert 'ctx.assistantMessage.finish = "error"' in patch
    assert "stops a repeated OpenAI 404 after one retry" in patch
