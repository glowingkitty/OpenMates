# backend/apps/audio/assistant_speech/acknowledgements.py
#
# Approved product text for prerecorded assistant-response acknowledgements.
# Text is grouped by locale and preprocessing category so generation tooling
# can create the same three deterministic variants for every mate voice.
# Runtime playback uses generated static assets, never these strings as TTS input.

from __future__ import annotations


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
