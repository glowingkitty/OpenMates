# contract-test-file: infrastructure
# backend/tests/test_notification_summary.py
#
# Notification type + summary: validation, the single post-processing call,
# incognito/hidden exclusion, the sealed Redis hand-off, the push content
# matrix and the proof that no credits are charged. All data is synthetic.
#
# Run: python -m pytest backend/tests/test_notification_summary.py -v
import ast
import asyncio
from pathlib import Path

import pytest

from backend.apps.ai.processing import postprocessor
from backend.apps.ai.processing.notification_summary import (
    SUMMARY_HARD_LIMIT, notification_headline, sanitize_notification_fields,
)
from backend.apps.ai.processing.postprocessor import handle_postprocessing
from backend.core.api.app.services.notification_headline_handoff import (
    HEADLINE_TTL_SECONDS, headline_key, read_headline, stage_headline,
)
from backend.core.api.app.services.push_notification_content import GENERIC_PUSH_TITLE, compose_push_content
from backend.apps.ai.utils.llm_utils import LLMPreprocessingCallResult


@pytest.mark.parametrize("arguments,expected", [
    ({"notification_type": "done", "notification_summary": "Added 4 models, 3 tests pass"}, ("done", "Added 4 models, 3 tests pass")),
    ({"notification_type": " Question ", "notification_summary": "**Which** garden bed first?"}, ("question", "Which garden bed first?")),
    ({"notification_type": "info", "notification_summary": '"Tomatoes need sun."'}, ("info", "Tomatoes need sun")),
    ({"notification_type": "warning", "notification_summary": "x"}, (None, None)),
    ({"notification_type": "done"}, (None, None)),
    ({"notification_summary": "No type"}, (None, None)),
    ({"notification_type": "done", "notification_summary": "  ``  "}, (None, None)),
    ({"notification_type": 3, "notification_summary": "x"}, (None, None)),
])
def test_sanitize_notification_fields_is_both_or_neither(arguments, expected):
    assert sanitize_notification_fields(arguments) == expected


def test_overlong_summary_is_cut_at_a_word_boundary_within_the_hard_limit():
    kind, summary = sanitize_notification_fields({"notification_type": "info", "notification_summary": "word " * 60})
    assert kind == "info" and len(summary) <= SUMMARY_HARD_LIMIT and summary.endswith("…")
    assert notification_headline("done", "Gemini 4 models added, 3 tests pass") == "✅ Gemini 4 models added, 3 tests pass"
    assert notification_headline("question", "Which tool?").startswith("❓ ")
    assert notification_headline("info", "Facts").startswith("ℹ️ ")


async def _run_postprocessing(monkeypatch, llm_arguments, **kwargs):
    calls = []

    async def fake_llm(**call_kwargs):
        calls.append(call_kwargs)
        return LLMPreprocessingCallResult(arguments=llm_arguments)

    async def no_translation(**translate_kwargs):
        return {key: translate_kwargs.get(key) for key in ("chat_summary", "share_cta_text", "updated_chat_title")} | {
            "new_chat_suggestions": translate_kwargs["new_chat_suggestions"]}

    monkeypatch.setattr(postprocessor, "call_preprocessing_llm", fake_llm)
    monkeypatch.setattr(postprocessor, "translate_postprocessing_metadata", no_translation)
    monkeypatch.setattr(postprocessor, "resolve_fallback_servers_from_provider_config", lambda _model: [])
    properties = {name: {"type": "string"} for name in ("chat_summary", "notification_type", "notification_summary")}
    result = await handle_postprocessing(
        task_id="synthetic-task", user_message="Add the models", assistant_response="Done: models added.",
        chat_summary=None, chat_tags=[], message_history=[], secrets_manager=None, cache_service=None,
        available_app_ids=["ai"], output_language="en", user_system_language="en",
        base_instructions={"postprocess_response_tool": {"type": "function", "function": {
            "name": "postprocess", "parameters": {"properties": properties, "required": list(properties)}}}},
        **kwargs,
    )
    return result, calls


@pytest.mark.anyio
async def test_one_llm_call_returns_type_and_summary_and_bills_nothing(monkeypatch):
    result, calls = await _run_postprocessing(monkeypatch, {
        "chat_summary": "Models added.", "notification_type": "done", "notification_summary": "Added 4 models, 3 tests pass"})
    assert (result.notification_type, result.notification_summary) == ("done", "Added 4 models, 3 tests pass")
    assert len(calls) == 1  # no extra LLM request for the notification text
    assert "notification_summary" in calls[0]["tool_definition"]["function"]["parameters"]["properties"]
    # Platform cost: the step passes no usage callback, so no per-user usage entry is created.
    assert calls[0].get("usage_callback") is None


@pytest.mark.anyio
async def test_incognito_chats_get_no_postprocessing_and_so_no_notification_content(monkeypatch):
    result, calls = await _run_postprocessing(monkeypatch, {
        "chat_summary": "x", "notification_type": "done", "notification_summary": "Secret detail"}, is_incognito=True)
    assert result is None and calls == []


