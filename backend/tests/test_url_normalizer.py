# backend/tests/test_url_normalizer.py
#
# Unit tests for URL normalization hardening helpers.
# Verifies deterministic URL normalization plus model-backed link safety
# processing for message text (markdown links + plain URLs).
#
# Architecture: docs/architecture/prompt-injection.md

import pytest

from backend.shared.python_utils import url_normalizer
from backend.shared.python_utils.url_normalizer import (
    extract_urls_from_content,
    extract_urls_from_text,
    sanitize_url_remove_fragment,
    sanitize_url_remove_query_and_fragment,
    sanitize_text_urls_with_safeguard,
)
from backend.shared.python_utils.markdown_links import iter_markdown_links


class _FakeSafeguard:
    def __init__(self, malicious_urls: set[str] | None = None, error: str | None = None) -> None:
        self.malicious_urls = malicious_urls or set()
        self.error = error
        self.calls: list[list[str]] = []

    async def initialize(self, secrets_manager) -> None:
        return None

    async def report_malicious_urls(self, *, urls: list[str], assistant_response: str):
        self.calls.append(urls)
        return type(
            "Report",
            (),
            {"all_urls_safe": not self.malicious_urls, "malicious_urls": self.malicious_urls, "error": self.error},
        )()


def test_sanitize_url_remove_fragment_keeps_query() -> None:
    url = "https://example.com/path?a=1&b=2#section"
    assert sanitize_url_remove_fragment(url) == "https://example.com/path?a=1&b=2"


def test_sanitize_url_remove_query_and_fragment() -> None:
    url = "https://example.com/path?a=1&b=2#section"
    assert sanitize_url_remove_query_and_fragment(url) == "https://example.com/path"


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


def test_non_youtube_url_still_stripped() -> None:
    """Non-YouTube URLs should still have all query params stripped."""
    url = "https://example.com/page?v=something&t=123"
    assert sanitize_url_remove_query_and_fragment(url) == "https://example.com/page"


def test_extract_urls_from_content_recurses_source_payloads() -> None:
    payload = {
        "user": "Please inspect https://user.example.com/start.",
        "tool": {
            "results": [
                {"url": "https://docs.example.com/page?ref=1#section"},
                "Mirror: [doc](https://docs.example.com/page?ref=1#section)",
            ]
        },
    }

    assert extract_urls_from_content(payload) == {
        "https://user.example.com/start",
        "https://docs.example.com/page?ref=1#section",
    }


def test_extract_urls_from_text_strips_inline_code_backtick() -> None:
    text = "POST to `https://ws.api.video/videos`."

    assert extract_urls_from_text(text) == {"https://ws.api.video/videos"}


def test_markdown_link_scanner_keeps_balanced_parentheses() -> None:
    links = list(iter_markdown_links("Read [Bash](wiki:Bash_(Unix_shell)) and [docs](https://example.com/a_(b))."))

    assert [(link.label, link.href) for link in links] == [
        ("Bash", "wiki:Bash_(Unix_shell)"),
        ("docs", "https://example.com/a_(b)"),
    ]


@pytest.mark.asyncio
async def test_safeguard_url_processing_keeps_safe_url_with_params(monkeypatch) -> None:
    text = "Read https://example.com/page?ref=public#intro."
    fake = _FakeSafeguard()
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(text, secrets_manager=object())

    assert result == text
    assert fake.calls == [["https://example.com/page?ref=public#intro"]]


@pytest.mark.asyncio
async def test_safeguard_url_processing_removes_reported_malicious_url(monkeypatch) -> None:
    text = "Read https://example.com/sensitiveuserdata."
    fake = _FakeSafeguard(malicious_urls={"https://example.com/sensitiveuserdata"})
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(text, secrets_manager=object())

    assert result == "Read [link removed]."


@pytest.mark.asyncio
async def test_safeguard_url_processing_removes_unsafe_markdown_url(monkeypatch) -> None:
    text = "Open [profile](https://example.com/user/alice-private-token)."
    fake = _FakeSafeguard(malicious_urls={"https://example.com/user/alice-private-token"})
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(text, secrets_manager=object())

    assert result == "Open profile."


@pytest.mark.asyncio
async def test_safeguard_url_processing_removes_assistant_url_missing_from_sources(
    monkeypatch,
) -> None:
    text = "Secret link: https://evil.example.com/user-secret-path."
    fake = _FakeSafeguard()
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(
        text,
        secrets_manager=object(),
        allowed_source_urls={"https://docs.example.com/original"},
    )

    assert result == "Secret link: [link removed]."
    assert fake.calls == []


@pytest.mark.asyncio
async def test_safeguard_url_processing_keeps_assistant_url_found_in_sources(
    monkeypatch,
) -> None:
    text = "Use https://docs.example.com/original."
    fake = _FakeSafeguard()
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(
        text,
        secrets_manager=object(),
        allowed_source_urls={"https://docs.example.com/original"},
    )

    assert result == text
    assert fake.calls == [["https://docs.example.com/original"]]


@pytest.mark.asyncio
async def test_safeguard_keeps_source_backed_inline_code_url(monkeypatch) -> None:
    text = "POST to `https://ws.api.video/videos`."
    fake = _FakeSafeguard()
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(
        text,
        secrets_manager=object(),
        allowed_source_urls={"https://ws.api.video/videos"},
    )

    assert result == text
    assert fake.calls == [["https://ws.api.video/videos"]]


@pytest.mark.asyncio
async def test_safeguard_removes_assistant_created_inline_code_url(monkeypatch) -> None:
    text = "POST to `https://evil.example.com/secret`."
    fake = _FakeSafeguard()
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(
        text,
        secrets_manager=object(),
        allowed_source_urls={"https://ws.api.video/videos"},
    )

    assert result == "POST to `[link removed]`."
    assert fake.calls == []


@pytest.mark.asyncio
async def test_safeguard_keeps_source_backed_markdown_url_with_parentheses(monkeypatch) -> None:
    text = "Read [docs](https://example.com/path_(x))."
    fake = _FakeSafeguard()
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(
        text,
        secrets_manager=object(),
        allowed_source_urls={"https://example.com/path_(x)"},
    )

    assert result == text
    assert fake.calls == [["https://example.com/path_(x)"]]


@pytest.mark.asyncio
async def test_safeguard_url_processing_fails_closed_on_batch_error(monkeypatch) -> None:
    text = "Use https://docs.example.com/original."
    fake = _FakeSafeguard(
        malicious_urls={"https://docs.example.com/original"},
        error="safeguard_error",
    )
    monkeypatch.setattr(url_normalizer, "_get_safeguard_client", lambda: fake)

    result = await sanitize_text_urls_with_safeguard(
        text,
        secrets_manager=object(),
        allowed_source_urls={"https://docs.example.com/original"},
    )

    assert result == "Use [link removed]."
    assert fake.calls == [["https://docs.example.com/original"]]
