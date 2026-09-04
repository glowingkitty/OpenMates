# backend/core/api/app/routes/handlers/websocket_handlers/assistant_speech_handler.py
#
# First-party, owner-scoped core for assistant-response speech requests.
# The future WebSocket route supplies real authorization, limits, and dispatch;
# this unit-testable handler rejects invalid work before dispatching plaintext.
# Client results retain only safe status and encrypted asset metadata.

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from backend.apps.ai.assistant_speech.streaming import _speech_source_identity

MAX_SEGMENTS_PER_REQUEST = 20
MAX_SPEAKABLE_TEXT_LENGTH = 2_000
SAFE_RESULT_FIELDS = ("segment_id", "sequence", "status", "generated_asset_id", "duration_seconds", "error", "retryable", "kind")
ASSISTANT_SPEECH_REDELIVERABLE_STATUSES = {"ready"}
ASSISTANT_SPEECH_INELIGIBLE_STATUSES = {"cancelled", "deleted", "invalidated"}
HISTORICAL_SPEECH_VOICE_PROFILE = {"key": "george", "version": 1}


async def handle_assistant_speech_request(
    *,
    user_id: str | None,
    payload: Mapping[str, object],
    authorize: Callable[..., Awaitable[Mapping[str, object]]],
    rate_limit: Callable[..., bool | Awaitable[bool]],
    budget_preflight: Callable[..., bool | Awaitable[bool]],
    dispatch: Callable[..., Awaitable[Mapping[str, object] | None]],
) -> dict[str, object]:
    """Authorize bounded transient segments and return a plaintext-free status."""
    if not user_id:
        return _error("authentication_required")

    chat_id = str(payload.get("chat_id") or "")
    assistant_message_id = str(payload.get("assistant_message_id") or "")
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        return _error("invalid_segments")
    if len(segments) > MAX_SEGMENTS_PER_REQUEST:
        return _error("too_many_segments")
    authorization = await authorize(
        user_id=user_id,
        chat_id=chat_id,
        assistant_message_id=assistant_message_id,
    )
    if authorization.get("chat_owner_id") != user_id:
        return _error("forbidden")
    if authorization.get("message_role") != "assistant":
        return _error("assistant_message_required")
    if any(not isinstance(segment, Mapping) or len(str(segment.get("speakable_text") or "")) > MAX_SPEAKABLE_TEXT_LENGTH for segment in segments):
        return _error("segment_text_too_long")
    if any(
        not isinstance(segment, Mapping)
        or not str(segment.get("speakable_text") or "").strip()
        or not isinstance(segment.get("source_version"), int)
        or not isinstance(segment.get("sequence"), int)
        or not str(segment.get("kind") or "")
        or not str(segment.get("source_hash") or "")
        for segment in segments
    ):
        return _error("canonical_segment_required")
    if not await _resolve(rate_limit(user_id=user_id, chat_id=chat_id, segment_count=len(segments))):
        return _error("rate_limited")
    for segment in segments:
        if not isinstance(segment, Mapping) or not await _resolve(
            budget_preflight(
                user_id=user_id,
                chat_id=chat_id,
                assistant_message_id=assistant_message_id,
                segment=segment,
            ),
        ):
            return _error("insufficient_budget")

    dispatched = await dispatch(
        user_id=user_id,
        chat_id=chat_id,
        assistant_message_id=assistant_message_id,
        segments=segments,
    )
    results = dispatched if isinstance(dispatched, list) else [dispatched]
    return {"status": "accepted", "segments": [_safe_result(result) for result in results if result]}


def _error(error: str) -> dict[str, str]:
    return {"status": "error", "error": error}


async def _resolve(value: bool | Awaitable[bool]) -> bool:
    return bool(await value) if inspect.isawaitable(value) else bool(value)


def _safe_result(result: Mapping[str, object]) -> dict[str, object]:
    return {field: result[field] for field in SAFE_RESULT_FIELDS if field in result}


