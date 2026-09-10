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
    import backend.apps.ai.tasks.stream_consumer as stream_consumer
    from backend.apps.ai.tasks.stream_consumer import (
        _fix_bad_embed_display_text,
        _fix_mixed_url_embed_references,
        _INLINE_EMBED_LINK_PATTERN,
        _BARE_EMBED_REF_PATTERN,
        _MIXED_URL_EMBED_PATTERN,
        _EMBED_REF_SUFFIX_PATTERN,
    )

except ImportError as _exc:
    STREAM_IMPORT_ERROR = str(_exc)
else:
    STREAM_IMPORT_ERROR = None

from backend.apps.ai.utils.embed_display_text import (
    derive_display_text_from_embed_ref,
    derive_embed_display_title,
    escape_markdown_link_label,
    is_bad_embed_display_text,
)


# ---------------------------------------------------------------------------
# is_bad_embed_display_text — pure function, no async needed
# ---------------------------------------------------------------------------


class TestIsBadEmbedDisplayText:
    """Tests for detecting when LLM used the embed_ref slug as display text."""

    # --- Pattern 1: Exact match (display == embed_ref) ---

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_exact_match_domain_ref(self):
        assert is_bad_embed_display_text("macrumors.com-MvT", "macrumors.com-MvT") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_exact_match_slug_ref(self):
        assert is_bad_embed_display_text("eiffel-tower-p2R", "eiffel-tower-p2R") is True

    # --- Pattern 2: Suffix only (display == random suffix) ---

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_suffix_only_3char(self):
        assert is_bad_embed_display_text("MvT", "macrumors.com-MvT") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_suffix_only_2char(self):
        assert is_bad_embed_display_text("k8", "wikipedia.org-k8") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_suffix_only_4char(self):
        assert is_bad_embed_display_text("x4F2", "ryanair-0600-x4F2") is True

    # --- Pattern 3: Domain-with-suffix (display has dot + same suffix base) ---

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_domain_with_suffix(self):
        assert is_bad_embed_display_text("computerweekly.com-Kzy", "computerweekly.com-Kzy") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_domain_with_different_suffix_same_base(self):
        """Both have same base domain, different suffix — still matches because exact match."""
        assert is_bad_embed_display_text("news.ycombinator.com-ANo", "news.ycombinator.com-ANo") is True

    # --- Pattern 4: Bare domain (display == embed_ref minus suffix) ---

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_bare_domain(self):
        assert is_bad_embed_display_text("macrumors.com", "macrumors.com-MvT") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_bare_domain_subdomain(self):
        assert is_bad_embed_display_text("news.ycombinator.com", "news.ycombinator.com-ANo") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_bare_slug_no_domain(self):
        assert is_bad_embed_display_text("eiffel-tower", "eiffel-tower-p2R") is True

    # --- Good display text (should NOT be flagged) ---

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_proper_title(self):
        assert is_bad_embed_display_text("New MacBook Pro", "macrumors.com-MvT") is False

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_proper_descriptive_text(self):
        assert is_bad_embed_display_text("Hacker News", "news.ycombinator.com-ANo") is False

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_proper_place_name(self):
        assert is_bad_embed_display_text("Eiffel Tower", "eiffel-tower-p2R") is False

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_proper_article_title(self):
        assert is_bad_embed_display_text("UK cybersecurity firms report record revenue", "computerweekly.com-Kzy") is False

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_proper_flight_description(self):
        assert is_bad_embed_display_text("Ryanair 06:00 flight", "ryanair-0600-x4F") is False

    # --- Edge cases ---

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_empty_display_text(self):
        assert is_bad_embed_display_text("", "macrumors.com-MvT") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_empty_embed_ref(self):
        assert is_bad_embed_display_text("Some Text", "") is False

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_both_empty(self):
        assert is_bad_embed_display_text("", "") is False

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_whitespace_only(self):
        assert is_bad_embed_display_text("   ", "macrumors.com-MvT") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_empty_display_text_is_bad_inline_label(self):
        assert is_bad_embed_display_text("", "ice-0800-PsB") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_large_preview_marker_is_not_bad(self):
        assert is_bad_embed_display_text("!", "ice-0800-PsB") is False

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_non_domain_connection_ref_exact_match(self):
        assert is_bad_embed_display_text("ice-0800-PsB", "ice-0800-PsB") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_non_domain_connection_ref_base_match(self):
        assert is_bad_embed_display_text("ice-0800", "ice-0800-PsB") is True

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_suffix_in_ref(self):
        """If embed_ref has no recognizable suffix, patterns 2-4 don't apply."""
        assert is_bad_embed_display_text("example", "example") is True  # Still exact match

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_display_partial_overlap_not_flagged(self):
        """Display text that partially overlaps but is clearly different content."""
        assert is_bad_embed_display_text("MacRumors Article About MvT", "macrumors.com-MvT") is False


# contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
def test_escape_markdown_link_label():
    assert (
        escape_markdown_link_label("Research [Draft] <img src=x>\nUpdate")
        == "Research \\[Draft\\] &lt;img src=x&gt; Update"
    )


# ---------------------------------------------------------------------------
# _fix_mixed_url_embed_references — synchronous
# ---------------------------------------------------------------------------


@pytest.mark.skipif(STREAM_IMPORT_ERROR is not None, reason=f"Backend dependencies not installed: {STREAM_IMPORT_ERROR}")
class TestFixMixedUrlEmbedReferences:
    """Tests for rewriting [text](https://url) (embed:ref) → [text](embed:ref)."""

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_space_separated(self):
        """Standard case: URL and embed ref separated by a space."""
        text = "Check out [Mistral Small 4](https://mistral.ai/news/small-4) (embed:mistral.ai-nvh) for details."
        result = _fix_mixed_url_embed_references(text)
        assert result == "Check out [Mistral Small 4](embed:mistral.ai-nvh) for details."

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_space(self):
        """URL and embed ref immediately adjacent."""
        text = "[Technical Changelog](https://docs.mistral.ai/changelog)(embed:docs.mistral.ai-pFX)"
        result = _fix_mixed_url_embed_references(text)
        assert result == "[Technical Changelog](embed:docs.mistral.ai-pFX)"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
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

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_mixed_refs_unchanged(self):
        """Response with proper embed refs should not be modified."""
        text = "See [Mistral Small 4](embed:mistral.ai-nvh) for details."
        result = _fix_mixed_url_embed_references(text)
        assert result == text

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_plain_url_link_unchanged(self):
        """Standard markdown URL link without embed ref is not touched."""
        text = "Visit [Google](https://google.com) for search."
        result = _fix_mixed_url_embed_references(text)
        assert result == text

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_empty_string(self):
        assert _fix_mixed_url_embed_references("") == ""

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_none_input(self):
        assert _fix_mixed_url_embed_references(None) is None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_embed_keyword(self):
        """Fast path: no '(embed:' in text skips regex entirely."""
        text = "Just a normal response with [a link](https://example.com)."
        result = _fix_mixed_url_embed_references(text)
        assert result == text

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_http_url(self):
        """http:// (not https://) should also be handled."""
        text = "[Old Site](http://legacy.example.com/page) (embed:legacy.example.com-x1Y)"
        result = _fix_mixed_url_embed_references(text)
        assert result == "[Old Site](embed:legacy.example.com-x1Y)"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_preserves_surrounding_text(self):
        """Text before and after the mixed pattern is preserved."""
        text = "Before text. [Link](https://example.com/page) (embed:example.com-abc) After text."
        result = _fix_mixed_url_embed_references(text)
        assert result.startswith("Before text. ")
        assert result.endswith(" After text.")

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
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
# _fix_backticked_inline_embed_references — synchronous
# ---------------------------------------------------------------------------


@pytest.mark.skipif(STREAM_IMPORT_ERROR is not None, reason=f"Backend dependencies not installed: {STREAM_IMPORT_ERROR}")
class TestFixBacktickedInlineEmbedReferences:
    """Tests for unwrapping inline-code embed links so the UI can render them."""

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_unwraps_backticked_embed_link(self):
        text = "- `[Ausflugsziele in Brandenburg - Die Top 20](embed:komoot.com-2gG)`"

        result = stream_consumer._fix_backticked_inline_embed_references(text)

        assert result == "- [Ausflugsziele in Brandenburg - Die Top 20](embed:komoot.com-2gG)"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_unwraps_multiple_backticked_embed_links(self):
        text = (
            "1. `[First](embed:first.example-a1B)`\n"
            "2. `[Second](embed:second.example-c3D)`"
        )

        result = stream_consumer._fix_backticked_inline_embed_references(text)

        assert "`[First]" not in result
        assert "`[Second]" not in result
        assert "[First](embed:first.example-a1B)" in result
        assert "[Second](embed:second.example-c3D)" in result

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_leaves_normal_inline_code_unchanged(self):
        text = "Use `pnpm install` before [Docs](embed:docs.example-a1B)."

        result = stream_consumer._fix_backticked_inline_embed_references(text)

        assert result == text


