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
