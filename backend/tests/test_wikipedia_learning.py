# contract-test-file: supporting surface=rest_api assertions=wikipedia-mentions.links.name-consistency,wikipedia-mentions.learning.public-cache,wikipedia-mentions.learning.chat-and-memory
"""Public bundle identity, output validation, shared caching and failure isolation."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from backend.tests.test_wikipedia_mentions import _import_wikipedia_proxy
from backend.shared.providers.wikipedia.learning import (
    LEARNING_CACHE_TTL,
    learning_cache_key,
    learning_messages,
    public_article,
    validate_learning_output,
    wiki_label_matches,
)


@pytest.mark.parametrize(
    "label,title,expected",
    [
        ("Ada Lovelace", "Ada_Lovelace", True),
        ("ada lovelace", "Ada Lovelace", True),
        ("Mercury", "Mercury (planet)", True),
        ("Fraction", "Mathematics", False),
        ("Einstein", "Albert Einstein", False),
        ("Python", "Computer science", False),
        ("Apple", "Apple Inc.", False),
        ("", "Ada Lovelace", False),
    ],
)
# contract-test: supporting surface=rest_api assertions=wikipedia-mentions.links.name-consistency
def test_clicked_name_matches_article(label, title, expected):
    assert wiki_label_matches(label, title) is expected


def article(**extra):
    return public_article(
        {
            "canonical_title": "Ada Lovelace",
            "description": "Mathematician",
            "extract": "Ada Lovelace wrote notes about the Analytical Engine.",
            **extra,
        },
        "en",
    )


# contract-test: supporting surface=rest_api assertions=wikipedia-mentions.learning.public-cache
def test_public_input_allowlist_and_content_sensitive_cache():
    a = article(
        chat="private chat",
        user_id="private user",
        age_group="13_15",
        memories=["private"],
    )
    serialized = json.dumps(learning_messages(a))
    assert "private" not in serialized
    assert "user_id" not in serialized
    assert learning_cache_key(a) == learning_cache_key(article())
    assert learning_cache_key(a) != learning_cache_key(
        article(extract="Updated public summary")
    )
    assert learning_cache_key(a) != learning_cache_key({**a, "language": "de"})


@pytest.mark.parametrize(
    "bad",
    [
        {"questions": ["one"], "related_titles": ["a", "b", "c"]},
        {"questions": ["one", "one", "two"], "related_titles": ["a", "b", "c"]},
        {
            "questions": ["one", "two", "https://bad.example"],
            "related_titles": ["a", "b", "c"],
        },
        {
            "questions": ["one", "two", "three"],
            "related_titles": ["a", "b", "c"],
            "chat": "private",
        },
    ],
)
# contract-test: supporting surface=rest_api assertions=wikipedia-mentions.learning.public-cache
def test_malformed_provider_output_rejected(bad):
    with pytest.raises(ValueError):
        validate_learning_output(bad)


class Redis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def get(self, k):
        return self.values.get(k)

    async def set(self, k, v, **opts):
        if opts.get("nx") and k in self.values:
            return False
        self.values[k] = v
        return True

    async def setex(self, k, ttl, v):
        self.values[k] = v
        self.ttls[k] = ttl

    async def incr(self, k):
        self.values[k] = int(self.values.get(k, 0)) + 1
        return self.values[k]

    async def expire(self, *args):
        pass

    async def exists(self, k):
        return k in self.values

    async def eval(self, script, num, k, token):
        if self.values.get(k) == token:
            self.values.pop(k, None)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=wikipedia-mentions.learning.public-cache
async def test_two_accounts_share_one_generation(monkeypatch):
    proxy = _import_wikipedia_proxy()
    redis = Redis()
    monkeypatch.setattr(proxy, "_cache_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(proxy, "_reserve_shared_wikipedia_budget", AsyncMock())
    monkeypatch.setattr(
        "backend.apps.ai.processing.wikipedia_context.build_wikipedia_reference_context",
        AsyncMock(side_effect=lambda refs, **kw: refs),
    )
    calls = []

    async def generate(a, key, provider):
        calls.append((a, key, provider))
        await asyncio.sleep(0.01)
        return {
            "questions": [
                "Explain Ada Lovelace.",
                "Compare Ada Lovelace and Babbage.",
                "Test my understanding of Ada Lovelace.",
            ],
            "related_titles": ["Analytical Engine", "Charles Babbage", "Algorithm"],
        }

    monkeypatch.setattr(proxy, "generate_learning_guide", generate)
    monkeypatch.setattr(
        proxy,
        "batch_validate_topics",
        AsyncMock(
            return_value=[
                SimpleNamespace(
                    wiki_title="Analytical engine", description="Mechanical computer"
                )
            ]
        ),
    )

    def request(uid):
        return SimpleNamespace(
            user_id=uid,
            app=SimpleNamespace(
                state=SimpleNamespace(
                    secrets_manager=SimpleNamespace(
                        get_secret=AsyncMock(return_value="test-secret")
                    )
                )
            ),
        )

    a, b = await asyncio.gather(
        proxy._learning_payload(request("one"), article()),
        proxy._learning_payload(request("two"), article()),
    )
    assert a == b
    assert len(calls) == 1
    assert set(calls[0][0]) == {
        "language",
        "canonical_title",
        "source_url",
        "description",
        "lead_extract",
    }
    assert redis.ttls[learning_cache_key(article())] == LEARNING_CACHE_TTL
    assert a["related_articles"][0]["title"] == "Analytical engine"
    assert not any(k.endswith(":lock") for k in redis.values)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=wikipedia-mentions.learning.public-cache
async def test_failed_generation_is_not_cached_and_can_retry(monkeypatch):
    proxy = _import_wikipedia_proxy()
    redis = Redis()
    monkeypatch.setattr(proxy, "_cache_client", AsyncMock(return_value=redis))
    monkeypatch.setattr(
        "backend.apps.ai.processing.wikipedia_context.build_wikipedia_reference_context",
        AsyncMock(side_effect=lambda refs, **kw: refs),
    )
    monkeypatch.setattr(
        proxy,
        "generate_learning_guide",
        AsyncMock(side_effect=RuntimeError("no provider")),
    )
    req = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                secrets_manager=SimpleNamespace(
                    get_secret=AsyncMock(return_value="secret")
                )
            )
        )
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        await proxy._learning_payload(req, article())
    assert error.value.status_code == 503
    assert learning_cache_key(article()) not in redis.values
    assert not any(k.endswith(":lock") for k in redis.values)
