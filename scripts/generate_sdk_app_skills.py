#!/usr/bin/env python3
"""Generate npm and Python SDK app-skill namespaces from app metadata.

Purpose: keep native SDK skill methods in parity with backend app.yml files.
Architecture: docs/specs/sdk-cli-parity-v1/spec.yml.
Security: generator emits typed wrappers only; runtime API-key auth remains server-side.
Tests: frontend/packages/openmates-cli/tests/sdkGenerator.test.ts and
packages/openmates-python/tests/test_sdk_generator.py.
"""

from __future__ import annotations

import json
import pprint
import re
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
APPS_DIR = REPO_ROOT / "backend" / "apps"
NPM_GENERATED = REPO_ROOT / "frontend" / "packages" / "openmates-cli" / "src" / "generated" / "appSkills.ts"
PY_GENERATED = REPO_ROOT / "packages" / "openmates-python" / "openmates" / "generated" / "app_skills.py"


def camel_case(value: str) -> str:
    parts = re.split(r"[-_\s]+", value)
    if not parts:
        return value
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def snake_case(value: str) -> str:
    value = re.sub(r"[^0-9A-Za-z]+", "_", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.strip("_").lower()


def ts_identifier(value: str) -> str:
    candidate = camel_case(value)
    if not re.match(r"^[A-Za-z_$]", candidate):
        candidate = f"app{candidate}"
    return re.sub(r"[^0-9A-Za-z_$]", "", candidate)


def py_identifier(value: str) -> str:
    candidate = snake_case(value)
    if not candidate or not re.match(r"^[A-Za-z_]", candidate):
        candidate = f"app_{candidate}"
    return candidate


def first_sentence(text: str | None) -> str:
    if not text:
        return "Run this OpenMates app skill."
    flattened = " ".join(str(text).split())
    return flattened[:500]


def load_skills() -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    for app_file in sorted(APPS_DIR.glob("*/app.yml")):
        app_id = app_file.parent.name
        data = yaml.safe_load(app_file.read_text(encoding="utf-8")) or {}
        app_skills = data.get("skills") or []
        if not isinstance(app_skills, list):
            continue
        for skill in app_skills:
            if not isinstance(skill, dict):
                continue
            skill_id = skill.get("id")
            if not isinstance(skill_id, str) or not skill_id:
                continue
            if skill.get("internal") is True:
                continue
            api_config = skill.get("api_config") or {}
            if isinstance(api_config, dict) and api_config.get("expose_post") is False:
                continue
            skills.append(
                {
                    "app_id": app_id,
                    "skill_id": skill_id,
                    "app_namespace_ts": ts_identifier(app_id),
                    "skill_method_ts": ts_identifier(skill_id),
                    "app_namespace_py": py_identifier(app_id),
                    "skill_method_py": py_identifier(skill_id),
                    "description_key": skill.get("description_translation_key") or "",
                    "description": first_sentence(skill.get("preprocessor_hint")),
                    "schema": skill.get("tool_schema") or {"type": "object", "properties": {}},
                }
            )
    return skills


def generate_ts(skills: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        grouped.setdefault(skill["app_namespace_ts"], []).append(skill)

    lines = [
        "/*",
        " * Generated OpenMates SDK app-skill namespaces.",
        " * Source: backend app metadata files",
        " * Regenerate with: python3 scripts/generate_sdk_app_skills.py",
        " */",
        "",
        "export type AppSkillRunner = <T = unknown>(appId: string, skillId: string, input: unknown) => Promise<T>;",
        "export type SkillInput = Record<string, unknown>;",
        "",
        "export const APP_SKILL_METADATA = " + json.dumps(skills, indent=2) + " as const;",
        "",
    ]
    for namespace, namespace_skills in sorted(grouped.items()):
        class_name = f"{namespace[:1].upper()}{namespace[1:]}AppSkills"
        lines.append(f"export class {class_name} {{")
        lines.append("  private readonly runSkill: AppSkillRunner;")
        lines.append("  constructor(runSkill: AppSkillRunner) {")
        lines.append("    this.runSkill = runSkill;")
        lines.append("  }")
        for skill in sorted(namespace_skills, key=lambda item: item["skill_method_ts"]):
            method = skill["skill_method_ts"]
            description = skill["description"].replace("*/", "* /")
            key = skill["description_key"]
            lines.append("  /**")
            lines.append(f"   * {description}")
            if key:
                lines.append(f"   * Description key: {key}")
            lines.append(f"   * Skill: {skill['app_id']}/{skill['skill_id']}")
            lines.append("   */")
            lines.append(f"  async {method}<T = unknown>(input: SkillInput): Promise<T> {{")
            lines.append(f"    return this.runSkill<T>({json.dumps(skill['app_id'])}, {json.dumps(skill['skill_id'])}, input);")
            lines.append("  }")
        lines.append("}")
        lines.append("")

    lines.append("export class GeneratedAppSkills {")
    lines.append("  constructor(runSkill: AppSkillRunner) {")
    for namespace in sorted(grouped):
        class_name = f"{namespace[:1].upper()}{namespace[1:]}AppSkills"
        lines.append(f"    this.{namespace} = new {class_name}(runSkill);")
    lines.append("  }")
    for namespace in sorted(grouped):
        class_name = f"{namespace[:1].upper()}{namespace[1:]}AppSkills"
        lines.append(f"  readonly {namespace}: {class_name};")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def generate_py(skills: list[dict[str, Any]]) -> str:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for skill in skills:
        grouped.setdefault(skill["app_namespace_py"], []).append(skill)

    lines = [
        '"""Generated OpenMates SDK app-skill namespaces.',
        "",
        "Source: backend app metadata files",
        "Regenerate with: python3 scripts/generate_sdk_app_skills.py",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Any, Callable",
        "",
        f"APP_SKILL_METADATA = {pprint.pformat(skills, width=100)}",
        "",
        "SkillRunner = Callable[[str, str, dict[str, Any]], dict[str, Any]]",
        "",
    ]
    for namespace, namespace_skills in sorted(grouped.items()):
        class_name = "".join(part.capitalize() for part in namespace.split("_")) + "AppSkills"
        lines.append(f"class {class_name}:")
        lines.append("    def __init__(self, run_skill: SkillRunner):")
        lines.append("        self._run_skill = run_skill")
        for skill in sorted(namespace_skills, key=lambda item: item["skill_method_py"]):
            method = skill["skill_method_py"]
            description = skill["description"].replace('"""', '\"\"\"')
            key = skill["description_key"]
            lines.append("")
            lines.append(f"    def {method}(self, input_data: dict[str, Any]) -> dict[str, Any]:")
            lines.append(f"        \"\"\"{description}")
            if key:
                lines.append("")
                lines.append(f"        Description key: {key}")
            lines.append(f"        Skill: {skill['app_id']}/{skill['skill_id']}")
            lines.append("        \"\"\"")
            lines.append(f"        return self._run_skill({json.dumps(skill['app_id'])}, {json.dumps(skill['skill_id'])}, input_data)")
        lines.append("")

    lines.append("class GeneratedAppSkills:")
    lines.append("    def __init__(self, run_skill: SkillRunner):")
    for namespace in sorted(grouped):
        class_name = "".join(part.capitalize() for part in namespace.split("_")) + "AppSkills"
        lines.append(f"        self.{namespace} = {class_name}(run_skill)")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    skills = load_skills()
    if not skills:
        raise SystemExit("No SDK app skills found")
    NPM_GENERATED.parent.mkdir(parents=True, exist_ok=True)
    PY_GENERATED.parent.mkdir(parents=True, exist_ok=True)
    NPM_GENERATED.write_text(generate_ts(skills), encoding="utf-8")
    PY_GENERATED.write_text(generate_py(skills), encoding="utf-8")
    print(f"Generated {len(skills)} app skill methods")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
