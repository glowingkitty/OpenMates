"""Durable admission for detached embed workers.

The broker receives only a version and opaque intent ID. The transaction stores
an HMAC of the complete task invocation, so no prompt or media arguments are
persisted in the producer ledger.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from collections.abc import Mapping
from typing import Any

from backend.shared.python_utils.chat_recovery_context import (
    RequiredRecoveryOutputError, active_authenticated_direct_skill,
    active_recovery_output_context, active_legacy_output_context,
)
from backend.shared.python_utils.volatile_embed_authority import (
    EMBED_HEADER, active_volatile_ai_context, make_embed_header,
    require_live_incognito_session,
)


PRODUCER_HEADER = "openmates_output_producer"
PRODUCER_VERSION = 1


def bind_task_invocation(*, task_name: str, task_uuid: str, args: list[Any], kwargs: dict[str, Any]) -> str:
    """Bind every broker argument without retaining a raw or plain digest copy."""
    secret = os.getenv("INTERNAL_API_SHARED_TOKEN")
    if not secret:
        raise RuntimeError("Internal producer binding key is unavailable")
    body = json.dumps(
        {"task_name": task_name, "task_uuid": task_uuid, "args": args, "kwargs": kwargs},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


async def _transaction(operation: str, data: Mapping[str, Any]) -> dict[str, Any]:
    from backend.core.api.app.services.chat_recovery_service import ChatRecoveryService
    from backend.core.api.app.services.directus import DirectusService

    directus = DirectusService()
    try:
        return await ChatRecoveryService(directus).execute(operation, data)
    finally:
        await directus.close()


async def dispatch_recoverable_embed_task(
    producer: Any, *, task_name: str, queue: str,
    args: list[Any] | None = None, kwargs: dict[str, Any] | None = None,
    owner_id: str, target_chat_id: str, message_id: str, embed_id: str,
    output_kind: str = "embed", output_version: int = 1,
    max_children: int = 32,
    task_uuid: str | None = None,
) -> Any:
    """Register an admitted AI task before publishing it to Celery."""
    call_args = args if args is not None else []
    call_kwargs = kwargs if kwargs is not None else {}
    task_uuid = task_uuid or str(uuid.uuid4())
    context = active_recovery_output_context.get()
    if context is None:
        raise RequiredRecoveryOutputError("Detached AI output lacks durable recovery admission")
    options: dict[str, Any] = {"task_id": task_uuid}

    owner_hash = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()
    if (
        owner_id != context.owner_id or owner_hash != context.owner_hash
        or target_chat_id != context.target_chat_id or not message_id or not embed_id
    ):
        raise RuntimeError("Detached embed identity differs from admitted AI turn")
    binding = bind_task_invocation(
        task_name=task_name, task_uuid=task_uuid, args=call_args, kwargs=call_kwargs,
    )
    result = await _transaction("register_output_producer", {
        "protocol_version": PRODUCER_VERSION,
        "task_uuid": task_uuid,
        "task_name": task_name,
        "kwargs_binding": binding,
        "hashed_user_id": context.owner_hash,
        "root_chat_id": context.root_chat_id,
        "target_chat_id": context.target_chat_id,
        "turn_id": context.turn_id,
        "preflight_id": context.preflight_id,
        "inference_task_id": context.inference_task_id,
        "chat_key_version": context.key_version,
        "primary_embed_id": embed_id,
        "primary_message_id": message_id,
        "primary_output_kind": output_kind,
        "primary_output_version": output_version,
        "max_children": max_children,
    })
    if result.get("producer_intent_id") != task_uuid or result.get("status") != "PENDING":
        raise RuntimeError("Detached embed registration did not commit")
    options["headers"] = {PRODUCER_HEADER: {
        "version": PRODUCER_VERSION, "intent_id": task_uuid,
    }}

    send_options: dict[str, Any] = {"name": task_name, "queue": queue, **options}
    if args is not None:
        send_options["args"] = call_args
    if kwargs is not None:
        send_options["kwargs"] = call_kwargs
    return producer.send_task(**send_options)


async def dispatch_authorized_direct_skill_task(
    producer: Any, *, task_name: str, queue: str,
    args: list[Any] | None = None, kwargs: dict[str, Any] | None = None,
    owner_id: str, embed_id: str, target_chat_id: str | None = None,
    message_id: str | None = None, task_uuid: str | None = None,
) -> Any:
    """Publish a REST skill only under its authenticated request principal."""
    principal = active_authenticated_direct_skill.get()
    if principal is None:
        raise RuntimeError("Authenticated direct skill principal is missing")
    expected_name = f"apps.{principal.app_id}.tasks.skill_{principal.skill_id}"
    if principal.app_id == "videos" and principal.skill_id == "create":
        expected_name = "apps.videos.tasks.render_remotion"
    if (
        task_name != expected_name or owner_id != principal.owner_id
        or hashlib.sha256(owner_id.encode()).hexdigest() != principal.owner_hash
        or not embed_id
    ):
        raise RuntimeError("Direct skill invocation differs from authenticated request")
    call_args = args if args is not None else []
    call_kwargs = kwargs if kwargs is not None else {}
    task_uuid = task_uuid or str(uuid.uuid4())
    binding = bind_task_invocation(
        task_name=task_name, task_uuid=task_uuid, args=call_args, kwargs=call_kwargs,
    )
    result = await _transaction("register_authorized_direct_skill", {
        "protocol_version": PRODUCER_VERSION,
        "task_uuid": task_uuid, "task_name": task_name, "kwargs_binding": binding,
        "actor_user_id": principal.owner_id,
        "hashed_user_id": principal.owner_hash,
        "primary_embed_id": embed_id,
        "target_chat_id": target_chat_id or None,
        "primary_message_id": message_id or None,
        "hashed_team_id": hashlib.sha256(principal.team_id.encode()).hexdigest()
        if principal.team_id else None,
    })
    if result.get("producer_intent_id") != task_uuid or result.get("status") != "DIRECT_AUTHORIZED":
        raise RuntimeError("Direct skill registration did not commit")
    options: dict[str, Any] = {
        "name": task_name, "queue": queue, "task_id": task_uuid,
        "headers": {PRODUCER_HEADER: {"version": PRODUCER_VERSION, "intent_id": task_uuid}},
    }
    if args is not None:
        options["args"] = call_args
    if kwargs is not None:
        options["kwargs"] = call_kwargs
    return producer.send_task(**options)


async def dispatch_legacy_embed_task(
    producer: Any, *, task_name: str, queue: str,
    args: list[Any] | None = None, kwargs: dict[str, Any] | None = None,
    owner_id: str, target_chat_id: str, message_id: str, embed_id: str,
    task_uuid: str | None = None,
) -> Any:
    """Register an epoch-0 output against its durable root cutover admission."""
    context = active_legacy_output_context.get()
    if context is None:
        raise RequiredRecoveryOutputError("Legacy detached output lacks cutover admission")
    if (
        context.owner_id != owner_id
        or context.owner_hash != hashlib.sha256(owner_id.encode()).hexdigest()
        or context.target_chat_id != target_chat_id
        or not message_id or not embed_id
    ):
        raise RequiredRecoveryOutputError("Legacy detached identity mismatch")
    call_args = args if args is not None else []
    call_kwargs = kwargs if kwargs is not None else {}
    task_uuid = task_uuid or str(uuid.uuid4())
    binding = bind_task_invocation(
        task_name=task_name, task_uuid=task_uuid, args=call_args, kwargs=call_kwargs,
    )
    result = await _transaction("register_legacy_output_producer", {
        "protocol_version": PRODUCER_VERSION,
        "task_uuid": task_uuid, "task_name": task_name, "kwargs_binding": binding,
        "actor_user_id": context.owner_id, "hashed_user_id": context.owner_hash,
        "legacy_task_identity": context.legacy_task_identity,
        "root_chat_id": context.root_chat_id,
        "target_chat_id": context.target_chat_id,
        "root_turn_id": context.root_turn_id,
        "root_user_message_id": context.root_user_message_id,
        "primary_message_id": message_id, "primary_embed_id": embed_id,
    })
    if result.get("producer_intent_id") != task_uuid or result.get("status") != "LEGACY_AUTHORIZED":
        raise RequiredRecoveryOutputError("Legacy detached registration did not commit")
    options: dict[str, Any] = {
        "name": task_name, "queue": queue, "task_id": task_uuid,
        "headers": {PRODUCER_HEADER: {"version": PRODUCER_VERSION, "intent_id": task_uuid}},
    }
    if args is not None:
        options["args"] = call_args
    if kwargs is not None:
        options["kwargs"] = call_kwargs
    return producer.send_task(**options)


async def dispatch_volatile_embed_task(
    producer: Any, *, task_name: str, queue: str,
    args: list[Any] | None = None, kwargs: dict[str, Any] | None = None,
    owner_id: str, target_chat_id: str, message_id: str, embed_id: str,
    task_uuid: str | None = None,
) -> Any:
    """Sign exact ephemeral work; never create a persisted chat/output record."""
    context = active_volatile_ai_context.get()
    if context is None:
        raise RequiredRecoveryOutputError("Volatile detached output lacks signed admission")
    if context.mode == "incognito":
        try:
            await require_live_incognito_session(
                context.session_nonce or "", context.owner_hash,
            )
        except ValueError as exc:
            raise RequiredRecoveryOutputError("Incognito live session closed") from exc
    call_args = args if args is not None else []
    call_kwargs = kwargs if kwargs is not None else {}
    task_uuid = task_uuid or str(uuid.uuid4())
    binding = bind_task_invocation(
        task_name=task_name, task_uuid=task_uuid, args=call_args, kwargs=call_kwargs,
    )
    header = make_embed_header(
        context, task_uuid=task_uuid, task_name=task_name,
        kwargs_binding=binding, owner_id=owner_id, chat_id=target_chat_id,
        message_id=message_id, embed_id=embed_id,
    )
    options: dict[str, Any] = {
        "name": task_name, "queue": queue, "task_id": task_uuid,
        "headers": {EMBED_HEADER: header},
    }
    if args is not None:
        options["args"] = call_args
    if kwargs is not None:
        options["kwargs"] = call_kwargs
    return producer.send_task(**options)
