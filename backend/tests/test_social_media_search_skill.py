# backend/tests/test_social_media_search_skill.py
#
# Unit tests for Social Media search dispatch and provider routing.
# These tests keep topic search async behavior covered without a live worker or
# network access to Reddit/Bluesky.

import sys
from types import ModuleType

import pytest

celery_stub = ModuleType("celery")
celery_stub.Celery = object
sys.modules.setdefault("celery", celery_stub)

from backend.apps.social_media import search_collection  # noqa: E402
from backend.apps.social_media.skills.search import SearchSkill  # noqa: E402
from backend.shared.providers.bluesky.public import BlueskyPost, BlueskyResult  # noqa: E402
from backend.shared.providers.reddit.rss import RedditRssPost, RedditRssResult  # noqa: E402


class DummyApp:
    secrets_manager = None


class FakeSecretsManager:
    pass


class _FakeTaskSignature:
    def __init__(self, task_id):
        self.id = task_id


class _FakeCeleryProducer:
    def __init__(self):
        self.sent = []

    def send_task(self, name, kwargs, queue):
        self.sent.append({"name": name, "kwargs": kwargs, "queue": queue})
        return _FakeTaskSignature(f"task-{len(self.sent)}")


def make_skill(celery=None) -> SearchSkill:
    return SearchSkill(
        app=DummyApp(),
        app_id="social_media",
        skill_id="search",
        skill_name="Search",
        skill_description="Search social media posts.",
        celery_producer=celery,
    )


@pytest.mark.asyncio
async def test_search_skill_dispatches_celery_with_placeholder_embed():
    celery = _FakeCeleryProducer()
    skill = make_skill(celery)
    skill._current_chat_id = "chat-1"
    skill._current_message_id = "message-1"

    response = await skill.execute(
        requests=[{"platform": "all", "query": "privacy ai", "sort": "latest", "limit": 5}],
        user_id="user-1",
        placeholder_embed_ids=["embed-123"],
        user_vault_key_id="vault-key-1",
    )

    assert response.status == "processing"
    assert response.task_id == "task-1"
    assert response.embed_id == "embed-123"
    assert celery.sent[0]["name"] == "apps.social_media.tasks.skill_search"
    assert celery.sent[0]["queue"] == "app_social_media"
    arguments = celery.sent[0]["kwargs"]["arguments"]
    assert arguments["embed_id"] == "embed-123"
    assert arguments["chat_id"] == "chat-1"
    assert arguments["message_id"] == "message-1"
    assert arguments["user_vault_key_id"] == "vault-key-1"
    assert arguments["requests"][0]["query"] == "privacy ai"


@pytest.mark.asyncio
async def test_collect_search_results_defaults_to_all_supported_platforms(monkeypatch):
    captured = {}

    async def fake_search_posts(query: str, **kwargs):
        captured["bluesky_query"] = query
        captured["bluesky_kwargs"] = kwargs
        return BlueskyResult(
            page=query,
            sort="top",
            request_count=1,
            posts=[
                BlueskyPost(
                    id="at://did:plc:abc/app.bsky.feed.post/3abcxyz",
                    page=query,
                    title="A useful post",
                    body="A useful post about privacy AI.",
                    author="openmates.bsky.social",
                    url="https://bsky.app/profile/openmates.bsky.social/post/3abcxyz",
                )
            ],
        )

    async def fake_search_reddit_posts(query: str, **kwargs):
        captured["reddit_query"] = query
        captured["reddit_kwargs"] = kwargs
        return RedditRssResult(
            page=query,
            sort="new",
            request_count=1,
            posts=[
                RedditRssPost(
                    id="abc123",
                    page=query,
                    title="Reddit post",
                    body="A Reddit post about privacy AI.",
                    author="/u/example",
                    url="https://www.reddit.com/r/privacy/comments/abc123/post/",
                )
            ],
        )

    monkeypatch.setattr(search_collection, "search_posts", fake_search_posts)
    monkeypatch.setattr(search_collection, "search_reddit_posts", fake_search_reddit_posts)

    results = await search_collection.collect_search_results(
        [{"query": "privacy ai", "sort": "top", "limit": 5}],
        secrets_manager=FakeSecretsManager(),
        reddit_proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert [result.platform for result in results] == ["bluesky", "reddit"]
    assert captured["bluesky_query"] == "privacy ai"
    assert captured["bluesky_kwargs"]["sort"] == "top"
    assert captured["bluesky_kwargs"]["limit"] == 5
    assert isinstance(captured["bluesky_kwargs"]["secrets_manager"], FakeSecretsManager)
    assert captured["reddit_query"] == "privacy ai"
    assert captured["reddit_kwargs"]["proxy_url"] == "http://user-rotate:pass@p.webshare.io:80/"
    assert results[0].posts[0].author == "openmates.bsky.social"
    assert results[1].posts[0].author == "/u/example"


@pytest.mark.asyncio
async def test_collect_search_results_rejects_unsupported_platform():
    results = await search_collection.collect_search_results([{"platform": "mastodon", "query": "privacy ai"}])

    assert results[0].posts == []
    assert results[0].errors == ["Unsupported social search platform: mastodon"]
