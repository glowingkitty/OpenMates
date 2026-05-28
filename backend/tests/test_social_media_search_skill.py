# backend/tests/test_social_media_search_skill.py
#
# Unit tests for Social Media search dispatch and provider routing.
# These tests keep topic search async behavior covered without a live worker or
# network access to Reddit/Bluesky.

import sys
from types import ModuleType

import pytest
from pydantic import ValidationError

from backend.apps.social_media import search_collection  # noqa: E402
from backend.shared.providers.bluesky.public import BlueskyPost, BlueskyResult  # noqa: E402
from backend.shared.providers.mastodon.public import MastodonPost, MastodonResult  # noqa: E402
from backend.shared.providers.reddit.json import RedditSearchSort  # noqa: E402
from backend.shared.providers.reddit.rss import RedditRssPost, RedditRssResult  # noqa: E402


@pytest.fixture
def search_skill_class(monkeypatch):
    celery_stub = ModuleType("celery")
    celery_stub.Celery = object
    monkeypatch.setitem(sys.modules, "celery", celery_stub)

    from backend.apps.social_media.skills.search import SearchSkill

    return SearchSkill


class DummyApp:
    secrets_manager = None


class FakeSecretsManager:
    pass


def test_search_request_rejects_too_many_comments():
    with pytest.raises(ValidationError):
        search_collection.SearchRequestItem(platform="reddit", query="privacy ai", comments_limit=6)


class _FakeTaskSignature:
    def __init__(self, task_id):
        self.id = task_id


class _FakeCeleryProducer:
    def __init__(self):
        self.sent = []

    def send_task(self, name, kwargs, queue):
        self.sent.append({"name": name, "kwargs": kwargs, "queue": queue})
        return _FakeTaskSignature(f"task-{len(self.sent)}")


def make_skill(search_skill_class, celery=None):
    return search_skill_class(
        app=DummyApp(),
        app_id="social_media",
        skill_id="search",
        skill_name="Search",
        skill_description="Search social media posts.",
        celery_producer=celery,
    )


@pytest.mark.asyncio
async def test_search_skill_dispatches_celery_with_placeholder_embed(search_skill_class):
    celery = _FakeCeleryProducer()
    skill = make_skill(search_skill_class, celery)
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
    assert arguments["external_request"] is False
    assert arguments["requests"][0]["query"] == "privacy ai"