@pytest.mark.anyio
async def test_sub_chats_never_get_notification_content(monkeypatch):
    result, calls = await _run_postprocessing(monkeypatch, {
        "chat_summary": "x", "notification_type": "done", "notification_summary": "Secret detail"}, is_sub_chat=True)
    parameters = calls[0]["tool_definition"]["function"]["parameters"]
    assert "notification_type" not in parameters["properties"] and "notification_summary" not in parameters["properties"]
    assert not {"notification_type", "notification_summary"} & set(parameters["required"])
    assert (result.notification_type, result.notification_summary) == (None, None)


@pytest.mark.anyio
async def test_unusable_model_output_falls_back_to_generic(monkeypatch):
    result, _ = await _run_postprocessing(monkeypatch, {"chat_summary": "x", "notification_type": "shout", "notification_summary": "Hi"})
    assert (result.notification_type, result.notification_summary) == (None, None)


def test_authenticated_postprocessing_call_has_no_usage_callback_and_no_credit_code_in_new_modules():
    """The summary is a platform cost: nothing on this path may reach credit billing."""
    root = Path(__file__).resolve().parents[1]
    tree = ast.parse((root / "apps/ai/tasks/ask_skill_task.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "handle_postprocessing"]
    assert calls and all("usage_callback" not in {k.arg for k in c.keywords} for c in calls)
    for module in ("apps/ai/processing/notification_summary.py", "core/api/app/services/notification_headline_handoff.py",
                   "core/api/app/services/push_notification_content.py"):
        source = (root / module).read_text()
        assert "billing" not in source and "credits" not in source


class _Redis:
    def __init__(self):
        self.values, self.ttl = {}, {}

    async def set(self, key, value, ex=None):
        self.values[key], self.ttl[key] = value, ex

    async def get(self, key):
        return self.values.get(key)


def _services():
    redis = _Redis()

    async def client():
        return redis

    class Cache:
        @property
        def client(self):
            return client()

        async def get_user_by_id(self, user_id):
            return {"vault_key_id": "synthetic-vault-key"}

    class Encryption:
        async def encrypt_with_user_key(self, plaintext, key_id):
            return "sealed:" + plaintext[::-1], key_id

        async def decrypt_with_user_key(self, ciphertext, key_id):
            return ciphertext.removeprefix("sealed:")[::-1]

    return redis, Cache(), Encryption()


def test_headline_is_sealed_in_redis_expires_and_reads_back():
    redis, cache, encryption = _services()
    assert asyncio.run(stage_headline(cache_service=cache, directus_service=None, encryption_service=encryption,
                                      user_id="u", chat_id="c", task_id="t", notification_type="done",
                                      summary="Added 4 models")) is True
    key = headline_key("u", "c", "t")
    assert "Added 4 models" not in redis.values[key] and redis.ttl[key] == HEADLINE_TTL_SECONDS
    assert asyncio.run(read_headline(cache_service=cache, encryption_service=encryption, vault_key_id="synthetic-vault-key",
                                     user_id="u", chat_id="c", task_id="t")) == "✅ Added 4 models"
    assert asyncio.run(read_headline(cache_service=cache, encryption_service=encryption, vault_key_id="synthetic-vault-key",
                                     user_id="u", chat_id="c", task_id="other")) is None


def test_invalid_headline_is_not_staged():
    redis, cache, encryption = _services()
    for kind, summary in (("shout", "x"), ("done", ""), (None, None)):
        assert asyncio.run(stage_headline(cache_service=cache, directus_service=None, encryption_service=encryption,
                                          user_id="u", chat_id="c", task_id="t", notification_type=kind, summary=summary)) is False
    assert redis.values == {}


@pytest.mark.parametrize("prefs,headline,hidden,expected", [
    ({}, "✅ Added 4 models", False, ("✅ Added 4 models", 'in "Garden notes"', "")),
    ({"includeChatTitle": False}, "✅ Added 4 models", False, (GENERIC_PUSH_TITLE, None, "")),
    ({"includePreview": True}, "✅ Added 4 models", False, ("✅ Added 4 models", 'in "Garden notes"', "The beds are planned.")),
    ({"includeChatTitle": False, "includePreview": True}, None, False, (GENERIC_PUSH_TITLE, None, "The beds are planned.")),
    ({}, None, False, ("Mate in Garden notes", None, "")),
    ({"includePreview": True}, "✅ Added 4 models", True, (GENERIC_PUSH_TITLE, None, "")),
])
def test_push_content_matrix(prefs, headline, hidden, expected):
    content = compose_push_content(preferences=prefs, headline=headline, chat_title="Garden notes", mate_name="Mate",
                                   preview_text="The beds are planned.", hidden=hidden)
    assert (content.title, content.context, content.body) == expected
    assert (content.sealed_title is None) == (content.title == GENERIC_PUSH_TITLE)
