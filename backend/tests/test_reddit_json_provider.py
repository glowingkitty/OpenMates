# backend/tests/test_reddit_json_provider.py
#
# Unit tests for the Reddit JSON social-media provider.
# These tests use static Reddit JSON samples so URL construction, filtering,
# normalization, and comment parsing stay stable without live network access.

import pytest
import http.client

from backend.shared.providers.reddit import json as reddit_json


LISTING_PAYLOAD = {
    "data": {
        "children": [
            {
                "kind": "t3",
                "data": {
                    "id": "abc123",
                    "subreddit": "privacy",
                    "title": "Privacy-focused chatbot feedback?",
                    "selftext": "I built a chatbot and want feedback.",
                    "author": "example_builder",
                    "permalink": "/r/privacy/comments/abc123/privacyfocused_chatbot_feedback/",
                    "created_utc": 1779364775.0,
                    "score": 42,
                    "ups": 45,
                    "downs": 0,
                    "upvote_ratio": 0.97,
                    "num_comments": 12,
                    "stickied": False,
                    "over_18": False,
                    "is_self": True,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "stickied",
                    "subreddit": "privacy",
                    "title": "Rules",
                    "selftext": "Read the rules.",
                    "author": "mod",
                    "permalink": "/r/privacy/comments/stickied/rules/",
                    "created_utc": 1779364775.0,
                    "score": 100,
                    "ups": 100,
                    "num_comments": 100,
                    "stickied": True,
                    "over_18": False,
                    "is_self": True,
                },
            },
        ]
    }
}

MIXED_FILTER_PAYLOAD = {
    "data": {
        "children": [
            {
                "kind": "t3",
                "data": {
                    "id": "selfpost",
                    "subreddit": "buildinpublic",
                    "title": "Self post with traction",
                    "selftext": "Full text.",
                    "author": "builder",
                    "permalink": "/r/buildinpublic/comments/selfpost/post/",
                    "created_utc": 1779364775.0,
                    "score": 20,
                    "ups": 20,
                    "num_comments": 8,
                    "stickied": False,
                    "over_18": False,
                    "is_self": True,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "linkpost",
                    "subreddit": "buildinpublic",
                    "title": "Link post",
                    "selftext": "",
                    "author": "builder",
                    "permalink": "/r/buildinpublic/comments/linkpost/post/",
                    "created_utc": 1779364775.0,
                    "score": 30,
                    "ups": 30,
                    "num_comments": 3,
                    "stickied": False,
                    "over_18": False,
                    "is_self": False,
                },
            },
            {
                "kind": "t3",
                "data": {
                    "id": "nsfwpost",
                    "subreddit": "buildinpublic",
                    "title": "NSFW post",
                    "selftext": "Filtered.",
                    "author": "builder",
                    "permalink": "/r/buildinpublic/comments/nsfwpost/post/",
                    "created_utc": 1779364775.0,
                    "score": 99,
                    "ups": 99,
                    "num_comments": 99,
                    "stickied": False,
                    "over_18": True,
                    "is_self": True,
                },
            },
        ]
    }
}


DETAIL_PAYLOAD = [
    {"data": {"children": []}},
    {
        "data": {
            "children": [
            {
                "kind": "t1",
                "data": {
                    "id": "comment1",
                        "author": "useful_user",
                        "body": "The hard part is proving what data leaves the device.",
                        "permalink": "/r/privacy/comments/abc123/post/comment1/",
                        "created_utc": 1779364875.0,
                        "score": 7,
                        "ups": 8,
                    "downs": 0,
                },
            },
            {
                "kind": "t1",
                "data": {
                    "id": "removed",
                    "author": "removed_user",
                    "body": "[removed]",
                    "permalink": "/r/privacy/comments/abc123/post/removed/",
                    "created_utc": 1779365075.0,
                    "score": 100,
                    "ups": 100,
                    "downs": 0,
                },
            },
            {
                "kind": "t1",
                "data": {
                    "id": "comment2",
                    "author": "higher_score_user",
                    "body": "This higher scored comment should be first.",
                    "permalink": "/r/privacy/comments/abc123/post/comment2/",
                    "created_utc": 1779364975.0,
                    "score": 20,
                    "ups": 21,
                    "downs": 0,
                },
            }
            ]
        }
    },
]


