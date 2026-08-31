# backend/apps/audio/assistant_speech/worker.py
#
# Per-segment assistant-response speech orchestration.
# Dependencies are injected so provider, encrypted storage, and billing remain
# separate from this transient plaintext boundary and easy to test in isolation.
# Results deliberately exclude source text, raw audio bytes, and provider data.

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

SafetyCheck = Callable[..., Awaitable[Mapping[str, object]]]
ProviderGenerate = Callable[..., Awaitable[Mapping[str, object]]]
StoreEncrypted = Callable[..., Awaitable[Mapping[str, str]]]
ChargeUsage = Callable[..., Awaitable[Mapping[str, str]]]


async def generate_speech_segment(
    *,
    segment: Mapping[str, object],
    voice_profile: Mapping[str, object],
    safety_check: SafetyCheck,
    provider_generate: ProviderGenerate,
    store_encrypted: StoreEncrypted,
    charge_usage: ChargeUsage,
) -> dict[str, object]:
    """Generate, encrypt, and charge exactly one approved speech segment."""
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
    audio_bytes = generated["audio_bytes"]
    duration_seconds = float(generated["duration_seconds"])
    stored_asset = await store_encrypted(audio_bytes=audio_bytes, segment_id=segment_id)
    generated_asset_id = str(stored_asset["generated_asset_id"])
    try:
        usage = await charge_usage(
            idempotency_key=_idempotency_key(segment, voice_profile),
            duration_seconds=duration_seconds,
        )
    except Exception:
        # The asset is internal until settlement succeeds. A retry can charge this
        # durable encrypted result without repeating the provider request.
        return {
            "segment_id": segment_id,
            "status": "settlement_pending",
            "pending_generated_asset_id": generated_asset_id,
            "pending_duration_seconds": duration_seconds,
            "retryable": True,
        }
    return {
        "segment_id": segment_id,
        "status": "ready",
        "generated_asset_id": generated_asset_id,
        "duration_seconds": duration_seconds,
        "billing_usage_id": usage["usage_id"],
    }


def _idempotency_key(segment: Mapping[str, object], voice_profile: Mapping[str, object]) -> str:
    return "assistant-speech:{chat}:{message}:{segment}:{source}:{profile}".format(
        chat=segment.get("chat_id", ""),
        message=segment.get("assistant_message_id", ""),
        segment=segment["segment_id"],
        source=segment.get("source_hash", ""),
        profile=voice_profile.get("profile_id", ""),
    )