@pytest.mark.asyncio
async def test_search_skill_marks_external_request_for_rest_dispatch(search_skill_class):
    celery = _FakeCeleryProducer()
    skill = make_skill(search_skill_class, celery)

    await skill.execute(
        requests=[{"platform": "bluesky", "query": "openmates", "limit": 1}],
        user_id="user-1",
        external_request=True,
    )

    assert celery.sent[0]["kwargs"]["arguments"]["external_request"] is True


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

    async def fake_search_reddit_posts_json(query: str, **kwargs):
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

    async def fake_search_mastodon_posts(query: str, **kwargs):
        captured["mastodon_query"] = query
        captured["mastodon_kwargs"] = kwargs
        return MastodonResult(
            page="mastodon.social",
            sort="latest",
            request_count=1,
            posts=[
                MastodonPost(
                    id="mastodon-123",
                    page="mastodon.social",
                    title="Mastodon post",
                    body="A Mastodon post about privacy AI.",
                    author="openmates@mastodon.social",
                    url="https://mastodon.social/@openmates/123",
                )
            ],
        )

    monkeypatch.setattr(search_collection, "search_posts", fake_search_posts)
    monkeypatch.setattr(search_collection, "search_reddit_posts_json", fake_search_reddit_posts_json)
    monkeypatch.setattr(search_collection, "search_mastodon_posts", fake_search_mastodon_posts)

    results = await search_collection.collect_search_results(
        [{"query": "privacy ai", "page": "privacy", "sort": "comments", "time_range": "week", "limit": 5}],
        secrets_manager=FakeSecretsManager(),
        reddit_proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert [result.platform for result in results] == ["bluesky", "mastodon", "reddit"]
    assert captured["bluesky_query"] == "privacy ai"
    assert captured["bluesky_kwargs"]["sort"] == "comments"
    assert captured["bluesky_kwargs"]["limit"] == 5
    assert isinstance(captured["bluesky_kwargs"]["secrets_manager"], FakeSecretsManager)
    assert captured["mastodon_query"] == "privacy ai"
    assert captured["mastodon_kwargs"]["instances"] == ["privacy"]
    assert captured["mastodon_kwargs"]["limit"] == 5
    assert captured["reddit_query"] == "privacy ai"
    assert captured["reddit_kwargs"]["proxy_url"] == "http://user-rotate:pass@p.webshare.io:80/"
    assert captured["reddit_kwargs"]["page"] == "privacy"
    assert captured["reddit_kwargs"]["sort"] == RedditSearchSort.COMMENTS
    assert results[0].posts[0].author == "openmates.bsky.social"
    assert results[1].posts[0].author == "openmates@mastodon.social"
    assert results[2].posts[0].author == "/u/example"


@pytest.mark.asyncio
async def test_collect_search_results_falls_back_to_rss_when_json_fails(monkeypatch):
    async def fake_search_reddit_posts_json(query: str, **kwargs):
        return RedditRssResult(page=query, sort="new", request_count=1, errors=["json failed"])

    async def fake_search_reddit_posts(query: str, **kwargs):
        return RedditRssResult(
            page=query,
            sort="new",
            request_count=1,
            posts=[
                RedditRssPost(
                    id="abc123",
                    page=query,
                    title="Fallback post",
                    body="Fallback body.",
                    author="/u/example",
                    url="https://www.reddit.com/r/privacy/comments/abc123/post/",
                )
            ],
        )

    monkeypatch.setattr(search_collection, "search_reddit_posts_json", fake_search_reddit_posts_json)
    monkeypatch.setattr(search_collection, "search_reddit_posts", fake_search_reddit_posts)

    results = await search_collection.collect_search_results(
        [{"platform": "reddit", "query": "privacy ai", "sort": "new", "limit": 5}],
        reddit_proxy_url="http://user-rotate:pass@p.webshare.io:80/",
    )

    assert results[0].provider == "Reddit"
    assert results[0].posts[0].title == "Fallback post"
    assert "Reddit temporarily used a fallback source." in results[0].warnings
    assert "json failed" in results[0].warnings
    assert results[0].errors == []


@pytest.mark.asyncio
async def test_collect_search_results_searches_mastodon_with_extra_instances(monkeypatch):
    captured = {}

    async def fake_search_mastodon_posts(query: str, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return MastodonResult(
            page="mastodon.social, fosstodon.org",
            sort="latest",
            request_count=2,
            posts=[
                MastodonPost(
                    id="mastodon-123",
                    page="mastodon.social",
                    title="Mastodon post",
                    body="A Mastodon post about privacy AI.",
                    author="openmates@mastodon.social",
                    url="https://mastodon.social/@openmates/123",
                )
            ],
        )

    monkeypatch.setattr(search_collection, "search_mastodon_posts", fake_search_mastodon_posts)

    results = await search_collection.collect_search_results(
        [
            {
                "platform": "mastodon",
                "query": "privacy ai",
                "page": "fosstodon.org",
                "mastodon_instances": ["hachyderm.io"],
                "sort": "top",
                "limit": 5,
                "include_comments": True,
                "comments_limit": 2,
            }
        ]
    )

    assert captured["query"] == "privacy ai"
    assert captured["kwargs"] == {
        "instances": ["fosstodon.org", "hachyderm.io"],
        "limit": 5,
        "include_comments": True,
        "comments_limit": 2,
    }
    assert results[0].provider == "Mastodon"
    assert results[0].posts[0].platform == "mastodon"
    assert "Mastodon public search returns instance-ranked recent results" in results[0].warnings[0]
    assert results[0].errors == []


@pytest.mark.asyncio
async def test_collect_search_results_rejects_unsupported_platform():
    results = await search_collection.collect_search_results([{"platform": "threads", "query": "privacy ai"}])

    assert results[0].posts == []
    assert results[0].errors == ["Unsupported social search platform: threads"]


@pytest.mark.asyncio
async def test_collect_search_results_soft_skips_unavailable_reddit_for_all_search():
    results = await search_collection.collect_search_results([{"platform": "all", "query": "privacy ai", "limit": 5}])

    reddit_result = next(result for result in results if result.platform == "reddit")
    assert reddit_result.posts == []
    assert reddit_result.errors == []
    assert reddit_result.warnings == [search_collection.REDDIT_PROXY_REQUIRED_WARNING]


@pytest.mark.asyncio
async def test_collect_search_results_hides_raw_bluesky_auth_errors(monkeypatch):
    async def fake_search_posts(query: str, **kwargs):
        return BlueskyResult(
            page=query,
            sort="latest",
            request_count=0,
            warnings=["Bluesky topic search may require authentication. Configure SECRET__BLUESKY__IDENTIFIER."],
            errors=["Could not search Bluesky posts for privacy ai: HTTP 403: <html>Forbidden</html>"],
        )

    monkeypatch.setattr(search_collection, "search_posts", fake_search_posts)

    explicit = await search_collection.collect_search_results([{"platform": "bluesky", "query": "privacy ai", "limit": 5}])
    assert explicit[0].warnings == [search_collection.BLUESKY_AUTH_REQUIRED_WARNING]
    assert explicit[0].errors == [search_collection.BLUESKY_AUTH_REQUIRED_WARNING]

    multi = await search_collection.collect_search_results([{"platform": "all", "query": "privacy ai", "limit": 5}])
    bluesky_result = next(result for result in multi if result.platform == "bluesky")
    assert bluesky_result.errors == []
    assert search_collection.BLUESKY_AUTH_REQUIRED_WARNING in bluesky_result.warnings
