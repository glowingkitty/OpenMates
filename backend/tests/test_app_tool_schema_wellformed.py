# contract-test-file: infrastructure
"""Every app.yml skill tool_schema is a well-formed JSON schema that provider tool declarations accept.

An unquoted comma in a YAML flow mapping (``{description: A, b.}``) silently turns the
text after the comma into a null-valued key. Gemini's FunctionDeclaration rejects such
extra keys, so every request that offered the skill failed (provider_exhausted).
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_DIR = REPO_ROOT / "backend" / "apps"
NULLABLE_KEYWORDS = {"default", "const", "example"}


def _defects(value: object, path: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if child is None and key not in NULLABLE_KEYWORDS:
                found.append(f"{child_path}: null value (unquoted comma in a flow mapping?)")
            if key == "properties":
                if not isinstance(child, dict):
                    found.append(f"{child_path}: properties must be a mapping")
                else:
                    found.extend(f"{child_path}.{name}: property schema must be a mapping"
                                 for name, schema in child.items() if not isinstance(schema, dict))
            found.extend(_defects(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_defects(child, f"{path}[{index}]"))
    return found


def test_skill_tool_schemas_have_no_stray_keys() -> None:
    offenders: list[str] = []
    for app_yml in sorted(APPS_DIR.glob("*/app.yml")):
        data = yaml.safe_load(app_yml.read_text(encoding="utf-8")) or {}
        for skill in data.get("skills") or []:
            if isinstance(skill, dict) and "tool_schema" in skill:
                where = f"{app_yml.relative_to(REPO_ROOT)}:{skill.get('id')}.tool_schema"
                offenders.extend(f"{where}{defect}" for defect in _defects(skill["tool_schema"], ""))
    assert offenders == []


def test_detects_comma_split_flow_mapping() -> None:
    schema = yaml.safe_load("properties:\n  relation: {type: string, description: How they relate, in a few words.}\n")
    assert _defects(schema, "") != []
