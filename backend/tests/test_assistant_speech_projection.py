# backend/tests/test_assistant_speech_projection.py
#
# Contract coverage for deterministic assistant-response speech projection.
# Speech preserves prose and producer summaries without sending raw response
# markup through a cleanup model or persisting segment plaintext.
#

from pathlib import Path

import pytest

from backend.apps.ai.assistant_speech.projection import (
    project_streaming_speech_segment,
    project_speech_segments,
    select_prerecorded_acknowledgement,
)
from backend.apps.ai.utils.mate_utils import load_mates_config
from backend.apps.audio.assistant_speech.acknowledgements import ACKNOWLEDGEMENT_TEXTS
from backend.apps.audio.assistant_speech.voice_profiles import resolve_assistant_voice_profile
from backend.scripts.generate_assistant_acknowledgements import build_plan, _reconcile_existing_assets


EXPECTED_MATE_PROFILE_KEYS = {
    "ace",
    "burton",
    "colin",
    "denise",
    "elton",
    "finn",
    "george",
    "hiro",
    "leon",
    "lisa",
    "makani",
    "mark",
    "melvin",
    "monika",
    "scarlett",
    "sophia",
    "suki",
}


# contract-test: direct surface=rest_api assertions=assistant-speech.voice.fixed-versioned-mate-profile
def test_loads_a_typed_versioned_voice_profile_for_every_builtin_mate() -> None:
    mates_dir = Path(__file__).resolve().parents[1] / "apps" / "ai" / "mates"

    mates = load_mates_config(str(mates_dir))

    assert mates
    assert all(mate.voice_profile is not None for mate in mates)
    assert {mate.voice_profile.key for mate in mates if mate.voice_profile} == EXPECTED_MATE_PROFILE_KEYS
    assert {mate.voice_profile.version for mate in mates if mate.voice_profile} == {1}


# contract-test: direct surface=rest_api assertions=assistant-speech.voice.fixed-versioned-mate-profile
def test_resolves_a_provider_neutral_profile_without_exposing_voice_ids() -> None:
    resolved = resolve_assistant_voice_profile("hiro", version=1)

    assert resolved.provider == "elevenlabs"
    assert resolved.model == "eleven_v3"
    assert resolved.output_format == "mp3_44100_128"
    assert resolved.voice_settings == {"speed": 1.0}
    assert not hasattr(resolved, "voice_id")


# contract-test: direct surface=rest_api assertions=assistant-speech.voice.fixed-versioned-mate-profile
def test_resolves_a_unique_provider_voice_for_every_builtin_mate() -> None:
    provider_voice_ids = {
        resolve_assistant_voice_profile(key, version=1).elevenlabs_request()["voice_id"]
        for key in EXPECTED_MATE_PROFILE_KEYS
    }

    assert len(provider_voice_ids) == len(EXPECTED_MATE_PROFILE_KEYS)


# contract-test: direct surface=rest_api assertions=assistant-speech.acknowledgement.deterministic-free,assistant-speech.voice.fixed-versioned-mate-profile
def test_selects_a_deterministic_prerecorded_acknowledgement_without_charge() -> None:
    clips = [
        {
            "clip_id": f"mate-a-en-general-v{variant}",
            "voice_profile_id": "mate-a-v1",
            "voice_profile_version": 1,
            "language": "en",
            "request_category": "general",
        }
        for variant in range(1, 4)
    ]

    selections = {
        select_prerecorded_acknowledgement(
            clips=clips,
            voice_profile_id="mate-a-v1",
            voice_profile_version=1,
            language="en",
            request_category="general",
            selection_seed=f"turn-{index}",
        )["clip_id"]
        for index in range(100)
    }
    repeated = select_prerecorded_acknowledgement(
        clips=clips,
        voice_profile_id="mate-a-v1",
        voice_profile_version=1,
        language="en",
        request_category="general",
        selection_seed="stable-turn",
    )

    assert selections == {"mate-a-en-general-v1", "mate-a-en-general-v2", "mate-a-en-general-v3"}
    assert repeated == select_prerecorded_acknowledgement(
        clips=clips,
        voice_profile_id="mate-a-v1",
        voice_profile_version=1,
        language="en",
        request_category="general",
        selection_seed="stable-turn",
    )
    assert repeated == {
        "clip_id": repeated["clip_id"],
        "runtime_generation": False,
        "runtime_credits_charged": 0,
    }


