"""First-party handoff for one selected Project's pre-consent Focus metadata."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from backend.apps.ai.tasks.async_skill_continuation import (
    async_skill_continuation_key, async_skill_latest_user_turn_key,
    dispatch_async_skill_continuation,
)
from backend.core.api.app.services.project_focus_routing import validated_focus_candidates_for_project
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError, ProjectWriteAuthorizationService,
)


async def handle_project_focus_catalog_result(
    *, websocket: Any, manager: Any, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any],
) -> None:
    chat_id, request_id, project_id = (payload.get(key) for key in ("chat_id", "request_id", "project_id"))
    if (not all(isinstance(value, str) and 0 < len(value) <= 128 for value in (chat_id, request_id, project_id))
            or not isinstance(payload.get("focuses"), (list, type(None)))
            or isinstance(payload.get("focuses"), list) and len(payload["focuses"]) > 20):
        await websocket.send_json({"type": "project_focus_catalog_error", "payload": {"code": "invalid_catalog"}})
        return
    try:
        if not manager.can_execute_project_file_job(user_id, device_fingerprint_hash, chat_id):
            raise ProjectWriteAuthorizationError("PROJECT_EXECUTOR_NOT_READY")
        context = await cache_service.get(async_skill_continuation_key(request_id))
        cached_at = context.get("cached_at") if isinstance(context, dict) else None
        if (not isinstance(context, dict) or context.get("app_id") != "system"
                or context.get("skill_id") != "project_focus_catalog"
                or (context.get("tool_arguments") or {}).get("project_id") != project_id
                or not isinstance(cached_at, (int, float))
                or not 0 <= time.time() - cached_at <= 5 * 60):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_STALE", status_code=409)
        request = context.get("request_data")
        if (not isinstance(request, dict) or request.get("user_id") != user_id
                or request.get("chat_id") != chat_id
                or request.get("is_incognito") or request.get("is_external")):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_STALE", status_code=409)
        if await cache_service.get(async_skill_latest_user_turn_key(user_id, chat_id)) != request.get("message_id"):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_STALE", status_code=409)
        team_id = request.get("team_id")
        authorization = ProjectWriteAuthorizationService(directus_service, cache_service)
        await authorization._require_chat_access(user_id, chat_id, team_id)
        project, _ = await authorization._require_project_access(user_id, project_id, team_id, write=False)
        if project.get("archived"):
            raise ProjectWriteAuthorizationError("PROJECT_ARCHIVED", status_code=409)
        candidates = request.get("project_focus_candidates")
        selected = next((row for row in candidates if isinstance(row, dict)
                         and row.get("project_id") == project_id
                         and row.get("auto_selection", True) is True), None) if isinstance(candidates, list) else None
        if selected is None:
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_STALE", status_code=409)
        offered = {**selected, "focuses": payload["focuses"] or []}
        valid = await validated_focus_candidates_for_project(
            offered, directus_service=directus_service, user_id=user_id, team_id=team_id,
        ) if payload["focuses"] is not None else []
        # One result can win this handoff. A second tab or replay cannot cause
        # another continuation or replace the exact chosen Project.
        client = await cache_service.client
        claim_key = (f"project-focus-catalog:claimed:{hashlib.sha256(user_id.encode()).hexdigest()}:{request_id}")
        if not client or not await client.set(claim_key, "1", ex=300, nx=True):
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_STALE", status_code=409)
        replacement = [{**row, "focuses": valid} if row.get("project_id") == project_id else row
                       for row in candidates if isinstance(row, dict)]
        await dispatch_async_skill_continuation(
            cache_service=cache_service, async_task_id=request_id,
            completed_results=[{"project_id": project_id,
                                "catalog_received": payload["focuses"] is not None,
                                "catalog_unavailable": payload["focuses"] is None}],
            project_routing_focus_id=f"project-{project_id}",
            selected_project_focus_candidates=replacement,
        )
        await websocket.send_json({"type": "project_focus_catalog_confirmed", "payload": {
            "chat_id": chat_id, "request_id": request_id,
        }})
    except ProjectWriteAuthorizationError as exc:
        await websocket.send_json({"type": "project_focus_catalog_error", "payload": {
            "chat_id": chat_id, "request_id": request_id, "code": exc.code,
        }})
