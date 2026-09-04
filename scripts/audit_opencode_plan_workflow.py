#!/usr/bin/env python3
"""Audit OpenCode Plan-driven workflow wiring.

OpenMates relies on prompt instructions, skills, and deterministic Plan scripts
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
    "plan_validate.py",
    "plan_verify.py",
    "schema_version",
    "subject_commit",
    "V-UI-VISUAL-SMOKE",
    "viewports: [laptop, mobile]",
    "handoff",
    "narration outline",
    "frame-only review",
    "proof-video",
    "narration audio is optional",
    "OpenCode response-media",
}
PLAN_EDIT_PERMISSION_ITEMS = (
    ("*", "deny"),
    ("docs/plans/**/plan.yml", "allow"),
)
SKILL_TERMS = {
    ".claude/skills/create-demo-video/SKILL.md": {
        "proof_video_workflow.py start --current",
        "audio is off by default",
        "WebVTT",
        "Never burn captions",
        "immutable one-to-twelve-frame",
        "product_defect",
        "opencode_response_media.py",
        "actual `openmates` CLI",
        "periodically every five seconds",
        "forty-eight cumulative submitted frames",
        "proof_video_workflow.py review",
        "mandatory\nper-frame critical UI scan",
        "intent as `obvious`",
        "ask the user for consent",
        "Do not ask that visual-intent question",
        "proof_video_workflow.py approve-intent",
    },
    ".claude/skills/create-plan/SKILL.md": {
        "Risk tier",
        "assumptions",
        "schema_version",
        "handoff",
        "Specification references",
        "plan_validate.py",
    },
    ".claude/skills/tasks-from-plan/SKILL.md": {
        "Failed required checks",
        "verification_ids",
        "ownership",
        "handoff",
        "frame-only",
        "response-media embedding",
    },
    ".claude/skills/verify-plan/SKILL.md": {
        "Continue On Failure",
        "Failed required checks",
        "visual smoke",
        "subject commits",
        "Specification references",
        "plan_verify.py",
    },
    ".claude/skills/define-specification/SKILL.md": {
        "Specifications define durable truth",
        "scripts/specifications.py validate",
        "specification.yml",
    },
    ".claude/skills/backfill-specification/SKILL.md": {
        "scripts/specifications.py check-test",
        "define-specification",
        "Specification assertions",
    },
}
CANONICAL_SKILLS = tuple(SKILL_TERMS)
PROOF_REVIEWER_TERMS = {
    "one to twelve clean image frames",
    "Never request or read the\nfull video",
    "capture_defect",
    "render_defect",
    "product_defect",
    "uncertain",
    "incidental_findings",
    "frame_reviews",
    "Before evaluating",
    "intent as `obvious`",
    "requires user consent before code changes",
    "every supplied frame",
}
OPENCODE_PROOF_REVIEWER_TERMS = {
    "mode: all",
    '"*": deny',
    "review-prompt-round-*.json",
    "frames/*",
    "grep: deny",
    "glob: deny",
    "external_directory: deny",
}
INSTRUCTION_TERMS = {
    "AGENTS.md": {"continue through all actionable tasks", "temporary file waits", "Agent Workflow Retrospective", "task-closing", "None observed", "snippet_html", "same task-closing assistant response"},
    "CLAUDE.md": {"Agent Workflow Retrospective", "task-closing", "None observed"},
    "docs/contributing/guides/agent-workflow-core.md": {"Lazy-load", "Final responses", "verification commands", "full video", "proof-video", "narration audio is optional", "opencode_response_media.py", "actual `openmates` CLI", "--latest-run-type", "every `*.spec.ts` run", "OpenMates CLI E2E", "Agent Workflow Retrospective", "task-closing", "None observed", "snippet_html", "same task-closing response"},
    "scripts/spec_demo.py": {"REVIEW_QUALITY_CATEGORIES", "frame_reviews", "canonical review request"},
    "scripts/proof_video_workflow.py": {"disposition", "auto_fix", "ask_user", "Before evaluating assertions"},
    ".claude/rules/session-lifecycle.md": {
        "File waits are not user blockers",
        "complete: true",
        "snippet_html",
        "same response",
    },
}
OPENCODE_COORDINATION_TERMS = {
    "OPENCODE_SESSION_ID",
    'runBridge("PreToolUse"',
    "edit-lease",
    'OPENMATES_ROOT_GUARD || "strict"',
    "Direct Docker Compose lifecycle mutations bypass",
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
        failures.append("agent.plan.permission.edit must provide Plan-only edit access")
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


def audit_opencode_proof_video_reviewer(root: Path = REPO_ROOT) -> list[str]:
    path = root / ".opencode/agents/proof-video-reviewer.md"
    if not path.exists():
        return ["missing generated OpenCode proof-video reviewer"]
    text = path.read_text(encoding="utf-8")
    problems = [
        f"OpenCode proof-video reviewer missing required term: {term}"
        for term in sorted(OPENCODE_PROOF_REVIEWER_TERMS)
        if term not in text
    ]
    if "**/test-results/proof-videos/**" in text:
        problems.append("OpenCode proof-video reviewer read access is not scoped to its current run directory")
    return problems


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
        durable_idle_guards = (
            "continuationSuppressedForTest",
            'continuationCommand("claim"',
            'mediaCommand("claim"',
        )
        if not all(term in source for term in durable_idle_guards):
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
        + audit_opencode_proof_video_reviewer()
        + audit_skill_mirrors()
        + audit_instructions()
        + audit_opencode_coordination()
    )


def main() -> int:
    failures = audit()
    if failures:
        print("FAIL OpenCode Plan workflow audit", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1
    print("PASS OpenCode Plan workflow audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