# ---------------------------------------------------------------------------
# Regex pattern tests — verify the compiled patterns match expected inputs
# ---------------------------------------------------------------------------


@pytest.mark.skipif(STREAM_IMPORT_ERROR is not None, reason=f"Backend dependencies not installed: {STREAM_IMPORT_ERROR}")
class TestInlineEmbedLinkPattern:
    """Tests for _INLINE_EMBED_LINK_PATTERN regex."""

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_standard_embed_link(self):
        text = "[Computer Weekly](embed:computerweekly.com-Kzy)"
        match = _INLINE_EMBED_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "Computer Weekly"
        assert match.group(2) == "computerweekly.com-Kzy"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_slug_based_ref(self):
        text = "[Eiffel Tower](embed:eiffel-tower-p2R)"
        match = _INLINE_EMBED_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(2) == "eiffel-tower-p2R"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_plain_url(self):
        text = "[Google](https://google.com)"
        match = _INLINE_EMBED_LINK_PATTERN.search(text)
        assert match is None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_empty_brackets(self):
        text = "[](embed:test-ref)"
        match = _INLINE_EMBED_LINK_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == ""
        assert match.group(2) == "test-ref"


@pytest.mark.skipif(STREAM_IMPORT_ERROR is not None, reason=f"Backend dependencies not installed: {STREAM_IMPORT_ERROR}")
class TestBareEmbedRefPattern:
    """Tests for _BARE_EMBED_REF_PATTERN — brackets without (embed:...) parenthetical."""

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_bare_domain_ref(self):
        text = "Check [computerweekly.com-Kzy] for details."
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "computerweekly.com-Kzy"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_subdomain_ref(self):
        text = "See [news.ycombinator.com-ANo] here."
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "news.ycombinator.com-ANo"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_when_followed_by_parenthetical(self):
        """Should NOT match [text](something) — the (?!\\() lookahead prevents it."""
        text = "[Computer Weekly](embed:computerweekly.com-Kzy)"
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_plain_text_brackets(self):
        """Plain text in brackets without an embed-ref suffix should not match."""
        text = "[some text here] more words"
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_non_domain_connection_ref(self):
        text = "See [ice-0800-PsB] here."
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "ice-0800-PsB"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_text_with_spaces(self):
        """Brackets with spaces should not match (pattern requires no spaces)."""
        text = "[Computer Weekly] article"
        match = _BARE_EMBED_REF_PATTERN.search(text)
        assert match is None


@pytest.mark.skipif(STREAM_IMPORT_ERROR is not None, reason=f"Backend dependencies not installed: {STREAM_IMPORT_ERROR}")
class TestMixedUrlEmbedPattern:
    """Tests for _MIXED_URL_EMBED_PATTERN regex."""

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_with_space(self):
        text = "[Mistral Small 4](https://mistral.ai/news/small-4) (embed:mistral.ai-nvh)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "Mistral Small 4"
        assert match.group(2) == "https://mistral.ai/news/small-4"
        assert match.group(3) == "mistral.ai-nvh"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_without_space(self):
        text = "[Changelog](https://docs.mistral.ai/changelog)(embed:docs.mistral.ai-pFX)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is not None
        assert match.group(3) == "docs.mistral.ai-pFX"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_http_url(self):
        text = "[Old Site](http://legacy.example.com) (embed:legacy.example.com-x1Y)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is not None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_correct_embed_ref(self):
        """Correct embed-only link should not match."""
        text = "[Article](embed:example.com-abc)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_plain_url_only(self):
        text = "[Article](https://example.com/article)"
        match = _MIXED_URL_EMBED_PATTERN.search(text)
        assert match is None


