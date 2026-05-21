# backend/tests/test_bluesky_public_provider.py
#
# Unit tests for the public Bluesky social-media provider. These tests use static
# AppView payloads so request routing and normalization stay stable without
# depending on live Bluesky availability or network access.

import pytest

from backend.shared.providers.bluesky import public


POST_VIEW = {
    "uri": "at://did:plc:abc/app.bsky.feed.post/3abcxyz",
    "cid": "cid",
    "author": {
        "did": "did:plc:abc",
        "handle": "openmates.bsky.social",
        "displayName": "OpenMates",
        "avatar": "https://cdn.example/avatar.jpg",
    },
    "record": {
        "text": "Privacy-first AI assistants are finally getting useful.",
        "createdAt": "2026-05-12T14:10:00.000Z",
    },
    "replyCount": 2,
    "repostCount": 3,
    "likeCount": 5,
    "quoteCount": 1,
    "indexedAt": "2026-05-12T14:10:05.000Z",
    "embed": {
        "images": [
            {
                "thumb": "https://cdn.example/thumb.jpg",
                "fullsize": "https://cdn.example/full.jpg",
            }
        ]
    },
}

REPLY_VIEW = {
    "uri": "at://did:plc:def/app.bsky.feed.post/3replyxyz",
    "author": {
        "handle": "reply.example.com",
        "displayName": "Reply Person",
    },
    "record": {
        "text": "This is a useful reply.",
        "createdAt": "2026-05-12T14:20:00.000Z",
    },
    "replyCount": 1,
    "likeCount": 4,
}


@pytest.mark.asyncio
async def test_fetch_author_posts_normalizes_appview_feed(monkeypatch):
    captured = {}

    async def fake_fetch_json(path: str, params: dict[str, str], **kwargs):
        captured["path"] = path
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"cursor": "next", "feed": [{"post": POST_VIEW}]}

    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.fetch_author_posts("@openmates.bsky.social", limit=100, include_comments=False)

    assert captured["path"] == "/xrpc/app.bsky.feed.getAuthorFeed"
    assert captured["params"]["actor"] == "openmates.bsky.social"
    assert captured["params"]["limit"] == "25"
    assert result.provider == "Bluesky"
    assert result.cursor == "next"
    assert result.request_count == 1
    assert len(result.posts) == 1
    assert result.posts[0].author == "openmates.bsky.social"
    assert result.posts[0].url == "https://bsky.app/profile/openmates.bsky.social/post/3abcxyz"
    assert result.posts[0].like_count == 5
    assert result.posts[0].media_url == "https://cdn.example/full.jpg"


@pytest.mark.asyncio
async def test_fetch_author_posts_hydrates_direct_replies(monkeypatch):
    calls = []

    async def fake_fetch_json(path: str, params: dict[str, str], **kwargs):
        calls.append((path, params))
        if path == "/xrpc/app.bsky.feed.getAuthorFeed":
            return {"feed": [{"post": POST_VIEW}]}
        return {"thread": {"post": POST_VIEW, "replies": [{"post": REPLY_VIEW}]}}

    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.fetch_author_posts("openmates.bsky.social", limit=1, include_comments=True, comments_limit=5)

    assert [call[0] for call in calls] == [
        "/xrpc/app.bsky.feed.getAuthorFeed",
        "/xrpc/app.bsky.feed.getPostThread",
    ]
    assert calls[1][1]["uri"] == POST_VIEW["uri"]
    assert result.request_count == 2
    assert result.posts[0].fetched_comment_count == 1
    assert result.posts[0].comments[0].author == "reply.example.com"
    assert result.posts[0].comments[0].body == "This is a useful reply."


