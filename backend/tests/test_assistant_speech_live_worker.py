"""Live speech runs the real worker/helper without storage, files or replay."""
import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend.apps.audio.assistant_speech import live_stream
from backend.shared.python_utils import voice_call_admission
from backend.shared.python_utils.assistant_speech_audio import validate_assistant_speech_audio_event
from backend.shared.python_utils.storage_availability import storage_unavailable_error
from backend.tests.test_assistant_speech_storage_preflight import speech_preflight  # noqa: F401


@pytest.fixture
def live_worker(request, monkeypatch):
    case = request.getfixturevalue("speech_preflight")
    case.arguments.update(
        segment_id="a" * 64, chat_id="11111111-1111-4111-8111-111111111111",
        assistant_message_id="22222222-2222-4222-8222-222222222222",
        voice_turn_id="33333333-3333-4333-8333-333333333333", voice_call_id="c" * 32,
        kind="voice_prose_clause", sequence=0, source_version=3,
    )
    case.row.update(segment_id=case.arguments["segment_id"], sequence=0, kind="voice_prose_clause",
                    source_version=3, execution_version=4, manifest_id="f" * 64)
    case.timeline = []
    case.events = []
    case.writes = []
    case.stream_calls = []
    case.stream_closed = False
    case.stream_waiting = asyncio.Event()
    case.stream_stall = False
    case.stream_failure = False
    case.stream_chunks = [b"ID3first", b"second"]
    case.admission = AsyncMock()
    monkeypatch.setattr(voice_call_admission, "require_active_voice_dispatch", case.admission)
    case.initialize_storage = AsyncMock(side_effect=storage_unavailable_error())
    case.require_storage = AsyncMock(side_effect=storage_unavailable_error())
    monkeypatch.setattr(case.module, "initialize_task_storage", case.initialize_storage)
    monkeypatch.setattr(case.module, "require_storage_available", case.require_storage)
    case.probe.side_effect = AssertionError("Live speech must never probe S3")
    case.task._s3_service.upload_file = AsyncMock(side_effect=AssertionError("Live speech must never upload"))
    case.task._directus_service.create_item = AsyncMock(side_effect=AssertionError("No upload record for live speech"))
    original_update = case.task._directus_service.update_item_if_version
    async def update(collection, row_id, data, version, **kwargs):
        case.writes.append((collection, dict(data)))
        case.timeline.append(f"persist:{data.get('status')}")
        return await original_update(collection, row_id, data, version, **kwargs)
    case.task._directus_service.update_item_if_version = update
    async def credit(**kwargs):
        case.timeline.append("credits")
    async def safety(**kwargs):
        case.timeline.append("safety")
        return SimpleNamespace(approved=True, user_facing_message="")
    case.credits.side_effect = credit
    case.safety.side_effect = safety
    async def publish(channel, event):
        if event["type"] == "assistant_speech_audio":
            validate_assistant_speech_audio_event(event, channel=channel)
            case.timeline.append(event["payload"]["phase"])
            assert case.row["status"] == "generating"
            assert not case.row.get("billable_character_count")
        else:
            case.timeline.append("terminal")
        case.events.append(event)
        return True
    case.task._cache_service.publish_event = AsyncMock(side_effect=publish)
    class Client:
        text_to_speech = case.provider
        async def stream_text_to_speech(self, **request):
            case.stream_calls.append(request)
            case.timeline.append("provider")
            assert "safety" in case.timeline and "credits" in case.timeline
            try:
                for chunk in case.stream_chunks:
                    yield chunk
                if case.stream_failure:
                    raise RuntimeError("Mistral speech generation failed")
                if case.stream_stall:
                    case.stream_waiting.set()
                    await asyncio.Event().wait()
            finally:
                case.stream_closed = True
    case.client_factory = Mock(return_value=Client())
    monkeypatch.setattr(case.module, "MistralSpeechClient", case.client_factory)
    case.billing = Mock(side_effect=lambda *args, **kwargs: case.timeline.append("billing"))
    monkeypatch.setattr(case.module.app, "send_task", case.billing)
    return case


def assert_no_storage(case):
    case.initialize_storage.assert_not_awaited()
    case.require_storage.assert_not_awaited()
    case.probe.assert_not_called()
    case.store.assert_not_awaited()
    case.task._s3_service.upload_file.assert_not_awaited()
    case.task._directus_service.create_item.assert_not_awaited()
    case.provider.assert_not_awaited()
    assert "generated_asset_id" not in case.row
    assert all(collection == "assistant_speech_segments" for collection, _ in case.writes)
    assert all("audio_bytes" not in data and "audio_data" not in data and "speakable_text" not in data
               and "generated_asset_id" not in data for _, data in case.writes)


