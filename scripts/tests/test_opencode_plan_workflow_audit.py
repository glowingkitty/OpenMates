"""Tests for the OpenCode Plan workflow audit.

Purpose: prove the OpenCode Plan Mode and Plan skill wiring are checked
deterministically instead of relying on prompt memory.
Architecture: import the audit module and exercise config checks in memory.
Security: no credentials, network calls, or product data are involved.
Tests: python3 -m pytest scripts/tests/test_opencode_plan_workflow_audit.py.
"""

# contract-test-file: tooling

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = ROOT / "scripts/audit_opencode_plan_workflow.py"
COORDINATION_PLUGIN_FIXTURE = " ".join(
    [
        "OPENCODE_SESSION_ID",
        'runBridge("PreToolUse"',
        "edit-lease",
        'OPENMATES_ROOT_GUARD || "strict"',
        "Direct Docker Compose lifecycle mutations bypass",
    ]
)


def load_audit_module():
    module_spec = importlib.util.spec_from_file_location("audit_opencode_plan_workflow", AUDIT_PATH)
    assert module_spec and module_spec.loader
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    module_spec.loader.exec_module(module)
    return module


def test_opencode_plan_workflow_audit_passes_current_repo():
    audit = load_audit_module()

    assert audit.audit() == []


def test_opencode_plan_workflow_audit_requires_plan_agent():
    audit = load_audit_module()
    config = {
        "instructions": sorted(audit.REQUIRED_INSTRUCTIONS),
        "permission": {"skill": {"*": "allow", "gsd-*": "deny"}},
    }

    failures = audit.audit_config(config)

    assert any("agent.plan" in failure for failure in failures)


def test_opencode_plan_workflow_audit_allows_plan_mode_to_edit_only_executable_plans():
    audit = load_audit_module()
    config = audit._load_opencode_config()
    config["agent"]["plan"] = dict(config["agent"]["plan"])
    config["agent"]["plan"]["permission"] = dict(config["agent"]["plan"]["permission"])
    config["agent"]["plan"]["permission"]["edit"] = {
        "*": "deny",
        "docs/plans/**/plan.yml": "allow",
    }

    failures = audit.audit_config(config)

    assert not any("agent.plan.permission.edit" in failure for failure in failures)


def test_opencode_plan_workflow_audit_rejects_broad_plan_mode_edit_access():
    audit = load_audit_module()
    config = audit._load_opencode_config()
    config["agent"]["plan"] = dict(config["agent"]["plan"])
    config["agent"]["plan"]["permission"] = dict(config["agent"]["plan"]["permission"])
    config["agent"]["plan"]["permission"]["edit"] = "allow"

    failures = audit.audit_config(config)

    assert any("Plan-only edit access" in failure for failure in failures)


def test_opencode_plan_workflow_audit_rejects_reversed_plan_mode_edit_precedence():
    audit = load_audit_module()
    config = audit._load_opencode_config()
    config["agent"]["plan"] = dict(config["agent"]["plan"])
    config["agent"]["plan"]["permission"] = dict(config["agent"]["plan"]["permission"])
    config["agent"]["plan"]["permission"]["edit"] = {
        "docs/plans/**/plan.yml": "allow",
        "*": "deny",
    }

    failures = audit.audit_config(config)

    assert any("Plan-only edit access" in failure for failure in failures)


def test_opencode_plan_workflow_audit_detects_skill_mirror_drift(tmp_path):
    audit = load_audit_module()
    claude_skill = tmp_path / ".claude" / "skills" / "create-plan" / "SKILL.md"
    agent_skill = tmp_path / ".agents" / "skills" / "create-plan" / "SKILL.md"
    claude_skill.parent.mkdir(parents=True)
    agent_skill.parent.mkdir(parents=True)
    claude_skill.write_text("canonical", encoding="utf-8")
    agent_skill.write_text("drifted", encoding="utf-8")

    failures = audit.audit_skill_mirrors(tmp_path)

    assert any("mirror drifted" in failure for failure in failures)


def test_opencode_plan_workflow_audit_requires_coordination_plugin(tmp_path):
    audit = load_audit_module()

    failures = audit.audit_opencode_coordination(tmp_path)

    assert failures == ["missing OpenCode session coordination plugin"]


def test_opencode_plan_workflow_audit_rejects_blocking_lease_coordinator(tmp_path):
    audit = load_audit_module()
    plugin = tmp_path / ".opencode" / "plugins" / "openmates-hooks.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(COORDINATION_PLUGIN_FIXTURE, encoding="utf-8")
    warning_guard = tmp_path / ".claude" / "hooks" / "pre-edit-guard.sh"
    warning_guard.parent.mkdir(parents=True)
    warning_guard.write_text("additionalContext WARNING: File exit 0", encoding="utf-8")
    lease_script = tmp_path / "scripts" / "opencode_file_leases.py"
    lease_script.parent.mkdir(parents=True)
    lease_script.write_text("blocking lease coordinator", encoding="utf-8")

    failures = audit.audit_opencode_coordination(tmp_path)

    assert "blocking OpenCode file lease coordinator must remain removed" in failures


