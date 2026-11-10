"""Consent orchestration before main prompt construction or model inference."""

from __future__ import annotations

import json
import uuid
from typing import Any


async def request_project_focus_catalog(*, task_id: str, directus_service: Any, request_data: Any, preprocessing_results: Any,
                                       cache_service: Any, skill_config_dict: dict[str, Any] | None,
                                       project_id: str) -> None:
    """Ask the owner client for one selected Project's metadata, without consent."""
    from backend.apps.ai.tasks.async_skill_continuation import cache_async_skill_continuation_context
    if (request_data.is_external or request_data.is_incognito or not cache_service
            or "project_file_jobs" not in (request_data.client_capabilities or [])
            or not any(row.get("project_id") == project_id and row.get("auto_selection", True) is True
                       for row in request_data.project_focus_candidates)):
        raise PermissionError("Project metadata routing unavailable")
    request_id = str(uuid.uuid4())
    await cache_async_skill_continuation_context(
        cache_service=cache_service, async_task_id=request_id, request_data=request_data,
        skill_config_dict=skill_config_dict, app_id="system", skill_id="project_focus_catalog",
        tool_name="project_focus_catalog", tool_arguments={"project_id": project_id},
        source_delivery_task_id=task_id, directus_service=directus_service,
        preprocessing_result=preprocessing_results, requires_current_turn=True,
        defer_until_initial_response_complete=True, ttl_seconds=300,
    )
    request_data.awaiting_async_skill_continuation = True
    redis_client = await cache_service.client
    await redis_client.publish(f"user_cache_events:{request_data.user_id}", json.dumps({
        "event_type": "project_focus_catalog_requested", "payload": {
            "chat_id": request_data.chat_id, "request_id": request_id,
            "project_id": project_id, "team_id": request_data.team_id,
        },
    }))


async def request_project_creation(*, task_id: str, directus_service: Any, request_data: Any,
                                   preprocessing_results: Any, cache_service: Any,
                                   skill_config_dict: dict[str, Any] | None,
                                   proposal: dict[str, Any]) -> dict[str, Any]:
    """Ask the chat's executor client to create an encrypted Project.

    Contract: docs/plans/cloud-project-development/contracts/project-create-request.md.
    The original turn resumes when the client's ``project_create_result`` arrives.
    """
    from backend.apps.ai.processing.project_creation_routing import project_creation_skip_reason
    from backend.apps.ai.tasks.async_skill_continuation import cache_async_skill_continuation_context
    from backend.core.api.app.services.project_create_request_service import (
        PROJECT_CREATE_EVENT, PROJECT_CREATE_REQUEST_TTL, ProjectCreateRequestService,
        build_project_create_action, new_project_create_request_id,
    )
    # Recheck the request-field gate: a resumed or replayed result cannot bypass it.
    if not cache_service or project_creation_skip_reason(request_data) is not None:
        raise PermissionError("Project creation was not offered for this turn")
    action = build_project_create_action(
        request_id=new_project_create_request_id(), name=proposal["proposed_name"],
        chat_id=request_data.chat_id, message_id=request_data.message_id,
        team_id=request_data.team_id, origin="preprocessor", kind=proposal["kind"],
    )
    await cache_async_skill_continuation_context(
        cache_service=cache_service, async_task_id=action["request_id"], request_data=request_data,
        skill_config_dict=skill_config_dict, app_id="system", skill_id="project_create_request",
        tool_name="create_project_request",
        # The name stays out of the model-visible completion arguments.
        tool_arguments={"kind": action["kind"], "subfolder": action["subfolder"]},
        source_delivery_task_id=task_id, directus_service=directus_service,
        preprocessing_result=preprocessing_results, requires_current_turn=True,
        defer_until_initial_response_complete=True, ttl_seconds=PROJECT_CREATE_REQUEST_TTL,
    )
    await ProjectCreateRequestService(cache_service).create_pending(user_id=request_data.user_id, action=action)
    request_data.awaiting_async_skill_continuation = True
    redis_client = await cache_service.client
    await redis_client.publish(f"user_cache_events:{request_data.user_id}", json.dumps({
        "event_type": PROJECT_CREATE_EVENT, "payload": {
            "chat_id": request_data.chat_id, "request_id": action["request_id"],
            "pending_client_action": action,
        },
    }))
    return action


