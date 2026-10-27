"""Authored focus content resolves without invented keys or executable placeholders."""
from pathlib import Path
from types import SimpleNamespace
import json

import yaml

from backend.shared.python_utils import focus_mode_skill_loader as loader

ROOT = Path(__file__).resolve().parents[2]


def source(tmp_path, *, body="", translations=None):
    file = tmp_path / "SKILL.md"
    file.write_text(f"---\nid: sample\napp: demo\n---\n# Sample\n{body}")
    catalogue = tmp_path / "sources/focus_modes/demo_sample.yml"
    catalogue.parent.mkdir(parents=True)
    catalogue.write_text(yaml.safe_dump(translations or {"description": {"en": "Sample"}}))
    return file


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_bodyless_mode_does_not_emit_missing_prompt_or_process_keys(tmp_path, monkeypatch):
    file = source(tmp_path)
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(tmp_path / "sources"))
    focus = loader.load_focus_mode_from_skill_md(str(file), "demo")
    assert not focus.get("systemprompt_translation_key")
    assert not focus.get("process_translation_key")
    assert not focus.get("system_prompt")


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_authored_body_is_retained_without_inventing_a_translation_target(tmp_path, monkeypatch):
    file = source(tmp_path, body="## System prompt\nUse the user's supplied facts.\n\n## Process\n- Review the facts.\n")
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(tmp_path / "sources"))
    focus = loader.load_focus_mode_from_skill_md(str(file), "demo")
    assert focus["system_prompt"] == "Use the user's supplied facts."
    assert focus["process"] == ["Review the facts."]
    assert not focus.get("systemprompt_translation_key")
    assert not focus.get("process_translation_key")


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_translation_backed_mode_keeps_locale_selection_in_existing_runtime_resolver(tmp_path, monkeypatch):
    file = source(tmp_path, translations={"systemprompt": {"en": "Use the supplied facts.", "de": "Verwende die Angaben."}})
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(tmp_path / "sources"))
    focus = loader.load_focus_mode_from_skill_md(str(file), "demo")
    assert focus["systemprompt_translation_key"] == "focus_modes.demo_sample.systemprompt"
    assert "system_prompt" not in focus  # Do not force English ahead of runtime locale resolution.


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deployed_compiled_translation_catalogue_supports_source_free_images(tmp_path, monkeypatch):
    file = source(tmp_path)
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(tmp_path / "not-mounted"))
    locales = tmp_path / "locales"
    locales.mkdir()
    (locales / "en.json").write_text(json.dumps({"focus_modes": {"demo_sample": {"systemprompt": {"text": "Authored fallback."}}}}))
    monkeypatch.setenv("TRANSLATIONS_DIR", str(locales))
    focus = loader.load_focus_mode_from_skill_md(str(file), "demo")
    assert focus["systemprompt_translation_key"] == "focus_modes.demo_sample.systemprompt"
    assert "system_prompt" not in focus


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_social_prompt_migration_preserves_all_twenty_one_existing_translations():
    base = ROOT / "frontend/packages/ui/src/i18n"
    languages = [row["code"] for row in json.loads((base / "languages.json").read_text())["languages"]]
    new = yaml.safe_load((base / "sources/focus_modes/social_media_content_calendar_strategist.yml").read_text())["systemprompt"]
    old = yaml.safe_load((base / "sources/app_focus_modes/social_media.yml").read_text())["content_calendar_strategist.systemprompt"]
    assert len(languages) == 21
    for language in languages:
        assert new[language].strip() == old[language].strip()
        assert new[language].strip() and "[T:" not in new[language]


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_registry_discovers_real_nonphased_canonical_instructions_without_changing_legacy_permissions(tmp_path, monkeypatch):
    from backend.core.api.app.services import skill_registry as registry
    from backend.shared.python_schemas.app_metadata_schemas import AppYAML
    app_dir = tmp_path / "demo"
    focus_dir = app_dir / "focus_modes/sample"
    focus_dir.mkdir(parents=True)
    (focus_dir / "SKILL.md").write_text("---\nid: sample\napp: demo\n---\n# Sample\n## System prompt\nUse the supplied facts.\n")
    (app_dir / "app.yml").write_text(yaml.safe_dump({"name_translation_key": "demo", "description_translation_key": "demo.description", "skills": [], "focuses": [{"id": "sample", "name_translation_key": "demo.sample", "description_translation_key": "demo.sample.description", "default_enabled": False, "allowed_apps": ["web"]}]}))
    monkeypatch.setenv("TRANSLATIONS_SOURCES_DIR", str(tmp_path / "sources"))
    monkeypatch.setenv("TRANSLATIONS_DIR", str(tmp_path / "locales"))
    monkeypatch.setattr(registry, "APPS_DIR", str(tmp_path))
    monkeypatch.setattr(registry, "scan_filesystem_for_apps", lambda: ["demo"])

    class App:
        def __init__(self, *, preloaded_config_dict, **kwargs):
            self.app_config = AppYAML.model_validate(preloaded_config_dict)
            self.is_valid = True
            self.skill_classes = {}

    monkeypatch.setattr(registry, "BaseApp", App)
    _, metadata = registry.build_skill_registry(feature_availability=SimpleNamespace(is_enabled=lambda _: True))
    focus = metadata["demo"].focuses[0]
    assert focus.system_prompt == "Use the supplied facts."
    assert focus.allowed_apps == ["web"]
    assert focus.default_enabled is False
    assert focus.phases is None


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_all_canonical_focus_instruction_keys_point_to_authored_sections():
    for path in (ROOT / "backend/apps").glob("*/focus_modes/*/SKILL.md"):
        app = path.parents[2].name
        focus = loader.load_focus_mode_from_skill_md(str(path), app)
        authored = loader.authored_focus_translations(app, focus["id"])
        for key, section in [("systemprompt_translation_key", "systemprompt"), ("process_translation_key", "process")]:
            if focus.get(key):
                assert authored.get(section), f"{app}.{focus['id']} has no authored {section}"
                assert "[T:" not in authored[section]


# contract-test: supporting surface=gui.web assertions=settings-ui.localization.visible-content-resolves
def test_retired_health_focus_names_and_descriptions_remain_available_for_saved_history():
    base = ROOT / "frontend/packages/ui/src/i18n"
    languages = [row["code"] for row in json.loads((base / "languages.json").read_text())["languages"]]
    labels = yaml.safe_load((base / "sources/focus_modes/main.yml").read_text())
    legacy = yaml.safe_load((base / "sources/app_focus_modes/health.yml").read_text())
    for focus_id in ["prepare_doctor_report", "health_insights", "prepare_doctor_appointment"]:
        for language in languages:
            assert labels[f"health_{focus_id}"][language]
            assert labels[f"health_{focus_id}.description"][language]
            assert legacy[focus_id][language]
            assert legacy[f"{focus_id}.description"][language]
        assert f"{focus_id}.systemprompt" not in legacy
        assert f"{focus_id}.process" not in legacy
