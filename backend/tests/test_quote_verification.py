# backend/tests/test_quote_verification.py
# -------------------------------------------------------------------
# Unit tests for the post-streaming source-quote verification pipeline.
# Covers: regex pattern matching, Unicode normalisation for substring
# matching, and the _extract_searchable_text helper.
#
# These are pure-logic tests: they mock embed caching/decryption so
# they run instantly without Directus or Redis.
# -------------------------------------------------------------------

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

_IMPORTS_OK = True
try:
    from backend.apps.ai.tasks.stream_consumer import _SOURCE_QUOTE_PATTERN
    from backend.core.api.app.services.embed_service import EmbedService
except ImportError as _exc:
    _IMPORTS_OK = False
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")
    # Stubs so module-level references don't raise NameError during collection
    _SOURCE_QUOTE_PATTERN = None  # type: ignore[assignment]
    EmbedService = None  # type: ignore[assignment,misc]


def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio needed)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# 1. PATTERN MATCHING TESTS
# ---------------------------------------------------------------------------


class TestSourceQuotePatternMatching:
    """Test that _SOURCE_QUOTE_PATTERN catches the expected blockquote formats."""

    def test_canonical_format(self):
        line = '> [We want a country where everyone is free](embed:thepinknews.com-XSi)'
        m = _SOURCE_QUOTE_PATTERN.search(line)
        assert m is not None
        assert m.group(1) == "We want a country where everyone is free"
        assert m.group(2) == "thepinknews.com-XSi"

    def test_canonical_with_leading_spaces(self):
        line = '>   [verbatim snippet](embed:bbc.co.uk-a9F)'
        m = _SOURCE_QUOTE_PATTERN.search(line)
        assert m is not None

    def test_no_match_plain_blockquote(self):
        line = '> This is just a regular blockquote'
        assert _SOURCE_QUOTE_PATTERN.search(line) is None

    def test_no_match_inline_link_no_embed(self):
        line = '> [text](https://example.com)'
        assert _SOURCE_QUOTE_PATTERN.search(line) is None

    def test_quoted_text_with_curly_quotes(self):
        line = '> [\u201cWe want a country\u2026\u201d](embed:thepinknews.com-XSi)'
        m = _SOURCE_QUOTE_PATTERN.search(line)
        assert m is not None, "Curly-quoted text inside brackets should match"

    def test_multiline_response_extracts_all(self):
        text = (
            "Some intro text.\n"
            "\n"
            "> [First quote](embed:source-a1B)\n"
            "\n"
            "More prose.\n"
            "\n"
            "> [Second quote](embed:source-c3D)\n"
        )
        matches = list(_SOURCE_QUOTE_PATTERN.finditer(text))
        assert len(matches) == 2
        assert matches[0].group(1) == "First quote"
        assert matches[1].group(1) == "Second quote"


# ---------------------------------------------------------------------------
# 2. _extract_searchable_text TESTS
# ---------------------------------------------------------------------------


class TestExtractSearchableText:

    def test_flat_dict(self):
        decoded = {"title": "Article Title", "description": "Some description text"}
        result = EmbedService._extract_searchable_text(decoded)
        assert "Article Title" in result
        assert "Some description text" in result

    def test_extra_snippets_pipe_delimited(self):
        decoded = {"extra_snippets": "snippet one|snippet two|snippet three"}
        result = EmbedService._extract_searchable_text(decoded)
        assert "snippet one" in result
        assert "snippet two" in result
        assert "snippet three" in result

    def test_nested_results_array(self):
        decoded = {
            "results": [
                {"title": "Result 1", "description": "Desc 1"},
                {"title": "Result 2", "description": "Desc 2"},
            ]
        }
        result = EmbedService._extract_searchable_text(decoded)
        assert "Result 1" in result
        assert "Desc 2" in result

    def test_empty_dict(self):
        assert EmbedService._extract_searchable_text({}) == ""

    def test_non_dict(self):
        assert EmbedService._extract_searchable_text("plain string") == "plain string"

    def test_none_input(self):
        assert EmbedService._extract_searchable_text(None) == ""


# ---------------------------------------------------------------------------
# 3. UNICODE NORMALISATION TESTS — BUG REPRODUCERS for OPE-431
#    These must FAIL before the fix and PASS after.
# ---------------------------------------------------------------------------