async def request_project_focus(*, task_id: str, request_data: Any,
                                preprocessing_results: Any, candidate: dict[str, Any],
                                cache_service: Any, directus_service: Any,
                                encryption_service: Any, user_vault_key_id: str | None,
                                skill_config_dict: dict[str, Any] | None,
                                log_prefix: str) -> str:
    from backend.apps.ai.tasks.async_skill_continuation import cache_async_skill_continuation_context
    from backend.core.api.app.services.embed_service import EmbedService
    from backend.core.api.app.services.project_focus_request_service import (
        PROJECT_FOCUS_REQUEST_TTL, ProjectFocusRequestService,
    )
    focus_id = f"project-{candidate['project_id']}"
    if (focus_id not in (preprocessing_results.relevant_focus_modes or [])
            or candidate.get("auto_selection", True) is not True
            or "project_file_jobs" not in (request_data.client_capabilities or [])
            or request_data.project_access_declined or request_data.is_incognito
            or request_data.is_external or not cache_service):
        raise PermissionError("Project activation was not offered for this turn")
    service = ProjectFocusRequestService(cache_service, directus_service)
    # Recheck current ownership and policy; a model choice cannot bypass either.
    project, _ = await service.authorization._require_project_access(
        request_data.user_id, candidate["project_id"], request_data.team_id, write=False,
    )
    settings = await directus_service.project.get_project_settings(
        candidate["project_id"], request_data.user_id, team_id=request_data.team_id,
    )
    if project.get("archived") or settings and settings.get("auto_selection") is False:
        raise PermissionError("Project automatic selection is disabled")
    policy = (settings or {}).get("focus_activation_policy") or "delayed"
    if policy not in {"delayed", "immediate", "approval"}:
        raise PermissionError("Invalid Project activation policy")
    embed = await EmbedService(
        cache_service=cache_service, directus_service=directus_service,
        encryption_service=encryption_service,
    ).create_focus_mode_activation_embed(
        focus_id=focus_id, app_id="projects", focus_mode_name=f"Work on {candidate['name']}",
        chat_id=request_data.chat_id, message_id=request_data.message_id,
        user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
        user_vault_key_id=user_vault_key_id, task_id=task_id, log_prefix=log_prefix,
    )
    if not embed:
        raise RuntimeError("Project access confirmation could not be created")
    request_id = embed["embed_id"]
    await cache_async_skill_continuation_context(
        cache_service=cache_service, async_task_id=request_id, request_data=request_data,
        skill_config_dict=skill_config_dict, app_id="system", skill_id="activate_focus_mode",
        tool_name="activate_focus_mode", tool_arguments={"focus_id": focus_id},
        source_delivery_task_id=task_id, directus_service=directus_service,
        preprocessing_result=preprocessing_results, requires_current_turn=True,
        defer_until_initial_response_complete=True, ttl_seconds=PROJECT_FOCUS_REQUEST_TTL,
    )
    pending = await service.create_pending(
        user_id=request_data.user_id, chat_id=request_data.chat_id, request_id=request_id,
        project_id=candidate["project_id"], message_id=request_data.message_id,
        team_id=request_data.team_id, activation_policy=policy,
        selected_specialist=getattr(preprocessing_results, "pending_project_specialist", None),
    )
    redis_client = await cache_service.client
    await redis_client.publish(f"user_cache_events:{request_data.user_id}", json.dumps({
        "event_type": "focus_mode_pending", "payload": service.pending_event(pending),
    }))
    return embed["embed_reference"]
