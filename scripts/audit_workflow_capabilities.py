#!/usr/bin/env python3
"""Audit Workflow app-skill capability metadata.

Workflow automation must fail closed. Every public skill in backend/apps/*/app.yml
therefore needs an explicit workflow classification: either a complete enabled
contract or a stable unavailable reason. This deterministic script is used by the
workflow app-skill expansion spec and can run without importing app runtime code.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_ROOT = REPO_ROOT / "backend" / "apps"
WORKFLOW_CLASSIFICATION_FILE = REPO_ROOT / "backend" / "core" / "api" / "app" / "services" / "workflow_capabilities.yml"

EXECUTION_MODES = {"sync", "workflow_ai", "async_job", "sandbox"}
EFFECTS = {"read", "notify", "chat_write", "generate", "compute", "code_execution"}
APPROVALS = {"never", "side_effect_confirmation", "always"}
BINDING_REQUIREMENTS = {
    "none",
    "location",
    "provider_account",
    "connected_account_or_csv",
    "notification_preferences",
    "chat_owner",
}
UNAVAILABLE_REASONS = {
    "WORKFLOW_CLASSIFICATION_REQUIRED",
    "WORKFLOW_INTERNAL_SKILL",
    "WORKFLOW_SKILL_NOT_IMPLEMENTED",
    "WORKFLOW_SKILL_NOT_REGISTERED",
    "WORKFLOW_APP_NOT_REGISTERED",
    "WORKFLOW_METADATA_INVALID",
    "WORKFLOW_EXECUTION_MODE_UNSUPPORTED",
    "WORKFLOW_EFFECT_UNSUPPORTED",
    "WORKFLOW_TEST_EXAMPLE_REQUIRED",
    "WORKFLOW_CONNECTED_ACCOUNT_REQUIRED",
    "WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED",
    "WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED",
    "WORKFLOW_RUNTIME_UNSUPPORTED",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit workflow capability metadata in app.yml files")
    parser.add_argument("--json", action="store_true", help="Print machine-readable audit issues")
    args = parser.parse_args()

    issues = audit_workflow_capabilities()
    if args.json:
        print(json.dumps([issue.as_dict() for issue in issues], indent=2, sort_keys=True))
    elif issues:
        for issue in issues:
            print(f"{issue.file}:{issue.skill}: {issue.code}: {issue.message}")
    else:
        print("PASS workflow capability metadata audit")
    return 1 if issues else 0


class AuditIssue:
    def __init__(self, file: str, skill: str, code: str, message: str) -> None:
        self.file = file
        self.skill = skill
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {
            "file": self.file,
            "skill": self.skill,
            "code": self.code,
            "message": self.message,
        }


def audit_workflow_capabilities() -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    classifications = _load_workflow_classifications()
    for app_file in sorted(APPS_ROOT.glob("*/app.yml")):
        relative_file = app_file.relative_to(REPO_ROOT).as_posix()
        with app_file.open("r", encoding="utf-8") as handle:
            app_metadata = yaml.safe_load(handle) or {}
        if not isinstance(app_metadata, Mapping):
            issues.append(AuditIssue(relative_file, "<app>", "APP_METADATA_INVALID", "app.yml must be a mapping"))
            continue
        app_id = str(app_metadata.get("id") or app_file.parent.name)
        skills = app_metadata.get("skills") or []
        if not isinstance(skills, list):
            issues.append(AuditIssue(relative_file, app_id, "SKILLS_INVALID", "skills must be a list"))
            continue
        for skill in skills:
            if not isinstance(skill, Mapping):
                issues.append(AuditIssue(relative_file, app_id, "SKILL_INVALID", "skill entry must be a mapping"))
                continue
            skill_id = str(skill.get("id") or "<missing>")
            if skill.get("internal") is True:
                continue
            issues.extend(_audit_skill(relative_file, app_id, skill_id, skill, classifications))
    return issues


def _audit_skill(
    file: str,
    app_id: str,
    skill_id: str,
    skill: Mapping[str, Any],
    classifications: Mapping[str, Any],
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    workflow = skill.get("workflow")
    full_skill_id = f"{app_id}.{skill_id}"
    if workflow is None:
        workflow = classifications.get(full_skill_id)
    if not isinstance(workflow, Mapping):
        return [
            AuditIssue(
                file,
                full_skill_id,
                "WORKFLOW_CLASSIFICATION_REQUIRED",
                "public non-internal skills must declare workflow availability or an unavailable reason",
            )
        ]

    available = workflow.get("available")
    if not isinstance(available, bool):
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_METADATA_INVALID", "workflow.available must be boolean"))
        return issues
    if available is False:
        reason = workflow.get("unavailable_reason")
        if reason not in UNAVAILABLE_REASONS:
            issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_METADATA_INVALID", "unavailable workflow skills need a stable unavailable_reason"))
        return issues

    for field_name in ("execution_mode", "effect", "unattended", "approval", "binding_requirements", "test_allowed", "output_schema"):
        if field_name not in workflow:
            issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_METADATA_INVALID", f"workflow.{field_name} is required when available is true"))
    if workflow.get("execution_mode") not in EXECUTION_MODES:
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_EXECUTION_MODE_UNSUPPORTED", "unsupported workflow.execution_mode"))
    if workflow.get("effect") not in EFFECTS:
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_EFFECT_UNSUPPORTED", "unsupported workflow.effect"))
    if not isinstance(workflow.get("unattended"), bool):
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_METADATA_INVALID", "workflow.unattended must be boolean"))
    if workflow.get("approval") not in APPROVALS:
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_METADATA_INVALID", "unsupported workflow.approval"))
    requirements = workflow.get("binding_requirements")
    if not isinstance(requirements, list) or not set(requirements).issubset(BINDING_REQUIREMENTS):
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_METADATA_INVALID", "unsupported workflow.binding_requirements"))
    if not isinstance(workflow.get("output_schema"), Mapping):
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_METADATA_INVALID", "workflow.output_schema must be a mapping"))
    test_allowed = workflow.get("test_allowed")
    if not isinstance(test_allowed, bool):
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_METADATA_INVALID", "workflow.test_allowed must be boolean"))
    elif test_allowed and not _valid_example(workflow.get("test_example_input"), skill.get("tool_schema")):
        issues.append(AuditIssue(file, full_skill_id, "WORKFLOW_TEST_EXAMPLE_REQUIRED", "test_allowed skills need schema-valid test_example_input"))
    return issues


def _load_workflow_classifications() -> dict[str, Any]:
    if not WORKFLOW_CLASSIFICATION_FILE.exists():
        return {}
    with WORKFLOW_CLASSIFICATION_FILE.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, Mapping):
        return {}
    capabilities = payload.get("capabilities") or {}
    return dict(capabilities) if isinstance(capabilities, Mapping) else {}


def _valid_example(value: Any, schema: Any) -> bool:
    if not isinstance(value, Mapping) or not isinstance(schema, Mapping) or schema.get("type") != "object":
        return False
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return False
    required = schema.get("required", [])
    if not isinstance(required, list) or any(key not in value for key in required):
        return False
    return all(key in properties and _matches_schema(item, properties[key]) for key, item in value.items())


def _matches_schema(value: Any, schema: Any) -> bool:
    if not isinstance(schema, Mapping):
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    schema_type = schema.get("type")
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "array":
        items = schema.get("items")
        return isinstance(value, list) and all(_matches_schema(item, items) for item in value)
    if schema_type == "object":
        return _valid_example(value, schema)
    return False


if __name__ == "__main__":
    sys.exit(main())
