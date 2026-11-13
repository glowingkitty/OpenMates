"""First-party completion report for a client-executed Project creation.

Access model: first-party authenticated WebSocket only (session device with the
``project_create_requests`` capability that holds this chat's executor). Not
reachable through the public REST API. Existing AI turn budgets apply; no
inference runs here. Contract: openmates.project_create_request v1, see
docs/plans/cloud-project-development/contracts/project-create-request.md.

On ``created`` the client has already created the encrypted Project (Apply and
show) and activated its default focus via ``POST /v1/projects/{id}/focus/activate``.
This handler verifies that authority server-side and resumes the original turn
with the Project focus active, so the Project file tools are available. For
``created`` it also publishes ``focus_mode_activated`` with the bound default
focus id, so every client persists the chat's encrypted active focus, and hands
the resumed turn a one-shot record for its activation card.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation
from backend.core.api.app.services.project_create_request_service import (
    PROJECT_CREATE_CONFIRMED_EVENT,
    PROJECT_CREATE_ERROR_EVENT,
    PROJECT_CREATE_FOCUS_ACTIVATED_EVENT,
    PROJECT_CREATE_WRITE_MODE,
    ProjectCreateRequestService,
    continuation_result,
    parse_project_create_result,
    require_new_project,
    require_report_matches_location,
)
from backend.core.api.app.services.project_write_authorization_service import (
    ProjectWriteAuthorizationError,
    ProjectWriteAuthorizationService,
    focus_id_hash,
)

logger = logging.getLogger(__name__)


async def _require_created_project(*, authorization: ProjectWriteAuthorizationService, user_id: str,
                                   pending: dict[str, Any], report: dict[str, Any]) -> None:
    """The reported Project is new, owned, Apply and show, and its focus is active here."""
    team_id = pending.get("team_id")
    await authorization._require_chat_access(user_id, pending["chat_id"], team_id)
    project, _ = await authorization._require_project_access(user_id, report["project_id"], team_id, write=True)
    if project.get("archived"):
        raise ProjectWriteAuthorizationError("PROJECT_ARCHIVED", status_code=409)
    require_new_project(project, pending)
    settings = await authorization.directus_service.project.get_project_settings(
        report["project_id"], user_id, team_id=team_id,
    )
    if not settings or settings.get("write_mode") != PROJECT_CREATE_WRITE_MODE:
        raise ProjectWriteAuthorizationError("PROJECT_CREATE_WRITE_MODE_MISMATCH", status_code=409)
    focus = await authorization.get_active_focus(user_id=user_id, chat_id=pending["chat_id"])
    if (not focus or focus.get("project_id") != report["project_id"] or focus.get("team_id") != team_id
            or focus.get("focus_id_hash") != focus_id_hash(report["focus_id"])):
        raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED", status_code=409)


async def _announce_created_focus(*, cache_service: Any, service: ProjectCreateRequestService, user_id: str,
                                   pending: dict[str, Any], report: dict[str, Any]) -> None:
    """Before the turn resumes: card record for the resumed turn, then the activation event.

    The event names the verified binding's default focus id (a bare UUID), which
    is what clients encrypt as ``encrypted_active_focus_id`` and what
    ``GET /v1/projects/focus/current`` returns, so the focus pill resolves it.
    """
    if not await service.record_created(user_id=user_id, pending=pending, report=report):
        logger.warning("Project create activation card unavailable chat=%s request=%s",
                       report["chat_id"], report["request_id"])
    redis_client = await cache_service.client
    if not redis_client:
        logger.warning("Project create focus event not published chat=%s request=%s",
                       report["chat_id"], report["request_id"])
        return
    await redis_client.publish(f"user_cache_events:{user_id}", json.dumps({
        "event_type": PROJECT_CREATE_FOCUS_ACTIVATED_EVENT,
        "payload": {"chat_id": report["chat_id"], "focus_id": report["focus_id"]},
    }))


async def handle_project_create_result(
    *, websocket: Any, manager: Any, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any],
) -> None:
    chat_id = payload.get("chat_id") if isinstance(payload, dict) else None
    request_id = payload.get("request_id") if isinstance(payload, dict) else None
    try:
        report = parse_project_create_result(payload)
        if not manager.can_execute_project_create(user_id, device_fingerprint_hash, report["chat_id"]):
            raise ProjectWriteAuthorizationError("PROJECT_EXECUTOR_NOT_READY")
        service = ProjectCreateRequestService(cache_service)
        pending = await service.require_pending(user_id=user_id, chat_id=report["chat_id"],
                                                request_id=report["request_id"])
        require_report_matches_location(pending, report)
        if report["status"] == "created":
            await _require_created_project(
                authorization=ProjectWriteAuthorizationService(directus_service, cache_service),
                user_id=user_id, pending=pending, report=report,
            )
        await service.claim(user_id=user_id, request_id=report["request_id"])
        await service.finish(user_id=user_id, chat_id=report["chat_id"], request_id=report["request_id"])
        if report["status"] == "created":
            await _announce_created_focus(cache_service=cache_service, service=service, user_id=user_id,
                                          pending=pending, report=report)
        logger.info("Project create result chat=%s request=%s status=%s",
                    report["chat_id"], report["request_id"], report["status"])
        await dispatch_async_skill_continuation(
            cache_service=cache_service, async_task_id=report["request_id"],
            completed_results=[continuation_result(pending, report)],
        )
        await websocket.send_json({"type": PROJECT_CREATE_CONFIRMED_EVENT, "payload": {
            "chat_id": report["chat_id"], "request_id": report["request_id"], "status": report["status"],
        }})
    except ProjectWriteAuthorizationError as exc:
        await websocket.send_json({"type": PROJECT_CREATE_ERROR_EVENT, "payload": {
            "chat_id": chat_id if isinstance(chat_id, str) else None,
            "request_id": request_id if isinstance(request_id, str) else None, "code": exc.code,
        }})
