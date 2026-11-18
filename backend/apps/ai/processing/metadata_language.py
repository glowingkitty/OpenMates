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
    """Prompt rule for models that generate metadata from the conversation.

    Name the fallback language once per prompt: repeating it (e.g. in every tool
    field) made the dev real-model check write English chats in the UI language.
    """
    return (
        "Write in the same language as the user's own words (ignore quoted text, code and data); "
        "never translate them into another language. Only if the user's language cannot be told, "
        f"for example a very short or mixed message, use {language_name(fallback_language)} ({fallback_language})."
    )


# Tool field rule that complements the system prompt without naming the fallback again.
CONVERSATION_LANGUAGE_FIELD_RULE = "Use the same language as the user's own words; never translate them."


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
