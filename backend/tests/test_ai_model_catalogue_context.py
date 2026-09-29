"""The model discussion prompt uses bounded, dated provider metadata."""

# contract-test-file: infrastructure

from datetime import date
from pathlib import Path

import yaml

from backend.apps.ai.processing.ai_model_catalogue_context import build_ai_model_catalogue_context


def test_current_models_are_selected_by_family_and_future_entries_are_omitted() -> None:
    providers = {
        "openai": {
            "name": "OpenAI",
            "models": [
                {"name": "Current Text", "for_app_skill": "ai.ask", "release_date": "2026-09-20", "description": "Current language model", "capability_level": "high", "reasoning": True, "input_types": ["text", "image"], "output_types": ["text"]},
                {"name": "Old Text", "for_app_skill": "ai.ask", "release_date": "2023-01-01"},
                {"name": "Future Text", "for_app_skill": "ai.ask", "release_date": "2026-10-01"},
                {"name": "Current Image", "for_app_skill": "images.generate", "release_date": "2026-08-01"},
            ],
        },
        "anthropic": {"name": "Anthropic", "models": [
            {"name": "Other Text", "for_app_skill": "ai.ask", "release_date": "2026-09-22"},
        ]},
    }
    context = build_ai_model_catalogue_context(providers, ["llm"], today=date(2026, 9, 29))

    assert context.index("Other Text") < context.index("Current Text")
    assert "Old Text" not in context
    assert "Future Text" not in context
    assert "Current Image" not in context
    assert "capability high; reasoning; input text, image; output text" in context
    assert "Subscription prices, included usage" in context
    assert build_ai_model_catalogue_context(providers, [], today=date(2026, 9, 29)) == ""


def test_audio_without_release_date_is_labeled_unknown() -> None:
    context = build_ai_model_catalogue_context(
        {"speech": {"name": "Speech", "models": [
            {"name": "Speech One", "for_app_skill": "audio.speak"},
        ]}},
        ["audio"],
        today=date(2026, 9, 29),
    )
    assert "release date unrecorded: Speech — Speech One" in context


def test_real_provider_catalogue_supplies_current_text_image_video_and_audio_context() -> None:
    providers_dir = Path(__file__).parents[1] / "providers"
    provider_configs = {}
    for name in ("openai", "anthropic", "google", "recraft", "mistral", "elevenlabs"):
        provider_configs[name] = yaml.safe_load((providers_dir / f"{name}.yml").read_text())

    context = build_ai_model_catalogue_context(
        provider_configs, ["llm", "image", "video", "audio"], today=date(2026, 9, 29)
    )
    assert "GPT-6 Sol" in context
    assert "Claude Opus 5.5" in context
    assert "GPT Image 2" in context
    assert "Veo 3.1" in context
    assert "ElevenLabs Flash v2.5" in context
    assert len(context) < 8_000
