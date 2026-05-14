# backend/tests/test_reddit_rss_provider.py
#
# Unit tests for the Reddit RSS social-media provider.
# These tests use static Atom feed samples so the normalized schema and parser
# behavior remain stable without depending on live Reddit availability.

import pytest

from backend.shared.providers.reddit import rss
from backend.shared.providers.reddit.rss import _headers, _parse_comment_feed, _parse_post_feed, _search_feed_url


POST_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Privacy-focused chatbot feedback?</title>
    <updated>2026-05-12T13:15:53+00:00</updated>
    <author><name>/u/example_builder</name></author>
    <link href="https://www.reddit.com/r/privacy/comments/abc123/privacyfocused_chatbot_feedback/" />
    <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;I built a chatbot and want feedback.&lt;/p&gt;&lt;/div&gt;&lt;!-- SC_ON --&gt; &amp;#32; submitted by &amp;#32; &lt;a href="https://www.reddit.com/user/example_builder"&gt; /u/example_builder &lt;/a&gt;</content>
  </entry>
</feed>
"""


COMMENT_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Privacy-focused chatbot feedback?</title>
    <updated>2026-05-12T13:15:53+00:00</updated>
    <author><name>/u/example_builder</name></author>
    <link href="https://www.reddit.com/r/privacy/comments/abc123/privacyfocused_chatbot_feedback/" />
    <content type="html">&lt;p&gt;Original post body should not be parsed as a comment.&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>Comment by AutoModerator</title>
    <updated>2026-05-12T13:16:00+00:00</updated>
    <author><name>/u/AutoModerator</name></author>
    <link href="https://www.reddit.com/r/privacy/comments/abc123/privacyfocused_chatbot_feedback/mod1/" />
    <content type="html">&lt;p&gt;Read the rules.&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>Comment by useful_user</title>
    <updated>2026-05-12T13:17:00+00:00</updated>
    <author><name>/u/useful_user</name></author>
    <link href="https://www.reddit.com/r/privacy/comments/abc123/privacyfocused_chatbot_feedback/comment1/" />
    <content type="html">&lt;p&gt;The hard part is proving what data leaves the device.&lt;/p&gt;</content>
  </entry>
</feed>
"""


TWO_POST_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>First opportunity</title>
    <updated>2026-05-12T13:15:53+00:00</updated>
    <author><name>/u/example_builder</name></author>
    <link href="https://www.reddit.com/r/privacy/comments/abc123/first_opportunity/" />
    <content type="html">&lt;p&gt;First post body.&lt;/p&gt;</content>
  </entry>
  <entry>
    <title>Second opportunity</title>
    <updated>2026-05-12T13:20:53+00:00</updated>
    <author><name>/u/example_two</name></author>
    <link href="https://www.reddit.com/r/privacy/comments/def456/second_opportunity/" />
    <content type="html">&lt;p&gt;Second post body.&lt;/p&gt;</content>
  </entry>
