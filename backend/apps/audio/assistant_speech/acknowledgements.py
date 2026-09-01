# backend/apps/audio/assistant_speech/acknowledgements.py
#
# Approved product text for prerecorded assistant-response acknowledgements.
# Text is grouped by locale and preprocessing category so generation tooling
# can create the same three deterministic variants for every mate voice.
# Runtime playback uses generated static assets, never these strings as TTS input.

from __future__ import annotations


ACKNOWLEDGEMENT_ASSET_ROOT = "/audio/assistant-acknowledgements"
ACKNOWLEDGEMENT_TEXTS: dict[str, dict[str, tuple[str, ...]]] = {
    "en-US": {
        "general": (
            "Sure, let's take a look.",
            "Alright, let's work on it.",
            "Okay, I'll help you with that.",
        ),
        "lookup": (
            "Sure, I'll look that up.",
            "Okay, let me check.",
            "Got it, I'll find the details.",
        ),
        "reasoning": (
            "Okay, let me think for a moment.",
            "Sure, I'll work through it step by step.",
            "Got it, I'll take a closer look.",
        ),
        "action": (
            "Okay, I'm on it.",
            "Sure, I'll take care of that.",
            "Got it, I'll get started.",
        ),
    },
    "de-DE": {
        "general": (
            "Klar, schauen wir es uns an.",
            "Alles klar, gehen wir es an.",
            "Okay, ich helfe dir dabei.",
        ),
        "lookup": (
            "Klar, ich schaue das nach.",
            "Okay, ich sehe kurz nach.",
            "Alles klar, ich suche die Details heraus.",
        ),
        "reasoning": (
            "Okay, lass mich kurz nachdenken.",
            "Klar, ich gehe das Schritt für Schritt durch.",
            "Alles klar, ich sehe mir das genauer an.",
        ),
        "action": (
            "Okay, mache ich.",
            "Klar, ich kümmere mich darum.",
            "Alles klar, ich lege los.",
        ),
    },
}


def build_acknowledgement_clips(
    *,
    voice_profile_id: str,
    voice_profile_version: int,
    language: str,
) -> list[dict[str, object]]:
    """Build public static clip metadata for one approved mate and locale."""
    locale = _resolve_locale(language)
    if locale is None:
        return []

    clips: list[dict[str, object]] = []
    for category, variants in ACKNOWLEDGEMENT_TEXTS[locale].items():
        for variant, _text in enumerate(variants, start=1):
            clip_id = f"{voice_profile_id}-{locale}-{category}-{variant}"
            clips.append(
                {
                    "clip_id": clip_id,
                    "voice_profile_id": voice_profile_id,
                    "voice_profile_version": voice_profile_version,
                    "language": locale,
                    "request_category": category,
                    "variant": variant,
                    "asset_url": (
                        f"{ACKNOWLEDGEMENT_ASSET_ROOT}/{voice_profile_id}/{locale}/{category}-{variant}.mp3"
                    ),
                }
            )
    return clips


def _resolve_locale(language: str) -> str | None:
    if language in ACKNOWLEDGEMENT_TEXTS:
        return language
    base_language = language.split("-", maxsplit=1)[0].lower()
    return next(
        (
            locale
            for locale in ACKNOWLEDGEMENT_TEXTS
            if locale.split("-", maxsplit=1)[0].lower() == base_language
        ),
        None,
    )
