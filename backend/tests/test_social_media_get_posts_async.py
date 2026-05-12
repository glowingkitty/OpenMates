# backend/tests/test_social_media_get_posts_async.py
#
# Unit tests for the Social Media get-posts async dispatch path.
# These tests keep the long-running collection flow covered without requiring
# a live Celery worker or network access to Reddit/Bluesky.

import sys
from types import ModuleType, SimpleNamespace

import pytest

celery_stub = ModuleType("celery")
celery_stub.Celery = object
sys.modules.setdefault("celery", celery_stub)

from backend.apps.social_media import collection  # noqa: E402
from backend.apps.social_media.skills.get_posts import GetPostsSkill  # noqa: E402


class _FakeTaskSignature:
    def __init__(self, task_id):
        self.id = task_id


class _FakeCeleryProducer:
    def __init__(self):
        self.sent = []

    def send_task(self, name, kwargs, queue):
        self.sent.append({"name": name, "kwargs": kwargs, "queue": queue})
        return _FakeTaskSignature(f"task-{len(self.sent)}")


@pytest.mark.asyncio
async def test_get_posts_skill_dispatches_celery_with_placeholder_embed():
    celery = _FakeCeleryProducer()
    skill = GetPostsSkill(
        app=None,
        app_id="social_media",
        skill_id="get-posts",
        skill_name="Get posts",
        skill_description="Fetch posts",
        celery_producer=celery,
    )
    skill._current_chat_id = "chat-1"
    skill._current_message_id = "message-1"

    response = await skill.execute(
        [{"platform": "reddit", "page": "ClaudeCode", "limit": 5}],
        user_id="user-1",
        placeholder_embed_ids=["embed-123"],
        user_vault_key_id="vault-key-1",
    )

    assert response.status == "processing"
    assert response.task_id == "task-1"
    assert response.embed_id == "embed-123"
    assert celery.sent[0]["name"] == "apps.social_media.tasks.skill_get-posts"
    assert celery.sent[0]["queue"] == "app_social_media"
    arguments = celery.sent[0]["kwargs"]["arguments"]
    assert arguments["embed_id"] == "embed-123"
    assert arguments["chat_id"] == "chat-1"
    assert arguments["message_id"] == "message-1"
    assert arguments["user_vault_key_id"] == "vault-key-1"
    assert arguments["requests"][0]["page"] == "ClaudeCode"


@pytest.mark.asyncio
async def test_get_posts_skill_dispatches_one_task_per_placeholder_embed():
    celery = _FakeCeleryProducer()
    skill = GetPostsSkill(
        app=None,
        app_id="social_media",
        skill_id="get-posts",
        skill_name="Get posts",
        skill_description="Fetch posts",
        celery_producer=celery,
    )
    skill._current_chat_id = "chat-1"
    skill._current_message_id = "message-1"

    response = await skill.execute(
        [
            {"platform": "reddit", "page": "ClaudeCode", "limit": 5},
            {"platform": "bluesky", "page": "openmates.bsky.social", "limit": 5},
        ],
        user_id="user-1",
        placeholder_embed_ids=["embed-1", "embed-2"],
    )

    assert response.status == "processing"
    assert response.task_ids == ["task-1", "task-2"]
    assert response.embed_ids == ["embed-1", "embed-2"]
    assert [sent["kwargs"]["arguments"]["embed_id"] for sent in celery.sent] == ["embed-1", "embed-2"]
    assert [sent["kwargs"]["arguments"]["requests"][0]["platform"] for sent in celery.sent] == ["reddit", "bluesky"]


@pytest.mark.asyncio
async def test_collect_posts_normalizes_supported_and_unsupported_platforms(monkeypatch):
    captured = {}

    async def fake_fetch_subreddit_posts(*args, **kwargs):
        captured["reddit_proxy_url"] = kwargs.get("proxy_url")
        return SimpleNamespace(
            platform="reddit",
            page="ClaudeCode",
            sort="new",
            posts=[],
            request_count=2,
            rate_limit=None,
            rate_limited=False,
            next_retry_after_seconds=None,
            comments_skipped_count=0,
            warnings=[],
            errors=[],
        )

    async def fake_fetch_author_posts(*args, **kwargs):
        return SimpleNamespace(
            platform="bluesky",
            page="openmates.bsky.social",
            sort="new",
            posts=[],
            provider="bluesky_public",
            request_count=1,
            warnings=[],
            errors=[],
        )

    monkeypatch.setattr(collection, "fetch_subreddit_posts", fake_fetch_subreddit_posts)
    monkeypatch.setattr(collection, "fetch_author_posts", fake_fetch_author_posts)

    results = await collection.collect_posts(
        [
            {"platform": "reddit", "page": "ClaudeCode", "limit": 5},
            {"platform": "bluesky", "page": "openmates.bsky.social", "limit": 5},
            {"platform": "unknown", "page": "example"},
        ],
        reddit_proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert [item.platform for item in results] == ["reddit", "bluesky", "unknown"]
    assert results[0].provider == "reddit_rss"
    assert results[0].request_count == 2
    assert captured["reddit_proxy_url"] == "http://user-rotate:pass@p.webshare.io:80/"
    assert results[1].provider == "bluesky_public"
    assert results[2].errors == ["Unsupported social platform: unknown"]


@pytest.mark.asyncio
async def test_collect_posts_rejects_reddit_without_webshare_proxy(monkeypatch):
    async def unexpected_fetch_subreddit_posts(*args, **kwargs):
        raise AssertionError("Reddit RSS must not be fetched without Webshare proxy")

    monkeypatch.setattr(collection, "fetch_subreddit_posts", unexpected_fetch_subreddit_posts)

    results = await collection.collect_posts([{"platform": "reddit", "page": "ClaudeCode", "limit": 5}])

    assert results[0].posts == []
    assert results[0].provider == "reddit_rss"
    assert results[0].errors == ["Reddit RSS requests require Webshare proxy credentials."]
