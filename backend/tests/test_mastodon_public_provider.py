# backend/tests/test_mastodon_public_provider.py
#
# Unit tests for the public Mastodon social-media provider. These tests use
# static Mastodon API payloads so account normalization, status parsing, and
# reply hydration stay stable without depending on live instance availability.
#
# Architecture: docs/architecture/apps/social-media.md

import pytest

from backend.shared.providers.mastodon import public


ACCOUNT = {
    "id": "1",
    "acct": "Gargron",
    "display_name": "Eugen",
    "avatar": "https://cdn.example/avatar.jpg",
    "avatar_static": "https://cdn.example/avatar-static.jpg",
}

STATUS = {
    "id": "123",
    "url": "https://mastodon.social/@Gargron/123",
    "created_at": "2026-05-20T14:26:52.855Z",
    "content": "<p>Hello <strong>Mastodon</strong><br />second line</p>",
    "account": ACCOUNT,
    "replies_count": 2,
    "reblogs_count": 3,
    "favourites_count": 4,
    "media_attachments": [
        {
            "url": "https://cdn.example/full.jpg",
            "preview_url": "https://cdn.example/preview.jpg",
        }
    ],
    "card": {
        "url": "https://example.com/article",
        "title": "Linked article",
    },
}

REPLY = {
    "id": "456",
    "url": "https://mastodon.social/@someone/456",
    "created_at": "2026-05-20T14:30:00.000Z",
    "content": "<p><span>Reply body</span></p>",
    "account": {
        "acct": "someone@example.com",
        "display_name": "Someone",
    },
    "replies_count": 0,
    "reblogs_count": 0,
    "favourites_count": 7,
}


@pytest.mark.asyncio
async def test_fetch_account_posts_normalizes_profile_url_and_replies(monkeypatch):
    calls = []

    async def fake_fetch_json(instance: str, path: str, params: dict[str, str]):
        calls.append((instance, path, params))
        if path == "/api/v1/accounts/lookup":
            return ACCOUNT
        if path == "/api/v1/accounts/1/statuses":
            return [STATUS]
        if path == "/api/v1/statuses/123/context":
            return {"descendants": [REPLY]}
        raise AssertionError(path)

    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.fetch_account_posts("https://mastodon.social/@Gargron", limit=5, include_comments=True)

    assert result.provider == "Mastodon"
    assert result.page == "Gargron@mastodon.social"
    assert result.request_count == 3
    assert calls[0] == ("mastodon.social", "/api/v1/accounts/lookup", {"acct": "Gargron"})
    assert result.posts[0].body == "Hello Mastodon\nsecond line"
    assert result.posts[0].author == "Gargron"
    assert result.posts[0].like_count == 4
    assert result.posts[0].media_url == "https://cdn.example/full.jpg"
    assert result.posts[0].external_url == "https://example.com/article"
    assert result.posts[0].fetched_comment_count == 1
    assert result.posts[0].comments[0].body == "Reply body"
    assert result.posts[0].comments[0].like_count == 7


@pytest.mark.asyncio
async def test_fetch_account_posts_accepts_user_at_instance(monkeypatch):
    calls = []

    async def fake_fetch_json(instance: str, path: str, params: dict[str, str]):
        calls.append((instance, path, params))
        if path == "/api/v1/accounts/lookup":
            return ACCOUNT
        return []

    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.fetch_account_posts("@Gargron@mastodon.social", include_comments=False)

    assert calls[0] == ("mastodon.social", "/api/v1/accounts/lookup", {"acct": "Gargron"})
    assert result.page == "Gargron@mastodon.social"
    assert result.request_count == 2


@pytest.mark.asyncio
async def test_fetch_account_posts_rejects_missing_instance():
    result = await public.fetch_account_posts("Gargron")

    assert result.posts == []
    assert result.errors == ["Mastodon requests require a profile URL or account in user@instance format."]


@pytest.mark.asyncio
async def test_fetch_account_posts_keeps_posts_when_context_fetch_fails(monkeypatch):
    async def fake_fetch_json(instance: str, path: str, params: dict[str, str]):
        if path == "/api/v1/accounts/lookup":
            return ACCOUNT
        if path == "/api/v1/accounts/1/statuses":
            return [STATUS]
        raise RuntimeError("context failed")

    monkeypatch.setattr(public, "_fetch_json", fake_fetch_json)

    result = await public.fetch_account_posts("Gargron@mastodon.social", include_comments=True)

    assert len(result.posts) == 1
    assert result.posts[0].comments == []
    assert "context failed" in result.warnings[0]
