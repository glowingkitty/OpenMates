from types import SimpleNamespace
from unittest.mock import AsyncMock


# contract-test: direct surface=rest_api assertions=video-call.audio.intentional-interruption,video-call.lifecycle.recovery-and-billing
async def test_ended_call_cancels_queued_speech_before_safety_or_provider_work(monkeypatch):
    from backend.apps.audio.assistant_speech import segment_task
    from backend.shared.python_utils import voice_call_admission

    row = {"segment_id": "segment", "status": "queued", "execution_version": 0}

    async def claim(*args, lease_id):
        row.update(status="generating", lease_id=lease_id)
        return row

    async def invalidate(*args):
        row["status"] = "cancelled"

    authority = AsyncMock(side_effect=ValueError("Voice call has ended"))
    provider = AsyncMock()
    monkeypatch.setattr(voice_call_admission, "require_active_voice_dispatch", authority)
    monkeypatch.setattr(segment_task, "get_speech_segment", AsyncMock(side_effect=lambda *args: row))
    monkeypatch.setattr(segment_task, "claim_speech_segment_execution", claim)
    monkeypatch.setattr(segment_task, "invalidate_speech_segment", invalidate)
    monkeypatch.setattr(segment_task, "initialize_task_storage", AsyncMock())
    monkeypatch.setattr(segment_task, "require_storage_available", AsyncMock())
    monkeypatch.setattr(segment_task, "ensure_audio_credit_headroom", AsyncMock())
    monkeypatch.setattr(segment_task, "resolve_assistant_voice_profile", lambda *args, **kwargs:
                        SimpleNamespace(key="george", version=2, model="voxtral-mini-tts-3-0", provider="mistral"))
    monkeypatch.setattr(segment_task, "MistralSpeechClient", provider)
    task = SimpleNamespace(initialize_core_services=AsyncMock(), _directus_service=object(),
                           _cache_service=object(), _secrets_manager=object())
    result = await segment_task._async_generate_assistant_speech_segment(task, {
        "segment_id": "segment", "user_id": "owner", "chat_id": "chat",
        "assistant_message_id": "answer", "voice_call_id": "a" * 32,
        "voice_turn_id": "user-turn", "speakable_text": "Hello.",
        "voice_profile_key": "george", "voice_profile_version": 2,
    })
    assert result == {"segment_id": "segment", "status": "cancelled"}
    assert row["status"] == "cancelled"
    authority.assert_awaited_once()
    assert authority.await_args.args[1]["message_id"] == "user-turn"
    provider.assert_not_called()
