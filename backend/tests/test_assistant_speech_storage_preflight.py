"""Speech preflight retries remain strictly before paid or ambiguous work."""

from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
import sys

from botocore.exceptions import ReadTimeoutError
from fastapi import HTTPException
import pytest


@pytest.fixture
def speech_preflight(monkeypatch):
    """Run the real task and S3 availability probe with local boundary doubles."""
    from backend.apps.audio.assistant_speech import segment_task
    from backend.core.api.app.services.s3.service import S3UploadService

    row = {"id": "row", "segment_id": "opening", "sequence": -1, "status": "queued"}

    class Directus:
        async def get_items(self, _collection, **_kwargs):
            return [row]

        async def update_item_if_version(self, _collection, _id, data, version, **kwargs):
            if row.get("execution_version", 0) != version:
                return None
            if any(row.get(key) != value for key, value in kwargs.get("extra_filters", {}).items()):
                return None
            row.update(data)
            return row

    storage = S3UploadService.__new__(S3UploadService)
    storage.configured = True
    storage.environment = "development"
    storage.availability_client = SimpleNamespace(head_bucket=Mock(return_value={}))
    task = SimpleNamespace(
        initialize_core_services=AsyncMock(), _directus_service=Directus(),
        _cache_service=SimpleNamespace(publish_event=AsyncMock()),
        _secrets_manager=object(), _s3_service=storage,
    )
    safety = AsyncMock(return_value=SimpleNamespace(approved=True, user_facing_message=""))
    safety_module = ModuleType("backend.apps.audio.skills.speak_skill")
    safety_module.classify_audio_speech_safety = safety
    monkeypatch.setitem(sys.modules, safety_module.__name__, safety_module)
    provider = AsyncMock(return_value=SimpleNamespace(
        audio_bytes=b"speech", duration_seconds=1, mime_type="audio/mpeg",
    ))
    store = AsyncMock()
    credits = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr(segment_task, "resolve_assistant_voice_profile", lambda *_args, **_kwargs: SimpleNamespace(
        key="george", version=2, model="voxtral-mini-tts-3-0", provider="mistral",
        mistral_request=lambda: {"voice_id": "voice", "model": "voxtral-mini-tts-3-0"},
    ))
    monkeypatch.setattr(segment_task, "MistralSpeechClient", lambda **_kwargs: SimpleNamespace(text_to_speech=provider))
    monkeypatch.setattr(segment_task, "store_generated_audio_asset", store)
    monkeypatch.setattr(segment_task, "ensure_audio_credit_headroom", credits)
    monkeypatch.setattr(segment_task.asyncio, "sleep", sleep)
    arguments = {
        "segment_id": "opening", "user_id": "owner", "chat_id": "chat",
        "assistant_message_id": "answer", "speakable_text": "Let me check that.",
        "voice_profile_key": "george", "voice_profile_version": 2,
        "kind": "waiting_confirmation",
    }
    return SimpleNamespace(
        module=segment_task, task=task, row=row, arguments=arguments,
        probe=storage.availability_client.head_bucket, provider=provider,
        store=store, safety=safety, credits=credits, sleep=sleep,
    )


def read_timeout():
    """Match the provider exception sanitized by the actual S3 health probe."""
    return ReadTimeoutError(endpoint_url="https://storage.invalid")


# contract-test: direct surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,assistant-speech.billing.segment-success-once,assistant-speech.execution.first-segment-progressive,storage-resilience.operations.fail-before-cost
async def test_opening_speech_recovers_one_preflight_read_timeout_without_replaying_paid_work(speech_preflight):
    case = speech_preflight
    case.probe.side_effect = [read_timeout(), {}]
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)
    redelivery = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)

    assert result["status"] == redelivery["status"] == "ready"
    assert result["sequence"] == -1
    assert result["generated_asset_id"] == redelivery["generated_asset_id"]
    assert case.probe.call_count == 2
    case.sleep.assert_awaited_once_with(case.module.STORAGE_PREFLIGHT_RETRY_SECONDS)
    case.safety.assert_awaited_once()
    case.credits.assert_awaited_once()
    case.provider.assert_awaited_once()
    case.store.assert_awaited_once()


# contract-test: direct surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,storage-resilience.operations.fail-before-cost
async def test_persistent_storage_failure_stops_after_one_preflight_retry(speech_preflight):
    case = speech_preflight
    case.probe.side_effect = read_timeout()
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)

    assert result["status"] == "error"
    assert result["retryable"] is True
    assert case.probe.call_count == 2
    case.sleep.assert_awaited_once()
    case.safety.assert_not_awaited()
    case.credits.assert_not_awaited()
    case.provider.assert_not_awaited()
    case.store.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=assistant-speech.failure.nonblocking-visible-resumable,video-call.audio.intentional-interruption,storage-resilience.operations.fail-before-cost
@pytest.mark.parametrize("change,expected_status", [("cancelled", "cancelled"), ("new-lease", "queued")])
async def test_preflight_retry_rechecks_cancellation_and_execution_lease(speech_preflight, change, expected_status):
    case = speech_preflight
    case.probe.side_effect = [read_timeout(), {}]

    async def interrupt(_delay):
        case.row.update({"status": "cancelled"} if change == "cancelled" else {"lease_id": "new-owner"})

    case.sleep.side_effect = interrupt
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)

    assert result == {"segment_id": "opening", "status": expected_status}
    assert case.probe.call_count == 1
    case.safety.assert_not_awaited()
    case.credits.assert_not_awaited()
    case.provider.assert_not_awaited()
    case.store.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=storage-resilience.operations.fail-before-cost
async def test_nonstorage_preflight_failure_is_not_retried(speech_preflight, monkeypatch):
    case = speech_preflight
    guard = AsyncMock(side_effect=HTTPException(status_code=403, detail="Forbidden"))
    monkeypatch.setattr(case.module, "require_storage_available", guard)
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)

    assert result["status"] == "error"
    guard.assert_awaited_once()
    case.sleep.assert_not_awaited()
    case.provider.assert_not_awaited()
    case.store.assert_not_awaited()


# contract-test: direct surface=rest_api assertions=assistant-speech.billing.segment-success-once,assistant-speech.failure.nonblocking-visible-resumable
@pytest.mark.parametrize("failure_boundary", ["provider", "store"])
async def test_storage_error_after_submission_never_replays_provider_or_upload(speech_preflight, failure_boundary):
    from backend.shared.python_utils.storage_availability import storage_unavailable_error

    case = speech_preflight
    getattr(case, failure_boundary).side_effect = storage_unavailable_error()
    result = await case.module._async_generate_assistant_speech_segment(case.task, case.arguments)

    assert result["status"] == "error"
    assert case.probe.call_count == 1
    case.sleep.assert_not_awaited()
    case.provider.assert_awaited_once()
    assert case.store.await_count == (1 if failure_boundary == "store" else 0)