async def handle_assistant_speech_websocket(
    *,
    manager: object,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Mapping[str, object],
    authorize: Callable[..., Awaitable[Mapping[str, object]]],
    rate_limit: Callable[..., bool | Awaitable[bool]],
    budget_preflight: Callable[..., bool | Awaitable[bool]],
    dispatch: Callable[..., Awaitable[Mapping[str, object] | None]],
    retry: Callable[..., Awaitable[Mapping[str, object] | None]],
    cancel: Callable[..., Awaitable[None]],
    delete: Callable[..., Awaitable[None]],
) -> None:
    """Route first-party request, retry, and deletion actions without echoing text."""
    action = str(payload.get("action") or "request")
    if action == "request":
        result = await handle_assistant_speech_request(
            user_id=user_id,
            payload=payload,
            authorize=authorize,
            rate_limit=rate_limit,
            budget_preflight=budget_preflight,
            dispatch=dispatch,
        )
    elif action == "retry":
        result = await handle_assistant_speech_request(
            user_id=user_id,
            payload=payload,
            authorize=authorize,
            rate_limit=rate_limit,
            budget_preflight=budget_preflight,
            dispatch=dispatch,
        )
    elif action in {"delete", "cancel"}:
        authorization = await authorize(
            user_id=user_id,
            chat_id=str(payload.get("chat_id") or ""),
            assistant_message_id=str(payload.get("assistant_message_id") or ""),
        )
        if authorization.get("chat_owner_id") != user_id:
            result = _error("forbidden")
        else:
            lifecycle_action = cancel if action == "cancel" else delete
            await lifecycle_action(user_id=user_id, chat_id=payload.get("chat_id"), assistant_message_id=payload.get("assistant_message_id"))
            result = {"status": "cancelled" if action == "cancel" else "deleted"}
    else:
        result = _error("invalid_action")
    await manager.send_personal_message({"type": "assistant_speech_status", "payload": result}, user_id, device_fingerprint_hash)


