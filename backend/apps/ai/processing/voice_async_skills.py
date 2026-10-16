"""Explicit, owner-sealed voice admission for existing detached app workers.

The call broker supplies issued row authority after its normal safety/approval
checks. Celery receives routing identities only; the original app task still
owns generation, billing, cancellation, embed updates and provider retries.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any
import uuid

from backend.shared.python_utils.chat_recovery_context import (
    RequiredRecoveryOutputError, VerifiedOutputProducer, active_verified_output_producer,
)
from backend.shared.python_utils.embed_producer_dispatch import bind_task_invocation
from backend.shared.python_utils.voice_action_receipts import (
    RECEIPT_TTL_SECONDS, _client, _key, _owned_chat, _vault,
    admit_voice_action_receipt, load_voice_action_receipt, persist_voice_action_receipt,
    release_voice_action_admission,
)

VOICE_TASK_HEADER = "openmates_voice_output"
_IDENTITY = ("user_id", "user_hash", "session_id", "chat_id", "call_id",
             "user_message_id", "assistant_message_id", "operation_id")


@dataclass
class VoiceAsyncState:
    binding: dict[str, Any]
    request_id: str
    cache_service: Any
    directus_service: Any
    encryption_service: Any
    embed_service: Any
    dispatched: bool = False
    artifact_ids: list[str] = field(default_factory=list)
    embed_references: list[str] = field(default_factory=list)
    actions: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class VoiceWorkerContext:
    binding: dict[str, Any]
    request_id: str
    task_id: str
    task_name: str
    invocation_binding: str
    embed_id: str
    arguments: dict[str, Any]


active_voice_output_context: ContextVar[VoiceAsyncState | None] = ContextVar(
    "active_voice_output_context", default=None)
active_voice_worker_context: ContextVar[VoiceWorkerContext | None] = ContextVar(
    "active_voice_worker_context", default=None)


@asynccontextmanager
async def voice_async_output_context(*, binding: dict, request_id: str,
                                     cache_service: Any, directus_service: Any,
                                     encryption_service: Any, embed_service: Any):
    """Bind authenticated server authority, never tool-supplied arguments."""
    if (not all(isinstance(binding.get(k), str) and binding[k] for k in _IDENTITY)
            or binding["user_hash"] != hashlib.sha256(binding["user_id"].encode()).hexdigest()):
        raise RequiredRecoveryOutputError("Invalid voice output identity")
    state = VoiceAsyncState(dict(binding), request_id, cache_service, directus_service,
                            encryption_service, embed_service)
    token = active_voice_output_context.set(state)
    try:
        yield state
    finally:
        active_voice_output_context.reset(token)


async def dispatch_voice_embed_task(producer: Any, *, task_name: str, queue: str,
                                   kwargs: dict[str, Any], task_uuid: str | None = None,
                                   app_id: str | None = None, skill_id: str | None = None) -> Any:
    """Seal the exact existing task and attach its canonical processing embed."""
    from backend.shared.python_utils.embed_producer_worker import PROTECTED_EMBED_TASK_NAMES
    state = active_voice_output_context.get()
    arguments = kwargs.get("arguments", {})
    if state is None or task_name not in PROTECTED_EMBED_TASK_NAMES:
        raise RequiredRecoveryOutputError("Voice detached task lacks explicit admission")
    app_id, skill_id = app_id or kwargs.get("app_id"), skill_id or kwargs.get("skill_id")
    remotion = task_name == "apps.videos.tasks.render_remotion"
    if (remotion and (app_id, skill_id) != ("videos", "create")) or (
        not remotion and task_name != f"apps.{app_id}.tasks.skill_{skill_id}"
    ):
        raise RequiredRecoveryOutputError("Voice detached skill metadata mismatch")
    binding = state.binding
    if (arguments.get("user_id") != binding["user_id"]
            or arguments.get("chat_id") != binding["chat_id"]
            or arguments.get("message_id") != binding["assistant_message_id"]
            or arguments.get("team_id") or arguments.get("external_request")
            or not arguments.get("embed_id")):
        raise RequiredRecoveryOutputError("Voice detached task identity mismatch")
    embed_id = arguments["embed_id"]
    task_id = task_uuid or str(uuid.uuid4())
    child_binding = {**binding, "operation_id": task_id}
    child_request_id = f"voice-async:{task_id}"
    client = await _client(state.cache_service)
    # The existing committed-action permit is the server's issued-row authority.
    permit = await client.get(_key("permit", binding["user_id"], binding["session_id"], state.request_id))
    if not permit:
        raise RequiredRecoveryOutputError("Voice action was not admitted")
    if isinstance(permit, bytes):
        permit = permit.decode()
    key_id = await _vault(state.cache_service, state.directus_service, binding["user_id"])
    admitted = json.loads(await state.encryption_service.decrypt_with_user_key(permit, key_id))
    if any(admitted.get(k) != binding[k] for k in _IDENTITY) or admitted.get("request_id") != state.request_id:
        raise RequiredRecoveryOutputError("Voice action admission mismatch")
    from backend.apps.ai.processing.voice_call_broker import transport_key
    for operation in (binding["operation_id"], binding.get("request_cancel_id")):
        if operation and await client.exists(transport_key(operation, "cancel")):
            raise asyncio.CancelledError
    await _owned_chat(state.directus_service, binding["chat_id"], binding["user_hash"])
    arguments = dict(arguments, **({"vault_key_id": key_id} if remotion else {"user_vault_key_id": key_id}))
    kwargs = dict(kwargs, arguments=arguments)
    await admit_voice_action_receipt(cache_service=state.cache_service,
        directus_service=state.directus_service, encryption_service=state.encryption_service,
        binding=child_binding, request_id=child_request_id)
    try:
        common = dict(chat_id=binding["chat_id"], message_id=binding["assistant_message_id"],
            user_id=binding["user_id"], user_id_hash=binding["user_hash"],
            user_vault_key_id=key_id, task_id=task_id, embed_id=embed_id)
        if remotion:
            placeholder = await state.embed_service.create_remotion_video_embed_placeholder(
                **common, filename=arguments.get("filename"))
        else:
            placeholder = await state.embed_service.create_processing_embed_placeholder(
                **common, app_id=app_id, skill_id=skill_id, skill_task_id=task_id)
        if not placeholder or placeholder["embed_id"] != embed_id:
            raise RequiredRecoveryOutputError("Voice processing artifact unavailable")
        invocation_binding = bind_task_invocation(task_name=task_name, task_uuid=task_id, args=[], kwargs=kwargs)
        payload = dict(binding=child_binding, request_id=child_request_id, task_id=task_id,
                       task_name=task_name, invocation_binding=invocation_binding, kwargs=kwargs)
        sealed, _ = await state.encryption_service.encrypt_with_user_key(
            json.dumps(payload, separators=(",", ":")), key_id)
        if not isinstance(sealed, str) or not sealed.startswith("vault:v"):
            raise RequiredRecoveryOutputError("Voice task sealing failed")
        stored = await client.set(_key("task", binding["user_id"], task_id), sealed,
                                  ex=RECEIPT_TTL_SECONDS, nx=True)
        if not stored:
            raise RequiredRecoveryOutputError("Voice task identity already admitted")
        # The receipt retains this exact canonical placeholder even if the call
        # ends between broker acceptance and delivery of the dispatch response.
        await persist_voice_action_receipt(cache_service=state.cache_service,
            directus_service=state.directus_service, encryption_service=state.encryption_service,
            binding=child_binding, request_id=child_request_id, embed_refs=[embed_id])
        try:
            signature = producer.send_task(name=task_name, queue=queue, task_id=task_id,
                kwargs={"voice_task_ref": task_id, "user_id": binding["user_id"]},
                headers={VOICE_TASK_HEADER: {"version": 1, "task_id": task_id}})
        except Exception:
            # Publish a truthful failed placeholder; no paid task was accepted.
            await state.embed_service.update_embed_status_to_error(
                embed_id=embed_id, app_id=app_id, skill_id=skill_id,
                chat_id=binding["chat_id"], message_id=binding["assistant_message_id"],
                user_id=binding["user_id"], user_id_hash=binding["user_hash"],
                user_vault_key_id=key_id, error_message="Could not start asynchronous skill")
            await release_voice_action_admission(cache_service=state.cache_service,
                binding=child_binding, request_id=child_request_id)
            raise RequiredRecoveryOutputError("Voice task dispatch failed") from None
        state.dispatched = True
        state.artifact_ids.append(embed_id)
        state.embed_references.append(placeholder["embed_reference"])
        state.actions.append(dict(task_id=task_id, embed_id=embed_id, status="processing"))
        return signature
    except (Exception, asyncio.CancelledError):
        await release_voice_action_admission(cache_service=state.cache_service,
            binding=child_binding, request_id=child_request_id)
        raise



async def open_voice_task(*, task_name: str, task_id: str, args: tuple,
                          kwargs: dict, headers: dict, cache_service: Any,
                          directus_service: Any, encryption_service: Any) -> tuple[dict, VoiceWorkerContext]:
    """Open and verify a server-sealed invocation before paid provider work."""
    header = headers.get(VOICE_TASK_HEADER)
    if (args or set(kwargs) != {"voice_task_ref", "user_id"}
            or kwargs.get("voice_task_ref") != task_id
            or not isinstance(header, dict) or header != {"version": 1, "task_id": task_id}
            or type(header.get("version")) is not int
            or headers.get("openmates_output_producer") or headers.get("openmates_volatile_embed")):
        raise RequiredRecoveryOutputError("Invalid voice task envelope")
    owner = kwargs["user_id"]
    client = await _client(cache_service)
    # Individual skill cancellation uses the existing UI/backend task identity;
    # hangup and request speech cancellation do not cancel an accepted job.
    from backend.apps.ai.processing.skill_executor import CANCELLED_SKILLS_KEY_PREFIX
    if await client.exists(f"{CANCELLED_SKILLS_KEY_PREFIX}{task_id}"):
        raise RequiredRecoveryOutputError("Voice asynchronous skill individually cancelled")
    sealed = await client.get(_key("task", owner, task_id))
    if not sealed:
        raise RequiredRecoveryOutputError("Voice task admission unavailable")
    if isinstance(sealed, bytes):
        sealed = sealed.decode()
    plaintext = await encryption_service.decrypt_with_user_key(
        sealed, await _vault(cache_service, directus_service, owner))
    payload = json.loads(plaintext) if plaintext else {}
    binding, invocation = payload.get("binding", {}), payload.get("kwargs", {})
    arguments = invocation.get("arguments", {})
    expected = bind_task_invocation(task_name=task_name, task_uuid=task_id, args=[], kwargs=invocation)
    if (payload.get("task_name") != task_name or payload.get("task_id") != task_id
            or payload.get("invocation_binding") != expected or binding.get("user_id") != owner
            or binding.get("user_hash") != hashlib.sha256(owner.encode()).hexdigest()
            or arguments.get("user_id") != owner or arguments.get("chat_id") != binding.get("chat_id")
            or arguments.get("message_id") != binding.get("assistant_message_id") or arguments.get("team_id")):
        raise RequiredRecoveryOutputError("Voice task invocation mismatch")
    context = VoiceWorkerContext(binding, payload["request_id"], task_id, task_name,
                                 expected, arguments["embed_id"], arguments)
    await require_voice_publication(context=context, cache_service=cache_service,
        directus_service=directus_service, encryption_service=encryption_service,
        owner_hash=binding["user_hash"])
    await require_voice_task_can_generate(context=context, cache_service=cache_service,
                                          directus_service=directus_service)
    return invocation, context


async def require_voice_task_can_generate(*, context: VoiceWorkerContext,
                                          cache_service: Any, directus_service: Any) -> None:
    """Fence provider retries against the canonical encrypted completed output.