# contract-test: direct surface=rest_api assertions=assistant-speech.execution.first-segment-progressive,assistant-speech.billing.segment-success-once,assistant-speech.privacy.transient-plaintext-encrypted-audio
@pytest.mark.parametrize("kind,sequence", [("voice_prose_clause", 0), ("waiting_confirmation", -1)])
async def test_live_worker_streams_before_terminal_and_bills_once_without_storage_or_redelivery(live_worker, kind, sequence):
    case = live_worker
    case.arguments.update(kind=kind, sequence=sequence)
    case.row.update(kind=kind, sequence=sequence)
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)
    assert result["status"] == "ready" and result["sequence"] == sequence
    assert "generated_asset_id" not in result
    assert case.row["billable_character_count"] == len(case.arguments["speakable_text"])
    events = [event["payload"] for event in case.events if event["type"] == "assistant_speech_audio"]
    assert [event["phase"] for event in events] == ["start", "chunk", "chunk", "end"]
    assert [event["chunk_index"] for event in events] == [0, 0, 1, 2]
    assert b"".join(base64.b64decode(event["audio_data"]) for event in events if event["phase"] == "chunk") == b"ID3firstsecond"
    assert all(event["kind"] == kind and event["sequence"] == sequence and event["source_version"] == 3
               and event["execution_version"] == 5 for event in events)
    assert case.timeline.index("credits") < case.timeline.index("provider")
    assert case.timeline.index("safety") < case.timeline.index("provider")
    assert case.timeline.index("end") < case.timeline.index("persist:ready") < case.timeline.index("billing") < case.timeline.index("terminal")
    assert len(case.stream_calls) == 1 and case.stream_closed
    assert case.stream_calls[0]["text"] == case.arguments["speakable_text"]
    case.admission.assert_awaited()
    case.safety.assert_awaited_once()
    case.credits.assert_awaited_once()
    case.billing.assert_called_once()
    before_events = len(case.events)
    redelivery = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)
    assert redelivery == result
    assert len(case.stream_calls) == 1 and len(case.events) == before_events
    case.billing.assert_called_once()
    assert_no_storage(case)


# contract-test: direct surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.billing.segment-success-once,assistant-speech.execution.first-segment-progressive
async def test_provider_failure_closes_stream_and_never_persists_billable_characters_or_audio(live_worker):
    case = live_worker
    case.stream_failure = True
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)
    assert result["status"] == case.row["status"] == "error"
    assert case.stream_closed and len(case.stream_calls) == 1
    assert "billable_character_count" not in case.row
    assert all("billable_character_count" not in data for _, data in case.writes)
    assert [event["payload"]["phase"] for event in case.events if event["type"] == "assistant_speech_audio"] == ["start", "chunk", "chunk", "error"]
    assert_no_storage(case)


# contract-test: direct surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.billing.segment-success-once,video-call.audio.intentional-interruption
@pytest.mark.parametrize("interruption", ["cancelled-row", "cancelled-task"])
async def test_cancelling_stalled_live_worker_closes_provider_without_billing_or_storage(live_worker, monkeypatch, interruption):
    case = live_worker
    monkeypatch.setattr(live_stream, "ACTIVE_CHECK_INTERVAL_SECONDS", 0.01)
    case.stream_stall = True
    pending = asyncio.create_task(case.module._async_generate_assistant_speech_segment(case.task, case.arguments))
    await asyncio.wait_for(case.stream_waiting.wait(), 1)
    if interruption == "cancelled-row":
        case.row["status"] = "cancelled"
        result = await asyncio.wait_for(pending, 1)
        assert result["status"] == "cancelled"
    else:
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    assert case.stream_closed and len(case.stream_calls) == 1
    assert "billable_character_count" not in case.row
    case.billing.assert_not_called()
    assert_no_storage(case)


# contract-test: supporting surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.billing.segment-success-once
@pytest.mark.parametrize("blocked", ["safety", "credits"])
async def test_live_safety_and_credit_rejections_prevent_paid_stream_and_storage(live_worker, blocked):
    case = live_worker
    if blocked == "safety":
        case.safety.side_effect = None
        case.safety.return_value = SimpleNamespace(approved=False, user_facing_message="Unavailable")
    else:
        case.credits.side_effect = RuntimeError("Insufficient credits")
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)
    assert result["status"] == "error"
    assert not case.stream_calls
    case.client_factory.assert_not_called()
    assert "billable_character_count" not in case.row
    assert_no_storage(case)


# contract-test: direct surface=rest_api assertions=assistant-speech.billing.segment-success-once,assistant-speech.execution.first-segment-progressive,video-call.audio.intentional-interruption
@pytest.mark.parametrize("kind,sequence", [("voice_prose_clause", 0), ("waiting_confirmation", -1)])
async def test_hangup_after_completed_stream_settles_exact_execution_once_without_more_audio(live_worker, monkeypatch, kind, sequence):
    case = live_worker
    case.arguments.update(kind=kind, sequence=sequence)
    case.row.update(kind=kind, sequence=sequence)
    generate = case.module.generate_live_speech
    authority_checks_at_hangup = []
    async def completed_then_hangup(**kwargs):
        completion = await generate(**kwargs)
        # Provider done, final active check and live end publication have all
        # happened. Hangup wins before the worker persists its completion row.
        assert case.stream_closed and case.events[-1]["payload"]["phase"] == "end"
        case.row["status"] = "cancelled"
        case.admission.side_effect = RuntimeError("Call is inactive")
        authority_checks_at_hangup.append(case.admission.await_count)
        case.timeline.append("hangup")
        return completion
    monkeypatch.setattr(case.module, "generate_live_speech", completed_then_hangup)
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)
    assert result["status"] == case.row["status"] == "ready"
    assert case.row["billable_character_count"] == len(case.arguments["speakable_text"])
    assert case.admission.await_count == authority_checks_at_hangup[0]
    assert case.timeline.index("end") < case.timeline.index("hangup") < case.timeline.index("persist:ready")
    assert [event["payload"]["phase"] for event in case.events if event["type"] == "assistant_speech_audio"] == ["start", "chunk", "chunk", "end"]
    assert len([data for _, data in case.writes if data.get("status") == "ready"]) == 1
    case.billing.assert_called_once()
    before = len(case.events)
    redelivery = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)
    assert redelivery == result and len(case.events) == before and len(case.stream_calls) == 1
    case.billing.assert_called_once()
    assert_no_storage(case)
