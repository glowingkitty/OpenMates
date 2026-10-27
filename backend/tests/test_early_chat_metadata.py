# contract-test-file: infrastructure
"""Bounded optional metadata contracts; real multilingual quality runs on dev."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.processing import early_chat_metadata as metadata


def result(arguments=None, error=None):
    return SimpleNamespace(arguments=arguments, error_message=error)


VALID = {"title": "Vegetarian Weeknight Dinner Plan", "summary": "Planning quick vegetarian dinners for two under 40 euros."}


def test_projection_is_bounded_and_excludes_tool_private_context():
    messages = metadata.metadata_messages([
        {"role": "system", "content": "private system context"},
        {"role": "tool", "content": "private tool result"},
        {"role": "assistant", "content": "a" * 2000},
        {"role": "user", "content": "b" * 10000 + " important final constraint"},
        {"role": "user", "sender_name": "async_tool_result", "content": "private tool reply"},
    ], "fr")
    assert "UI language: fr" in messages[0]["content"]
    context = json.loads(messages[1]["content"])["conversation"]
    assert len(context) == 2 and len(context[0]["content"]) == 800
    assert context[-1]["content"].endswith("important final constraint")
    assert len(messages[1]["content"]) < 7100
    assert "private" not in messages[1]["content"]


@pytest.mark.parametrize("change", [
    {"chat_has_title": True}, {"current_chat_title": "Manually named"},
    {"is_incognito": True}, {"is_external": True}, {"is_anonymous": True},
    {"team_id": "team"}, {"is_sub_chat": True}, {"recovery_public_key": None},
    {"is_async_skill_continuation": True},
])
def test_only_eligible_new_saved_chats_generate_metadata(change):
    request = dict(chat_has_title=False, current_chat_title=None, user_id="owner",
                   recovery_preflight_id="admitted", recovery_public_key="key",
                   resolved_recovery_inference_task_id=lambda: "task")
    assert metadata.eligible_for_early_metadata(SimpleNamespace(**request))
    request.update(change)
    assert not metadata.eligible_for_early_metadata(SimpleNamespace(**request))


@pytest.mark.asyncio
async def test_mercury_primary_has_small_structured_intent_only_prompt(monkeypatch):
    from backend.apps.ai.utils import llm_utils
    call = AsyncMock(return_value=result(VALID))
    monkeypatch.setattr(llm_utils, "call_preprocessing_llm", call)
    generated = await metadata.generate_early_chat_metadata(task_id="task", message_history=[
        {"role": "user", "content": "Plane vegetarische Abendessen."}],
        user_system_language="de", secrets_manager=None)
    assert generated == metadata.EarlyChatMetadata(**VALID, model_id=metadata.PRIMARY_MODEL)
    kwargs = call.call_args.kwargs
    assert call.await_count == 1 and kwargs["model_id"] == "inception/mercury-3"
    assert kwargs["max_output_tokens"] == 384 and kwargs["reasoning_effort"] == "low"
    assert kwargs["fallback_models"] == [] and not kwargs["allow_retries"]
    assert "NOT been produced" in kwargs["message_history"][0]["content"]
    properties = kwargs["tool_definition"]["function"]["parameters"]["properties"]
    assert all("German (de)" in properties[field]["description"] for field in ("title", "summary"))


def test_natural_spanish_title_is_valid_navigation_metadata():
    arguments = {"title": "Plan de cuatro días en Lisboa con 300 euros",
                 "summary": "Planificar cuatro días en Lisboa con presupuesto de 300 euros y comparar opciones."}
    assert metadata._validated(arguments, metadata.PRIMARY_MODEL).title == arguments["title"]


@pytest.mark.parametrize("first", [result(error="unavailable"), result({"title": "x"}),
    result({**VALID, "summary": 123}), result({**VALID, "title": "word " * 13}),
    result({**VALID, "summary": "word " * 21}), result({**VALID, "extra": "unexpected"})])
@pytest.mark.asyncio
async def test_failed_or_malformed_mercury_uses_gemini(monkeypatch, first):
    from backend.apps.ai.utils import llm_utils
    call = AsyncMock(side_effect=[first, result(VALID)])
    monkeypatch.setattr(llm_utils, "call_preprocessing_llm", call)
    generated = await metadata.generate_early_chat_metadata(task_id="task", message_history=[
        {"role": "user", "content": "Compare dinner options"}], user_system_language="en", secrets_manager=None)
    assert generated.model_id == "google/gemini-3.5-flash-lite"
    assert [item.kwargs["model_id"] for item in call.call_args_list] == [metadata.PRIMARY_MODEL, metadata.FALLBACK_MODEL]


@pytest.mark.asyncio
async def test_timeout_reserves_a_separate_gemini_attempt(monkeypatch):
    from backend.apps.ai.utils import llm_utils
    calls = []
    async def call(**kwargs):
        calls.append(kwargs["model_id"])
        if len(calls) == 1:
            await asyncio.Event().wait()
        return result(VALID)
    monkeypatch.setattr(llm_utils, "call_preprocessing_llm", call)
    monkeypatch.setattr(metadata, "ATTEMPT_TIMEOUT_SECONDS", 0.01)
    generated = await metadata.generate_early_chat_metadata(task_id="task", message_history=[
        {"role": "user", "content": "Dinner options"}], user_system_language="en", secrets_manager=None)
    assert generated.model_id == metadata.FALLBACK_MODEL
    assert calls == [metadata.PRIMARY_MODEL, metadata.FALLBACK_MODEL]


@pytest.mark.asyncio
async def test_cancellation_never_starts_fallback(monkeypatch):
    from backend.apps.ai.utils import llm_utils
    entered = asyncio.Event()
    async def call(**kwargs):
        entered.set()
        await asyncio.Event().wait()
    mocked = AsyncMock(side_effect=call)
    monkeypatch.setattr(llm_utils, "call_preprocessing_llm", mocked)
    task = asyncio.create_task(metadata.generate_early_chat_metadata(task_id="task", message_history=[
        {"role": "user", "content": "Dinner options"}], user_system_language="en", secrets_manager=None))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert mocked.await_count == 1


@pytest.mark.asyncio
async def test_greeting_can_decline_and_total_outage_is_nonfatal(monkeypatch):
    from backend.apps.ai.utils import llm_utils
    call = AsyncMock(return_value=result({"title": None, "summary": None}))
    monkeypatch.setattr(llm_utils, "call_preprocessing_llm", call)
    generated = await metadata.generate_early_chat_metadata(task_id="task", message_history=[
        {"role": "user", "content": "Bonjour !"}], user_system_language="fr", secrets_manager=None)
    assert generated.title is None and generated.summary is None and call.await_count == 1
    call.side_effect = RuntimeError("provider unavailable")
    assert await metadata.generate_early_chat_metadata(task_id="task", message_history=[
        {"role": "user", "content": "Dinner options"}], user_system_language="en", secrets_manager=None) is None
