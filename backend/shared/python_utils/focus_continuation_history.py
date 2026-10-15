"""Rebuild a Focus continuation from its exact admitted user turn."""

import json
from datetime import datetime, timezone
from typing import Any

from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key


class FocusContinuationHistoryError(Exception):
    """A stale or incomplete source turn must never be replayed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def source_user_message_id(pending_context: dict[str, Any]) -> str:
    source_id = pending_context.get("agentic_context_turn_id") or pending_context.get("message_id")
    if not isinstance(source_id, str) or not source_id:
        raise FocusContinuationHistoryError("missing_source_turn")
    return source_id


def _row_ids(row: dict[str, Any]) -> set[str]:
    return {
        value for key in ("id", "message_id", "client_message_id", "clientMessageId")
        if isinstance(value := row.get(key), str) and value
    }


def _is_activation_message(content: str) -> bool:
    return '"type":"focus_mode_activation"' in content or '"type": "focus_mode_activation"' in content


def _decoded_rows(cached: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for serialized in cached:
        try:
            row = json.loads(serialized)
        except (TypeError, ValueError):
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


async def current_focus_source_turn(cache_service: Any, pending_context: dict[str, Any]) -> bool:
    """Check both cached user order and the latest-turn key before dispatch."""
    try:
        source_id = source_user_message_id(pending_context)
    except FocusContinuationHistoryError:
        return False
    user_id = pending_context.get("user_id")
    chat_id = pending_context.get("chat_id")
    if not isinstance(user_id, str) or not user_id or not isinstance(chat_id, str) or not chat_id:
        return False
    rows = _decoded_rows(await cache_service.get_ai_messages_history(user_id, chat_id))
    matching = [index for index, row in enumerate(rows) if source_id in _row_ids(row)]
    if len(matching) != 1 or rows[matching[0]].get("role") != "user":
        return False
    if any(row.get("role") == "user" for row in rows[:matching[0]]):
        return False
    return await cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id)) == source_id


async def rebuild_focus_continuation_history(
    *, cache_service: Any, encryption_service: Any, pending_context: dict[str, Any],
    user_vault_key_id: str,
) -> list[dict[str, Any]]:
    user_id = pending_context.get("user_id")
    chat_id = pending_context.get("chat_id")
    source_id = source_user_message_id(pending_context)
    if not isinstance(user_id, str) or not user_id or not isinstance(chat_id, str) or not chat_id:
        raise FocusContinuationHistoryError("missing_source_turn")
    latest = await cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id))
    if latest != source_id:
        raise FocusContinuationHistoryError("stale_source_turn")
    cached = await cache_service.get_ai_messages_history(user_id, chat_id)
    rows = _decoded_rows(cached)
    matching = [index for index, row in enumerate(rows) if source_id in _row_ids(row)]
    if len(matching) != 1:
        raise FocusContinuationHistoryError("ambiguous_source_turn" if matching else "missing_source_turn")
    source_index = matching[0]
    if rows[source_index].get("role") != "user":
        raise FocusContinuationHistoryError("invalid_source_turn")
    if any(row.get("role") == "user" for row in rows[:source_index]):
        raise FocusContinuationHistoryError("stale_source_turn")

    # AI cache is newest first. Discard only rows newer than the exact source,
    # including provisional assistant/control output from this pending turn.
    history: list[dict[str, Any]] = []
    for row in reversed(rows[source_index:]):
        role = row.get("role")
        if role not in ("user", "assistant", "system"):
            continue
        encrypted = row.get("encrypted_content")
        if not isinstance(encrypted, str) or not encrypted:
            if row is rows[source_index]:
                raise FocusContinuationHistoryError("invalid_source_turn")
            continue
        try:
            content = await encryption_service.decrypt_with_user_key(encrypted, user_vault_key_id)
        except Exception as exc:
            if row is rows[source_index]:
                raise FocusContinuationHistoryError("invalid_source_turn") from exc
            continue
        if not isinstance(content, str) or not content:
            if row is rows[source_index]:
                raise FocusContinuationHistoryError("invalid_source_turn")
            continue
        if role == "assistant" and _is_activation_message(content):
            continue
        history.append({
            "role": role,
            "content": content,
            "created_at": row.get("created_at", int(datetime.now(timezone.utc).timestamp())),
            "sender_name": row.get("sender_name", role),
            "category": row.get("category"),
        })
    if not history or history[-1]["role"] != "user":
        raise FocusContinuationHistoryError("invalid_source_turn")
    if not await current_focus_source_turn(cache_service, pending_context):
        raise FocusContinuationHistoryError("stale_source_turn")
    return history


async def publish_current_focus_continuation_failure(
    cache_service: Any, pending_context: dict[str, Any],
) -> bool:
    """Send a fixed owner-scoped terminal error only for the still-current turn."""
    try:
        source_id = source_user_message_id(pending_context)
    except FocusContinuationHistoryError:
        return False
    user_id = pending_context.get("user_id")
    chat_id = pending_context.get("chat_id")
    if not isinstance(user_id, str) or not user_id or not isinstance(chat_id, str) or not chat_id:
        return False
    cached = await cache_service.get_ai_messages_history(user_id, chat_id)
    rows = _decoded_rows(cached)
    matching = [index for index, row in enumerate(rows) if source_id in _row_ids(row)]
    if matching and any(row.get("role") == "user" for row in rows[:matching[0]]):
        return False
    if await cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id)) != source_id:
        return False
    published = await cache_service.publish_event(f"user_cache_events:{user_id}", {
        "event_type": "focus_mode_continuation_failed",
        "payload": {
            "chat_id": chat_id,
            "user_message_id": source_id,
        },
    })
    return bool(published)


FOCUS_AUTHORITY_TTL = 600


def focus_authority_root(request, execution_id: str) -> str:
    """Only internal Focus continuations resolve to their admitted root."""
    if request.is_focus_mode_continuation:
        return (getattr(request, "_focus_authority_task_id", None)
                or request.resolved_recovery_inference_task_id() or execution_id)
    return execution_id


def focus_authority_phase_key(user_id: str, chat_id: str, root_id: str) -> str:
    return f"focus_authority_phase:{user_id}:{chat_id}:{root_id}"


async def bind_focus_execution(cache, request, execution_id: str) -> None:
    if request.is_focus_mode_continuation:
        raw = await cache.get(f"focus_execution_root:{request.user_id}:{request.chat_id}:{execution_id}")
        if raw:
            mapped = json.loads(raw)
            if (mapped.get('request', {}).get('user_id') != request.user_id
                    or mapped.get('request', {}).get('chat_id') != request.chat_id
                    or mapped.get('request', {}).get('message_id') != request.message_id):
                raise RuntimeError("Focus continuation authority scope changed")
            object.__setattr__(request, '_focus_authority_task_id', mapped['root_id'])
    root_id = focus_authority_root(request, execution_id)
    if root_id == execution_id:
        return
    if await cache.get_active_ai_task(request.chat_id) != root_id:
        raise RuntimeError("Focus continuation no longer owns admitted authority")
    client = await cache.client
    key = focus_authority_phase_key(request.user_id, request.chat_id, root_id)
    changed = await client.eval(
        "if redis.call('GET',KEYS[2]) ~= ARGV[2] or redis.call('GET',KEYS[1]) == 'expired' then return 0 end "
        "redis.call('SET',KEYS[1],ARGV[3],'EX',ARGV[1]); return 1", 2,
        key, cache._get_active_task_key(request.chat_id), FOCUS_AUTHORITY_TTL, root_id,
        f"running:{execution_id}",
    )
    if not changed:
        raise RuntimeError("Focus continuation authority expired")
    envelope = focus_cleanup_envelope(request)
    await cache.set(f"focus_execution_root:{request.user_id}:{request.chat_id}:{execution_id}",
                    json.dumps({"root_id": root_id, "request": envelope}), ttl=FOCUS_AUTHORITY_TTL)


async def retain_focus_authority(cache, request, task_id: str, skill_config: dict) -> None:
    root_id = focus_authority_root(request, task_id)
    client = await cache.client
    await client.eval(
        "if redis.call('GET',KEYS[2]) ~= ARGV[1] then return 0 end "
        "local phase = redis.call('GET',KEYS[1]); "
        "if not phase or phase == ARGV[2] then "
        "redis.call('SET',KEYS[1],ARGV[3],'EX',ARGV[4]); return 1 end return 0", 2,
        focus_authority_phase_key(request.user_id, request.chat_id, root_id),
        cache._get_active_task_key(request.chat_id), root_id, f"running:{task_id}",
        f"pending:{task_id}", FOCUS_AUTHORITY_TTL,
    )
    # No user text, private context, keys or credentials enter this watchdog payload.
    envelope = focus_cleanup_envelope(request)
    await cache.set(f"focus_execution_root:{request.user_id}:{request.chat_id}:{task_id}",
                    json.dumps({"root_id": root_id, "request": envelope}), ttl=FOCUS_AUTHORITY_TTL)
    from backend.apps.ai.tasks.focus_mode_auto_confirm_task import expire_focus_authority
    expire_focus_authority.apply_async(kwargs={'request_envelope': envelope, 'root_id': root_id,
                                               'skill_config_dict': skill_config, 'pause_task_id': task_id}, countdown=35,
                                      queue='app_ai', exchange='app_ai', routing_key='app_ai')


async def expire_pending_focus_authority(cache, request, root_id: str, skill_config: dict, pause_task_id: str | None = None) -> bool:
    client = await cache.client
    changed = await client.eval(
        "if redis.call('GET',KEYS[1]) ~= ARGV[2] then return 0 end "
        "redis.call('SET',KEYS[1],'expired','EX',ARGV[1]); return 1", 1,
        focus_authority_phase_key(request.user_id, request.chat_id, root_id), FOCUS_AUTHORITY_TTL,
        f"pending:{pause_task_id or root_id}",
    )
    if not changed:
        return False
    from backend.apps.ai.tasks.ask_skill_task import _cleanup_on_task_failure
    if request.is_focus_mode_continuation:
        object.__setattr__(request, "_focus_authority_task_id", root_id)
    await _cleanup_on_task_failure(
        task_id=root_id, chat_id=request.chat_id, message_id=request.message_id,
        user_id=request.user_id, user_id_hash=request.user_id_hash,
        user_vault_key_id=await cache.get_user_vault_key_id(request.user_id),
        error_message="Focus continuation did not start before activation expired",
        cache_service=cache, request_data=request, skill_config_dict=skill_config,
    )
    return True


def focus_cleanup_envelope(request) -> dict:
    fields = ('user_id', 'user_id_hash', 'chat_id', 'message_id', 'team_id', 'team_id_hash',
              'recovery_task_id', 'recovery_inference_task_id', 'recovery_preflight_id',
              'is_focus_mode_continuation', 'is_incognito', 'is_external',
              'legacy_cutover_task_id', 'root_legacy_cutover_task_id', 'volatile_dispatch_task_id',
              'root_user_message_id', 'root_chat_id')
    return {**{field: getattr(request, field) for field in fields}, 'message_history': []}


async def cancel_focus_execution(cache, user_id: str, chat_id: str, execution_id: str) -> bool:
    raw = await cache.get(f"focus_execution_root:{user_id}:{chat_id}:{execution_id}")
    if not raw:
        return False
    try:
        value = json.loads(raw)
        from backend.apps.ai.skills.ask_skill import AskSkillRequest
        request = AskSkillRequest.model_validate(value['request'])
        root_id = value['root_id']
        object.__setattr__(request, '_focus_authority_task_id', root_id)
    except (TypeError, ValueError, KeyError):
        return False
    if (request.user_id != user_id or request.chat_id != chat_id
            or focus_authority_root(request, execution_id) != root_id
            or await cache.get_active_ai_task(chat_id) != root_id):
        return False
    client = await cache.client
    await client.set(focus_authority_phase_key(user_id, chat_id, root_id), 'expired', ex=FOCUS_AUTHORITY_TTL)
    await client.eval(
        "if redis.call('GET',KEYS[1]) == ARGV[1] then "
        "redis.call('SET',KEYS[1],ARGV[2],'EX',ARGV[3]); return 1 end return 0", 1,
        async_skill_latest_user_turn_key(user_id, chat_id), request.message_id,
        f"cancelled:{execution_id}", FOCUS_AUTHORITY_TTL,
    )
    from backend.apps.ai.tasks.ask_skill_task import _cleanup_on_task_failure
    from backend.apps.ai.tasks.focus_mode_auto_confirm_task import _load_ask_skill_config_from_app_yml
    await _cleanup_on_task_failure(
        task_id=execution_id, chat_id=chat_id, message_id=request.message_id,
        user_id=user_id, user_id_hash=request.user_id_hash,
        user_vault_key_id=await cache.get_user_vault_key_id(user_id),
        error_message="Focus continuation cancelled", cache_service=cache,
        request_data=request, skill_config_dict=_load_ask_skill_config_from_app_yml(),
        use_cancelled_status=True,
    )
    return True


async def prepare_focus_continuation_authority(cache, pending_context: dict, request_data: dict) -> str:
    """Bind a server-created child ID without inventing durable recovery metadata."""
    import uuid
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    root_id = (pending_context.get('focus_authority_task_id')
               or pending_context.get('recovery_inference_task_id') or pending_context.get('task_id'))
    if not isinstance(root_id, str) or not root_id:
        raise RuntimeError("Focus activation lacks admitted authority")
    child_id = str(uuid.uuid4())
    request_data['root_legacy_cutover_task_id'] = (
        pending_context.get('root_legacy_cutover_task_id') or pending_context.get('legacy_cutover_task_id')
    )
    request_data['root_user_message_id'] = pending_context.get('root_user_message_id') or pending_context.get('message_id')
    request = AskSkillRequest.model_validate(request_data)
    stored = await cache.set(f"focus_execution_root:{request.user_id}:{request.chat_id}:{child_id}",
                             json.dumps({'root_id': root_id, 'request': focus_cleanup_envelope(request)}),
                             ttl=FOCUS_AUTHORITY_TTL)
    if stored is False:
        raise RuntimeError("Focus continuation authority mapping could not be stored")
    return child_id
