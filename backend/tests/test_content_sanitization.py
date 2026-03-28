# backend/tests/test_content_sanitization.py
#
# Unit tests for the content sanitization module — the prompt injection defense layer.
# Focuses on the pure _split_text_into_chunks() function which handles text chunking
# for the LLM-based sanitization pipeline, and _load_llm_key_from_app_yml().
#
# Architecture: docs/architecture/prompt_injection_protection.md
# Run: python -m pytest backend/tests/test_content_sanitization.py -v

import os
import pytest

try:
    from backend.apps.ai.processing.content_sanitization import (
        _split_text_into_chunks,
        _load_llm_key_from_app_yml,
        PROMPT_INJECTION_PLACEHOLDER,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ===========================================================================
# _split_text_into_chunks
# ===========================================================================

class TestSplitTextIntoChunks:
    def test_short_text_single_chunk(self):
        """Text shorter than max_chars should produce a single chunk."""
        text = "Hello, world!"
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=100)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_empty_string(self):
        """Empty string should produce an empty list."""
        chunks = _split_text_into_chunks("", max_chars_per_chunk=100)
        assert chunks == []

    def test_text_exactly_at_boundary(self):
        """Text exactly max_chars long should produce a single chunk."""
        text = "a" * 50
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=50)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_splits_at_word_boundary(self):
        """Should prefer splitting at whitespace rather than mid-word.

        The 10% search window means we need chunk sizes large enough for the
        backward search to find whitespace (e.g. chunk_size=100 → 10 char window).
        """
        text = (
            "The quick brown fox jumps over the lazy dog and then runs across "
            "the meadow to find more interesting things to do on a sunny afternoon"
        )
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=50)
        # Each non-final chunk should end at a word boundary (whitespace)
        for chunk in chunks[:-1]:
            assert chunk[-1] == " ", f"Chunk should end with space but got: {chunk!r}"
        # Reassembled text should equal the original
        assert "".join(chunks) == text

    def test_no_whitespace_falls_back_to_char_boundary(self):
        """When no whitespace exists, should split at character boundary."""
        text = "a" * 100
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=30)
        assert len(chunks) == 4  # 30 + 30 + 30 + 10
        assert "".join(chunks) == text

    def test_newline_as_split_point(self):
        """Should recognize newlines as valid split points."""
        text = "first line content\nsecond line content\nthird"
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=20)
        # Should split at or near the newlines
        assert "".join(chunks) == text

    def test_tab_as_split_point(self):
        """Should recognize tabs as valid split points."""
        text = "column_one\tcolumn_two\tcolumn_three"
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=15)
        assert "".join(chunks) == text

    def test_preserves_all_content(self):
        """No content should be lost during chunking."""
        text = "The quick brown fox jumps over the lazy dog. " * 20
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=50)
        assert "".join(chunks) == text

    def test_large_text_chunk_sizes_reasonable(self):
        """Each chunk should be at most max_chars long."""
        text = "word " * 500  # 2500 chars
        max_chars = 100
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=max_chars)
        for chunk in chunks:
            assert len(chunk) <= max_chars + 1  # +1 for inclusive whitespace

    def test_single_long_word_exceeding_chunk_size(self):
        """A single word longer than max_chars should still be chunked."""
        text = "a" * 200 + " short"
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=50)
        assert "".join(chunks) == text
        assert len(chunks) >= 4  # 200/50 = 4 chunks for the long word

    def test_search_back_limit_10_percent(self):
        """The 10% backwards search should find nearby whitespace."""
        # Create text where whitespace is at exactly 10% back from chunk boundary
        # With max_chars=100, search_back_limit = 10 chars
        # Put space at position 91 (9 chars back from 100)
        text = "x" * 91 + " " + "y" * 108  # 91 + 1 + 108 = 200 chars
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=100)
        # Should split at the space (position 92, including space)
        assert chunks[0] == "x" * 91 + " "
        assert "".join(chunks) == text

    def test_max_chars_of_one(self):
        """Edge case: max_chars=1 should produce one chunk per character."""
        text = "abc"
        chunks = _split_text_into_chunks(text, max_chars_per_chunk=1)
        assert len(chunks) == 3
        assert "".join(chunks) == text


# ===========================================================================
# _load_llm_key_from_app_yml
# ===========================================================================

class TestLoadLlmKeyFromAppYml:
    def test_returns_none_when_file_missing(self, monkeypatch, tmp_path):
        """Should return None gracefully when app.yml doesn't exist."""
        # Point the function to a non-existent directory
        monkeypatch.setattr(os.path, "exists", lambda path: False)
        result = _load_llm_key_from_app_yml("content_sanitization_model")
        assert result is None

    def test_returns_none_for_empty_yaml(self, monkeypatch, tmp_path):
        """Should return None for empty YAML file."""
        yml_path = tmp_path / "app.yml"
        yml_path.write_text("")

        # Monkeypatch os.path.exists and open to use our temp file
        real_exists = os.path.exists
        monkeypatch.setattr(
            "backend.apps.ai.processing.content_sanitization.os.path.exists",
            lambda p: True if p.endswith("app.yml") else real_exists(p),
        )
        real_open = open
        monkeypatch.setattr(
            "builtins.open",
            lambda p, *a, **kw: real_open(str(yml_path), *a, **kw) if str(p).endswith("app.yml") else real_open(p, *a, **kw),
        )
        result = _load_llm_key_from_app_yml("nonexistent_key")
        assert result is None


# ===========================================================================
# PROMPT_INJECTION_PLACEHOLDER constant
# ===========================================================================

class TestConstants:
    def test_placeholder_is_visible(self):
        """The placeholder should clearly indicate content was removed."""
        assert "PROMPT INJECTION" in PROMPT_INJECTION_PLACEHOLDER
        assert "REMOVED" in PROMPT_INJECTION_PLACEHOLDER
