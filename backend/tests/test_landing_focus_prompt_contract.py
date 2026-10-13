"""Guard the English instructions used by the two landing focus examples.

Legacy focuses still use app.yml plus i18n at inference time. Their SKILL.md
files are canonical for authoring but do not replace those runtime instructions.
"""

from pathlib import Path

import yaml

from backend.shared.python_utils.focus_mode_skill_loader import parse_skill_md


ROOT = Path(__file__).resolve().parents[2]


def _focus_instructions(app: str, focus_id: str, directory: str) -> tuple[str, str]:
    app_metadata = yaml.safe_load((ROOT / f"backend/apps/{app}/app.yml").read_text())
    focus = next(item for item in app_metadata["focuses"] if item["id"] == focus_id)
    assert focus["systemprompt_translation_key"] == f"focus_modes.{app}_{focus_id}.systemprompt"
    translated = yaml.safe_load(
        (ROOT / f"frontend/packages/ui/src/i18n/sources/focus_modes/{app}_{focus_id}.yml").read_text()
    )
    canonical = parse_skill_md(str(ROOT / f"backend/apps/{app}/focus_modes/{directory}/SKILL.md"))
    return translated["systemprompt"]["en"], canonical["system_prompt"]


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_politics_first_turn_instruction_survives_legacy_translation_path() -> None:
    runtime, canonical = _focus_instructions("politics", "prepare_discussion", "prepare-discussion")
    for instruction in (runtime, canonical):
        assert "first assistant response after this focus activates" in instruction
        assert "respond to the user's original request immediately" in instruction
        assert "ask two or three specific questions" in instruction
        assert "begin the discussion preparation in that same response" in instruction


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_deep_research_delegation_instruction_survives_legacy_translation_path() -> None:
    runtime, canonical = _focus_instructions("web", "research", "research")
    for instruction in (runtime, canonical):
        assert "first tool action MUST be start_sub_chats" in instruction
        assert "instruct each child to use web-search and web-read" in instruction
        assert "return sourced findings" in instruction


# contract-test: supporting surface=rest_api assertions=focus-modes.full-instruction
def test_all_landing_focus_runtime_locales_keep_complete_instructions() -> None:
    locale_codes = {
        "en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr",
        "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv", "he",
    }
    for name, required_tools in (
        ("politics_prepare_discussion", ()),
        ("web_research", ("start_sub_chats", "web-search", "web-read")),
    ):
        data = yaml.safe_load(
            (ROOT / f"frontend/packages/ui/src/i18n/sources/focus_modes/{name}.yml").read_text()
        )["systemprompt"]
        assert set(data) - {"context", "verified_by_human"} == locale_codes
        english = data["en"]
        for lang in locale_codes:
            translated = data[lang]
            assert len(translated.split("\n\n")) == len(english.split("\n\n")), (name, lang)
            assert translated.count("## ") == english.count("## "), (name, lang)
            assert translated.count("\n- ") == english.count("\n- "), (name, lang)
            assert all(tool in translated for tool in required_tools), (name, lang)
