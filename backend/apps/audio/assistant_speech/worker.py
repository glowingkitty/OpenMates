# backend/apps/audio/assistant_speech/worker.py
#
# Per-segment assistant-response speech generation orchestration.
# Dependencies are injected so provider, encrypted storage, and metering remain
# separate from this transient plaintext boundary and easy to test in isolation.
# Results deliberately exclude source text, raw audio bytes, and provider data.

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

SafetyCheck = Callable[..., Awaitable[Mapping[str, object]]]
ProviderGenerate = Callable[..., Awaitable[Mapping[str, object]]]
StoreEncrypted = Callable[..., Awaitable[Mapping[str, str]]]
RecordSubmission = Callable[..., Awaitable[None]]


async def generate_speech_segment(
    *,
    segment: Mapping[str, object],
    voice_profile: Mapping[str, object],
    safety_check: SafetyCheck,
    provider_generate: ProviderGenerate,
    store_encrypted: StoreEncrypted,
    record_submission: RecordSubmission,
) -> dict[str, object]:
    """Generate and encrypt one approved speech segment for later aggregate billing."""
    segment_id = str(segment["segment_id"])
    speakable_text = str(segment["speakable_text"])
    safety = await safety_check(text=speakable_text)
    if not safety.get("approved"):
        return {
            "segment_id": segment_id,
            "status": "error",
            "error": str(safety.get("safe_error") or "Speech is unavailable for this paragraph."),
            "retryable": False,
        }

    generated = await provider_generate(text=speakable_text, voice_profile=dict(voice_profile))
    await record_submission(submitted_characters=len(speakable_text))
    audio_bytes = generated["audio_bytes"]
    duration_seconds = float(generated["duration_seconds"])
    stored_asset = await store_encrypted(audio_bytes=audio_bytes, segment_id=segment_id)
    generated_asset_id = str(stored_asset["generated_asset_id"])
    return {
        "segment_id": segment_id,
        "status": "ready",
        "generated_asset_id": generated_asset_id,
        "duration_seconds": duration_seconds,
    }
