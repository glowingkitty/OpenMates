# backend/tests/test_social_media_search_skill.py
#
# Unit tests for Social Media search dispatch and provider routing.
# These tests keep topic search async behavior covered without a live worker or
# network access to social platforms.

import sys
from types import ModuleType

import pytest
from pydantic import ValidationError

from backend.apps.social_media import search_collection  # noqa: E402
from backend.shared.providers.bluesky.public import BlueskyResult  # noqa: E402
from backend.shared.providers.mastodon.public import MastodonPost, MastodonResult  # noqa: E402


@pytest.fixture
def search_skill_class(monkeypatch):
    celery_stub = ModuleType("celery")
    celery_stub.Celery = object
    monkeypatch.setitem(sys.modules, "celery", celery_stub)

    from backend.apps.social_media.skills.search import SearchSkill
    from backend.apps.social_media.skills import search as search_module

    async def fake_dispatch(*, app_id, skill_id, arguments, celery_producer):
        sent = celery_producer.send_task(
            f"apps.{app_id}.tasks.skill_{skill_id}",
            kwargs={"arguments": arguments}, queue=f"app_{app_id}",
        )
        return sent.id

    monkeypatch.setattr(search_module, "execute_skill_via_celery", fake_dispatch)

    return SearchSkill


class DummyApp:
    secrets_manager = None


class FakeSecretsManager:
    pass


# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
def test_search_request_rejects_too_many_comments():
    with pytest.raises(ValidationError):
        search_collection.SearchRequestItem(platform="bluesky", query="privacy ai", comments_limit=6)


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
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
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
# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
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
# contract-test: supporting surface=rest_api assertions=app-skills.assistant.same-turn-completion,app-skills.execution.registered-validated
async def test_search_partial_dispatch_reports_only_accepted_jobs(search_skill_class):
    class FailingProducer(_FakeCeleryProducer):
        def send_task(self, name, kwargs, queue):
            if self.sent:
                raise RuntimeError("transport failed")
            return super().send_task(name, kwargs, queue)

    celery = FailingProducer()
    skill = make_skill(search_skill_class, celery)
    skill._current_chat_id = "chat-1"
    skill._current_message_id = "message-1"
    response = await skill.execute(
        requests=[
            {"platform": "bluesky", "query": "first", "limit": 1},
            {"platform": "bluesky", "query": "second", "limit": 1},
        ],
        user_id="user-1", placeholder_embed_ids=["embed-1", "embed-2"],
        same_turn_batch_id="logical:1",
    )
    assert response.status == "processing"
    assert response.task_ids == ["task-1"]
    assert response.embed_ids == ["embed-1"]
    assert response.error == "Some social media searches could not be dispatched"
    assert len(celery.sent) == 1
    assert celery.sent[0]["kwargs"]["arguments"]["same_turn_batch_id"] == "logical:1"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.surface.semantic-parity
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
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated
async def test_collect_search_results_rejects_unsupported_platform():
    results = await search_collection.collect_search_results([{"platform": "threads", "query": "privacy ai"}])

    assert results[0].posts == []
    assert results[0].errors == ["Unsupported social search platform: threads"]


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=app-skills.execution.registered-validated,app-skills.surface.semantic-parity
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
