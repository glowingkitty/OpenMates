# backend/tests/test_embed_link_fixes.py
#
# Unit tests for the embed link post-processing fixes in stream_consumer.py (OPE-9).
#
# These functions auto-correct broken embed reference links that LLMs (especially Gemini)
# produce in their responses — bare bracket refs, mixed URL+embed patterns, and bad
# display text that uses the raw embed_ref slug instead of a human-readable title.
#
# Bug history this test suite guards against:
#   - OPE-9: LLM produces [computerweekly.com-Kzy] instead of [Computer Weekly](embed:computerweekly.com-Kzy)
#   - Commit e9bd4564f: auto-correct mixed URL+embed references
#   - Commit 8ff811e79: detect bare embed refs in LLM response

import asyncio
import pytest

try:
    from backend.apps.ai.tasks.stream_consumer import (
        _is_bad_embed_display_text,
        _fix_bad_embed_display_text,
        _fix_mixed_url_embed_references,
        _INLINE_EMBED_LINK_PATTERN,
        _BARE_EMBED_REF_PATTERN,
        _MIXED_URL_EMBED_PATTERN,
        _EMBED_REF_SUFFIX_PATTERN,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ---------------------------------------------------------------------------
# _is_bad_embed_display_text — pure function, no async needed
# ---------------------------------------------------------------------------


class TestIsBadEmbedDisplayText:
    """Tests for detecting when LLM used the embed_ref slug as display text."""

    # --- Pattern 1: Exact match (display == embed_ref) ---

    def test_exact_match_domain_ref(self):
        assert _is_bad_embed_display_text("macrumors.com-MvT", "macrumors.com-MvT") is True

    def test_exact_match_slug_ref(self):
        assert _is_bad_embed_display_text("eiffel-tower-p2R", "eiffel-tower-p2R") is True

    # --- Pattern 2: Suffix only (display == random suffix) ---

    def test_suffix_only_3char(self):
        assert _is_bad_embed_display_text("MvT", "macrumors.com-MvT") is True

    def test_suffix_only_2char(self):
        assert _is_bad_embed_display_text("k8", "wikipedia.org-k8") is True

    def test_suffix_only_4char(self):
        assert _is_bad_embed_display_text("x4F2", "ryanair-0600-x4F2") is True

    # --- Pattern 3: Domain-with-suffix (display has dot + same suffix base) ---

    def test_domain_with_suffix(self):
        assert _is_bad_embed_display_text("computerweekly.com-Kzy", "computerweekly.com-Kzy") is True

    def test_domain_with_different_suffix_same_base(self):
        """Both have same base domain, different suffix — still matches because exact match."""
        assert _is_bad_embed_display_text("news.ycombinator.com-ANo", "news.ycombinator.com-ANo") is True

    # --- Pattern 4: Bare domain (display == embed_ref minus suffix) ---

    def test_bare_domain(self):
        assert _is_bad_embed_display_text("macrumors.com", "macrumors.com-MvT") is True

    def test_bare_domain_subdomain(self):
        assert _is_bad_embed_display_text("news.ycombinator.com", "news.ycombinator.com-ANo") is True

    def test_bare_slug_no_domain(self):
        assert _is_bad_embed_display_text("eiffel-tower", "eiffel-tower-p2R") is True

    # --- Good display text (should NOT be flagged) ---

    def test_proper_title(self):
        assert _is_bad_embed_display_text("New MacBook Pro", "macrumors.com-MvT") is False

    def test_proper_descriptive_text(self):
        assert _is_bad_embed_display_text("Hacker News", "news.ycombinator.com-ANo") is False

    def test_proper_place_name(self):
        assert _is_bad_embed_display_text("Eiffel Tower", "eiffel-tower-p2R") is False

    def test_proper_article_title(self):
        assert _is_bad_embed_display_text("UK cybersecurity firms report record revenue", "computerweekly.com-Kzy") is False

    def test_proper_flight_description(self):
        assert _is_bad_embed_display_text("Ryanair 06:00 flight", "ryanair-0600-x4F") is False

    # --- Edge cases ---

    def test_empty_display_text(self):
        assert _is_bad_embed_display_text("", "macrumors.com-MvT") is False

    def test_empty_embed_ref(self):
        assert _is_bad_embed_display_text("Some Text", "") is False

    def test_both_empty(self):
        assert _is_bad_embed_display_text("", "") is False

    def test_whitespace_only(self):
        assert _is_bad_embed_display_text("   ", "macrumors.com-MvT") is False

    def test_no_suffix_in_ref(self):
        """If embed_ref has no recognizable suffix, patterns 2-4 don't apply."""
        assert _is_bad_embed_display_text("example", "example") is True  # Still exact match

    def test_display_partial_overlap_not_flagged(self):
        """Display text that partially overlaps but is clearly different content."""
        assert _is_bad_embed_display_text("MacRumors Article About MvT", "macrumors.com-MvT") is False


# ---------------------------------------------------------------------------
# _fix_mixed_url_embed_references — synchronous
# ---------------------------------------------------------------------------


class TestFixMixedUrlEmbedReferences:
    """Tests for rewriting [text](https://url) (embed:ref) → [text](embed:ref)."""

    def test_space_separated(self):
        """Standard case: URL and embed ref separated by a space."""
        text = "Check out [Mistral Small 4](https://mistral.ai/news/small-4) (embed:mistral.ai-nvh) for details."
        result = _fix_mixed_url_embed_references(text)
        assert result == "Check out [Mistral Small 4](embed:mistral.ai-nvh) for details."

    def test_no_space(self):
        """URL and embed ref immediately adjacent."""
        text = "[Technical Changelog](https://docs.mistral.ai/changelog)(embed:docs.mistral.ai-pFX)"
        result = _fix_mixed_url_embed_references(text)
        assert result == "[Technical Changelog](embed:docs.mistral.ai-pFX)"

    def test_multiple_mixed_refs(self):
        """Multiple mixed patterns in one response."""
        text = (
            "See [Article One](https://example.com/one) (embed:example.com-aB1) and "
            "[Article Two](https://example.com/two) (embed:example.com-cD2) for context."
        )
        result = _fix_mixed_url_embed_references(text)
        assert "[Article One](embed:example.com-aB1)" in result
        assert "[Article Two](embed:example.com-cD2)" in result
        assert "https://" not in result

    def test_no_mixed_refs_unchanged(self):
        """Response with proper embed refs should not be modified."""
        text = "See [Mistral Small 4](embed:mistral.ai-nvh) for details."
        result = _fix_mixed_url_embed_references(text)
        assert result == text

    def test_plain_url_link_unchanged(self):
        """Standard markdown URL link without embed ref is not touched."""
        text = "Visit [Google](https://google.com) for search."
        result = _fix_mixed_url_embed_references(text)
        assert result == text

    def test_empty_string(self):
        assert _fix_mixed_url_embed_references("") == ""

    def test_none_input(self):
        assert _fix_mixed_url_embed_references(None) is None

    def test_no_embed_keyword(self):
        """Fast path: no '(embed:' in text skips regex entirely."""
        text = "Just a normal response with [a link](https://example.com)."
        result = _fix_mixed_url_embed_references(text)
        assert result == text

    def test_http_url(self):
        """http:// (not https://) should also be handled."""
        text = "[Old Site](http://legacy.example.com/page) (embed:legacy.example.com-x1Y)"
        result = _fix_mixed_url_embed_references(text)
        assert result == "[Old Site](embed:legacy.example.com-x1Y)"

    def test_preserves_surrounding_text(self):
        """Text before and after the mixed pattern is preserved."""
        text = "Before text. [Link](https://example.com/page) (embed:example.com-abc) After text."
        result = _fix_mixed_url_embed_references(text)
        assert result.startswith("Before text. ")
        assert result.endswith(" After text.")

    def test_multiline_response(self):
        """Mixed patterns across lines."""
        text = (
            "## Results\n\n"
            "1. [First Result](https://first.com/article) (embed:first.com-a1B)\n"
            "2. [Second Result](embed:second.com-c3D)\n"  # Already correct
            "3. [Third Result](https://third.com/page) (embed:third.com-e5F)\n"
        )
        result = _fix_mixed_url_embed_references(text)
        assert "[First Result](embed:first.com-a1B)" in result
        assert "[Second Result](embed:second.com-c3D)" in result  # Unchanged
        assert "[Third Result](embed:third.com-e5F)" in result
        assert "https://first.com" not in result
        assert "https://third.com" not in result


# ---------------------------------------------------------------------------
# Regex pattern tests — verify the compiled patterns match expected inputs
# ---------------------------------------------------------------------------


class TestInlineEmbedLinkPattern:
    """Tests for _INLINE_EMBED_LINK_PATTERN regex."""

    def test_matches_standard_embed_link(self):
        text = "[Computer Weekly](embed:computerweekly.com-Kzy)"
        match = _INLINE_EMBED_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "Computer Weekly"
        assert match.group(2) == "computerweekly.com-Kzy"

    def test_matches_slug_based_ref(self):
        text = "[Eiffel Tower](embed:eiffel-tower-p2R)"
        match = _INLINE_EMBED_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(2) == "eiffel-tower-p2R"

    def test_no_match_plain_url(self):
        text = "[Google](https://google.com)"
        match = _INLINE_EMBED_LINK_PATTERN.search(text)
        assert match is None

    def test_no_match_empty_brackets(self):
        text = "[](embed:test-ref)"
        # Empty display text still matches the regex (empty group 1)
        match = _INLINE_EMBED_LINK_PATTERN.search(text)
        # Pattern requires [^\]]+ so empty brackets shouldn't match
        assert match is None


class TestBareEmbedRefPattern:
    """Tests for _BARE_EMBED_REF_PATTERN — brackets without (embed:...) parenthetical."""

    def test_matches_bare_domain_ref(self):
        text = "Check [computerweekly.com-Kzy] for details."
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "computerweekly.com-Kzy"

    def test_matches_subdomain_ref(self):
        text = "See [news.ycombinator.com-ANo] here."
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "news.ycombinator.com-ANo"

    def test_no_match_when_followed_by_parenthetical(self):
        """Should NOT match [text](something) — the (?!\\() lookahead prevents it."""
        text = "[Computer Weekly](embed:computerweekly.com-Kzy)"
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is None

    def test_no_match_plain_text_brackets(self):
        """Plain text in brackets without a dot should not match."""
        text = "[some text here] more words"
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is None

    def test_no_match_text_with_spaces(self):
        """Brackets with spaces should not match (pattern requires no spaces)."""
        text = "[Computer Weekly] article"
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is None


class TestMixedUrlEmbedPattern:
    """Tests for _MIXED_URL_EMBED_PATTERN regex."""

    def test_matches_with_space(self):
        text = "[Mistral Small 4](https://mistral.ai/news/small-4) (embed:mistral.ai-nvh)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "Mistral Small 4"
        assert match.group(2) == "https://mistral.ai/news/small-4"
        assert match.group(3) == "mistral.ai-nvh"

    def test_matches_without_space(self):
        text = "[Changelog](https://docs.mistral.ai/changelog)(embed:docs.mistral.ai-pFX)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is not None
        assert match.group(3) == "docs.mistral.ai-pFX"

    def test_matches_http_url(self):
        text = "[Old Site](http://legacy.example.com) (embed:legacy.example.com-x1Y)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is not None

    def test_no_match_correct_embed_ref(self):
        """Correct embed-only link should not match."""
        text = "[Article](embed:example.com-abc)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is None

    def test_no_match_plain_url_only(self):
        text = "[Article](https://example.com/article)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is None


class TestEmbedRefSuffixPattern:
    """Tests for _EMBED_REF_SUFFIX_PATTERN — the random 2-4 char suffix at end."""

    def test_matches_3char_suffix(self):
        assert _EMBED_REF_SUFFIX_PATTERN.search("computerweekly.com-Kzy") is not None

    def test_matches_2char_suffix(self):
        assert _EMBED_REF_SUFFIX_PATTERN.search("wikipedia.org-k8") is not None

    def test_matches_4char_suffix(self):
        assert _EMBED_REF_SUFFIX_PATTERN.search("ryanair-0600-x4F2") is not None

    def test_no_match_no_suffix(self):
        assert _EMBED_REF_SUFFIX_PATTERN.search("example.com") is None

    def test_no_match_long_suffix(self):
        """Suffix longer than 4 chars should not match."""
        assert _EMBED_REF_SUFFIX_PATTERN.search("example.com-abcde") is None

    def test_no_match_single_char(self):
        """Single char suffix should not match (min is 2)."""
        assert _EMBED_REF_SUFFIX_PATTERN.search("example.com-a") is None


# ---------------------------------------------------------------------------
# _fix_bad_embed_display_text — async, requires service mocks
# ---------------------------------------------------------------------------


class TestFixBadEmbedDisplayText:
    """
    Tests for _fix_bad_embed_display_text (the async function).

    Since this function depends on CacheService/DirectusService/EncryptionService for
    embed title lookups, we test:
      1. Early return when services are None (no crash, returns input unchanged)
      2. No matches case (response without embed links)
    """

    def test_returns_unchanged_when_no_services(self):
        """When cache/encryption services are None, returns input unchanged."""
        text = "[macrumors.com-MvT](embed:macrumors.com-MvT) has the details."
        result = asyncio.get_event_loop().run_until_complete(
            _fix_bad_embed_display_text(
                aggregated_response=text,
                tool_calls_info=None,
                cache_service=None,
                directus_service=None,
                encryption_service=None,
                user_vault_key_id=None,
            )
        )
        assert result == text

    def test_returns_unchanged_empty_string(self):
        result = asyncio.get_event_loop().run_until_complete(
            _fix_bad_embed_display_text(
                aggregated_response="",
                tool_calls_info=None,
                cache_service=None,
                directus_service=None,
                encryption_service=None,
                user_vault_key_id=None,
            )
        )
        assert result == ""

    def test_returns_unchanged_no_embed_links(self):
        text = "This is a normal response with no embed links whatsoever."
        result = asyncio.get_event_loop().run_until_complete(
            _fix_bad_embed_display_text(
                aggregated_response=text,
                tool_calls_info=None,
                cache_service=None,
                directus_service=None,
                encryption_service=None,
                user_vault_key_id=None,
            )
        )
        assert result == text