The existing cache journal is authoritative while awaiting client encryption;
the normal saved embed is the cache-miss fallback after the client commits it.
    """
    client = await _client(cache_service)
    cached = await client.get(f"embed:{context.embed_id}")
    output = json.loads(cached) if cached else await directus_service.embed.get_sync_embed_by_id(context.embed_id)
    if not isinstance(output, dict) or output.get("status") != "finished":
        return
    binding = context.binding
    if (output.get("hashed_user_id") != binding["user_hash"]
            or output.get("hashed_chat_id") != hashlib.sha256(binding["chat_id"].encode()).hexdigest()
            or output.get("hashed_message_id") != hashlib.sha256(binding["assistant_message_id"].encode()).hexdigest()):
        raise RequiredRecoveryOutputError("Voice completed output identity mismatch")
    raise RequiredRecoveryOutputError("Voice task already has a canonical completed output")


async def require_voice_publication(*, context: VoiceWorkerContext, cache_service: Any,
                                    directus_service: Any, encryption_service: Any,
                                    owner_hash: str) -> None:
    """Recheck owner and committed issued-row receipt after generation."""
    binding = context.binding
    receipt = await load_voice_action_receipt(cache_service=cache_service,
        directus_service=directus_service, encryption_service=encryption_service,
        user_id=binding["user_id"], user_hash=owner_hash,
        session_id=binding["session_id"], request_id=context.request_id)
    if (owner_hash != binding["user_hash"] or not receipt
            or receipt.get("assistant_message_id") != binding["assistant_message_id"]
            or receipt.get("user_message_id") != binding["user_message_id"]
            or receipt.get("call_id") != binding["call_id"]
            or receipt.get("operation_id") != binding["operation_id"]
            or context.embed_id not in receipt["embed_refs"]):
        raise RequiredRecoveryOutputError("Voice output authority unavailable")


@contextmanager
def bound_voice_worker(context: VoiceWorkerContext):
    from backend.shared.python_utils.private_inference_logging import private_inference_logging
    token = active_voice_worker_context.set(context)
    producer_token = active_verified_output_producer.set(VerifiedOutputProducer(
        classification="authorized_voice", intent_id=context.task_id, task_id=context.task_id,
        task_name=context.task_name, kwargs_binding=context.invocation_binding,
        primary_embed_id=context.embed_id, primary_message_id=context.binding["assistant_message_id"],
        target_chat_id=context.binding["chat_id"], owner_hash=context.binding["user_hash"],
        intent_kind="voice_chat"))
    try:
        with private_inference_logging():
            yield
    finally:
        active_verified_output_producer.reset(producer_token)
        active_voice_worker_context.reset(token)


def voice_task_result(value: Any, context: VoiceWorkerContext) -> dict:
    """Keep provider output in the encrypted normal embed, outside Celery results."""
    status = value.get("status") if isinstance(value, dict) else None
    if isinstance(value, dict) and (value.get("error") or status in {"rejected", "failed"}):
        status = "error"
    return {"task_id": context.task_id, "embed_id": context.embed_id,
            "status": status if status in {"finished", "error", "cancelled"} else "finished"}


async def settle_voice_async_completion(*, context: VoiceWorkerContext,
                                        completed_results: list[dict],
                                        result_status: str) -> None:
    """Preserve fixed-price social billing when skipping the ordinary AI reply.

Media generators already settle their own actual provider usage. Social tasks
normally rely on the continuation's billing, so use the same idempotent helper
for those successful completions without launching inference.
    """
    if not context.task_name.startswith("apps.social_media.tasks.") or result_status != "finished":
        return
    from backend.apps.ai.processing.main_processor import _charge_skill_credits
    from backend.apps.ai.skills.ask_skill import AskSkillRequest
    from backend.core.api.app.services.skill_registry import get_global_registry
    binding = context.binding
    request = AskSkillRequest(user_id=binding["user_id"], user_id_hash=binding["user_hash"],
        chat_id=binding["chat_id"], message_id=binding["assistant_message_id"], message_history=[])
    skill_id = context.task_name.removeprefix("apps.social_media.tasks.skill_")
    await _charge_skill_credits(task_id=context.task_id, execution_id=context.task_id,
        request_data=request, app_id="social_media", skill_id=skill_id,
        discovered_apps_metadata=get_global_registry().all_metadata(),
        results=completed_results, parsed_args=context.arguments,
        provider_result_data=completed_results, log_prefix="[VoiceAsyncCompletion]")
