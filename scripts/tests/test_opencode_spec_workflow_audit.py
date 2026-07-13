"""Tests for the OpenCode spec workflow audit.

Purpose: prove the OpenCode Plan Mode and SDD skill wiring are checked
deterministically instead of relying on prompt memory.
Architecture: import the audit module and exercise config checks in memory.
Security: no credentials, network calls, or product data are involved.
Tests: python3 -m pytest scripts/tests/test_opencode_spec_workflow_audit.py.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/audit_opencode_spec_workflow.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_opencode_spec_workflow", AUDIT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_opencode_spec_workflow_audit_passes_current_repo():
    audit = load_audit_module()

    assert audit.audit() == []


def test_opencode_spec_workflow_audit_requires_plan_agent():
    audit = load_audit_module()
    config = {
        "instructions": sorted(audit.REQUIRED_INSTRUCTIONS),
        "permission": {"skill": {"*": "allow", "gsd-*": "deny"}},
    }

    failures = audit.audit_config(config)

    assert any("agent.plan" in failure for failure in failures)


def test_opencode_spec_workflow_audit_allows_plan_mode_to_edit_only_executable_specs():
    audit = load_audit_module()
    config = audit._load_opencode_config()
    config["agent"]["plan"] = dict(config["agent"]["plan"])
    config["agent"]["plan"]["permission"] = dict(config["agent"]["plan"]["permission"])
    config["agent"]["plan"]["permission"]["edit"] = {
        "*": "deny",
        "docs/specs/**/spec.yml": "allow",
    }

    failures = audit.audit_config(config)

    assert not any("agent.plan.permission.edit" in failure for failure in failures)


def test_opencode_spec_workflow_audit_rejects_broad_plan_mode_edit_access():
    audit = load_audit_module()
    config = audit._load_opencode_config()
    config["agent"]["plan"] = dict(config["agent"]["plan"])
    config["agent"]["plan"]["permission"] = dict(config["agent"]["plan"]["permission"])
    config["agent"]["plan"]["permission"]["edit"] = "allow"

    failures = audit.audit_config(config)

    assert any("spec-only edit access" in failure for failure in failures)


def test_opencode_spec_workflow_audit_rejects_reversed_plan_mode_edit_precedence():
    audit = load_audit_module()
    config = audit._load_opencode_config()
    config["agent"]["plan"] = dict(config["agent"]["plan"])
    config["agent"]["plan"]["permission"] = dict(config["agent"]["plan"]["permission"])
    config["agent"]["plan"]["permission"]["edit"] = {
        "docs/specs/**/spec.yml": "allow",
        "*": "deny",
    }

    failures = audit.audit_config(config)

    assert any("spec-only edit access" in failure for failure in failures)


def test_opencode_spec_workflow_audit_detects_skill_mirror_drift(tmp_path):
    audit = load_audit_module()
    claude_skill = tmp_path / ".claude" / "skills" / "specify" / "SKILL.md"
    agent_skill = tmp_path / ".agents" / "skills" / "specify" / "SKILL.md"
    claude_skill.parent.mkdir(parents=True)
    agent_skill.parent.mkdir(parents=True)
    claude_skill.write_text("canonical", encoding="utf-8")
    agent_skill.write_text("drifted", encoding="utf-8")

    failures = audit.audit_skill_mirrors(tmp_path)

    assert any("mirror drifted" in failure for failure in failures)


def test_opencode_spec_workflow_audit_requires_coordination_plugin(tmp_path):
    audit = load_audit_module()

    failures = audit.audit_opencode_coordination(tmp_path)

    assert failures == ["missing OpenCode session coordination plugin"]


def test_opencode_spec_workflow_audit_rejects_blocking_lease_coordinator(tmp_path):
    audit = load_audit_module()
    plugin = tmp_path / ".opencode" / "plugins" / "openmates-hooks.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text('OPENCODE_SESSION_ID runBridge("PreToolUse"', encoding="utf-8")
    warning_guard = tmp_path / ".claude" / "hooks" / "pre-edit-guard.sh"
    warning_guard.parent.mkdir(parents=True)
    warning_guard.write_text("additionalContext WARNING: File exit 0", encoding="utf-8")
    lease_script = tmp_path / "scripts" / "opencode_file_leases.py"
    lease_script.parent.mkdir(parents=True)
    lease_script.write_text("blocking lease coordinator", encoding="utf-8")

    failures = audit.audit_opencode_coordination(tmp_path)

    assert "blocking OpenCode file lease coordinator must remain removed" in failures


def test_opencode_spec_workflow_audit_rejects_idle_spec_continuation(tmp_path):
    audit = load_audit_module()
    plugin = tmp_path / ".opencode" / "plugins" / "openmates-hooks.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(
        'OPENCODE_SESSION_ID runBridge("PreToolUse" session.idle',
        encoding="utf-8",
    )
    warning_guard = tmp_path / ".claude" / "hooks" / "pre-edit-guard.sh"
    warning_guard.parent.mkdir(parents=True)
    warning_guard.write_text("additionalContext WARNING: File exit 0", encoding="utf-8")

    failures = audit.audit_opencode_coordination(tmp_path)

    assert any("forbidden blocking term" in failure for failure in failures)
