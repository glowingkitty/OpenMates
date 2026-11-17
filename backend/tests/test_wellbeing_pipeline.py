"""Wellbeing layer: question set, instructions, card, counters, validation."""


import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from toon_format import decode

from backend.apps.ai.processing import jev_preprocessing, wellbeing_support
from backend.apps.ai.processing.wellbeing_level import compute_level
from backend.apps.ai.processing.wellbeing_questions import WELLBEING_SIGNALS, wellbeing_questions
from backend.shared.providers.typesafe.batching import question_batches
from backend.shared.providers.typesafe.client import DecisionProviderUnavailable, MAX_QUESTIONS

# contract-test: direct surface=rest_api assertions=wellbeing-support.no-extra-call
def test_questions_are_part_of_public_decisions_without_a_new_batch():
    public = jev_preprocessing._public_decision_questions(True)
    assert set(wellbeing_questions()) <= set(public)
    assert len(wellbeing_questions()) == len(WELLBEING_SIGNALS) == 10
    without = {key: value for key, value in public.items() if key not in wellbeing_questions()}
    state = {"messages": ["Hello"]}
    try:
        assert len(question_batches(state, without)) == len(question_batches(state, public)) == 1
    except DecisionProviderUnavailable:
        pytest.skip("Jev input tokenizer is not installed in this environment")
    assert len(public) < MAX_QUESTIONS


# contract-test: direct surface=rest_api assertions=wellbeing-support.gentle-check-in
def test_instruction_for_levels():
    assert wellbeing_support.instruction_for(compute_level([], {}, now=1)) is None
    level1 = wellbeing_support.instruction_for(compute_level([], {"hopelessness_isolation": 0.4}, now=1))
    level2 = wellbeing_support.instruction_for(compute_level([], {"suicidal": 0.65}, now=1))
    assert "check-in" in level1 and "Support comes first" in level2
    grounding = wellbeing_support.instruction_for(compute_level([], {"reality_loss": 0.5}, now=1))
    assert "do not affirm" in grounding


class FakeRedis:
    def __init__(self):
        self.counts, self.ttl = {}, {}

    async def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1

    async def expire(self, key, seconds):
        self.ttl[key] = seconds


def _cache():
    redis = FakeRedis()
    cache = SimpleNamespace(publish_event=AsyncMock(), client=_awaitable(redis))
    return cache, redis


def _awaitable(value):
    async def get():
        return value
    return get()


def _request(history=None):
    return SimpleNamespace(user_id="u", chat_id="c", wellbeing_scores=history)


# contract-test: direct surface=rest_api assertions=wellbeing-support.client-only-storage
@pytest.mark.asyncio
async def test_level_two_counts_anonymously_and_publishes_only_the_history_event():
    cache, redis = _cache()
    result = SimpleNamespace(wellbeing_scores={"suicidal": 0.7}, output_language="de")
    assessment = await wellbeing_support.publish(cache, _request(), result)
    assert assessment.level == 2 and wellbeing_support.card_due(assessment)
    events = {call.args[1]["event_type"]: call.args[1]["payload"] for call in cache.publish_event.await_args_list}
    assert list(events) == ["wellbeing_scores_updated"]
    assert events["wellbeing_scores_updated"]["scores"][-1]["s"] == {"suicidal": 0.7}
    assert list(redis.counts) and all(k.startswith("wellbeing:card_shown:") for k in redis.counts)
    assert all("u" != part for key in redis.counts for part in key.split(":")[2:])
    assert list(redis.ttl.values()) == [3 * 24 * 3600]


# contract-test: direct surface=rest_api assertions=wellbeing-support.helpline-card
@pytest.mark.asyncio
async def test_card_is_a_helplines_embed_referenced_before_the_answer_text():
    sent = {}

    async def send(**kwargs):
        sent.update(kwargs)
        return True

    embed_service = SimpleNamespace(
        _generate_direct_embed_ref=lambda type_, id_, meta: f"helplines-{id_[:6]}",
        encryption_service=SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("enc", None))),
        send_embed_data_to_client=send, _schedule_embed_persistence_fallback=lambda _id: None,
    )
    secrets = SimpleNamespace(get_secret=AsyncMock(return_value=None))
    result = SimpleNamespace(wellbeing_scores={"suicidal": 0.7}, output_language="de")
    ref = await wellbeing_support.create_card_embed(embed_service, secrets, _request(), result, "m1", "vault")
    assert sent["embed_type"] == "helplines" and sent["status"] == "finished" and sent["message_id"] == "m1"
    content = decode(sent["content_toon"])
    assert content["source"] == "emergency_only" and content["emergency_number"] == "112"
    assert content["country"] == "DE" and content["language"] == "de" and content["lines"] == []
    assert content["directory_url"] == wellbeing_support.DIRECTORY_URL
    assert sent["finished_cache_data"]["encrypted_content"] == "enc"
    answer = ref + "Here is how I can help with your task."
    assert answer.startswith("```json") and answer.index(sent["embed_id"]) < answer.index("Here is how")
    assert json.loads(ref.split("\n")[1]) == {"type": "helplines", "embed_id": sent["embed_id"]}


# contract-test: supporting surface=rest_api assertions=wellbeing-support.helpline-card
@pytest.mark.asyncio
async def test_level_one_has_no_card_and_quiet_turns_emit_nothing():
    cache, redis = _cache()
    result = SimpleNamespace(wellbeing_scores={"hopelessness_isolation": 0.4}, output_language="en")
    await wellbeing_support.publish(cache, _request(), result)
    assert [c.args[1]["event_type"] for c in cache.publish_event.await_args_list] == ["wellbeing_scores_updated"]
    assert all(k.startswith("wellbeing:checkin:") for k in redis.counts)
    quiet_cache, _ = _cache()
    await wellbeing_support.publish(quiet_cache, _request(), SimpleNamespace(wellbeing_scores={"mania": 0.05}))
    quiet_cache.publish_event.assert_not_awaited()


# contract-test: supporting surface=rest_api assertions=wellbeing-support.client-only-storage
def test_malformed_payload_is_treated_as_empty_and_logged_without_values(caplog):
    with caplog.at_level(logging.WARNING):
        assert wellbeing_support.incoming_history([{"t": 1, "s": {"suicidal": 9.99}}]) == []
    assert "malformed" in caplog.text and "9.99" not in caplog.text


# contract-test: direct surface=rest_api assertions=wellbeing-support.client-only-storage
def test_scores_are_not_part_of_persisted_or_logged_surfaces():
    pytest.importorskip("redis")
    from backend.apps.ai.processing.preprocessor import PreprocessingResult
    assert "wellbeing" not in open("backend/apps/ai/tasks/preprocessing_resume.py").read()
    result = PreprocessingResult(wellbeing_scores={"suicidal": 0.9})
    assert "wellbeing_scores" not in result.model_dump()
    assert "suicidal" not in repr(result)
    source = open("backend/shared/python_utils/private_inference_logging.py").read()
    assert "wellbeing" not in source
