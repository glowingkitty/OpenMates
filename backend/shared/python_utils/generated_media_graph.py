"""Recoverable parent/child graph for an asynchronous media-generation invocation."""

from __future__ import annotations

from typing import Any
from contextvars import ContextVar

try:
    from toon_format import encode as toon_encode
except ImportError:  # pragma: no cover - lightweight contract-test environments
    import json

    def toon_encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)


MEDIA_CHILD_TYPES = {
    "images": "generated_image",
    "audio": "generated_audio",
    "music": "generated_music",
    "videos": "generated_video",
    "models3d": "generated_model",
}

# Match the former per-output Celery soft limits. A batch keeps every advertised
# request slot but cannot let one provider call consume the entire invocation.
PER_CHILD_TIMEOUT_SECONDS = {
    ("images", "generate"): 600,
    ("images", "generate_draft"): 600,
    ("images", "vectorize"): 180,
    ("audio", "generate"): 600,
    ("audio", "speak"): 600,
    ("music", "generate"): 900,
    ("videos", "generate"): 1800,
    ("models3d", "generate"): 900,
}

active_media_batch_child: ContextVar[bool] = ContextVar("active_media_batch_child", default=False)

# Completion needs attribution and a child reference, not the asset's encrypted
# storage metadata or short-lived download tokens. The full result stays on the
# owner-bound embed and generated-asset record.
COMPLETION_RESULT_FIELDS = frozenset({
    "id", "type", "prompt", "text_preview", "model", "provider_model",
    "provider", "mode", "generation_type", "duration_seconds", "aspect_ratio",
    "resolution", "output_filetype", "billing_status", "generated_at",
})


def media_completion_result(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key in COMPLETION_RESULT_FIELDS}


def generated_media_embed_ref(app_id: str, child_embed_id: str) -> str:
    """A stable visible reference for an already registered output child."""
    return f"generated-{app_id}-{child_embed_id.replace('-', '')[:12]}"


def generated_media_parent_ref(app_id: str, parent_embed_id: str) -> str:
    return f"generated-media-{app_id}-{parent_embed_id.replace('-', '')[:12]}"


async def run_generated_media_batch(
    task: Any,
    *,
    app_id: str,
    skill_id: str,
    arguments: dict[str, Any],
    generate_one: Any,
) -> dict[str, Any]:
    """Run one registered producer with a distinct asset ID for each request."""
    import hashlib
    import asyncio
    from datetime import datetime, timezone

    from backend.core.api.app.services.embed_service import EmbedService
    from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError

    parent_id = str(arguments["embed_id"])
    requests = arguments.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("Generated media batch has no requests")
    if len(requests) > 32:
        raise ValueError("Generated media batch exceeds registered child limit")
    child_timeout = PER_CHILD_TIMEOUT_SECONDS.get((app_id, skill_id))
    if child_timeout is None:
        raise ValueError("Generated media batch has no bounded child timeout")
    children: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        if not isinstance(request, dict):
            failures.append({"request_index": index, "error": "Invalid request"})
            continue
        child_id = EmbedService._registered_child_embed_id(parent_id, index)
        child_args = {
            **arguments, **request,
            "embed_id": child_id,
            "producer_embed_id": parent_id,
            "media_child_index": index,
            "media_batch": True,
        }
        child_args.pop("requests", None)
        try:
            token = active_media_batch_child.set(True)
            try:
                result = await asyncio.wait_for(
                    generate_one(task, app_id, skill_id, child_args), timeout=child_timeout,
                )
            finally:
                active_media_batch_child.reset(token)
            if not isinstance(result, dict) or result.get("status") != "finished":
                failures.append({"request_index": index, "error": "Generation did not finish"})
                continue
            children.append({
                "request_index": index,
                "child_embed_id": child_id,
                "embed_ref": generated_media_embed_ref(app_id, child_id),
                "result": result,
            })
        except RequiredRecoveryOutputError:
            raise
        except TimeoutError:
            failures.append({"request_index": index, "error": "Generation timed out"})
        except Exception:
            failures.append({"request_index": index, "error": "Generation failed"})
    if arguments.get("chat_id") and arguments.get("message_id"):
        await task.initialize_core_services()
        try:
            service = EmbedService(task._cache_service, task._directus_service, task._encryption_service)
            user_id = str(arguments["user_id"])
            await finalize_generated_media_parent(
                service, parent_embed_id=parent_id, app_id=app_id, skill_id=skill_id,
                children=children, failures=failures,
                chat_id=str(arguments["chat_id"]),
                message_id=str(arguments["message_id"]),
                user_id=user_id, user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
                created_at=int(datetime.now(timezone.utc).timestamp()),
                log_prefix=f"[media batch:{task.request.id}]",
            )
            # The registered task ID is the one terminal slot in the same-turn
            # barrier. Dispatch only after the parent manifest has sealed every
            # successful child, including when other request slots failed.
            from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation
            completed_results = [
                {
                    **media_completion_result(row["result"]),
                    "parent_embed_id": parent_id,
                    "parent_embed_ref": generated_media_parent_ref(app_id, parent_id),
                    "request_index": row["request_index"],
                    "child_embed_id": row["child_embed_id"],
                    "embed_ref": row["embed_ref"],
                    "status": "finished",
                }
                for row in children
            ] + [
                {
                    "parent_embed_id": parent_id,
                    "parent_embed_ref": generated_media_parent_ref(app_id, parent_id),
                    "request_index": row["request_index"], "status": "error", "error": row["error"],
                }
                for row in failures
            ]
            completed_results.sort(key=lambda row: row["request_index"])
            await dispatch_async_skill_continuation(
                cache_service=task._cache_service,
                async_task_id=task.request.id,
                completed_results=completed_results,
                result_status="finished" if not failures else "failed",
                request_metadata={
                    "app_id": app_id, "skill_id": skill_id,
                    "parent_embed_id": parent_id,
                    "parent_embed_ref": generated_media_parent_ref(app_id, parent_id),
                    "user_id": str(arguments["user_id"]),
                    "chat_id": str(arguments["chat_id"]),
                    "message_id": str(arguments["message_id"]),
                    **({"same_turn_batch_id": str(arguments["same_turn_batch_id"])}
                       if arguments.get("same_turn_batch_id") else {}),
                },
            )
        finally:
            await task.cleanup_services()
    return {
        "embed_id": parent_id,
        "status": "finished" if not failures else "partial" if children else "error",
        "results": [row["result"] for row in children],
        "completed_results": children,
        "child_embed_ids": [row["child_embed_id"] for row in children],
        "failed_results": failures,
    }


