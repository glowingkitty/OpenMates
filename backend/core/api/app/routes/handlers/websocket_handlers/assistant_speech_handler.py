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

from backend.apps.ai.assistant_speech.projection import speech_fallback_variants, project_final_voice_clauses
from backend.apps.ai.assistant_speech.streaming import _speech_source_identity

MAX_SEGMENTS_PER_REQUEST = 20
MAX_VOICE_REPLAY_CLAUSES = 256
MAX_SOURCE_MARKDOWN_LENGTH = 256_000
MAX_SPEAKABLE_TEXT_LENGTH = 2_000
SAFE_RESULT_FIELDS = ("segment_id", "sequence", "request_sequence", "status", "generated_asset_id", "duration_seconds", "error", "retryable", "kind")
ASSISTANT_SPEECH_REDELIVERABLE_STATUSES = {"ready"}
ASSISTANT_SPEECH_INELIGIBLE_STATUSES = {"cancelled", "deleted", "invalidated"}
HISTORICAL_SPEECH_VOICE_PROFILE = {"key": "george", "version": 2}
# This in-process marker cannot be supplied by an untrusted JSON request.
_VERIFIED_VOICE_SOURCE = object()


async def handle_assistant_speech_request(
    *,
    user_id: str | None,
    payload: Mapping[str, object],
    authorize: Callable[..., Awaitable[Mapping[str, object]]],
    rate_limit: Callable[..., bool | Awaitable[bool]],
    budget_preflight: Callable[..., bool | Awaitable[bool]],
    dispatch: Callable[..., Awaitable[Mapping[str, object] | None]],
    resolve_segments: Callable[..., Awaitable[list[Mapping[str, object]] | None]] | None = None,
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
    if resolve_segments is not None:
        try:
            resolved = await resolve_segments(chat_id=chat_id, assistant_message_id=assistant_message_id,
                segments=segments, source_markdown=payload.get("source_markdown"), action=payload.get("action", "request"))
        except (ValueError, TypeError):
            return _error("speech_source_no_longer_current")
        if resolved is not None:
            segments = resolved
            if not segments or len(segments) > MAX_VOICE_REPLAY_CLAUSES:
                return _error("invalid_segments")
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
    # Deferred rows register chapter identities without starting provider work.
    # Charging the whole batch here exhausts the quota before chapter two of a
    # 20-paragraph response can request its audio through action=generate.
    immediate_segment_count = 1 if payload.get("defer_after_first") else len(segments)
    if not await _resolve(rate_limit(user_id=user_id, chat_id=chat_id, segment_count=immediate_segment_count)):
        return _error("rate_limited")
    for index, segment in enumerate(segments):
        if payload.get("defer_after_first") and index > 0:
            continue
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
        defer_after_first=bool(payload.get("defer_after_first")),
        require_registered=payload.get("action") == "generate",
    )
    results = dispatched if isinstance(dispatched, list) else [dispatched]
    return {"status": "accepted", "chat_id": chat_id, "message_id": assistant_message_id,
            "segments": [_safe_result(result) for result in results if result]}


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
    resolve_segments: Callable[..., Awaitable[list[Mapping[str, object]] | None]] | None = None,
) -> None:
    """Route first-party request, retry, and deletion actions without echoing text."""
    action = str(payload.get("action") or "request")
    if action in {"request", "generate"}:
        result = await handle_assistant_speech_request(
            user_id=user_id,
            payload=payload,
            authorize=authorize,
            rate_limit=rate_limit,
            budget_preflight=budget_preflight,
            dispatch=dispatch,
            resolve_segments=resolve_segments,
        )
    elif action == "retry":
        result = await handle_assistant_speech_request(
            user_id=user_id,
            payload=payload,
            authorize=authorize,
            rate_limit=rate_limit,
            budget_preflight=budget_preflight,
            dispatch=dispatch,
            resolve_segments=resolve_segments,
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

    async def sequence_offset_for(*, chat_id: object, assistant_message_id: object, source_version: int) -> int:
        offset_key = (str(chat_id), str(assistant_message_id), source_version)
        if offset_key not in sequence_offsets:
            prelude_rows = await directus_service.get_items(
                "assistant_speech_segments",
                params={
                    "filter[user_id][_eq]": user_id,
                    "filter[chat_id][_eq]": chat_id,
                    "filter[assistant_message_id][_eq]": assistant_message_id,
                    "filter[source_version][_eq]": source_version,
                    "filter[sequence][_eq]": 0,
                    "filter[kind][_eq]": "app_use_announcement",
                    "limit": 1,
                },
                no_cache=True,
            )
            sequence_offsets[offset_key] = 1 if prelude_rows else 0
        return sequence_offsets[offset_key]

    async def find_canonical_segment(
        segment: Mapping[str, object],
        *,
        chat_id: object,
        assistant_message_id: object,
        excluded_segment_ids: set[str] | None = None,
    ) -> tuple[Mapping[str, object], str] | None:
        text = str(segment.get("speakable_text") or "").strip()
        source_version = int(segment["source_version"])
        request_sequence = int(segment.get("request_sequence", segment["sequence"]))
        sequence_offset = await sequence_offset_for(
            chat_id=chat_id,
            assistant_message_id=assistant_message_id,
            source_version=source_version,
        )
        base_filters = {
            "filter[user_id][_eq]": user_id,
            "filter[chat_id][_eq]": chat_id,
            "filter[assistant_message_id][_eq]": assistant_message_id,
            "filter[source_version][_eq]": source_version,
            "filter[kind][_eq]": segment["kind"],
            "filter[manifest_id][_eq]": hashlib.sha256(f"{chat_id}:{assistant_message_id}".encode()).hexdigest(),
        }
        excluded = excluded_segment_ids or set()

        def eligible(row: Mapping[str, object]) -> bool:
            return (
                str(row.get("segment_id") or "") not in excluded
                and (str(row.get("status") or "") not in ASSISTANT_SPEECH_INELIGIBLE_STATUSES
                     or row.get("status") == "cancelled" and not row.get("generated_asset_id"))
            )

        async def exact_match(candidate_text: str) -> Mapping[str, object] | None:
            rows = await directus_service.get_items(
                "assistant_speech_segments",
                params={
                    **base_filters,
                    "filter[source_hash][_eq]": _speech_source_identity(candidate_text),
                    "filter[sequence][_eq]": request_sequence + sequence_offset,
                    "limit": 1,
                },
                no_cache=True,
            )
            return next((row for row in rows if eligible(row)), None)

        async def identity_match(candidate_text: str) -> Mapping[str, object] | None:
            rows = await directus_service.get_items(
                "assistant_speech_segments",
                params={
                    **base_filters,
                    "filter[source_hash][_eq]": _speech_source_identity(candidate_text),
                    "sort": "sequence",
                    "limit": MAX_SEGMENTS_PER_REQUEST,
                },
                no_cache=True,
            )
            return next((row for row in rows if eligible(row)), None)

        row = await exact_match(text)
        if row:
            return row, text

        # Older projections could deduplicate repeated semantic summaries and
        # shift every later sequence. Content identity remains canonical within
        # this owner/message/version scope, so replay may safely recover it.
        row = await identity_match(text)
        if row:
            return row, text

        if str(segment["kind"]) in {"embed_summary", "code_summary", "table_summary"}:
            variants = tuple(candidate for candidate in speech_fallback_variants(text) if candidate != text)
            for candidate_text in variants:
                row = await exact_match(candidate_text)
                if row:
                    return row, candidate_text
            for candidate_text in variants:
                row = await identity_match(candidate_text)
                if row:
                    return row, candidate_text
        return None

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
        match = await find_canonical_segment(
            segment,
            chat_id=kwargs["chat_id"],
            assistant_message_id=kwargs["assistant_message_id"],
        )
        existing, canonical_text = match if match else (None, text)
        if existing and str(existing.get("status") or "") in ASSISTANT_SPEECH_REDELIVERABLE_STATUSES:
            return True
        try:
            await ensure_audio_credit_headroom(
                user_id=user_id,
                estimated_credits=calculate_assistant_response_speech_credits(submitted_characters=len(canonical_text)),
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
        defer_after_first = bool(kwargs.get("defer_after_first"))
        require_registered = bool(kwargs.get("require_registered"))
        first_sequence = min(int(segment["sequence"]) for segment in segments if isinstance(segment, Mapping))
        safe_results: list[dict[str, object]] = []
        normalized: list[dict[str, object]] = []
        historical_by_version: dict[int, list[dict[str, object]]] = {}
        matched_segment_ids: set[str] = set()
        for segment in segments:
            if not isinstance(segment, Mapping):
                continue
            text = str(segment.get("speakable_text") or "").strip()
            source_hash = _speech_source_identity(text)
            match = await find_canonical_segment(
                segment,
                chat_id=kwargs["chat_id"],
                assistant_message_id=kwargs["assistant_message_id"],
                excluded_segment_ids=matched_segment_ids,
            )
            if match is None:
                if require_registered:
                    safe_results.append({"sequence": int(segment["sequence"]), "status": "error", "error": "Speech source is no longer current.", "retryable": False})
                    continue
                source_version = int(segment["source_version"])
                request_sequence = int(segment["sequence"])
                sequence = request_sequence + await sequence_offset_for(
                    chat_id=kwargs["chat_id"],
                    assistant_message_id=kwargs["assistant_message_id"],
                    source_version=source_version,
                )
                historical_by_version.setdefault(source_version, []).append({
                    "segment_id": hashlib.sha256(
                        f"{kwargs['chat_id']}:{kwargs['assistant_message_id']}:{source_version}:{sequence}:{source_hash}".encode(),
                    ).hexdigest(),
                    "source_version": source_version,
                    "sequence": sequence,
                    "request_sequence": request_sequence,
                    "kind": str(segment["kind"]),
                    "source_hash": source_hash,
                    "speakable_text": text,
                    "voice_profile_key": segment["voice_profile_key"] if segment.get("_verified_voice_source") is _VERIFIED_VOICE_SOURCE else HISTORICAL_SPEECH_VOICE_PROFILE["key"],
                    "voice_profile_version": segment["voice_profile_version"] if segment.get("_verified_voice_source") is _VERIFIED_VOICE_SOURCE else HISTORICAL_SPEECH_VOICE_PROFILE["version"],
                    **({key: segment[key] for key in ("live_mock_mode", "live_mock_group", "live_mock_required") if segment.get(key)}
                       if segment.get("_verified_voice_source") is _VERIFIED_VOICE_SOURCE else {}),
                    "dispatch_status": "registered" if defer_after_first and request_sequence != first_sequence else "queued",
                })
                continue
            row, canonical_text = match
            if row.get("status") == "cancelled":
                reset = await directus_service.update_item_if_version(
                    "assistant_speech_segments", str(row.get("id") or row["segment_id"]),
                    {"status": "registered"}, int(row.get("execution_version") or 0),
                    version_field="execution_version", extra_filters={"status": "cancelled"},
                )
                if not reset:
                    safe_results.append({"segment_id": str(row["segment_id"]), "sequence": int(row["sequence"]), "status": "error", "error": "Speech is temporarily unavailable.", "retryable": True})
                    continue
                row = {**row, "status": "registered"}
            source_hash = _speech_source_identity(canonical_text)
            matched_segment_ids.add(str(row["segment_id"]))
            request_sequence = int(segment["sequence"])
            status = str(row.get("status") or "")
            if status in ASSISTANT_SPEECH_REDELIVERABLE_STATUSES or (status == "error" and not row.get("retryable")):
                safe_results.append(_safe_result({**row, "request_sequence": request_sequence}))
                continue
            should_generate = not (defer_after_first and request_sequence != first_sequence)
            if status == "registered" and should_generate:
                version = int(row.get("execution_version") or 0)
                queued = await directus_service.update_item_if_version(
                    "assistant_speech_segments", str(row.get("id") or row["segment_id"]),
                    {"status": "queued", "execution_version": version + 1}, version,
                    version_field="execution_version", extra_filters={"status": "registered"},
                )
                if not queued:
                    safe_results.append(_safe_result({**row, "status": "queued", "request_sequence": request_sequence}))
                    continue
                row = {**row, "status": "queued", "execution_version": version + 1}
            normalized.append({
                "segment_id": str(row["segment_id"]),
                "source_version": int(row["source_version"]),
                "sequence": int(row["sequence"]),
                "request_sequence": request_sequence,
                "kind": str(row["kind"]),
                "source_hash": source_hash,
                "speakable_text": canonical_text,
                "voice_profile_key": str(row["voice_profile_key"]),
                "voice_profile_version": int(row["voice_profile_version"]),
                **{key: row[key] for key in ("live_mock_mode", "live_mock_group", "live_mock_required") if row.get(key)},
                "dispatch_status": "registered" if not should_generate else "queued",
            })
        for source_version, historical_segments in historical_by_version.items():
            manifest = await create_manifest_and_segments(
                directus_service,
                user_id=user_id,
                chat_id=str(kwargs["chat_id"]),
                assistant_message_id=str(kwargs["assistant_message_id"]),
                source_version=source_version,
                voice_profile={"key": historical_segments[0]["voice_profile_key"],
                               "version": historical_segments[0]["voice_profile_version"]},
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
                    matched_segment_ids.add(str(segment["segment_id"]))
                    continue
                match = await find_canonical_segment(
                    segment,
                    chat_id=kwargs["chat_id"],
                    assistant_message_id=kwargs["assistant_message_id"],
                    excluded_segment_ids=matched_segment_ids,
                )
                if match:
                    row, _canonical_text = match
                    matched_segment_ids.add(str(row["segment_id"]))
                    safe_results.append(_safe_result({**row, "request_sequence": segment["request_sequence"]}))
                else:
                    safe_results.append({
                        "segment_id": segment["segment_id"],
                        "sequence": segment["sequence"],
                        "request_sequence": segment["request_sequence"],
                        "kind": segment["kind"],
                        "status": "error",
                        "error": "Speech is temporarily unavailable.",
                        "retryable": False,
                    })
        user_vault_key_id = await get_user_vault_key_id() if normalized else None
        for segment in normalized:
            if segment.get("dispatch_status") == "registered":
                continue
            if not user_vault_key_id:
                safe_results.append({"segment_id": segment["segment_id"], "sequence": segment["sequence"], "request_sequence": segment["request_sequence"], "kind": segment["kind"], "status": "error", "error": "Speech is temporarily unavailable.", "retryable": True})
                continue
            worker_segment = {key: value for key, value in segment.items() if key != "request_sequence"}
            app.send_task("apps.audio.tasks.assistant_speech_segment", kwargs={"arguments": {**worker_segment, "user_id": user_id, "user_vault_key_id": user_vault_key_id, "chat_id": kwargs["chat_id"], "assistant_message_id": kwargs["assistant_message_id"]}}, queue="app_music")
        queued = (
            {
                "segment_id": segment["segment_id"],
                "sequence": segment["sequence"],
                "request_sequence": segment["request_sequence"],
                "kind": segment["kind"],
                "status": "registered" if segment.get("dispatch_status") == "registered" else "queued",
            }
            for segment in normalized
            if user_vault_key_id or segment.get("dispatch_status") == "registered"
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
        resolve_segments=lambda **kwargs: resolve_registered_voice_segments(directus_service, user_id=user_id, **kwargs),
    )


async def resolve_registered_voice_segments(directus: Any, *, user_id: str, chat_id: str,
        assistant_message_id: str, segments: list[Mapping[str, object]],
        source_markdown: object, action: str) -> list[Mapping[str, object]] | None:
    """Authorize a separate manual cache from a call's registered source hashes.

    The owner/message/version query and server HMAC comparison are authoritative;
    client Markdown is only a candidate source and is never stored or echoed.
    """
    version = segments[0].get("source_version") if isinstance(segments[0], Mapping) else None
    rows = await directus.get_items("assistant_speech_segments", params={
        "filter[user_id][_eq]": user_id, "filter[chat_id][_eq]": chat_id,
        "filter[assistant_message_id][_eq]": assistant_message_id,
        "filter[kind][_eq]": "voice_prose_clause",
        "filter[manifest_id][_neq]": hashlib.sha256(f"{chat_id}:{assistant_message_id}".encode()).hexdigest(),
        "sort": "sequence", "limit": MAX_VOICE_REPLAY_CLAUSES + 1,
    }, no_cache=True)
    if not rows:
        if any(segment.get("kind") == "voice_prose_clause" for segment in segments):
            raise ValueError("Voice source is not registered")
        return None
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("Voice replay requires canonical source version")
    rows = [row for row in rows if row.get("source_version") == version]
    if not rows:
        raise ValueError("Voice source version is unavailable")
    if not isinstance(source_markdown, str) or len(source_markdown) > MAX_SOURCE_MARKDOWN_LENGTH:
        raise ValueError("Voice replay requires bounded canonical source")
    candidates: dict[str, list[str]] = {}
    for text in project_final_voice_clauses(source_markdown):
        candidates.setdefault(_speech_source_identity(text), []).append(text)
    requested_ids = {str(segment.get("segment_id")) for segment in segments if segment.get("segment_id")}
    if action == "generate" and not requested_ids:
        raise ValueError("Voice generation requires canonical segment identity")
    resolved: list[Mapping[str, object]] = []
    for row in rows:
        if int(row.get("sequence", -1)) < 0 or row.get("status") in {"deleted", "invalidated"}:
            continue
        sequence = int(row["sequence"])
        manual_id = hashlib.sha256(f"{chat_id}:{assistant_message_id}:{version}:{sequence}:{row['source_hash']}".encode()).hexdigest()
        if action == "generate" and manual_id not in requested_ids:
            continue
        choices = candidates.get(str(row["source_hash"]))
        if not choices:
            raise ValueError("Canonical voice source does not match registered clauses")
        text = choices.pop(0)
        resolved.append({"segment_id": manual_id, "sequence": sequence,
            "source_version": version, "kind": "voice_prose_clause",
            "source_hash": row["source_hash"], "speakable_text": text,
            "voice_profile_key": row.get("voice_profile_key") or HISTORICAL_SPEECH_VOICE_PROFILE["key"],
            # v3 is ephemeral Eleven call speech. A separate manual cache uses
            # the same server-verified voice identity with its Mistral v2 preset.
            "voice_profile_version": (2 if row.get("voice_profile_version") == 3 else
                                      row.get("voice_profile_version") or HISTORICAL_SPEECH_VOICE_PROFILE["version"]),
            **{key: row[key] for key in ("live_mock_mode", "live_mock_group", "live_mock_required") if row.get(key)},
            "_verified_voice_source": _VERIFIED_VOICE_SOURCE})
    if not resolved or len(resolved) > MAX_VOICE_REPLAY_CLAUSES or (
        action == "generate" and {str(row["segment_id"]) for row in resolved} != requested_ids
    ):
        raise ValueError("Canonical voice source is unavailable")
    return resolved
