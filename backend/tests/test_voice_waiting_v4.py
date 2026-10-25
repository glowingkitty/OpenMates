"""Finite call waiting speech follows v4 while preserving manual Speak storage."""
from backend.tests.test_assistant_speech_live_worker import live_worker as live_worker
from backend.tests.test_assistant_speech_storage_preflight import speech_preflight as speech_preflight


# contract-test: supporting surface=rest_api assertions=video-call.audio.spoken-rich-response,video-call.chat.ethics
async def test_waiting_prelude_uses_v4_live_adapter_and_never_uploads(live_worker, monkeypatch):
    from backend.apps.audio.assistant_speech import realtime_turn
    from backend.apps.audio.assistant_speech.voice_profiles import resolve_assistant_voice_profile
    case = live_worker
    case.arguments.update(kind="waiting_confirmation", sequence=-1, voice_profile_version=3)
    case.row.update(kind="waiting_confirmation", sequence=-1, voice_profile_version=3)
    monkeypatch.setattr(case.module, "resolve_assistant_voice_profile", resolve_assistant_voice_profile)
    monkeypatch.setattr(realtime_turn, "ElevenRealtimeFiniteClient", case.client_factory)
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)
    assert result["status"] == "ready" and result["sequence"] == -1
    assert case.stream_calls[0]["model"] == "eleven_v4_turbo"
    assert case.stream_calls[0]["voice_id"] == resolve_assistant_voice_profile("george", version=3).elevenlabs_request()["voice_id"]
    case.safety.assert_awaited_once()
    case.credits.assert_awaited_once()
    case.billing.assert_called_once()
    case.store.assert_not_awaited()
    case.initialize_storage.assert_not_awaited()
    case.task._s3_service.upload_file.assert_not_awaited()
    assert not case.row.get("generated_asset_id")
    assert all(event["payload"]["kind"] == "waiting_confirmation"
               for event in case.events if event["type"] == "assistant_speech_audio")