async def send_generated_media_child(
    embed_service: Any,
    *,
    parent_embed_id: str,
    child_embed_id: str,
    child_index: int,
    content: dict[str, Any],
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    created_at: int,
    log_prefix: str,
) -> str:
    """Publish one actual asset child under its stable registered output ID."""
    app_id = str(content["app_id"])
    child_type = MEDIA_CHILD_TYPES[app_id]
    from backend.shared.python_utils.chat_recovery_context import active_verified_output_producer
    producer = active_verified_output_producer.get()
    is_registered = producer is not None and producer.classification == "registered_ai"
    has_distinct_parent = parent_embed_id != child_embed_id
    if is_registered and has_distinct_parent:
        expected_id = embed_service._registered_child_embed_id(parent_embed_id, child_index)
        if child_embed_id != expected_id:
            raise ValueError("Generated media child does not match producer registration")
    child_ref = generated_media_embed_ref(app_id, child_embed_id)
    child_content = {**content, "type": child_type, "embed_ref": child_ref}
    await embed_service.send_embed_data_to_client(
        embed_id=child_embed_id,
        embed_type=child_type,
        content_toon=toon_encode(child_content),
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        status="finished",
        encryption_mode="client",
        created_at=created_at,
        updated_at=created_at,
        parent_embed_id=parent_embed_id if has_distinct_parent else None,
        log_prefix=log_prefix,
        check_cache_status=False,
        app_id=app_id,
        skill_id=child_type,
        producer_child_index=child_index if is_registered and has_distinct_parent else None,
        producer_final_children=[] if is_registered and not has_distinct_parent else None,
    )
    return child_ref


async def finalize_generated_media_parent(
    embed_service: Any,
    *,
    parent_embed_id: str,
    app_id: str,
    skill_id: str,
    children: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    chat_id: str,
    message_id: str,
    user_id: str,
    user_id_hash: str,
    created_at: int,
    log_prefix: str,
) -> None:
    """Close the one producer after all request slots have reached a terminal state."""
    ordered = sorted(children, key=lambda row: int(row["request_index"]))
    child_ids = [str(row["child_embed_id"]) for row in ordered]
    content = {
        "app_id": app_id,
        "skill_id": skill_id,
        "embed_ref": generated_media_parent_ref(app_id, parent_embed_id),
        "status": "finished" if child_ids else "error",
        "result_count": len(child_ids),
        "embed_ids": child_ids,
        "output_embed_refs": [str(row["embed_ref"]) for row in ordered],
        "failed_results": failures,
    }
    if failures:
        content["partial_failure"] = bool(child_ids)
        content["error"] = f"{len(failures)} output(s) could not be generated"
    await embed_service.send_embed_data_to_client(
        embed_id=parent_embed_id,
        embed_type="app_skill_use",
        content_toon=toon_encode(content),
        chat_id=chat_id,
        message_id=message_id,
        user_id=user_id,
        user_id_hash=user_id_hash,
        status="finished",  # terminal manifest even when all slots failed
        encryption_mode="client",
        created_at=created_at,
        updated_at=created_at,
        embed_ids=child_ids,
        log_prefix=log_prefix,
        check_cache_status=False,
        producer_final_children=[
            {"subject_id": child_id, "output_kind": "embed", "output_version": 1}
            for child_id in child_ids
        ],
    )
