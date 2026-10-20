"""Bounded model recovery includes output and editorial failures, not just HTTP."""
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.apps.ai.daily_inspiration import config, writer


def draft(collection):
    identity = "wiki_title" if collection == "articles" else "selected_video_youtube_id"
    return {collection: [{identity: "source", "phrase": "Water evaporates from surfaces. How do clouds form?",
                         "title": "How Clouds Form", "assistant_response": "Water evaporates. Vapor condenses. What happens next?",
                         "follow_up_suggestions": ["What is evaporation?", "Why does vapor condense?", "How do clouds form?"]}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("collection", ["articles", "inspirations"])
@pytest.mark.parametrize("failure", ["transport", "exception", "timeout", "empty", "malformed", "followups", "editorial"])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_second_mercury_attempt_recovers_all_failure_classes(monkeypatch, collection, failure):
    monkeypatch.setattr(writer, "RETRY_DELAY_SECONDS", 0)
    calls, reviews = [], []
    payload = draft(collection)

    async def call(**kwargs):
        calls.append(kwargs)
        assert kwargs["fallback_models"] == [] and kwargs["allow_retries"] is False
        assert kwargs["reasoning_effort"] == "low"
        assert kwargs["single_attempt_timeout_seconds"] == writer.ATTEMPT_TIMEOUT_SECONDS
        if len(calls) == 1:
            if failure == "exception":
                raise ConnectionError()
            if failure == "timeout":
                raise TimeoutError()
            if failure == "transport":
                return SimpleNamespace(arguments=None, error_message="HTTP 429")
            if failure == "empty":
                return SimpleNamespace(arguments={}, error_message=None)
            if failure == "malformed":
                return SimpleNamespace(arguments={collection: ["bad"]}, error_message=None)
            if failure == "followups":
                broken = deepcopy(payload)
                broken[collection][0]["follow_up_suggestions"] = []
                return SimpleNamespace(arguments=broken, error_message=None)
        return SimpleNamespace(arguments=payload, error_message=None)

    async def accept(arguments):
        reviews.append(arguments)
        return [] if failure == "editorial" and len(reviews) == 1 else ["reviewed"]

    result = await writer.write_reviewed_cards(writer_call=call, accept=accept, count=1, collection=collection)
    assert result == ["reviewed"]
    assert [row["model_id"] for row in calls] == [config.MERCURY_WRITER] * 2
    assert len(reviews) == (2 if failure == "editorial" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted_attempt", [1, 3, None])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_fallback_is_exactly_bounded_and_always_reviewed(monkeypatch, accepted_attempt):
    monkeypatch.setattr(writer, "RETRY_DELAY_SECONDS", 0)
    models, reviews = [], []

    async def call(**kwargs):
        models.append(kwargs["model_id"])
        assert kwargs["single_attempt_timeout_seconds"] == writer.ATTEMPT_TIMEOUT_SECONDS
        return SimpleNamespace(arguments=draft("articles"), error_message=None)

    async def accept(arguments):
        reviews.append(arguments)
        return ["allowed"] if len(reviews) == accepted_attempt else []

    cards = await writer.write_reviewed_cards(writer_call=call, accept=accept, count=1, collection="articles")
    assert cards == (["allowed"] if accepted_attempt else [])
    expected = [config.MERCURY_WRITER, config.MERCURY_WRITER, config.FALLBACK_WRITER]
    assert models == expected[:accepted_attempt] if accepted_attempt else models == expected
    assert len(reviews) == len(models)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_cancellation_does_not_issue_another_paid_attempt():
    async def call(**_kwargs):
        raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await writer.write_reviewed_cards(writer_call=call, accept=None, count=1, collection="articles")


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_attempt_deadline_reserves_a_real_gemini_attempt(monkeypatch):
    monkeypatch.setattr(writer, "ATTEMPT_TIMEOUT_SECONDS", .01)
    monkeypatch.setattr(writer, "RETRY_DELAY_SECONDS", 0)
    models = []

    async def call(**kwargs):
        models.append(kwargs["model_id"])
        assert kwargs["single_attempt_timeout_seconds"] == writer.ATTEMPT_TIMEOUT_SECONDS
        if len(models) < 3:
            await asyncio.sleep(10)
        return SimpleNamespace(arguments=draft("articles"), error_message=None)

    async def accept(_arguments):
        return ["reviewed"]

    assert await writer.write_reviewed_cards(writer_call=call, accept=accept, count=1, collection="articles") == ["reviewed"]
    assert models == [config.MERCURY_WRITER, config.MERCURY_WRITER, config.FALLBACK_WRITER]