@pytest.mark.skipif(STREAM_IMPORT_ERROR is not None, reason=f"Backend dependencies not installed: {STREAM_IMPORT_ERROR}")
class TestEmbedRefSuffixPattern:
    """Tests for _EMBED_REF_SUFFIX_PATTERN — the random 2-4 char suffix at end."""

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_3char_suffix(self):
        assert _EMBED_REF_SUFFIX_PATTERN.search("computerweekly.com-Kzy") is not None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_2char_suffix(self):
        assert _EMBED_REF_SUFFIX_PATTERN.search("wikipedia.org-k8") is not None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_matches_4char_suffix(self):
        assert _EMBED_REF_SUFFIX_PATTERN.search("ryanair-0600-x4F2") is not None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_no_suffix(self):
        assert _EMBED_REF_SUFFIX_PATTERN.search("example.com") is None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_long_suffix(self):
        """Suffix longer than 4 chars should not match."""
        assert _EMBED_REF_SUFFIX_PATTERN.search("example.com-abcde") is None

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_no_match_single_char(self):
        """Single char suffix should not match (min is 2)."""
        assert _EMBED_REF_SUFFIX_PATTERN.search("example.com-a") is None


class TestDeriveEmbedDisplayText:
    """Tests for safe display-text derivation from technical embed refs."""

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_domain_ref_uses_domain(self):
        assert derive_display_text_from_embed_ref("computerweekly.com-Kzy") == "according to computerweekly.com"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_web_fallback_uses_domain_instead_of_full_article_title(self):
        assert derive_embed_display_title({"type": "website", "title": "A very long article title", "url": "https://www.wired.com/story/test"}, "wired.com-Ab1") == "according to wired.com"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_connection_ref_uses_carrier_and_time(self):
        assert derive_display_text_from_embed_ref("ice-0800-PsB") == "ICE 08:00"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_flixtrain_ref_uses_brand_casing(self):
        assert derive_display_text_from_embed_ref("flixtrain-1423-3VT") == "FlixTrain 14:23"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_unknown_ref_never_returns_raw_suffix(self):
        assert derive_display_text_from_embed_ref("travel-result-Ab1") == "Travel Result"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_connection_child_title_from_fields(self):
        child = {
            "embed_ref": "ice-0800-PsB",
            "operator": "ICE",
            "departure": "2026-06-04T08:00:00",
            "arrival": "2026-06-04T13:26:00",
        }
        assert derive_embed_display_title(child, "ice-0800-PsB") == "ICE 08:00-13:26"

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_bad_title_falls_back_to_ref_label(self):
        child = {"title": "ice-0800-PsB"}
        assert derive_embed_display_title(child, "ice-0800-PsB") == "ICE 08:00"


# ---------------------------------------------------------------------------
# _fix_bad_embed_display_text — async, requires service mocks
# ---------------------------------------------------------------------------


