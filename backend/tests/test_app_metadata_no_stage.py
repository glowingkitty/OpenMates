# backend/tests/test_app_metadata_no_stage.py
#
# Deterministic metadata audit for the simplified feature availability model.
# The stage field was removed; off-by-default features must use sparse
# default_enabled: false metadata instead.
#
# Spec: docs/specs/simplified-feature-availability/spec.yml

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition, AppYAML


REPO_ROOT = Path(__file__).resolve().parents[2]
APPS_DIR = REPO_ROOT / "backend" / "apps"


def _walk_metadata(value: object, path: str = "") -> list[str]:
    matches: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key == "stage":
                matches.append(child_path)
            matches.extend(_walk_metadata(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            matches.extend(_walk_metadata(child, f"{path}[{index}]"))
    return matches


def test_app_yml_files_do_not_contain_stage() -> None:
    offenders: list[str] = []
    for app_yml in sorted(APPS_DIR.glob("*/app.yml")):
        data = yaml.safe_load(app_yml.read_text(encoding="utf-8")) or {}
        for match in _walk_metadata(data):
            offenders.append(f"{app_yml.relative_to(REPO_ROOT)}:{match}")

    assert offenders == []


def test_schema_rejects_stage_fields() -> None:
    with pytest.raises(ValidationError):
        AppSkillDefinition(
            id="search",
            name_translation_key="app_translations.web.skills.search.name",
            description_translation_key="app_translations.web.skills.search.description",
            class_path="web.skills.search_skill.SearchSkill",
            stage="production",
        )


def test_schema_rejects_default_enabled_true_noise() -> None:
    with pytest.raises(ValidationError):
        AppYAML(
            name_translation_key="app_translations.web.name",
            description_translation_key="app_translations.web.description",
            default_enabled=True,
        )


def test_schema_accepts_sparse_default_enabled_false() -> None:
    app = AppYAML(
        name_translation_key="app_translations.projects.name",
        description_translation_key="app_translations.projects.description",
        default_enabled=False,
    )

    assert app.default_enabled is False
