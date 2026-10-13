"""Reserved compact routing lane. It never runs stage two, main models or tools.

The admitted broker envelope is forwarded unchanged; private context hydrated in
this process is never serialized into a Celery message. Main keeps the original
assistant task identity and owns durable claims, billing and terminal cleanup.
"""
from __future__ import annotations

import asyncio
import logging
import time
from builtins import BaseExceptionGroup
from pathlib import Path
from typing import Any

from celery import Task
from backend.core.api.app.tasks.base_task import DedupedTask

from backend.core.api.app.tasks import celery_config
from backend.apps.ai.processing.stage_one_handoff import (
    request_fingerprint, routing_turn_is_current, routing_admission_is_current, store_stage_one,
)

logger = logging.getLogger(__name__)
_SOURCE_ROOT = Path(__file__).resolve().parents[4]
_SAFE_EXCEPTION_TYPES = frozenset({
    "AttributeError", "ConnectionError", "HTTPStatusError", "KeyError",
    "RuntimeError", "TimeoutError", "TypeError", "ValueError",
})


def _routing_failure_signature(error: Exception) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Keep fallback diagnostics bounded and free of exception messages or payloads."""
    types: list[str] = []
    frames: list[str] = []
    pending: list[tuple[BaseException, int]] = [(error, 0)]
    inspected = 0
    while pending and inspected < 32 and len(types) < 8:
        current, depth = pending.pop()
        inspected += 1
        if isinstance(current, BaseExceptionGroup):
            if depth < 8:
                remaining = max(0, 32 - inspected - len(pending))
                pending.extend((child, depth + 1) for child in reversed(current.exceptions[:remaining]))
            continue
        name = type(current).__name__
        types.append(name if name in _SAFE_EXCEPTION_TYPES else "OtherException")
        traceback = current.__traceback__
        while traceback and len(frames) < 6:
            filename = traceback.tb_frame.f_code.co_filename
            try:
                source_path = Path(filename).resolve()
                source = source_path.relative_to(_SOURCE_ROOT)
            except (OSError, ValueError):
                traceback = traceback.tb_next
                continue
            if (source.parts[:1] == ("backend",) and source.suffix == ".py"
                    and source_path.is_file()):
                frame = f"{source.as_posix()}:{traceback.tb_lineno}"
                if frame not in frames:
                    frames.append(frame)
            traceback = traceback.tb_next
    return tuple(types or ["OtherException"]), tuple(frames)


async def _routing_authority_is_current(cache: Any, directus: Any,
                                        request: Any, task_id: str) -> bool:
    """Join fresh Redis and durable admission checks at each routing fence."""
    checks = (
        asyncio.create_task(routing_turn_is_current(cache, request, task_id)),
        asyncio.create_task(routing_admission_is_current(directus, request, task_id)),
    )
    try:
        turn_current, admission_current = await asyncio.gather(*checks)
        return bool(turn_current and admission_current)
    except BaseException:
        for check in checks:
            if not check.done():
                check.cancel()
        await asyncio.gather(*checks, return_exceptions=True)
        raise


def eligible_for_routing_lane(request: dict) -> bool:
    """Restrict the lane to admitted ordinary first-party turns."""
    texts = [request.get("current_user_content") or ""] + [
        row.get("content", "") for row in request.get("message_history", [])
        if isinstance(row, dict) and row.get("role") == "user"
    ]
    return bool(request.get("user_id") and request.get("recovery_task_id")
                and request.get("recovery_preflight_id") and not any(request.get(flag) for flag in (
        "is_external", "is_anonymous", "is_incognito", "is_sub_chat", "user_task_id",
        "is_sub_chat_continuation", "is_async_skill_continuation", "is_focus_mode_continuation",
        "is_app_settings_memories_continuation", "is_connected_account_permission_continuation",
    )) and not any(marker in text for text in texts if isinstance(text, str)
                   for marker in ("<<<TEST_MOCK:", "<<<TEST_RECORD:", "<<<TEST_LIVE_")))


async def route_stage_one(request_data_dict: dict, skill_config_dict: dict,
                          inference_task_id: str) -> str | None:
    from backend.apps.ai.skills.ask_skill import AskSkillRequest, AskSkillDefaultConfig
    from backend.apps.ai.processing.preprocessor import handle_preprocessing
    from backend.apps.ai.processing.focus_phase_history import filter_focus_phase_history
    from backend.apps.ai.utils.instruction_loader import load_base_instructions
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.utils.encryption import EncryptionService
    from backend.core.api.app.utils.secrets_manager import SecretsManager
    from backend.core.api.app.utils.override_parser import parse_overrides, parse_overrides_from_messages
    from backend.core.api.app.services.client_context_continuation import await_client_context_phase
    from backend.shared.python_utils.recent_work_summary_client import (
        restore_private_context_payload, bind_restored_context_turn, override_safe_message_dicts,
    )
    from backend.shared.python_utils.recent_work_summary_cache import PRIVATE_CONTEXT_FIELDS
    from backend.apps.ai.tasks.ask_skill_task import (
        EarlyTypingLifecycle, EARLY_CATEGORY_ICONS, _early_typing_provider_metadata,
        _fetch_and_cache_apps_metadata,
    )
    request = AskSkillRequest.model_validate(request_data_dict)
    config = AskSkillDefaultConfig.model_validate(skill_config_dict)
    fingerprint = request_fingerprint(request.model_dump(mode="json"), config.model_dump(mode="json"))
    started_at = time.monotonic()
    cache = await celery_config.get_worker_cache_service()
    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    encryption = EncryptionService(cache_service=cache)
    directus = DirectusService(cache_service=cache, encryption_service=encryption)
    if not await _routing_authority_is_current(cache, directus, request, inference_task_id):
        return None
    logger.info("Stage-one admission current task=%s elapsed_ms=%.1f",
                inference_task_id, (time.monotonic() - started_at) * 1000)

    async def load_routing_configuration() -> tuple[dict, dict]:
        base = await cache.get_base_instructions() or load_base_instructions()
        apps = await cache.get_discovered_apps_metadata()
        if not apps:
            # A cache miss must use the same authoritative catalogue fallback as main.
            apps = await _fetch_and_cache_apps_metadata(cache, inference_task_id)
        return base, apps

    # The context and public configuration reads begin only after the durable
    # admission fence. Neither read authorizes a Project or an AI request.
    async with asyncio.TaskGroup() as reads:
        config_task = reads.create_task(load_routing_configuration())
        transient = await restore_private_context_payload(request.model_dump())
        bind_restored_context_turn(request, transient)
        for field in PRIVATE_CONTEXT_FIELDS:
            # Main alone unpacks this trusted descriptor for same-turn resume;
            # it is not a public AskSkillRequest field or routing context.
            if field not in {"async_tool_completion", "async_tool_history", "same_turn_request"}:
                setattr(request, field, transient.get(field, None if field == "accepted_plan_context" else []))
        await await_client_context_phase(cache_service=cache, request=request,
            phase="routing", encryption_service=encryption)
    base, apps = config_task.result()
    logger.info("Stage-one context and catalogue ready task=%s elapsed_ms=%.1f",
                inference_task_id, (time.monotonic() - started_at) * 1000)
    request.message_history = filter_focus_phase_history(request.message_history, chat_id=request.chat_id)
    overrides = None
    if request.message_history:
        overrides, cleaned = parse_overrides_from_messages(override_safe_message_dicts(request.message_history))
        if overrides and overrides.has_overrides and cleaned:
            for index in range(len(request.message_history) - 1, -1, -1):
                message = request.message_history[index]
                if message.role == "user" and message.sender_name != "async_tool_result":
                    message.content = cleaned[index]["content"]
                    break
    if (not overrides or not overrides.has_overrides) and request.current_user_content:
        overrides = parse_overrides(request.current_user_content)
        if overrides.has_overrides:
            request.current_user_content = overrides.cleaned_message
    if not apps:
        return None
    memories: dict[str, list[str]] = {}
    for key in request.app_settings_memories_metadata or []:
        if isinstance(key, str) and "-" in key:
            app, item = key.split("-", 1)
            if app and item:
                memories.setdefault(app, []).append(item)
    lifecycle = EarlyTypingLifecycle(cache, request, inference_task_id)

    async def load_encrypted_chat_key() -> str | None:
        try:
            item = await cache.get_chat_list_item_data(request.user_id, request.chat_id)
            encrypted_key = getattr(item, "encrypted_chat_key", None)
        except Exception:
            encrypted_key = None
        if encrypted_key:
            return encrypted_key
        try:
            rows = await directus.get_items("chats", {
                "filter[id][_eq]": request.chat_id,
                "fields": "encrypted_chat_key", "limit": 1,
            })
            return rows[0].get("encrypted_chat_key") if rows else None
        except Exception:
            return None

    # The key read is independent of fresh credits, Project eligibility and Jev.
    # It starts only after admission and the scoped routing context are verified.
    chat_key_task = asyncio.create_task(load_encrypted_chat_key())

    async def publish(routing: dict) -> None:
        encrypted_key = await chat_key_task
        # Recheck at publication: the turn can be replaced while Jev or key I/O runs.
        if not await _routing_authority_is_current(cache, directus, request, inference_task_id):
            raise RuntimeError("Routing authority no longer current")
        provider, region = _early_typing_provider_metadata(routing.get("model_id"))
        payload: dict[str, Any] = {
            "type": "ai_processing_started_event", "event_for_client": "ai_typing_started",
            "task_id": inference_task_id, "chat_id": request.chat_id,
            "user_id_uuid": request.user_id, "user_id_hash": request.user_id_hash,
            "user_message_id": request.message_id, "category": routing["category"],
            "model_name": routing.get("model_name"), "provider_name": provider,
            "server_region": region, "is_continuation": False,
        }
        if encrypted_key:
            payload["encrypted_chat_key"] = encrypted_key
        if not request.chat_has_title and routing["category"] in EARLY_CATEGORY_ICONS:
            payload["icon_names"] = [EARLY_CATEGORY_ICONS[routing["category"]]]
        await lifecycle.publish_stage_one(payload)
        logger.info("Stage-one Mate published task=%s elapsed_ms=%.1f",
                    inference_task_id, (time.monotonic() - started_at) * 1000)

    try:
        await handle_preprocessing(request_data=request, base_instructions=base, skill_config=config,
            cache_service=cache, secrets_manager=secrets_manager, directus_service=directus,
            encryption_service=encryption, user_app_settings_and_memories_metadata=memories,
            discovered_apps_metadata=apps, user_overrides=overrides,
            is_new_chat=not request.chat_has_title, on_early_routing=publish,
            stage_one_only=True, routing_scope_validated=True)
        routing = getattr(request, "_stage_one_routing", None)
        if not isinstance(routing, dict) or not routing.get("early_decisions"):
            return None
        if not await _routing_authority_is_current(cache, directus, request, inference_task_id):
            return None
        reference = await store_stage_one(cache=cache, encryption=encryption, request=request,
            task_id=inference_task_id, fingerprint=fingerprint, routing=routing,
            typing_started=lifecycle.started)
        logger.info("Stage-one sealed handoff ready task=%s elapsed_ms=%.1f",
                    inference_task_id, (time.monotonic() - started_at) * 1000)
        return reference
    finally:
        if not chat_key_task.done():
            chat_key_task.cancel()
        await asyncio.gather(chat_key_task, return_exceptions=True)


class StageOneRoutingTask(DedupedTask):
    """Keep the paid-routing dedup lock while retrying only broker publication."""

    def __call__(self, *args, **kwargs):
        if self.request.retries:
            # run() skips inference for every retry. Duplicate publication uses
            # the same original main ID and is fenced by main's own dedup lock.
            return self.run(*args, **kwargs)
        return super().__call__(*args, **kwargs)

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        # Do not release the original routing lock: an old retries=0 broker
        # delivery must stay rejected while the publication retry is pending.
        Task.on_retry(self, exc, task_id, args, kwargs, einfo)


@celery_config.app.task(bind=True, base=StageOneRoutingTask,
                       name="apps.ai.tasks.stage_one", soft_time_limit=25, time_limit=35)
def process_ai_stage_one_task(self, request_data_dict: dict, skill_config_dict: dict,
                              inference_task_id: str, legacy_batch_proof: dict | None = None,
                              routing_snapshot_ref: str | None = None):
    """Distinct routing task ID leaves original main dedup and durable claim intact."""
    from backend.apps.ai.tasks.ask_skill_task import process_ai_skill_ask_task
    reference = routing_snapshot_ref
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        if not self.request.retries and eligible_for_routing_lane(request_data_dict):
            reference = loop.run_until_complete(route_stage_one(
                request_data_dict, skill_config_dict, inference_task_id))
    except Exception as exc:
        # No private text in logs; main performs the complete safe fallback.
        try:
            leaf_types, source_frames = _routing_failure_signature(exc)
            logger.warning("Compact routing unavailable (leaf_types=%s source_frames=%s); using main routing",
                           leaf_types, source_frames)
        except Exception:
            # Diagnostics must never prevent dispatching the original main task.
            logger.warning("Compact routing unavailable (diagnostic_failed); using main routing")
    finally:
        try:
            from backend.apps.ai.llm_providers.google_client import close_google_clients_for_current_loop
            loop.run_until_complete(close_google_clients_for_current_loop())
        except Exception:
            pass
        loop.close()
    kwargs = {"request_data_dict": request_data_dict, "skill_config_dict": skill_config_dict}
    if legacy_batch_proof is not None:
        kwargs["legacy_batch_proof"] = legacy_batch_proof
    headers = dict(getattr(self.request, "headers", None) or {})
    headers.pop("x-openmates-stage-one-ref", None)
    if reference:
        headers["x-openmates-stage-one-ref"] = reference
    try:
        process_ai_skill_ask_task.apply_async(kwargs=kwargs, task_id=inference_task_id,
            queue="app_ai", exchange="app_ai", routing_key="app_ai", headers=headers)
    except Exception as exc:
        # Preserve the main identity and snapshot across publication retries. A
        # retry cannot repeat paid Stage-one inference; main dedup handles an
        # ambiguous publication that was already accepted by the broker.
        raise self.retry(exc=exc, countdown=1, max_retries=3, kwargs={
            "request_data_dict": request_data_dict, "skill_config_dict": skill_config_dict,
            "inference_task_id": inference_task_id, "legacy_batch_proof": legacy_batch_proof,
            "routing_snapshot_ref": reference,
        })
    return {"status": "main_dispatched", "stage_one_reusable": reference is not None}
