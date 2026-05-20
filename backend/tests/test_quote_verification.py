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
    from backend.apps.ai.tasks.stream_consumer import (
        _SOURCE_QUOTE_PATTERN,
        _extract_source_citations,
        _verify_and_strip_bad_quotes,
    )
    from backend.core.api.app.services.embed_service import EmbedService
except ImportError as _exc:
    _IMPORTS_OK = False
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")
    # Stubs so module-level references don't raise NameError during collection
    _SOURCE_QUOTE_PATTERN = None  # type: ignore[assignment]
    _extract_source_citations = None  # type: ignore[assignment]
    _verify_and_strip_bad_quotes = None  # type: ignore[assignment]
    EmbedService = None  # type: ignore[assignment,misc]


def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio needed)."""
    return asyncio.run(coro)


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


# ---------------------------------------------------------------------------
# 4. NON-CANONICAL QUOTE FORMAT DETECTION
#    _extract_source_citations must detect embed-linked blockquotes even when
#    the LLM doesn't use the canonical > [text](embed:ref) format.
# ---------------------------------------------------------------------------


class TestExtractSourceCitations:
    """
    _extract_source_citations returns a list of (quoted_text, embed_ref, full_match)
    tuples for ALL blockquote lines that reference an embed, regardless of format.
    """

    def test_canonical_format(self):
        """Standard format: > [text](embed:ref)"""
        text = '> [Flights start at 29 euros](embed:skyscanner.com-p3R)'
        results = _extract_source_citations(text)
        assert len(results) == 1
        assert results[0][0] == "Flights start at 29 euros"
        assert results[0][1] == "skyscanner.com-p3R"

    def test_multiple_canonical(self):
        text = (
            "Intro.\n"
            "\n"
            "> [First quote](embed:source-a1B)\n"
            "\n"
            "> [Second quote](embed:source-c3D)\n"
        )
        results = _extract_source_citations(text)
        assert len(results) == 2

    # ---- NON-CANONICAL FORMATS (the blind spot) ----

    def test_quoted_text_then_source_link(self):
        """Format: > "quoted text" [source](embed:ref) — text outside brackets."""
        text = '> "We want a country where everyone is free" [PinkNews](embed:thepinknews.com-XSi)'
        results = _extract_source_citations(text)
        assert len(results) == 1
        assert results[0][1] == "thepinknews.com-XSi"
        # Quoted text should be the blockquote content minus the embed link
        assert "We want a country" in results[0][0]

    def test_quoted_text_with_bare_embed_ref(self):
        """Format: > "quoted text" (embed:ref) — no brackets around source label."""
        text = '> "We want a country where everyone is free" (embed:thepinknews.com-XSi)'
        results = _extract_source_citations(text)
        assert len(results) == 1
        assert results[0][1] == "thepinknews.com-XSi"

    def test_blockquote_with_trailing_source(self):
        """Format: > Some claim about policy. [source](embed:ref)"""
        text = '> Magyar stated they want freedom for all. [source](embed:thepinknews.com-XSi)'
        results = _extract_source_citations(text)
        assert len(results) == 1
        assert results[0][1] == "thepinknews.com-XSi"
        assert "Magyar stated" in results[0][0]

    def test_attribution_line_after_quote(self):
        """Format: > "quoted text"\\n> — [Source](embed:ref)"""
        text = (
            '> "We want a country where everyone is free"\n'
            '> \u2014 [PinkNews](embed:thepinknews.com-XSi)'
        )
        results = _extract_source_citations(text)
        assert len(results) >= 1
        assert any(r[1] == "thepinknews.com-XSi" for r in results)

    def test_no_match_plain_blockquote(self):
        """Plain blockquote without any embed reference."""
        text = '> This is just a regular blockquote with no embed link.'
        results = _extract_source_citations(text)
        assert len(results) == 0

    def test_no_match_non_blockquote_embed(self):
        """Embed link NOT inside a blockquote should not be caught."""
        text = 'Check out [this article](embed:example.com-x1Y) for more info.'
        results = _extract_source_citations(text)
        assert len(results) == 0

    def test_mixed_canonical_and_noncanonical(self):
        """Response containing both formats — both should be detected."""
        text = (
            "Here are the findings:\n"
            "\n"
            "> [Exact snippet from source A](embed:source-a1B)\n"
            "\n"
            'He also noted:\n'
            '\n'
            '> "Another important finding from the research" [Source B](embed:source-c3D)\n'
        )
        results = _extract_source_citations(text)
        assert len(results) == 2
        refs = {r[1] for r in results}
        assert "source-a1B" in refs
        assert "source-c3D" in refs


# ---------------------------------------------------------------------------
# 5. RESPONSE-LEVEL STRIPPING TESTS
#    _verify_and_strip_bad_quotes must remove unverified quote blocks from the
#    final assistant response, using the same keyword arguments as production.
# ---------------------------------------------------------------------------


def _quote_verification_services() -> tuple[MagicMock, MagicMock, MagicMock]:
    return MagicMock(), MagicMock(), MagicMock()


class TestVerifyAndStripBadQuotes:

    def test_modified_quote_is_removed_from_response(self, monkeypatch):
        """Regression for issue 8eff9401: shortened/edited Wikipedia quote must disappear."""
        from toon_format import encode

        parent_embed_id = "382dba79-d27c-4026-a83b-655191219669"
        child_embed_id = "ac26ab3e-9b7f-463a-8cc4-2b707d822c32"
        embed_ref = "en.wikipedia.org-gDS"
        source_text = (
            'The tower was known as Burj Dubai ("Dubai Tower") until its official opening '
            'in January 2010. It was renamed in honour of the ruler of Abu Dhabi, Khalifa '
            'bin Zayed Al Nahyan; Abu Dhabi and the federal government of UAE lent Dubai '
            'tens of billions of US dollars so that Dubai could pay its debts - Dubai '
            'borrowed at least $80 billion for construction projects.'
        )
        modified_quote = (
            "The tower was known as Burj Dubai until its official opening in January 2010. "
            "It was renamed in honour of the ruler of Abu Dhabi, Khalifa bin Zayed Al Nahyan; "
            "Abu Dhabi and the federal government of UAE lent Dubai tens of billions of US "
            "dollars so that Dubai could pay its debts."
        )
        encoded_by_id = {
            parent_embed_id: encode({"embed_ids": child_embed_id}),
            child_embed_id: encode({"embed_ref": embed_ref, "description": source_text}),
        }

        async def fake_get_cached_embed_toon(self, embed_id, user_vault_key_id, log_prefix=""):
            return encoded_by_id.get(embed_id)

        monkeypatch.setattr(EmbedService, "_get_cached_embed_toon", fake_get_cached_embed_toon)

        cache_service, directus_service, encryption_service = _quote_verification_services()
        response = (
            "The Burj Khalifa was renamed during the opening.\n\n"
            f"> [{modified_quote}](embed:{embed_ref})\n\n"
            "That helped Dubai manage the debt crisis."
        )

        stripped = _run(_verify_and_strip_bad_quotes(
            aggregated_response=response,
            tool_calls_info=[{"embed_id": parent_embed_id}],
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_vault_key_id="key-1",
            known_valid_refs=set(),
        ))

        assert modified_quote not in stripped
        assert f"embed:{embed_ref}" not in stripped
        assert "The Burj Khalifa was renamed during the opening." in stripped
        assert "That helped Dubai manage the debt crisis." in stripped

    def test_unknown_embed_ref_quote_is_removed_from_response(self, monkeypatch):
        from toon_format import encode

        parent_embed_id = "parent-embed"
        known_ref = "example.com-a1B"
        hallucinated_ref = "fake.example-z9Z"

        async def fake_get_cached_embed_toon(self, embed_id, user_vault_key_id, log_prefix=""):
            if embed_id == parent_embed_id:
                return encode({"embed_ref": known_ref, "description": "Real source text."})
            return None

        monkeypatch.setattr(EmbedService, "_get_cached_embed_toon", fake_get_cached_embed_toon)

        cache_service, directus_service, encryption_service = _quote_verification_services()
        response = (
            "Intro.\n\n"
            f"> [This quote points at a non-existing embed ref](embed:{hallucinated_ref})\n\n"
            "Outro."
        )

        stripped = _run(_verify_and_strip_bad_quotes(
            aggregated_response=response,
            tool_calls_info=[{"embed_id": parent_embed_id}],
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_vault_key_id="key-1",
            known_valid_refs=set(),
        ))

        assert hallucinated_ref not in stripped
        assert "This quote points at a non-existing embed ref" not in stripped
        assert stripped.strip() == "Intro.\n\nOutro."

    def test_exact_quote_is_preserved_in_response(self, monkeypatch):
        from toon_format import encode

        parent_embed_id = "parent-embed"
        child_embed_id = "child-embed"
        embed_ref = "source.example-a1B"
        exact_quote = "Exact source text with no edits."
        encoded_by_id = {
            parent_embed_id: encode({"embed_ids": child_embed_id}),
            child_embed_id: encode({"embed_ref": embed_ref, "description": exact_quote}),
        }

        async def fake_get_cached_embed_toon(self, embed_id, user_vault_key_id, log_prefix=""):
            return encoded_by_id.get(embed_id)

        monkeypatch.setattr(EmbedService, "_get_cached_embed_toon", fake_get_cached_embed_toon)

        cache_service, directus_service, encryption_service = _quote_verification_services()
        response = f"Answer.\n\n> [{exact_quote}](embed:{embed_ref})"

        verified = _run(_verify_and_strip_bad_quotes(
            aggregated_response=response,
            tool_calls_info=[{"embed_id": parent_embed_id}],
            cache_service=cache_service,
            directus_service=directus_service,
            encryption_service=encryption_service,
            user_vault_key_id="key-1",
            known_valid_refs=set(),
        ))

        assert verified == response
