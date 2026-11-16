"""Language of generated chat metadata (title, summary, tags).

Specification: language-preferences.chat-metadata-language. Metadata follows
the language the user writes in. Only when that is unclear (a very short or
mixed message) does it fall back to the displayed interface language, then the
account language. The caller resolves that fallback once
(`user_system_language`: displayed UI language, else account language); the
model detects the writing language because it reads the conversation anyway.
"""
from __future__ import annotations

LANGUAGE_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
    "ru": "Russian", "ja": "Japanese", "zh": "Chinese", "ko": "Korean",
    "ar": "Arabic", "tr": "Turkish", "sv": "Swedish", "no": "Norwegian",
    "da": "Danish", "fi": "Finnish", "cs": "Czech", "ro": "Romanian",
    "hu": "Hungarian", "el": "Greek", "he": "Hebrew", "hi": "Hindi",
    "uk": "Ukrainian", "vi": "Vietnamese", "id": "Indonesian", "th": "Thai",
}


def language_name(code: str) -> str:
    """English name of an ISO 639-1 code (region suffix ignored), else the code."""
    return LANGUAGE_NAMES.get(code.split("-", 1)[0].lower(), code)


def conversation_language_instruction(fallback_language: str) -> str:
    """Prompt rule for models that generate metadata from the conversation."""
    return (
        "Write in the language the user writes in (their own words, not quoted text, code or data). "
        "Only if that is unclear, for example a very short or mixed message, use "
        f"{language_name(fallback_language)} ({fallback_language}), the user's interface language."
    )


def resolve_metadata_language(conversation_language: str | None, fallback_language: str,
                              supported: frozenset[str] | set[str]) -> str:
    """Detected conversation language when valid, else the interface/account fallback.

    The fallback may carry a region ("pt-BR"); its base code is used when supported,
    and English when neither is.
    """
    if isinstance(conversation_language, str) and conversation_language in supported:
        return conversation_language
    base = fallback_language.split("-", 1)[0].lower() if isinstance(fallback_language, str) else ""
    return base if base in supported else "en"