async def handle_assistant_speech_event(
    *,
    manager: Any,
    directus_service: Any,
    cache_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Mapping[str, object],
) -> None:
    """Bind the first-party WebSocket action to Directus, billing, and Celery."""
    from backend.apps.audio.pricing import (
        calculate_assistant_response_speech_credits,
    )
    from backend.apps.audio.tasks.common import ensure_audio_credit_headroom
    from backend.core.api.app.tasks.celery_config import app

    async def authorize(**kwargs: object) -> Mapping[str, object]:
        chat_id = str(kwargs["chat_id"])
        message_id = str(kwargs["assistant_message_id"])
        owned = await directus_service.chat.check_chat_ownership(chat_id, user_id)
        messages = await directus_service.get_items(
            "messages",
            params={"filter[chat_id][_eq]": chat_id, "filter[client_message_id][_eq]": message_id, "fields": "role", "limit": 1},
            no_cache=True,
        )
        return {"chat_owner_id": user_id if owned else None, "message_role": messages[0].get("role") if messages else None}

    async def rate_limit(**kwargs: object) -> bool:
        client = await cache_service.client
        if not client:
            return False
        key = f"assistant-speech:rate:{_speech_source_identity(user_id)}:{kwargs['chat_id']}"
        segment_count = int(kwargs["segment_count"])
        count = await client.incrby(key, segment_count)
        if count == segment_count:
            await client.expire(key, 60)
        return count <= MAX_SEGMENTS_PER_REQUEST

    sequence_offsets: dict[tuple[str, str, int], int] = {}

    async def find_canonical_segment(
        segment: Mapping[str, object],
        *,
        chat_id: object,
        assistant_message_id: object,
    ) -> Mapping[str, object] | None:
        text = str(segment.get("speakable_text") or "").strip()
        source_hash = _speech_source_identity(text)
        offset_key = (str(chat_id), str(assistant_message_id), int(segment["source_version"]))
        if offset_key not in sequence_offsets:
            prelude_rows = await directus_service.get_items(
                "assistant_speech_segments",
                params={
                    "filter[user_id][_eq]": user_id,
                    "filter[chat_id][_eq]": chat_id,
                    "filter[assistant_message_id][_eq]": assistant_message_id,
                    "filter[source_version][_eq]": segment["source_version"],
                    "filter[sequence][_eq]": 0,
                    "filter[kind][_eq]": "app_use_announcement",
                    "limit": 1,
                },
                no_cache=True,
            )
            sequence_offsets[offset_key] = 1 if prelude_rows else 0
        sequence_offset = sequence_offsets[offset_key]
        rows = await directus_service.get_items(
            "assistant_speech_segments",
            params={
                "filter[user_id][_eq]": user_id,
                "filter[chat_id][_eq]": chat_id,
                "filter[assistant_message_id][_eq]": assistant_message_id,
                "filter[source_version][_eq]": segment["source_version"],
                "filter[sequence][_eq]": int(segment["sequence"]) + sequence_offset,
                "filter[kind][_eq]": segment["kind"],
                "filter[source_hash][_eq]": source_hash,
                "limit": 1,
            },
            no_cache=True,
        )
        return rows[0] if rows else None

    async def get_user_vault_key_id() -> str | None:
        vault_key_id = await cache_service.get_user_vault_key_id(user_id)
        if vault_key_id:
            return str(vault_key_id)
        user_profile = await directus_service.user.get_user_profile(user_id)
        fallback = user_profile.get("vault_key_id") if user_profile else None
        return str(fallback) if fallback else None

    async def budget_preflight(**kwargs: object) -> bool:
        segment = kwargs["segment"]
        if not isinstance(segment, Mapping):
            return False
        text = str(segment.get("speakable_text") or "")
        if not text:
            return False
        existing = await find_canonical_segment(
            segment,
            chat_id=kwargs["chat_id"],
            assistant_message_id=kwargs["assistant_message_id"],
        )
        if existing and str(existing.get("status") or "") in ASSISTANT_SPEECH_REDELIVERABLE_STATUSES:
            return True
        try:
            await ensure_audio_credit_headroom(
                user_id=user_id,
                estimated_credits=calculate_assistant_response_speech_credits(submitted_characters=len(text)),
                operation_name="assistant response speech",
                log_prefix="[assistant-speech]",
            )
            return True
        except Exception:
            return False

    async def dispatch(**kwargs: object) -> list[dict[str, object]]:
        from backend.apps.audio.assistant_speech.persistence import create_manifest_and_segments, seal_speech_manifest

        segments = kwargs["segments"]
        if not isinstance(segments, list):
            return []
        safe_results: list[dict[str, object]] = []
        normalized: list[dict[str, object]] = []
        historical_by_version: dict[int, list[dict[str, object]]] = {}
        for segment in segments:
            if not isinstance(segment, Mapping):
                continue
            text = str(segment.get("speakable_text") or "").strip()
            source_hash = _speech_source_identity(text)
            row = await find_canonical_segment(
                segment,
                chat_id=kwargs["chat_id"],
                assistant_message_id=kwargs["assistant_message_id"],
            )
            if row is None:
                source_version = int(segment["source_version"])
                sequence = int(segment["sequence"])
                historical_by_version.setdefault(source_version, []).append({
                    "segment_id": hashlib.sha256(
                        f"{kwargs['chat_id']}:{kwargs['assistant_message_id']}:{source_version}:{sequence}:{source_hash}".encode(),
                    ).hexdigest(),
                    "source_version": source_version,
                    "sequence": sequence,
                    "kind": str(segment["kind"]),
                    "source_hash": source_hash,
                    "speakable_text": text,
                    "voice_profile_key": HISTORICAL_SPEECH_VOICE_PROFILE["key"],
                    "voice_profile_version": HISTORICAL_SPEECH_VOICE_PROFILE["version"],
                })
                continue
            status = str(row.get("status") or "")
            if status in ASSISTANT_SPEECH_REDELIVERABLE_STATUSES or (status == "error" and not row.get("retryable")):
                safe_results.append(_safe_result(row))
                continue
            if status in ASSISTANT_SPEECH_INELIGIBLE_STATUSES:
                continue
            normalized.append({
                "segment_id": str(row["segment_id"]),
                "source_version": int(row["source_version"]),
                "sequence": int(row["sequence"]),
                "kind": str(row["kind"]),
                "source_hash": source_hash,
                "speakable_text": text,
                "voice_profile_key": str(row["voice_profile_key"]),
                "voice_profile_version": int(row["voice_profile_version"]),
            })
        for source_version, historical_segments in historical_by_version.items():
            manifest = await create_manifest_and_segments(
                directus_service,
                user_id=user_id,
                chat_id=str(kwargs["chat_id"]),
                assistant_message_id=str(kwargs["assistant_message_id"]),
                source_version=source_version,
                voice_profile=HISTORICAL_SPEECH_VOICE_PROFILE,
                segments=historical_segments,
            )
            dispatch_ids = set(manifest["dispatch_segment_ids"])
            await seal_speech_manifest(directus_service, str(manifest["manifest_id"]))
            app.send_task(
                "apps.audio.tasks.assistant_speech_billing",
                kwargs={"arguments": {"manifest_id": str(manifest["manifest_id"])}},
                queue="app_music",
            )
            normalized.extend(segment for segment in historical_segments if segment["segment_id"] in dispatch_ids)
            for segment in historical_segments:
                if segment["segment_id"] in dispatch_ids:
                    continue
                row = await find_canonical_segment(
                    segment,
                    chat_id=kwargs["chat_id"],
                    assistant_message_id=kwargs["assistant_message_id"],
                )
                if row:
                    safe_results.append(_safe_result(row))
        user_vault_key_id = await get_user_vault_key_id() if normalized else None
        for segment in normalized:
            if not user_vault_key_id:
                safe_results.append({"segment_id": segment["segment_id"], "status": "error", "error": "Speech is temporarily unavailable.", "retryable": True})
                continue
            app.send_task("apps.audio.tasks.assistant_speech_segment", kwargs={"arguments": {**segment, "user_id": user_id, "user_vault_key_id": user_vault_key_id, "chat_id": kwargs["chat_id"], "assistant_message_id": kwargs["assistant_message_id"]}}, queue="app_music")
        queued = (
            {
                "segment_id": segment["segment_id"],
                "sequence": segment["sequence"],
                "kind": segment["kind"],
                "status": "queued",
            }
            for segment in normalized
            if user_vault_key_id
        )
        return [*safe_results, *queued]

    async def retry(**kwargs: object) -> Mapping[str, object] | None:
        segment_ids = kwargs.get("segment_ids")
        if not isinstance(segment_ids, list) or not segment_ids:
            return None
        rows = await directus_service.get_items(
            "assistant_speech_segments",
            params={
                "filter[user_id][_eq]": user_id,
                "filter[chat_id][_eq]": kwargs["chat_id"],
                "filter[assistant_message_id][_eq]": kwargs["assistant_message_id"],
                "filter[status][_eq]": "error",
                "filter[retryable][_eq]": True,
                "filter[segment_id][_in]": ",".join(str(segment_id) for segment_id in segment_ids),
                "limit": MAX_SEGMENTS_PER_REQUEST,
            },
            no_cache=True,
        )
        if not rows:
            return None
        user_vault_key_id = await get_user_vault_key_id()
        if not user_vault_key_id:
            return {"segment_id": str(rows[0]["segment_id"]), "status": "error", "error": "Speech is temporarily unavailable.", "retryable": True}
        for row in rows:
            app.send_task(
                "apps.audio.tasks.assistant_speech_segment",
                kwargs={
                    "arguments": {
                        "segment_id": row["segment_id"],
                        "user_id": user_id,
                        "user_vault_key_id": user_vault_key_id,
                        "chat_id": kwargs["chat_id"],
                        "assistant_message_id": kwargs["assistant_message_id"],
                        "source_hash": row["source_hash"],
                        "voice_profile_key": row["voice_profile_key"],
                        "voice_profile_version": row["voice_profile_version"],
                    },
                },
                queue="app_music",
            )
        return {"segment_id": str(rows[0]["segment_id"]), "status": "queued"}

    async def delete(**kwargs: object) -> None:
        from backend.apps.audio.assistant_speech.persistence import tombstone_speech_assets

        await tombstone_speech_assets(
            directus_service,
            user_id=user_id,
            chat_id=str(kwargs["chat_id"]),
            assistant_message_id=str(kwargs["assistant_message_id"]),
        )
        app.send_task(
            "apps.audio.tasks.assistant_speech_delete",
            kwargs={"arguments": {"user_id": user_id, "chat_id": str(kwargs["chat_id"]), "assistant_message_id": str(kwargs["assistant_message_id"])}},
            queue="app_music",
        )

    async def cancel(**kwargs: object) -> None:
        from backend.apps.audio.assistant_speech.persistence import cancel_queued_speech_assets

        await cancel_queued_speech_assets(
            directus_service,
            user_id=user_id,
            chat_id=str(kwargs["chat_id"]),
            assistant_message_id=str(kwargs["assistant_message_id"]),
        )

    await handle_assistant_speech_websocket(
        manager=manager, user_id=user_id, device_fingerprint_hash=device_fingerprint_hash, payload=payload,
        authorize=authorize, rate_limit=rate_limit, budget_preflight=budget_preflight, dispatch=dispatch, retry=retry, cancel=cancel, delete=delete,
    )