@pytest.mark.skipif(STREAM_IMPORT_ERROR is not None, reason=f"Backend dependencies not installed: {STREAM_IMPORT_ERROR}")
class TestFixBadEmbedDisplayText:
    """
    Tests for _fix_bad_embed_display_text (the async function).

    Since this function depends on CacheService/DirectusService/EncryptionService for
    embed title lookups, we test:
      1. Early return when services are None (no crash, returns input unchanged)
      2. No matches case (response without embed links)
    """

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_returns_unchanged_when_no_services(self):
        """When cache/encryption services are None, returns input unchanged."""
        text = "[macrumors.com-MvT](embed:macrumors.com-MvT) has the details."
        result = asyncio.run(
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

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_returns_unchanged_empty_string(self):
        result = asyncio.run(
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

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    def test_returns_unchanged_no_embed_links(self):
        text = "This is a normal response with no embed links whatsoever."
        result = asyncio.run(
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

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    @pytest.mark.asyncio
    async def test_converts_known_bare_embed_ref_without_other_bad_links(self, monkeypatch):
        from backend.core.api.app.services import embed_service as embed_service_module
        from toon_format import encode

        parent_id = "parent-embed"
        child_id = "child-embed"
        embed_ref = "openai.com-Tm7"
        encoded = {
            parent_id: encode({"embed_ids": child_id}),
            child_id: encode({"embed_ref": embed_ref, "title": "GPT-5.6 Launch"}),
        }

        class FakeEmbedService:
            def __init__(self, **_kwargs):
                pass

            async def _get_cached_embed_toon(self, embed_id, *_args):
                return encoded.get(embed_id)

        monkeypatch.setattr(embed_service_module, "EmbedService", FakeEmbedService)

        result = await _fix_bad_embed_display_text(
            aggregated_response=f"See [{embed_ref}] for details.",
            tool_calls_info=[{"embed_id": parent_id}],
            cache_service=object(),
            directus_service=None,
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )

        assert result == "See [GPT-5.6 Launch](embed:openai.com-Tm7) for details."

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    @pytest.mark.asyncio
    async def test_converts_grouped_known_cite_refs_to_inline_links(self, monkeypatch):
        from backend.core.api.app.services import embed_service as embed_service_module
        from toon_format import encode

        parent_id = "parent-embed"
        first_child_id = "first-child"
        second_child_id = "second-child"
        encoded = {
            parent_id: encode({"embed_ids": f"{first_child_id}|{second_child_id}"}),
            first_child_id: encode({
                "type": "website",
                "embed_ref": "cnbc.com-vcZ",
                "title": "CNBC AI Infrastructure",
            }),
            second_child_id: encode({
                "type": "website",
                "embed_ref": "secondtalent.com-RFp",
                "title": "Second Talent Market Report",
            }),
        }

        class FakeEmbedService:
            def __init__(self, **_kwargs):
                pass

            async def _get_cached_embed_toon(self, embed_id, *_args):
                return encoded.get(embed_id)

        monkeypatch.setattr(embed_service_module, "EmbedService", FakeEmbedService)

        result = await _fix_bad_embed_display_text(
            aggregated_response="Sources: [cite: cnbc.com-vcZ, secondtalent.com-RFp]",
            tool_calls_info=[{"embed_id": parent_id}],
            cache_service=object(),
            directus_service=None,
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )

        assert result == (
            "Sources: [according to cnbc.com](embed:cnbc.com-vcZ), "
            "[according to secondtalent.com](embed:secondtalent.com-RFp)"
        )

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    @pytest.mark.asyncio
    async def test_grouped_cites_preserve_markdown_literals_and_escape_titles(self, monkeypatch):
        from backend.core.api.app.services import embed_service as embed_service_module
        from toon_format import encode

        parent_id = "parent-embed"
        child_id = "child-embed"
        embed_ref = "example.com-X7z"
        title = "Research [Draft] <img src=x>"
        encoded = {
            parent_id: encode({"embed_ids": child_id}),
            child_id: encode({"type": "website", "embed_ref": embed_ref, "title": title}),
        }

        class FakeEmbedService:
            def __init__(self, **_kwargs):
                pass

            async def _get_cached_embed_toon(self, embed_id, *_args):
                return encoded.get(embed_id)

        monkeypatch.setattr(embed_service_module, "EmbedService", FakeEmbedService)
        grouped_cite = f"[cite: {embed_ref}]"
        response = (
            f"Source: {grouped_cite}\n\n"
            f"> Literal quote {grouped_cite}\n\n"
            f"Inline code `{grouped_cite}`\n\n"
            f"```text\nLiteral fenced code {grouped_cite}\n```"
        )

        result = await _fix_bad_embed_display_text(
            aggregated_response=response,
            tool_calls_info=[{"embed_id": parent_id}],
            cache_service=object(),
            directus_service=None,
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )

        assert result == (
            "Source: [according to example.com](embed:example.com-X7z)\n\n"
            f"> Literal quote {grouped_cite}\n\n"
            f"Inline code `{grouped_cite}`\n\n"
            f"```text\nLiteral fenced code {grouped_cite}\n```"
        )

    # contract-test: supporting surface=gui.web assertions=chats.rendering.inline-entity-interaction
    @pytest.mark.asyncio
    async def test_promotes_empty_known_image_ref_to_large_preview(self, monkeypatch):
        from backend.core.api.app.services import embed_service as embed_service_module
        from toon_format import encode

        parent_id = "parent-embed"
        child_id = "image-child"
        image_ref = "images.example-I9x"
        encoded = {
            parent_id: encode({"embed_ids": child_id}),
            child_id: encode({
                "type": "image_result",
                "embed_ref": image_ref,
                "title": "Repairing a smartphone",
            }),
        }

        class FakeEmbedService:
            def __init__(self, **_kwargs):
                pass

            async def _get_cached_embed_toon(self, embed_id, *_args):
                return encoded.get(embed_id)

        monkeypatch.setattr(embed_service_module, "EmbedService", FakeEmbedService)

        result = await _fix_bad_embed_display_text(
            aggregated_response=f"Relevant image:\n\n[](embed:{image_ref})",
            tool_calls_info=[{"embed_id": parent_id}],
            cache_service=object(),
            directus_service=None,
            encryption_service=object(),
            user_vault_key_id="vault-key",
        )

        assert result == f"Relevant image:\n\n[!](embed:{image_ref})"
