# backend/tests/test_url_normalizer.py
#
# Unit tests for URL normalization hardening helpers.
# Verifies deterministic stripping of query/fragment parameters from URLs
# and message text (markdown links + plain URLs) without any LLM dependency.
#
# Architecture: docs/architecture/prompt-injection.md

from backend.shared.python_utils.url_normalizer import (
    sanitize_url_remove_fragment,
    sanitize_url_remove_query_and_fragment,
    sanitize_text_urls_remove_query_and_fragment,
)


def test_sanitize_url_remove_fragment_keeps_query() -> None:
    url = "https://example.com/path?a=1&b=2#section"
    assert sanitize_url_remove_fragment(url) == "https://example.com/path?a=1&b=2"


def test_sanitize_url_remove_query_and_fragment() -> None:
    url = "https://example.com/path?a=1&b=2#section"
    assert sanitize_url_remove_query_and_fragment(url) == "https://example.com/path"


def test_sanitize_text_urls_markdown_and_plain() -> None:
    text = (
        "Check [doc](https://docs.example.com/page?token=abc#intro) and "
        "also visit https://news.example.com/story?id=42&utm_source=x#comments."
    )
    sanitized = sanitize_text_urls_remove_query_and_fragment(text)
    assert "[doc](https://docs.example.com/page)" in sanitized
    assert "https://news.example.com/story" in sanitized
    assert "?token=" not in sanitized
    assert "utm_source" not in sanitized
    assert "#intro" not in sanitized
    assert "#comments" not in sanitized


def test_sanitize_text_urls_preserves_non_url_text() -> None:
    text = "No links here, only plain text and numbers 123."
    assert sanitize_text_urls_remove_query_and_fragment(text) == text


# --- YouTube URL exception tests ---

def test_youtube_url_preserves_video_id() -> None:
    """YouTube watch URLs must keep the v= parameter (video ID)."""
    url = "https://www.youtube.com/watch?v=7YVrb3-ABYE"
    assert sanitize_url_remove_query_and_fragment(url) == "https://www.youtube.com/watch?v=7YVrb3-ABYE"


def test_youtube_url_preserves_timestamp() -> None:
    """YouTube watch URLs should keep both v= and t= parameters."""
    url = "https://www.youtube.com/watch?v=7YVrb3-ABYE&t=120"
    assert sanitize_url_remove_query_and_fragment(url) == "https://www.youtube.com/watch?v=7YVrb3-ABYE&t=120"


def test_youtube_url_strips_tracking_params() -> None:
    """YouTube tracking/analytics params (si, utm, list, etc.) must be stripped."""
    url = "https://www.youtube.com/watch?v=7YVrb3-ABYE&si=abc123&utm_source=twitter&list=PLxyz&index=3"
    result = sanitize_url_remove_query_and_fragment(url)
    assert "v=7YVrb3-ABYE" in result
    assert "si=" not in result
    assert "utm_source=" not in result
    assert "list=" not in result
    assert "index=" not in result


def test_youtube_url_strips_fragment() -> None:
    """YouTube fragment should be removed."""
    url = "https://www.youtube.com/watch?v=7YVrb3-ABYE#section"
    assert sanitize_url_remove_query_and_fragment(url) == "https://www.youtube.com/watch?v=7YVrb3-ABYE"


def test_youtube_url_rejects_invalid_video_id() -> None:
    """Invalid video IDs (wrong length or chars) should be stripped entirely."""
    # Too short
    url = "https://www.youtube.com/watch?v=short"
    assert sanitize_url_remove_query_and_fragment(url) == "https://www.youtube.com/watch"
    # Injection attempt
    url2 = "https://www.youtube.com/watch?v='; DROP TABLE--"
    assert "DROP" not in sanitize_url_remove_query_and_fragment(url2)


def test_youtube_timestamp_shorthand() -> None:
    """YouTube timestamps can use shorthand like 1h2m3s."""
    url = "https://www.youtube.com/watch?v=7YVrb3-ABYE&t=1h2m3s"
    result = sanitize_url_remove_query_and_fragment(url)
    assert "t=1h2m3s" in result


def test_youtube_in_text_preserves_video_id() -> None:
    """YouTube URLs inside message text should also preserve v= param."""
    text = "Watch this: https://www.youtube.com/watch?v=7YVrb3-ABYE&si=tracking123"
    result = sanitize_text_urls_remove_query_and_fragment(text)
    assert "v=7YVrb3-ABYE" in result
    assert "si=" not in result


def test_non_youtube_url_still_stripped() -> None:
    """Non-YouTube URLs should still have all query params stripped."""
    url = "https://example.com/page?v=something&t=123"
    assert sanitize_url_remove_query_and_fragment(url) == "https://example.com/page"