@pytest.mark.asyncio
async def test_fetch_subreddit_posts_json_normalizes_metrics_and_comments(monkeypatch):
    captured_urls = []

    async def fake_fetch(url: str, **kwargs):
        captured_urls.append(url)
        if "/comments/" in url:
            return reddit_json._FetchJsonResponse(DETAIL_PAYLOAD, reddit_json.RedditRateLimit(remaining=99.0))
        return reddit_json._FetchJsonResponse(LISTING_PAYLOAD, reddit_json.RedditRateLimit(remaining=99.0))

    monkeypatch.setattr(reddit_json, "_fetch_json_with_retry", fake_fetch)

    result = await reddit_json.fetch_subreddit_posts_json(
        "r/privacy",
        sort=reddit_json.RedditListingSort.COMMENTS,
        time_range=reddit_json.RedditTimeRange.WEEK,
        limit=5,
        include_comments=True,
        comments_limit=3,
        proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert captured_urls[0] == "https://www.reddit.com/r/privacy/search.json?q=%2A&restrict_sr=1&sort=comments&t=week&limit=5"
    assert captured_urls[1] == "https://www.reddit.com/comments/abc123.json?sort=top"
    assert result.request_count == 2
    assert len(result.posts) == 1
    assert result.posts[0].title == "Privacy-focused chatbot feedback?"
    assert result.posts[0].score == 42
    assert result.posts[0].like_count == 45
    assert result.posts[0].reply_count == 12
    assert result.posts[0].comments[0].body == "This higher scored comment should be first."
    assert result.posts[0].comments[0].score == 20


@pytest.mark.asyncio
async def test_search_reddit_posts_json_restricts_to_subreddit_and_filters(monkeypatch):
    captured = {}

    async def fake_fetch(url: str, **kwargs):
        captured["url"] = url
        return reddit_json._FetchJsonResponse(LISTING_PAYLOAD, reddit_json.RedditRateLimit(remaining=99.0))

    monkeypatch.setattr(reddit_json, "_fetch_json_with_retry", fake_fetch)

    result = await reddit_json.search_reddit_posts_json(
        "privacy ai",
        page="privacy",
        sort=reddit_json.RedditSearchSort.COMMENTS,
        time_range=reddit_json.RedditTimeRange.MONTH,
        min_comments=10,
        proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert captured["url"] == "https://www.reddit.com/r/privacy/search.json?q=privacy+ai&sort=comments&limit=10&t=month&restrict_sr=1"
    assert len(result.posts) == 1
    assert result.posts[0].id == "abc123"


@pytest.mark.asyncio
async def test_fetch_subreddit_posts_json_builds_top_week_url(monkeypatch):
    captured = {}

    async def fake_fetch(url: str, **kwargs):
        captured["url"] = url
        return reddit_json._FetchJsonResponse(LISTING_PAYLOAD, reddit_json.RedditRateLimit(remaining=99.0))

    monkeypatch.setattr(reddit_json, "_fetch_json_with_retry", fake_fetch)

    result = await reddit_json.fetch_subreddit_posts_json(
        "buildinpublic",
        sort=reddit_json.RedditListingSort.TOP,
        time_range=reddit_json.RedditTimeRange.WEEK,
        limit=5,
        include_comments=False,
        proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert captured["url"] == "https://www.reddit.com/r/buildinpublic/top.json?limit=5&t=week"
    assert result.posts[0].score == 42


@pytest.mark.asyncio
async def test_search_reddit_posts_json_maps_latest_to_new(monkeypatch):
    captured = {}

    async def fake_fetch(url: str, **kwargs):
        captured["url"] = url
        return reddit_json._FetchJsonResponse(LISTING_PAYLOAD, reddit_json.RedditRateLimit(remaining=99.0))

    monkeypatch.setattr(reddit_json, "_fetch_json_with_retry", fake_fetch)

    result = await reddit_json.search_reddit_posts_json(
        "privacy ai",
        sort=reddit_json.RedditSearchSort.LATEST,
        limit=5,
        proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert captured["url"] == "https://www.reddit.com/search.json?q=privacy+ai&sort=new&limit=5"
    assert result.sort == "new"


@pytest.mark.asyncio
async def test_fetch_subreddit_posts_json_applies_post_filters(monkeypatch):
    async def fake_fetch(url: str, **kwargs):
        return reddit_json._FetchJsonResponse(MIXED_FILTER_PAYLOAD, reddit_json.RedditRateLimit(remaining=99.0))

    monkeypatch.setattr(reddit_json, "_fetch_json_with_retry", fake_fetch)

    result = await reddit_json.fetch_subreddit_posts_json(
        "buildinpublic",
        include_comments=False,
        min_comments=5,
        include_link_posts=False,
        exclude_nsfw=True,
        proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert [post.id for post in result.posts] == ["selfpost"]


@pytest.mark.asyncio
async def test_fetch_json_with_retry_retries_incomplete_reads(monkeypatch):
    calls = 0
    sleeps: list[float] = []

    def fake_fetch_sync(url: str, proxy_url: str | None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise http.client.IncompleteRead(b"{", 10)
        return reddit_json._FetchJsonResponse(LISTING_PAYLOAD, reddit_json.RedditRateLimit(remaining=99.0))

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)

    monkeypatch.setattr(reddit_json, "_fetch_json_sync", fake_fetch_sync)
    monkeypatch.setattr(reddit_json.asyncio, "sleep", fake_sleep)

    response = await reddit_json._fetch_json_with_retry("https://www.reddit.com/r/privacy/new.json", proxy_url=None)

    assert calls == 2
    assert sleeps == [reddit_json.DEFAULT_429_RETRY_DELAY_SECONDS]
    assert response.data == LISTING_PAYLOAD