# contract-test: direct surface=rest_api assertions=assistant-speech.acknowledgement.deterministic-free
def test_approved_acknowledgement_catalog_has_three_confirming_variants_per_category() -> None:
    assert set(ACKNOWLEDGEMENT_TEXTS) == {"en-US", "de-DE"}
    for language_catalog in ACKNOWLEDGEMENT_TEXTS.values():
        assert set(language_catalog) == {"general", "lookup", "reasoning", "action"}
        assert all(len(variants) == 3 for variants in language_catalog.values())

    assert "Understood." not in ACKNOWLEDGEMENT_TEXTS["en-US"]["general"]
    assert ACKNOWLEDGEMENT_TEXTS["de-DE"]["reasoning"][0] == "Okay, lass mich kurz nachdenken."


# contract-test: direct surface=rest_api assertions=assistant-speech.acknowledgement.deterministic-free,assistant-speech.voice.fixed-versioned-mate-profile
def test_acknowledgement_generation_plan_is_complete_and_unique(tmp_path: Path) -> None:
    plan = build_plan("en-US", tmp_path)

    assert len(plan) == 17 * 4 * 3
    assert len({item["clip_id"] for item in plan}) == len(plan)
    assert {item["voice_profile_id"] for item in plan} == EXPECTED_MATE_PROFILE_KEYS


# contract-test: direct surface=rest_api assertions=assistant-speech.acknowledgement.deterministic-free
def test_acknowledgement_generation_repairs_orphans_and_rejects_corruption(tmp_path: Path) -> None:
    item = build_plan("en-US", tmp_path)[0]
    item["output_path"].parent.mkdir(parents=True)
    item["output_path"].write_bytes(b"valid audio")
    entries: dict[str, dict[str, object]] = {}

    assert _reconcile_existing_assets([item], entries) is True
    assert entries[item["clip_id"]]["sha256"]
    assert _reconcile_existing_assets([item], entries) is False

    item["output_path"].write_bytes(b"corrupt audio")
    with pytest.raises(RuntimeError, match="checksum validation"):
        _reconcile_existing_assets([item], entries)


# contract-test: direct surface=rest_api assertions=assistant-speech.projection.deterministic-semantic,assistant-speech.projection.no-cleanup-inference
def test_projects_only_safe_semantic_speech_without_raw_markup_or_urls() -> None:
    segments = project_speech_segments(
        blocks=[
            {"type": "prose", "text": "Here is the result."},
            {"type": "link", "label": "OpenMates guide", "url": "https://example.invalid/guide"},
            {"type": "code", "language": "python", "summary": "A Python example is available."},
            {"type": "map", "summary": "The map shows two nearby cafes."},
            {"type": "table", "summary": "The table compares three options."},
            {"type": "embed", "protocol": "openmates://private", "raw_payload": {"secret": "omit"}},
        ],
        language="en",
    )

    assert segments == [
        {"sequence": 0, "kind": "prose_paragraph", "speakable_text": "Here is the result."},
        {"sequence": 1, "kind": "prose_paragraph", "speakable_text": "OpenMates guide"},
        {"sequence": 2, "kind": "code_summary", "speakable_text": "A Python example is available."},
        {"sequence": 3, "kind": "embed_summary", "speakable_text": "The map shows two nearby cafes."},
        {"sequence": 4, "kind": "table_summary", "speakable_text": "The table compares three options."},
    ]
    assert "https://" not in repr(segments)
    assert "openmates://" not in repr(segments)
    assert "secret" not in repr(segments)


# contract-test: direct surface=rest_api assertions=assistant-speech.projection.deterministic-semantic,assistant-speech.projection.no-cleanup-inference
def test_projects_streamed_markdown_without_sending_protocol_code_json_or_table_syntax_to_tts() -> None:
    assert project_streaming_speech_segment(
        "Read [the guide](https://example.invalid/guide), then use `openmates://private`."
    ) == ("prose_paragraph", "Read the guide, then use.")
    assert project_streaming_speech_segment("```json\n{\"secret\": \"omit\"}\n```") == (
        "code_summary",
        "A code example is available.",
    )
    assert project_streaming_speech_segment("| Name | Value |\n| --- | --- |\n| A | 1 |") == (
        "table_summary",
        "A table is available.",
    )
    assert project_streaming_speech_segment('{"secret": "omit"}') == (
        "embed_summary",
        "Structured data is available.",
    )