def test_opencode_plan_workflow_audit_rejects_idle_plan_continuation(tmp_path):
    audit = load_audit_module()
    plugin = tmp_path / ".opencode" / "plugins" / "openmates-hooks.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(
        f"{COORDINATION_PLUGIN_FIXTURE} session.idle client.session.prompt(",
        encoding="utf-8",
    )
    warning_guard = tmp_path / ".claude" / "hooks" / "pre-edit-guard.sh"
    warning_guard.parent.mkdir(parents=True)
    warning_guard.write_text("additionalContext WARNING: File exit 0", encoding="utf-8")

    failures = audit.audit_opencode_coordination(tmp_path)

    assert any("must not prompt" in failure for failure in failures)


def test_opencode_plan_workflow_audit_allows_passive_idle_presence(tmp_path):
    audit = load_audit_module()
    plugin = tmp_path / ".opencode" / "plugins" / "openmates-hooks.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(f"{COORDINATION_PLUGIN_FIXTURE} session.idle", encoding="utf-8")
    warning_guard = tmp_path / ".claude" / "hooks" / "pre-edit-guard.sh"
    warning_guard.parent.mkdir(parents=True)
    warning_guard.write_text("additionalContext WARNING: File exit 0", encoding="utf-8")

    assert audit.audit_opencode_coordination(tmp_path) == []


def test_opencode_plan_workflow_audit_requires_modern_edit_lease_contract(tmp_path):
    audit = load_audit_module()
    plugin = tmp_path / ".opencode" / "plugins" / "openmates-hooks.js"
    plugin.parent.mkdir(parents=True)
    plugin.write_text('OPENCODE_SESSION_ID runBridge("PreToolUse"', encoding="utf-8")
    warning_guard = tmp_path / ".claude" / "hooks" / "pre-edit-guard.sh"
    warning_guard.parent.mkdir(parents=True)
    warning_guard.write_text("additionalContext WARNING: File exit 0", encoding="utf-8")

    failures = audit.audit_opencode_coordination(tmp_path)

    assert any("edit-lease" in failure for failure in failures)
    assert any("OPENMATES_ROOT_GUARD" in failure for failure in failures)
    assert any("Direct Docker Compose lifecycle mutations bypass" in failure for failure in failures)


def test_opencode_spec_workflow_audit_requires_demonstration_plan_terms():
    audit = load_audit_module()

    assert {
        "narration outline",
        "frame-only review",
        "proof-video",
        "narration audio is optional",
        "OpenCode response-media",
    }.issubset(audit.PLAN_PROMPT_TERMS)


def test_opencode_plan_workflow_audit_requires_demonstration_skill_terms():
    audit = load_audit_module()
    expected = {
        ".claude/skills/create-demo-video/SKILL.md": {
            "proof_video_workflow.py start --current",
            "audio is off by default",
            "WebVTT",
            "Never burn captions",
            "opencode_response_media.py",
            "actual `openmates` CLI",
            "periodically every five seconds",
            "forty-eight cumulative submitted frames",
            "proof_video_workflow.py review",
        },
        ".claude/skills/create-plan/SKILL.md": {"Specification references", "plan_validate.py"},
        ".claude/skills/tasks-from-plan/SKILL.md": {"frame-only", "response-media embedding"},
        ".claude/skills/verify-plan/SKILL.md": {"Specification references", "plan_verify.py"},
        ".claude/skills/define-specification/SKILL.md": {"scripts/specifications.py validate"},
        ".claude/skills/backfill-specification/SKILL.md": {"scripts/specifications.py check-test"},
    }

    for path, terms in expected.items():
        assert terms.issubset(audit.SKILL_TERMS[path])


def test_opencode_spec_workflow_audit_requires_bounded_proof_reviewer(tmp_path):
    audit = load_audit_module()
    reviewer = tmp_path / ".claude" / "agents" / "proof-video-reviewer.md"
    reviewer.parent.mkdir(parents=True)
    reviewer.write_text("incomplete", encoding="utf-8")

    failures = audit.audit_proof_video_reviewer(tmp_path)

    assert any("full video" in failure for failure in failures)
    assert any("product_defect" in failure for failure in failures)
    assert any("frame_reviews" in failure for failure in failures)
    assert any("Before evaluating" in failure for failure in failures)


def test_opencode_spec_workflow_audit_requires_demonstration_instruction_terms():
    audit = load_audit_module()

    assert "full video" in audit.INSTRUCTION_TERMS["docs/contributing/guides/agent-workflow-core.md"]
    assert "proof-video" in audit.INSTRUCTION_TERMS["docs/contributing/guides/agent-workflow-core.md"]
    assert "--latest-run-type" in audit.INSTRUCTION_TERMS["docs/contributing/guides/agent-workflow-core.md"]
    assert "every `*.spec.ts` run" in audit.INSTRUCTION_TERMS["docs/contributing/guides/agent-workflow-core.md"]
    assert "OpenMates CLI E2E" in audit.INSTRUCTION_TERMS["docs/contributing/guides/agent-workflow-core.md"]


def test_opencode_spec_workflow_audit_requires_cross_runtime_retrospective_terms():
    audit = load_audit_module()

    for path in ("AGENTS.md", "CLAUDE.md", "docs/contributing/guides/agent-workflow-core.md"):
        assert {
            "Agent Workflow Retrospective",
            "task-closing",
            "None observed",
        }.issubset(audit.INSTRUCTION_TERMS[path])
