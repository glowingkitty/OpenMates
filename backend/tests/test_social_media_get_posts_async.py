# backend/tests/test_social_media_get_posts_async.py
#
# Unit tests for the Social Media get-posts async dispatch path.
# These tests keep the long-running collection flow covered without requiring
# a live Celery worker or network access to Reddit/Bluesky.

import sys
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.apps.social_media import collection  # noqa: E402


@pytest.fixture
def get_posts_skill_class(monkeypatch):
    celery_stub = ModuleType("celery")
    celery_stub.Celery = object
    monkeypatch.setitem(sys.modules, "celery", celery_stub)

    from backend.apps.social_media.skills.get_posts import GetPostsSkill

    return GetPostsSkill


def test_get_posts_request_rejects_too_many_comments():
    with pytest.raises(ValidationError):
        collection.GetPostsRequestItem(platform="reddit", page="ClaudeCode", comments_limit=6)


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
async def test_get_posts_skill_dispatches_celery_with_placeholder_embed(get_posts_skill_class):
    celery = _FakeCeleryProducer()
    skill = get_posts_skill_class(
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
async def test_get_posts_skill_dispatches_one_task_per_placeholder_embed(get_posts_skill_class):
    celery = _FakeCeleryProducer()
    skill = get_posts_skill_class(
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

    async def fake_fetch_subreddit_posts_json(*args, **kwargs):
        captured["reddit_proxy_url"] = kwargs.get("proxy_url")
        captured["reddit_sort"] = kwargs.get("sort")
        return SimpleNamespace(
            platform="reddit",
            page="ClaudeCode",
            sort="comments",
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
        captured["bluesky_kwargs"] = kwargs
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

    async def fake_fetch_account_posts(*args, **kwargs):
        captured["mastodon_kwargs"] = kwargs
        return SimpleNamespace(
            platform="mastodon",
            page="Gargron@mastodon.social",
            sort="profile",
            posts=[],
            provider="mastodon_public",
            request_count=3,
            warnings=[],
            errors=[],
        )

    monkeypatch.setattr(collection, "fetch_subreddit_posts_json", fake_fetch_subreddit_posts_json)
    monkeypatch.setattr(collection, "fetch_author_posts", fake_fetch_author_posts)
    monkeypatch.setattr(collection, "fetch_account_posts", fake_fetch_account_posts)

    results = await collection.collect_posts(
        [
            {"platform": "reddit", "page": "ClaudeCode", "sort": "comments", "time_range": "week", "limit": 5},
            {"platform": "bluesky", "page": "openmates.bsky.social", "limit": 5},
            {"platform": "mastodon", "page": "Gargron@mastodon.social", "limit": 5},
            {"platform": "unknown", "page": "example"},
        ],
        reddit_proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert [item.platform for item in results] == ["reddit", "bluesky", "mastodon", "unknown"]
    assert results[0].provider == "reddit_json"
    assert results[0].request_count == 2
    assert captured["reddit_proxy_url"] == "http://user-rotate:pass@p.webshare.io:80/"
    assert captured["reddit_sort"] == collection.RedditListingSort.COMMENTS
    assert results[1].provider == "bluesky_public"
    assert captured["bluesky_kwargs"]["include_comments"] is True
    assert results[2].provider == "mastodon_public"
    assert captured["mastodon_kwargs"]["include_comments"] is True
    assert results[3].errors == ["Unsupported social platform: unknown"]


@pytest.mark.asyncio
async def test_collect_posts_rejects_reddit_without_webshare_proxy(monkeypatch):
    async def unexpected_fetch_subreddit_posts_json(*args, **kwargs):
        raise AssertionError("Reddit JSON must not be fetched without Webshare proxy")

    monkeypatch.setattr(collection, "fetch_subreddit_posts_json", unexpected_fetch_subreddit_posts_json)

    results = await collection.collect_posts([{"platform": "reddit", "page": "ClaudeCode", "limit": 5}])

    assert results[0].posts == []
    assert results[0].provider == "reddit_json"
    assert results[0].errors == ["Reddit JSON requests require Webshare proxy credentials."]


@pytest.mark.asyncio
async def test_collect_posts_falls_back_to_rss_when_json_fails(monkeypatch):
    async def fake_fetch_subreddit_posts_json(*args, **kwargs):
        return SimpleNamespace(
            platform="reddit",
            page="ClaudeCode",
            sort="new",
            posts=[],
            request_count=1,
            rate_limit=None,
            rate_limited=False,
            next_retry_after_seconds=None,
            comments_skipped_count=0,
            warnings=[],
            errors=["json failed"],
        )

    async def fake_fetch_subreddit_posts(*args, **kwargs):
        return SimpleNamespace(
            platform="reddit",
            page="ClaudeCode",
            sort="new",
            posts=[],
            request_count=1,
            rate_limit=None,
            rate_limited=False,
            next_retry_after_seconds=None,
            comments_skipped_count=0,
            warnings=[],
            errors=[],
        )

    monkeypatch.setattr(collection, "fetch_subreddit_posts_json", fake_fetch_subreddit_posts_json)
    monkeypatch.setattr(collection, "fetch_subreddit_posts", fake_fetch_subreddit_posts)

    results = await collection.collect_posts(
        [{"platform": "reddit", "page": "ClaudeCode", "limit": 5}],
        reddit_proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert results[0].provider == "reddit_rss"
    assert "Reddit JSON failed; fell back to Reddit RSS." in results[0].warnings
    assert "json failed" in results[0].warnings
    assert results[0].errors == []
