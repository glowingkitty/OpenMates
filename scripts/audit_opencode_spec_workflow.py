#!/usr/bin/env python3
"""Audit OpenCode spec-driven workflow wiring.

OpenMates relies on prompt instructions, skills, and deterministic spec scripts
to approximate the product Plans V1 flow before durable /v1/user-plans records
are available everywhere. This audit catches drift in the OpenCode Plan Mode
override, canonical SDD skills, and project instruction loading.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_CONFIG = REPO_ROOT / "opencode.json"
OPENCODE_COORDINATION_PLUGIN = Path(".opencode/plugins/openmates-hooks.js")
OPENCODE_BLOCKING_LEASE_SCRIPT = Path("scripts/opencode_file_leases.py")
OPENCODE_WARNING_GUARD = Path(".claude/hooks/pre-edit-guard.sh")
REQUIRED_INSTRUCTIONS = {
    "docs/contributing/guides/agent-workflow-core.md",
}
PLAN_PROMPT_TERMS = {
    "risk tier",
    "Tier 1",
    "Tier 2",
    "may edit only",
    "one clarifying question",
    "coverage_status",
    "verification_ids",
    "vague criteria",
    "Failed required checks",
    "spec_validate.py",
    "spec_verify.py",
    "schema_version",
    "subject_commit",
    "V-UI-VISUAL-SMOKE",
    "viewports: [laptop, mobile]",
    "handoff",
    "narration outline",
    "frame-only review",
    "proof-video",
    "narration audio is optional",
    "Discord delivery",
}
PLAN_EDIT_PERMISSION_ITEMS = (
    ("*", "deny"),
    ("docs/specs/**/spec.yml", "allow"),
)
SKILL_TERMS = {
    ".claude/skills/create-demo-video/SKILL.md": {
        "proof_video_workflow.py start --current",
        "audio is off by default",
        "bottom-centered",
        "three to eight",
        "product_defect",
    },
    ".claude/skills/specify/SKILL.md": {
        "Risk tier",
        "coverage_status",
        "verification_ids",
        "assumptions",
        "vague criteria",
        "schema_version",
        "V-UI-VISUAL-SMOKE",
        "viewports: [laptop, mobile]",
        "handoff",
        "narration outline",
        "demonstration eligibility",
    },
    ".claude/skills/plan-from-spec/SKILL.md": {
        "required assumptions",
        "coverage_status",
        "verification_ids",
        "approvals.implementation_plan",
        "handoff",
        "capture source",
        "full video",
    },
    ".claude/skills/tasks-from-spec/SKILL.md": {
        "failed required checks",
        "follow-up tasks",
        "verification_ids",
        "UI visual smoke",
        "--viewport laptop --viewport mobile",
        "ownership",
        "handoff",
        "frame-only review",
        "configured Discord publication",
        "optional narration audio",
    },
    ".claude/skills/verify-spec/SKILL.md": {
        "Continue On Failure",
        "coverage_status",
        "required assumptions",
        "failed required checks",
        "visual-smoke evidence",
        "laptop/mobile",
        "subject commit",
        "material",
        "frame-only",
        "publication_pending",
        "intentional audio status",
        "configured Discord delivery",
    },
}
CANONICAL_SKILLS = tuple(SKILL_TERMS)
PROOF_REVIEWER_TERMS = {
    "three to eight image frames",
    "Never request or read the\nfull video",
    "capture_defect",
    "render_defect",
    "product_defect",
    "uncertain",
}
INSTRUCTION_TERMS = {
    "AGENTS.md": {"continue through all actionable tasks", "temporary file waits", "Agent Workflow Retrospective", "task-closing", "None observed"},
    "CLAUDE.md": {"Agent Workflow Retrospective", "task-closing", "None observed"},
    "docs/contributing/guides/agent-workflow-core.md": {"Lazy-load", "Final responses", "verification commands", "full video", "proof-video", "narration audio is optional", "Discord delivery", "Agent Workflow Retrospective", "task-closing", "None observed"},
    ".claude/rules/session-lifecycle.md": {
        "Active executable specs are non-interruptible",
        "File waits are not user blockers",
    },
    "docs/contributing/guides/spec-driven-development.md": {"Risk Tiers", "Tier 1", "Tier 2", "UI visual smoke", "viewports: [laptop, mobile]", "demonstration review", "narration audio is optional", "publication_pending"},
}
OPENCODE_COORDINATION_TERMS = {
    "OPENCODE_SESSION_ID",
    'runBridge("PreToolUse"',
    "edit-lease",
    'OPENMATES_ROOT_GUARD || "strict"',
    "Docker Compose mutations require",
}
OPENCODE_WARNING_TERMS = {"additionalContext", "WARNING: File", "exit 0"}
FORBIDDEN_COORDINATION_TERMS = {
    "Waiting for file lease",
    "createFileLeaseCoordinator",
    "createSpecAutoContinue",
    "opencode_file_leases.py",
}
IDLE_SIDE_EFFECT_RE = re.compile(r"client\.session\.(?:prompt|command)\s*\(")


def _load_opencode_config(path: Path = OPENCODE_CONFIG) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_config(config: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    instructions = set(config.get("instructions", []))
    for instruction in sorted(REQUIRED_INSTRUCTIONS - instructions):
        failures.append(f"opencode.json missing instruction: {instruction}")

    plan_agent = config.get("agent", {}).get("plan")
    if not isinstance(plan_agent, dict):
        failures.append("opencode.json must define agent.plan for read-only Plan Mode")
        return failures

    permission = plan_agent.get("permission", {})
    edit_permission = permission.get("edit")
    if not isinstance(edit_permission, dict) or tuple(edit_permission.items()) != PLAN_EDIT_PERMISSION_ITEMS:
        failures.append("agent.plan.permission.edit must provide spec-only edit access")
    if permission.get("question") != "allow":
        failures.append("agent.plan.permission.question must be allow")
    if plan_agent.get("mode") != "primary":
        failures.append("agent.plan.mode must be primary")

    prompt = plan_agent.get("prompt", "")
    documented_plan_terms = PLAN_PROMPT_TERMS - {"schema_version"}
    instruction_text = "\n".join(
        (REPO_ROOT / path).read_text(encoding="utf-8")
        for path in instructions
        if (REPO_ROOT / path).is_file()
    )
    for term in sorted(PLAN_PROMPT_TERMS):
        if term not in prompt and not (term in documented_plan_terms and term in instruction_text):
            failures.append(f"agent.plan.prompt missing required term: {term}")
    return failures


def audit_skills(root: Path = REPO_ROOT) -> list[str]:
    failures: list[str] = []
    for rel_path, terms in SKILL_TERMS.items():
        path = root / rel_path
        if not path.exists():
            failures.append(f"missing canonical skill: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        for term in sorted(terms):
            if term not in text:
                failures.append(f"{rel_path} missing required term: {term}")
    return failures


def audit_proof_video_reviewer(root: Path = REPO_ROOT) -> list[str]:
    path = root / ".claude/agents/proof-video-reviewer.md"
    if not path.exists():
        return ["missing canonical proof-video reviewer"]
    text = path.read_text(encoding="utf-8")
    return [f"proof-video reviewer missing required term: {term}" for term in sorted(PROOF_REVIEWER_TERMS) if term not in text]


def audit_skill_mirrors(root: Path = REPO_ROOT) -> list[str]:
    failures: list[str] = []
    for claude_rel_path in CANONICAL_SKILLS:
        agent_rel_path = claude_rel_path.replace(".claude/skills/", ".agents/skills/", 1)
        claude_path = root / claude_rel_path
        agent_path = root / agent_rel_path
        if not agent_path.exists():
            failures.append(f"missing Agent Skill mirror: {agent_rel_path}")
            continue
        if claude_path.read_text(encoding="utf-8") != agent_path.read_text(encoding="utf-8"):
            failures.append(f"Agent Skill mirror drifted: {agent_rel_path}")
    return failures


def audit_instructions(root: Path = REPO_ROOT) -> list[str]:
    failures: list[str] = []
    for rel_path, terms in INSTRUCTION_TERMS.items():
        path = root / rel_path
        if not path.exists():
            failures.append(f"missing workflow instruction: {rel_path}")
            continue
        text = path.read_text(encoding="utf-8")
        for term in sorted(terms):
            if term not in text:
                failures.append(f"{rel_path} missing required workflow term: {term}")
    return failures


def audit_opencode_coordination(root: Path = REPO_ROOT) -> list[str]:
    failures: list[str] = []
    if (root / OPENCODE_BLOCKING_LEASE_SCRIPT).exists():
        failures.append("blocking OpenCode file lease coordinator must remain removed")

    path = root / OPENCODE_COORDINATION_PLUGIN
    if not path.exists():
        failures.append("missing OpenCode session coordination plugin")
        return failures

    source = path.read_text(encoding="utf-8")
    for term in sorted(OPENCODE_COORDINATION_TERMS):
        if term not in source:
            failures.append(f"OpenCode coordination plugin missing required term: {term}")
    for term in sorted(FORBIDDEN_COORDINATION_TERMS):
        if term in source:
            failures.append(f"OpenCode coordination plugin contains forbidden blocking term: {term}")
    if "session.idle" in source and IDLE_SIDE_EFFECT_RE.search(source):
        failures.append("OpenCode coordination plugin must not prompt or run commands from passive session.idle observation")

    warning_guard = root / OPENCODE_WARNING_GUARD
    if not warning_guard.exists():
        failures.append("missing OpenCode non-blocking edit warning guard")
        return failures
    warning_source = warning_guard.read_text(encoding="utf-8")
    for term in sorted(OPENCODE_WARNING_TERMS):
        if term not in warning_source:
            failures.append(f"OpenCode edit warning guard missing required term: {term}")
    return failures


def audit() -> list[str]:
    return (
        audit_config(_load_opencode_config())
        + audit_skills()
        + audit_proof_video_reviewer()
        + audit_skill_mirrors()
        + audit_instructions()
        + audit_opencode_coordination()
    )


def main() -> int:
    failures = audit()
    if failures:
        print("FAIL OpenCode spec workflow audit", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("PASS OpenCode spec workflow audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
