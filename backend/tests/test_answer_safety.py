"""Answer-safety decisions: withdrawal rules, event, live-check gating and no strikes."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import sys
from pathlib import Path

import yaml

from backend.apps.ai.processing import answer_safety as safety
from backend.apps.ai.processing.answer_safety import (
    LiveCheckGate, Withdrawal, decide_withdrawal, is_risky_chat,
)


NOTICE_YML = Path(__file__).resolve().parents[2] / "frontend/packages/ui/src/i18n/sources/answer_safety.yml"
LANGUAGES = "en de zh es fr pt ru ja ko it tr vi id pl nl ar hi th cs sv he".split()


class _YamlTranslations:
    """Reads the source yml directly; the built locale JSON is a deploy artifact."""

    def __init__(self) -> None:
        self.data = yaml.safe_load(NOTICE_YML.read_text(encoding="utf-8"))

    def get_nested_translation(self, key: str, lang: str, *_a, **_k) -> str:
        entry = self.data.get(key.split(".", 1)[1], {})
        return entry.get(lang, key)


@pytest.fixture(autouse=True)
def _yaml_translations(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.core.api.app.services.translations as translations

    monkeypatch.setattr(translations, "TranslationService", _YamlTranslations)


# contract-test: direct surface=rest_api assertions=answer-safety-check.withdraw-only-illegal-or-wellbeing
def test_notice_source_has_every_language() -> None:
    data = yaml.safe_load(NOTICE_YML.read_text(encoding="utf-8"))
    for key in ("illegal", "wellbeing"):
        assert data[key]["context"]
        assert all(data[key].get(lang) for lang in LANGUAGES)


# contract-test: direct surface=rest_api assertions=answer-safety-check.withdraw-only-illegal-or-wellbeing
def test_decide_withdrawal_branches() -> None:
    assert decide_withdrawal({"answer_illegal": 0, "answer_wellbeing_harm": 0}) is None
    assert decide_withdrawal({"answer_illegal": 6, "answer_wellbeing_harm": 6}) is None
    assert decide_withdrawal({"answer_illegal": 7, "answer_wellbeing_harm": 0}) == Withdrawal("illegal", 7)
    assert decide_withdrawal({"answer_illegal": 0, "answer_wellbeing_harm": 8}) == Withdrawal("wellbeing", 8)
    both = decide_withdrawal({"answer_illegal": 9, "answer_wellbeing_harm": 9})
    assert both is not None and both.reason == "illegal"
    assert decide_withdrawal({}) is None


# contract-test: direct surface=rest_api assertions=answer-safety-check.withdraw-only-illegal-or-wellbeing
def test_harmful_response_alone_never_withdraws() -> None:
    assert decide_withdrawal({"harmful_response": 9}) is None


# contract-test: direct surface=rest_api assertions=answer-safety-check.every-answer-checked
@pytest.mark.asyncio
async def test_incognito_style_answer_gets_one_minimal_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def fake_check(**kwargs):
        calls.append(kwargs)
        return Withdrawal("wellbeing", 8)

    monkeypatch.setattr(safety, "check_answer_safety", fake_check)
    withdrawal, extra = await safety.decide_finished_answer(
        postprocessing_scores=None, decision_model_id="m", user_message="q",
        assistant_response="a", secrets_manager=None, task_id="t",
    )
    assert withdrawal and withdrawal.reason == "wellbeing"
    assert extra == 1 and len(calls) == 1


# contract-test: direct surface=rest_api assertions=answer-safety-check.every-answer-checked
@pytest.mark.asyncio
async def test_postprocessing_scores_are_reused_without_extra_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safety, "check_answer_safety", AsyncMock(side_effect=AssertionError("extra call")))
    withdrawal, extra = await safety.decide_finished_answer(
        postprocessing_scores={"answer_illegal": 8, "answer_wellbeing_harm": 0}, decision_model_id=None,
        user_message="q", assistant_response="a", secrets_manager=None, task_id="t",
    )
    assert withdrawal == Withdrawal("illegal", 8) and extra == 0


# contract-test: direct surface=rest_api assertions=answer-safety-check.every-answer-checked
@pytest.mark.asyncio
async def test_missing_decision_model_is_an_error_not_a_silent_pass() -> None:
    with pytest.raises(RuntimeError):
        await safety.decide_finished_answer(
            postprocessing_scores=None, decision_model_id=None, user_message="q",
            assistant_response="a", secrets_manager=None, task_id="t",
        )


# contract-test: direct surface=rest_api assertions=answer-safety-check.no-strike,answer-safety-check.withdraw-only-illegal-or-wellbeing
@pytest.mark.asyncio
async def test_withdrawal_publishes_localized_event_scrubs_cache_and_gives_no_strike(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The withdrawal path must not even load the strike modules.
    strike_modules_before = {m for m in sys.modules if "image_safety" in m or "strike" in m}
    published = []
    stored = {}

    async def publish_event(channel, payload):
        published.append((channel, payload))

    async def set_history(user_id, chat_id, entries):
        stored["entries"] = entries
        return True

    cache = SimpleNamespace(
        publish_event=publish_event,
        get_ai_messages_history=AsyncMock(return_value=[
            json.dumps({"id": "m1", "encrypted_content": "SECRET", "encrypted_native_cache_context": "SECRET"}),
            json.dumps({"id": "other", "encrypted_content": "keep"}),
        ]),
        set_ai_messages_history=set_history,
        set=AsyncMock(return_value=True),
    )
    encryption = SimpleNamespace(encrypt_with_user_key=AsyncMock(side_effect=lambda text, key: (f"enc:{text}", None)))

    notice = await safety.withdraw_answer(
        withdrawal=Withdrawal("wellbeing", 8), cache_service=cache, encryption_service=encryption,
        user_vault_key_id="vk", user_id="u", user_id_hash="h", chat_id="c", task_id="t",
        message_id="m1", language="de", extra_decision_calls=1,
    )
    channel, payload = published[0]
    assert channel == "ai_typing_indicator_events::h"
    assert payload["type"] == "assistant_answer_withdrawn"
    assert payload["reason"] == "wellbeing" and payload["message_id"] == "m1" and payload["chat_id"] == "c"
    assert payload["notice_text"] == notice and notice
    assert "Antwort" in notice  # German notice, not the English one
    cache.set.assert_awaited_once_with(safety.withdrawn_marker_key("c", "m1"), "1", ttl=safety.WITHDRAWN_MARKER_TTL_SECONDS)
    entries = [json.loads(e) for e in stored["entries"]]
    assert entries[0]["encrypted_content"] == f"enc:{notice}"
    assert entries[0]["encrypted_native_cache_context"] is None
    assert entries[1]["encrypted_content"] == "keep"
    assert "SECRET" not in "".join(stored["entries"])
    assert {m for m in sys.modules if "image_safety" in m or "strike" in m} == strike_modules_before
    assert not any("strike" in str(p).lower() for _c, p in published)


# contract-test: direct surface=rest_api assertions=answer-safety-check.withdraw-only-illegal-or-wellbeing
def test_illegal_notice_is_localized_and_differs_from_wellbeing() -> None:
    assert safety.withdrawal_notice("illegal", "en") != safety.withdrawal_notice("wellbeing", "en")
    assert safety.withdrawal_notice("illegal", "xx") == safety.withdrawal_notice("illegal", "en")


def _prep(**fields):
    return SimpleNamespace(**fields)


# contract-test: direct surface=rest_api assertions=answer-safety-check.live-checks-risky-only
def test_risky_chat_rules() -> None:
    assert not is_risky_chat(_prep(harmful_or_illegal_score=3, misuse_risk_score=2), 7, 8)
    assert is_risky_chat(_prep(harmful_or_illegal_score=7, misuse_risk_score=0), 7, 8)
    assert is_risky_chat(_prep(harmful_or_illegal_score=0, misuse_risk_score=8), 7, 8)
    assert is_risky_chat(_prep(harmful_or_illegal_score=0, misuse_risk_score=0, wellbeing_level=2), 7, 8)
    assert not is_risky_chat(_prep(harmful_or_illegal_score=0, misuse_risk_score=0, wellbeing_level=1), 7, 8)


# contract-test: direct surface=rest_api assertions=answer-safety-check.live-checks-risky-only
@pytest.mark.asyncio
async def test_non_risky_chat_is_never_live_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    check = AsyncMock(side_effect=AssertionError("live check in a non-risky chat"))
    monkeypatch.setattr(safety, "check_answer_safety", check)
    gate = LiveCheckGate(risky=False, model_id="m", user_message="q", secrets_manager=None, task_id="t")
    for size in range(1500, 30000, 1500):
        assert await gate.maybe_check("x" * size) is None
    assert gate.calls == 0


# contract-test: direct surface=rest_api assertions=answer-safety-check.live-checks-risky-only
@pytest.mark.asyncio
async def test_risky_chat_checks_every_interval_and_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    check = AsyncMock(return_value=None)
    monkeypatch.setattr(safety, "check_answer_safety", check)
    gate = LiveCheckGate(risky=True, model_id="m", user_message="q", secrets_manager=None, task_id="t")
    assert await gate.maybe_check("x" * 1000) is None
    assert check.await_count == 0
    for size in range(1500, 30000, 500):
        await gate.maybe_check("x" * size)
    assert check.await_count == safety.MAX_LIVE_CHECKS_PER_ANSWER == 3
    assert gate.calls == 3


# contract-test: direct surface=rest_api assertions=answer-safety-check.live-checks-risky-only
@pytest.mark.asyncio
async def test_live_decision_is_returned_to_stop_the_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safety, "check_answer_safety", AsyncMock(return_value=Withdrawal("illegal", 9)))
    gate = LiveCheckGate(risky=True, model_id="m", user_message="q", secrets_manager=None, task_id="t")
    result = await gate.maybe_check("x" * 1600)
    assert result == Withdrawal("illegal", 9)


def _replace_env(marker, row):
    from backend.core.api.app.routes.handlers.websocket_handlers import replace_withdrawn_message_handler as h

    manager = SimpleNamespace(send_personal_message=AsyncMock(), broadcast_to_user=AsyncMock())
    cache = SimpleNamespace(get=AsyncMock(return_value=marker), delete_sync_messages_history=AsyncMock())
    chat = SimpleNamespace(
        check_chat_ownership=AsyncMock(return_value=True),
        get_message_for_chat_by_client_id=AsyncMock(return_value=row),
    )
    directus = SimpleNamespace(chat=chat, update_item=AsyncMock())
    return h, manager, cache, directus


async def _replace(env):
    h, manager, cache, directus = env
    await h.handle_replace_withdrawn_message(
        None, manager, cache, directus, "u", "dev",
        {"chat_id": "c", "message_id": "m1", "encrypted_content": "sealed"},
    )


# contract-test: direct surface=rest_api assertions=answer-safety-check.replace-only-withdrawn
@pytest.mark.asyncio
async def test_replace_accepts_only_a_message_the_server_withdrew() -> None:
    env = _replace_env("1", {"id": "row1", "role": "assistant"})
    await _replace(env)
    _, manager, cache, directus = env
    cache.get.assert_awaited_once_with(safety.withdrawn_marker_key("c", "m1"))
    directus.update_item.assert_awaited_once_with("messages", "row1", {"encrypted_content": "sealed"}, admin_required=True)
    assert manager.broadcast_to_user.await_args.args[0]["type"] == "assistant_message_replaced"


# contract-test: direct surface=rest_api assertions=answer-safety-check.replace-only-withdrawn
@pytest.mark.asyncio
async def test_replace_rejects_unmarked_messages_and_user_rows() -> None:
    env = _replace_env(None, {"id": "row1", "role": "assistant"})
    await _replace(env)
    assert env[3].update_item.await_count == 0
    assert env[1].send_personal_message.await_args.kwargs["message"]["type"] == "error"
    env = _replace_env("1", {"id": "row1", "role": "user"})
    await _replace(env)
    assert env[3].update_item.await_count == 0
