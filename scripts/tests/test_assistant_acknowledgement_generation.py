#!/usr/bin/env python3
"""Deterministic assistant acknowledgement generation tests.

These tests cover prompt construction and manifest safety for the static
assistant acknowledgement audio generator. They do not call ElevenLabs,
read Vault secrets, or generate audio bytes.
"""

# contract-test-file: tooling

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = PROJECT_ROOT / "backend" / "scripts" / "generate_assistant_acknowledgements.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("assistant_ack_generator", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["assistant_ack_generator"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("language", ["de-DE", "es-ES", "fr-FR"])
def test_localized_prompts_use_restrained_v3_tags_without_changing_transcripts(tmp_path, language):
    generator = load_generator()

    localized_plan = generator.build_plan(language, tmp_path)
    english_plan = generator.build_plan("en-US", tmp_path)
    localized_by_category = {
        item["request_category"]: item for item in localized_plan if item["voice_profile_id"] == "ace"
    }
    english_item = english_plan[0]

    assert localized_by_category["general"]["generation_tags"] == ("[warmly]",)
    assert localized_by_category["lookup"]["generation_tags"] == ("[curious]",)
    assert localized_by_category["reasoning"]["generation_tags"] == ("[thoughtful]", "[slow]")
    assert localized_by_category["action"]["generation_tags"] == ("[focused]",)
    assert localized_by_category["reasoning"]["generation_prompt"].startswith("[thoughtful] [slow] ")
    assert localized_by_category["reasoning"]["generation_prompt"].endswith(
        localized_by_category["reasoning"]["text"]
    )
    assert english_item["generation_tags"] == ()
    assert english_item["generation_prompt"] == english_item["text"]


def test_public_manifest_entry_omits_provider_prompt_metadata(tmp_path):
    generator = load_generator()
    item = generator.build_plan("de-DE", tmp_path)[0]
    audio_bytes = b"mock-mp3-bytes"

    entry = generator._public_entry(item, audio_bytes=audio_bytes, duration_seconds=1.25)

    assert entry["text"] == item["text"]
    assert entry["sha256"] == hashlib.sha256(audio_bytes).hexdigest()
    assert entry["duration_seconds"] == 1.25
    assert "generation_prompt" not in entry
    assert "generation_tags" not in entry
    assert not entry["text"].startswith("[")


def test_reconcile_existing_assets_preserves_unrelated_entries_and_checksums(tmp_path):
    generator = load_generator()
    item = generator.build_plan("de-DE", tmp_path)[0]
    output_path = item["output_path"]
    output_path.parent.mkdir(parents=True)
    output_path.write_bytes(b"de-audio")
    unrelated_entry = {
        "clip_id": "ace-en-US-general-1",
        "language": "en-US",
        "text": "Sure, let's take a look.",
        "relative_path": "ace/en-US/general-1.mp3",
        "sha256": "kept",
        "duration_seconds": 1.0,
    }
    entries = {unrelated_entry["clip_id"]: unrelated_entry}

    assert generator._reconcile_existing_assets([item], entries) is True
    assert entries[unrelated_entry["clip_id"]] == unrelated_entry
    assert entries[item["clip_id"]]["sha256"] == hashlib.sha256(b"de-audio").hexdigest()
    assert generator._reconcile_existing_assets([item], entries) is False

    entries[item["clip_id"]] = {**entries[item["clip_id"]], "sha256": "mismatch"}
    with pytest.raises(RuntimeError, match=item["clip_id"]):
        generator._reconcile_existing_assets([item], entries)

    output_path.unlink()
    assert generator._reconcile_existing_assets([item], entries) is True
    assert item["clip_id"] not in entries
    assert entries[unrelated_entry["clip_id"]] == unrelated_entry


def test_write_manifest_keeps_clean_text_and_existing_locale_entries(tmp_path):
    generator = load_generator()
    german_item = generator.build_plan("de-DE", tmp_path)[0]
    german_entry = generator._public_entry(german_item, audio_bytes=b"de-audio", duration_seconds=1.0)
    english_entry = {
        "clip_id": "ace-en-US-general-1",
        "voice_profile_id": "ace",
        "voice_profile_version": 1,
        "language": "en-US",
        "request_category": "general",
        "variant": 1,
        "text": "Sure, let's take a look.",
        "relative_path": "ace/en-US/general-1.mp3",
        "sha256": "kept",
        "duration_seconds": 1.0,
    }

    generator._write_manifest(tmp_path, {english_entry["clip_id"]: english_entry, german_entry["clip_id"]: german_entry})
    payload = json.loads((tmp_path / generator.MANIFEST_FILENAME).read_text(encoding="utf-8"))

    assert payload["provider_model_id"] == generator.ASSISTANT_RESPONSE_SPEECH_MODEL
    assert {entry["language"] for entry in payload["clips"]} == {"en-US", "de-DE"}
    assert all("generation_prompt" not in entry and "generation_tags" not in entry for entry in payload["clips"])
    assert next(entry for entry in payload["clips"] if entry["language"] == "de-DE")["text"] == german_item["text"]


@pytest.mark.parametrize("language", ["de-DE", "es-ES", "fr-FR"])
def test_localized_plan_has_expected_voice_category_variant_coverage(tmp_path, language):
    generator = load_generator()

    plan = generator.build_plan(language, tmp_path)
    voices = {item["voice_profile_id"] for item in plan}
    categories_by_voice = {
        voice: {item["request_category"] for item in plan if item["voice_profile_id"] == voice}
        for voice in voices
    }
    variants_by_voice_category = {
        (voice, category): {
            item["variant"]
            for item in plan
            if item["voice_profile_id"] == voice and item["request_category"] == category
        }
        for voice in voices
        for category in generator.ACKNOWLEDGEMENT_TEXTS[language]
    }

    assert len(voices) == 17
    assert len(plan) == 204
    assert {item["language"] for item in plan} == {language}
    assert set(frozenset(categories) for categories in categories_by_voice.values()) == {
        frozenset(generator.ACKNOWLEDGEMENT_TEXTS[language])
    }
    assert set(frozenset(variants) for variants in variants_by_voice_category.values()) == {
        frozenset({1, 2, 3})
    }