</feed>
"""


def test_parse_post_feed_returns_full_title_and_clean_body():
    posts = _parse_post_feed(POST_FEED, "privacy")

    assert len(posts) == 1
    assert posts[0].id == "abc123"
    assert posts[0].page == "privacy"
    assert posts[0].title == "Privacy-focused chatbot feedback?"
    assert posts[0].body == "I built a chatbot and want feedback."
    assert posts[0].author == "/u/example_builder"


def test_parse_comment_feed_skips_post_entry_and_automoderator():
    comments = _parse_comment_feed(
        COMMENT_FEED,
        "https://www.reddit.com/r/privacy/comments/abc123/privacyfocused_chatbot_feedback/",
    )

    assert len(comments) == 1
    assert comments[0].id == "comment1"
    assert comments[0].author == "/u/useful_user"
    assert comments[0].body == "The hard part is proving what data leaves the device."


def test_headers_bypass_cached_reddit_block_page():
    headers = _headers()

    assert headers["Cache-Control"] == "no-cache"
    assert headers["Pragma"] == "no-cache"


@pytest.mark.asyncio
async def test_fetch_subreddit_posts_stops_comments_at_request_budget(monkeypatch):
    async def fake_fetch(url: str, **kwargs):
        if "/comments/" in url:
            return rss._FetchResponse(text=COMMENT_FEED, rate_limit=rss.RedditRateLimit(remaining=80.0))
        return rss._FetchResponse(text=TWO_POST_FEED, rate_limit=rss.RedditRateLimit(remaining=90.0))

    monkeypatch.setattr(rss, "_fetch_text", fake_fetch)

    result = await rss.fetch_subreddit_posts("privacy", comments_limit=1, max_requests_per_call=2)

    assert result.request_count == 2
    assert result.comments_skipped_count == 1
    assert result.posts[0].fetched_comment_count == 1
    assert result.posts[1].fetched_comment_count == 0
    assert "request budget" in result.warnings[0]


@pytest.mark.asyncio
async def test_fetch_subreddit_posts_stops_comments_when_remaining_is_low(monkeypatch):
    async def fake_fetch(url: str, **kwargs):
        return rss._FetchResponse(text=TWO_POST_FEED, rate_limit=rss.RedditRateLimit(remaining=4.0))

    monkeypatch.setattr(rss, "_fetch_text", fake_fetch)

    result = await rss.fetch_subreddit_posts("privacy", min_remaining_for_comments=5.0)

    assert result.request_count == 1
    assert result.comments_skipped_count == 2
    assert all(post.fetched_comment_count == 0 for post in result.posts)
    assert "remaining budget is low" in result.warnings[0]


@pytest.mark.asyncio
async def test_fetch_subreddit_posts_retries_short_rate_limit(monkeypatch):
    calls = 0
    sleeps: list[float] = []

    async def fake_fetch(url: str, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise rss._RedditRssRateLimitError(
                "rate limited",
                status_code=429,
                rate_limit=rss.RedditRateLimit(remaining=0.0),
                retry_after_seconds=0.01,
            )
        return rss._FetchResponse(text=POST_FEED, rate_limit=rss.RedditRateLimit(remaining=99.0))

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)

    monkeypatch.setattr(rss, "_fetch_text", fake_fetch)
    monkeypatch.setattr(rss.asyncio, "sleep", fake_sleep)

    result = await rss.fetch_subreddit_posts("privacy", include_comments=False, max_inline_wait_seconds=1.0)

    assert calls == 2
    assert sleeps == [0.01]
    assert result.rate_limited is False
    assert result.request_count == 1
    assert len(result.posts) == 1


@pytest.mark.asyncio
async def test_fetch_subreddit_posts_returns_partial_result_for_long_rate_limit(monkeypatch):
    async def fake_fetch(url: str, **kwargs):
        if "/comments/" in url:
            raise rss._RedditRssRateLimitError(
                "rate limited",
                status_code=429,
                rate_limit=rss.RedditRateLimit(remaining=0.0, reset_seconds=60.0),
                retry_after_seconds=60.0,
            )
        return rss._FetchResponse(text=TWO_POST_FEED, rate_limit=rss.RedditRateLimit(remaining=90.0))

    monkeypatch.setattr(rss, "_fetch_text", fake_fetch)

    result = await rss.fetch_subreddit_posts("privacy", max_inline_wait_seconds=0.1)

    assert result.request_count == 1
    assert result.rate_limited is True
    assert result.next_retry_after_seconds == 60.0
    assert result.comments_skipped_count == 2
    assert len(result.posts) == 2


@pytest.mark.asyncio
async def test_fetch_subreddit_posts_passes_proxy_to_fetch(monkeypatch):
    captured = {}

    async def fake_fetch(url: str, **kwargs):
        captured["proxy_url"] = kwargs.get("proxy_url")
        return rss._FetchResponse(text=POST_FEED, rate_limit=rss.RedditRateLimit(remaining=90.0))

    monkeypatch.setattr(rss, "_fetch_text", fake_fetch)

    result = await rss.fetch_subreddit_posts(
        "privacy",
        include_comments=False,
        proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert result.errors == []
    assert captured["proxy_url"] == "http://user-rotate:pass@p.webshare.io:80/"


def test_search_feed_url_encodes_query_and_sort():
    url = _search_feed_url("privacy ai", "new", 5)

    assert url == "https://www.reddit.com/search.rss?q=privacy+ai&sort=new&limit=5"


@pytest.mark.asyncio
async def test_search_reddit_posts_fetches_search_feed(monkeypatch):
    captured = {}

    async def fake_fetch(url: str, **kwargs):
        captured["url"] = url
        captured["proxy_url"] = kwargs.get("proxy_url")
        return rss._FetchResponse(text=POST_FEED, rate_limit=rss.RedditRateLimit(remaining=90.0))

    monkeypatch.setattr(rss, "_fetch_text", fake_fetch)

    result = await rss.search_reddit_posts(
        "privacy ai",
        sort="latest",
        limit=5,
        proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert captured["url"] == "https://www.reddit.com/search.rss?q=privacy+ai&sort=new&limit=5"
    assert captured["proxy_url"] == "http://user-rotate:pass@p.webshare.io:80/"
    assert result.page == "privacy ai"
    assert result.sort == "new"
    assert result.request_count == 1
    assert len(result.posts) == 1