@pytest.mark.asyncio
async def test_fetch_author_posts_keeps_posts_when_thread_fetch_fails(monkeypatch):
    async def fake_fetch_json(path: str, params: dict[str, str], **kwargs):
        if path == "/xrpc/app.bsky.feed.getAuthorFeed":
            return {"feed": [{"post": POST_VIEW}]}
        raise RuntimeError("thread failed")

    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.fetch_author_posts("openmates.bsky.social", include_comments=True)

    assert len(result.posts) == 1
    assert result.posts[0].comments == []
    assert "thread failed" in result.warnings[0]


@pytest.mark.asyncio
async def test_search_posts_uses_public_search_endpoint_with_author_filter(monkeypatch):
    captured = {}

    async def fake_fetch_json(path: str, params: dict[str, str], **kwargs):
        captured["path"] = path
        captured["params"] = params
        captured["kwargs"] = kwargs
        return {"posts": [POST_VIEW]}

    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.search_posts("privacy ai", sort="top", limit=5, author="@openmates.bsky.social")

    assert captured["path"] == "/xrpc/app.bsky.feed.searchPosts"
    assert captured["params"] == {
        "q": "privacy ai",
        "sort": "top",
        "limit": "5",
        "author": "openmates.bsky.social",
    }
    assert result.page == "privacy ai"
    assert result.sort == "top"
    assert result.posts[0].body == "Privacy-first AI assistants are finally getting useful."


@pytest.mark.asyncio
async def test_search_posts_uses_auth_when_app_password_env_is_configured(monkeypatch):
    captured = {}

    async def fake_access_token(secrets_manager=None):
        return "jwt-token"

    async def fake_fetch_json(path: str, params: dict[str, str], **kwargs):
        captured["path"] = path
        captured["kwargs"] = kwargs
        return {"posts": [POST_VIEW]}

    monkeypatch.setattr(public, "_optional_access_token", fake_access_token)
    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.search_posts("privacy ai")

    assert captured["path"] == "/xrpc/app.bsky.feed.searchPosts"
    assert captured["kwargs"]["base_url"] == public.BLUESKY_PDS_BASE_URL
    assert captured["kwargs"]["access_token"] == "jwt-token"
    assert len(result.posts) == 1


@pytest.mark.asyncio
async def test_search_posts_requires_query():
    result = await public.search_posts("   ")

    assert result.request_count == 0
    assert result.posts == []
    assert result.errors == ["Bluesky topic search requires a query."]


@pytest.mark.asyncio
async def test_search_posts_warns_when_unauthenticated_search_fails(monkeypatch):
    async def fake_access_token(secrets_manager=None):
        return None

    async def fake_fetch_json(path: str, params: dict[str, str], **kwargs):
        raise RuntimeError("HTTP 403: Forbidden")

    monkeypatch.setattr(public, "_optional_access_token", fake_access_token)
    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.search_posts("privacy ai")

    assert result.posts == []
    assert "HTTP 403" in result.errors[0]
    assert "SECRET__BLUESKY__APP_PASSWORD" in result.warnings[0]


@pytest.mark.asyncio
async def test_optional_access_token_prefers_vault_secrets(monkeypatch):
    class FakeSecretsManager:
        async def get_secret(self, secret_path: str, secret_key: str):
            assert secret_path == public.BLUESKY_VAULT_PATH
            return {
                public.IDENTIFIER_VAULT_KEY: "openmates.bsky.social",
                public.APP_PASSWORD_VAULT_KEY: "app-password",
            }[secret_key]

    captured = {}

    def fake_create_session(identifier: str, app_password: str):
        captured["identifier"] = identifier
        captured["app_password"] = app_password
        return "jwt-token"

    async def fake_to_thread(func, *args):
        return func(*args)

    monkeypatch.setattr(public, "_create_session_sync", fake_create_session)
    monkeypatch.setattr(public.asyncio, "to_thread", fake_to_thread)

    token = await public._optional_access_token(secrets_manager=FakeSecretsManager())

    assert token == "jwt-token"
    assert captured == {"identifier": "openmates.bsky.social", "app_password": "app-password"}
