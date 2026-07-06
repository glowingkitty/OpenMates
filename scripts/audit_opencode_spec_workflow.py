#!/usr/bin/env python3
"""Audit OpenCode spec-driven workflow wiring.

OpenMates relies on prompt instructions, skills, and deterministic spec scripts
to approximate the product Plans V1 flow before durable /v1/user-plans records
are available everywhere. This audit catches drift in the OpenCode Plan Mode
override, canonical SDD skills, and project instruction loading.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_CONFIG = REPO_ROOT / "opencode.json"
REQUIRED_INSTRUCTIONS = {
    ".claude/rules/planning.md",
    ".claude/rules/testing.md",
    "docs/contributing/guides/spec-driven-development.md",
}
PLAN_PROMPT_TERMS = {
    "Do not edit",
    "one clarifying question",
    "coverage_status",
    "verification_ids",
    "vague criteria",
    "Failed required checks",
    "spec_validate.py",
    "spec_verify.py",
}
SKILL_TERMS = {
    ".claude/skills/specify/SKILL.md": {
        "coverage_status",
        "verification_ids",
        "assumptions",
        "vague criteria",
    },
    ".claude/skills/plan-from-spec/SKILL.md": {
        "required assumptions",
        "coverage_status",
        "verification_ids",
    },
    ".claude/skills/tasks-from-spec/SKILL.md": {
        "failed required checks",
        "follow-up tasks",
        "verification_ids",
    },
    ".claude/skills/verify-spec/SKILL.md": {
        "coverage_status",
        "required assumptions",
        "failed required checks",
    },
}
CANONICAL_SKILLS = tuple(SKILL_TERMS)


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
    if permission.get("edit") != "deny":
        failures.append("agent.plan.permission.edit must be deny")
    if permission.get("question") != "allow":
        failures.append("agent.plan.permission.question must be allow")
    if plan_agent.get("mode") != "primary":
        failures.append("agent.plan.mode must be primary")

    prompt = plan_agent.get("prompt", "")
    for term in sorted(PLAN_PROMPT_TERMS):
        if term not in prompt:
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


def audit() -> list[str]:
    return audit_config(_load_opencode_config()) + audit_skills() + audit_skill_mirrors()


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
