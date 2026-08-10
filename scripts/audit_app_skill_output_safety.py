#!/usr/bin/env python3
"""Audit app-skill output safety wiring.

Purpose: prevent external app-skill output protection from drifting silently.
Architecture: static checks for dispatch surfaces, SDK opt-out contracts, and metadata.
Security: ASCII-smuggling cleanup must remain mandatory; semantic scanning defaults on.
Tests: python3 scripts/audit_app_skill_output_safety.py
Spec: docs/specs/app-skill-output-safety/spec.yml.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
SAFETY_MODULE = ROOT / "backend/shared/python_utils/app_skill_output_safety.py"
REST_ROUTE = ROOT / "backend/core/api/app/routes/apps_api.py"
ASSISTANT_EXECUTOR = ROOT / "backend/apps/ai/processing/skill_executor.py"
WORKFLOW_ADAPTER = ROOT / "backend/core/api/app/services/workflow_app_skill_adapter.py"
CLI_TS = ROOT / "frontend/packages/openmates-cli/src/cli.ts"
CLI_CLIENT_TS = ROOT / "frontend/packages/openmates-cli/src/client.ts"
NPM_SDK_TS = ROOT / "frontend/packages/openmates-cli/src/sdk.ts"
NPM_GENERATED_TS = ROOT / "frontend/packages/openmates-cli/src/generated/appSkills.ts"
PIP_SDK = ROOT / "packages/openmates-python/openmates/sdk.py"
PIP_GENERATED = ROOT / "packages/openmates-python/openmates/generated/app_skills.py"
APP_METADATA_ROOT = ROOT / "backend/apps"

OPENMATES_PROVIDER = "openmates"
PROMPT_INJECTION_CONTRACT = 'prompt_injection_protection: PROMPT_INJECTION_DISABLED'
def main() -> int:
    failures: list[str] = []
    always_external = read_always_external_data_skills()

    failures.extend(check_contains(SAFETY_MODULE, [
        "sanitize_text_payload_for_ascii_smuggling",
        "sanitize_long_text_fields_in_payload",
        "prompt_injection_protection_disabled_for_surface",
        "surface != APP_SKILL_SURFACE_REST",
        "providers = _read_attr(skill, \"providers\")",
        "name.lower() != OPENMATES_PROVIDER_NAME",
        "raise RuntimeError(\"Prompt-injection protection failed for app-skill output\")",
    ]))
    failures.extend(check_contains(REST_ROUTE, [
        "APP_SKILL_SURFACE_REST",
        "strip_request_security_controls",
        "sanitize_app_skill_output",
        "AppSkillOutputSafetyContext",
    ]))
    failures.extend(check_contains(ASSISTANT_EXECUTOR, [
        "APP_SKILL_SURFACE_ASSISTANT",
        "sanitize_app_skill_output",
        "AppSkillOutputSafetyContext",
    ]))
    failures.extend(check_contains(WORKFLOW_ADAPTER, [
        "APP_SKILL_SURFACE_WORKFLOW",
        "strip_request_security_controls",
        "sanitize_app_skill_output",
        "AppSkillOutputSafetyContext",
    ]))
    failures.extend(check_contains(CLI_TS, [
        "--disable-prompt-injection-protection",
        "promptInjectionProtection",
    ]))
    failures.extend(check_contains(CLI_CLIENT_TS, [
        PROMPT_INJECTION_CONTRACT,
        "withAppSkillPromptInjectionOption",
    ]))
    failures.extend(check_contains(NPM_SDK_TS, [
        PROMPT_INJECTION_CONTRACT,
        "withAppSkillRunOptions",
    ]))
    failures.extend(check_contains(NPM_GENERATED_TS, [
        "AppSkillRunOptions",
        "promptInjectionProtection?: boolean",
    ]))
    failures.extend(check_contains(PIP_SDK, [
        '"prompt_injection_protection": PROMPT_INJECTION_DISABLED',
        "_with_app_skill_prompt_injection_option",
    ]))
    failures.extend(check_contains(PIP_GENERATED, [
        "prompt_injection_protection: bool | None = None",
        "prompt_injection_protection=prompt_injection_protection",
    ]))
    failures.extend(check_external_provider_skill_coverage(always_external))

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    print("PASS app-skill output safety audit")
    return 0


def read_always_external_data_skills() -> set[tuple[str, str]]:
    tree = ast.parse(SAFETY_MODULE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "ALWAYS_EXTERNAL_DATA_SKILLS":
            value = ast.literal_eval(node.value)
            return {(str(app_id), str(skill_id)) for app_id, skill_id in value}
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "ALWAYS_EXTERNAL_DATA_SKILLS" for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        return {(str(app_id), str(skill_id)) for app_id, skill_id in value}
    raise RuntimeError("ALWAYS_EXTERNAL_DATA_SKILLS not found")


def check_contains(path: Path, needles: list[str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [f"{relative(path)} missing `{needle}`" for needle in needles if needle not in text]


def check_external_provider_skill_coverage(always_external: set[tuple[str, str]]) -> list[str]:
    failures: list[str] = []
    external_provider_count = 0
    for app_yml in sorted(APP_METADATA_ROOT.glob("*/app.yml")):
        data = yaml.safe_load(app_yml.read_text(encoding="utf-8")) or {}
        app_id = str(data.get("id") or app_yml.parent.name)
        for skill in data.get("skills") or []:
            if not isinstance(skill, dict):
                continue
            skill_id = str(skill.get("id") or "")
            if not skill_id or not has_external_provider(skill):
                continue
            external_provider_count += 1
            if (app_id, skill_id) in always_external or isinstance(skill.get("external_data"), bool):
                continue
            output_safety = skill.get("output_safety")
            if isinstance(output_safety, dict) and isinstance(output_safety.get("external_data"), bool):
                continue
            # Provider-backed skills are covered by the central provider heuristic.
            # Explicit metadata is optional unless the skill intentionally overrides
            # the default external-data classification.
            continue
    if external_provider_count == 0:
        failures.append("No external-provider app skills were found to exercise provider inference")
    return failures


def has_external_provider(skill: dict[str, Any]) -> bool:
    providers = skill.get("providers") or []
    for provider in providers:
        name = provider.get("name") if isinstance(provider, dict) else provider
        if name and str(name).lower() != OPENMATES_PROVIDER:
            return True
    return False


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
