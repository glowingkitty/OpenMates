# contract-test-file: infrastructure
"""Chat metadata language: conversation language first, then UI, then account language."""
import pytest

from backend.apps.ai.processing.metadata_language import (
    conversation_language_instruction, resolve_metadata_language,
)

SUPPORTED = {"en", "de", "fr", "pt"}


# contract-test: supporting surface=rest_api assertions=language-preferences.chat-metadata-language
@pytest.mark.parametrize(("detected", "fallback", "expected"), [
    ("de", "en", "de"),        # German chat in an English interface stays German
    (None, "de", "de"),        # unclear detection uses the interface/account fallback
    ("xx", "fr", "fr"),        # invalid detection uses the fallback
    (None, "pt-BR", "pt"),     # regional fallback uses its supported base language
    (None, "eo", "en"),        # unsupported fallback ends at English
])
def test_resolve_metadata_language(detected, fallback, expected):
    assert resolve_metadata_language(detected, fallback, SUPPORTED) == expected


# contract-test: supporting surface=rest_api assertions=language-preferences.chat-metadata-language
def test_instruction_prefers_the_writing_language_and_names_the_fallback():
    text = conversation_language_instruction("en")
    assert text.startswith("Write in the language the user writes in")
    assert "very short or mixed message, use English (en)" in text