def _make_embed_service(content_dict: dict) -> EmbedService:
    """Create an EmbedService with mocked cache returning the given content."""
    from toon_format import encode
    svc = EmbedService(
        cache_service=MagicMock(),
        directus_service=MagicMock(),
        encryption_service=MagicMock(),
    )
    svc._get_cached_embed_toon = AsyncMock(return_value=encode(content_dict))
    return svc


def _verify(content_dict: dict, quoted_text: str) -> bool:
    """Synchronously call verify_quote_in_embed with mocked embed content."""
    svc = _make_embed_service(content_dict)
    return _run(svc.verify_quote_in_embed(
        embed_id="test-id",
        quoted_text=quoted_text,
        user_vault_key_id="key-1",
    ))


class TestVerifyQuoteNormalization:

    def test_exact_match(self):
        assert _verify(
            {"description": "We want a country where everyone is free."},
            "We want a country where everyone is free.",
        ) is True

    def test_case_insensitive(self):
        assert _verify(
            {"description": "We Want A Country Where Everyone Is Free."},
            "we want a country where everyone is free.",
        ) is True

    # ---- BUG REPRODUCERS (OPE-431): must fail before fix ----

    def test_curly_quotes_in_llm_vs_straight_in_embed(self):
        """Embed stores straight quotes, LLM outputs curly quotes."""
        assert _verify(
            {"description": '"We want a country where everyone is free," Magyar said.'},
            '\u201cWe want a country where everyone is free,\u201d Magyar said.',
        ) is True, "Curly vs straight quotes should match"

    def test_straight_quotes_in_llm_vs_curly_in_embed(self):
        """Embed stores curly quotes, LLM outputs straight quotes."""
        assert _verify(
            {"description": '\u201cWe want a country where everyone is free,\u201d Magyar said.'},
            '"We want a country where everyone is free," Magyar said.',
        ) is True, "Straight vs curly quotes should match"

    def test_typographic_ellipsis_vs_three_dots(self):
        """Embed has '...' but LLM uses Unicode ellipsis '…'."""
        assert _verify(
            {"description": "The plan includes reforms... but details are unclear."},
            "The plan includes reforms\u2026 but details are unclear.",
        ) is True, "Ellipsis vs three dots should match"

    def test_three_dots_vs_typographic_ellipsis(self):
        """Embed has '…', LLM writes '...'."""
        assert _verify(
            {"description": "The plan includes reforms\u2026 but details are unclear."},
            "The plan includes reforms... but details are unclear.",
        ) is True, "Three dots vs ellipsis should match"

    def test_curly_single_quotes(self):
        """LLM uses curly single quotes vs ASCII apostrophe."""
        assert _verify(
            {"description": "It's a landmark decision for the country's future."},
            "It\u2019s a landmark decision for the country\u2019s future.",
        ) is True, "Curly vs straight single quotes should match"

    def test_nbsp_vs_regular_space(self):
        """Embed contains NBSP; LLM uses regular space."""
        assert _verify(
            {"description": "100\u00a0percent of voters agreed."},
            "100 percent of voters agreed.",
        ) is True, "NBSP vs regular space should match"

    def test_em_dash_vs_double_hyphen(self):
        """Embed has em-dash; LLM uses double-hyphen."""
        assert _verify(
            {"description": "The leader\u2014who won by a landslide\u2014celebrated."},
            "The leader--who won by a landslide--celebrated.",
        ) is True, "Em-dash vs double-hyphen should match"

    def test_en_dash_vs_hyphen(self):
        """Embed has en-dash; LLM uses regular hyphen."""
        assert _verify(
            {"description": "Pages 10\u201320 cover the topic."},
            "Pages 10-20 cover the topic.",
        ) is True, "En-dash vs hyphen should match"

    def test_combined_typography_mismatch(self):
        """Multiple typography differences in a single quote."""
        assert _verify(
            {"description": '"It\'s clear... the leader\u2014who won\u201420 seats\u2014is confident," he said.'},
            '\u201cIt\u2019s clear\u2026 the leader\u2014who won\u201420 seats\u2014is confident,\u201d he said.',
        ) is True, "Combined typography differences should match"
