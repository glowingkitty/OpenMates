"""First-party authenticated Project consent completion; existing AI budgets apply."""

from typing import Any

from backend.apps.ai.tasks.async_skill_continuation import dispatch_async_skill_continuation
from backend.core.api.app.services.project_focus_request_service import ProjectFocusRequestService
from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationError


async def handle_project_focus_decision(
    *, websocket: Any, manager: Any, cache_service: Any, directus_service: Any,
    user_id: str, device_fingerprint_hash: str, payload: dict[str, Any],
) -> None:
    chat_id, request_id, accepted = payload.get("chat_id"), payload.get("request_id"), payload.get("accepted")
    if not isinstance(chat_id, str) or not isinstance(request_id, str) or type(accepted) is not bool:
        await websocket.send_json({"type": "project_focus_decision_error", "payload": {"code": "invalid_decision"}})
        return
    service = ProjectFocusRequestService(cache_service, directus_service)
    try:
        if not manager.can_execute_project_file_job(user_id, device_fingerprint_hash, chat_id):
            raise ProjectWriteAuthorizationError("PROJECT_EXECUTOR_NOT_READY")
        pending = await service.require_pending(user_id=user_id, chat_id=chat_id, request_id=request_id,
                                                require_completed_countdown=accepted)
        if accepted:
            focus = await service.authorization.get_active_focus(user_id=user_id, chat_id=chat_id)
            if not focus or focus.get("project_id") != pending["project_id"] or focus.get("team_id") != pending.get("team_id"):
                raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUIRED")
        specialist_context = None
        if accepted and isinstance(pending.get("selected_specialist"), dict):
            selected = pending["selected_specialist"]
            supplied = payload.get("specialist_document")
            if isinstance(supplied, dict) and all(supplied.get(field) == selected.get(field)
                    for field in ("focus_id", "item_id", "revision")):
                try:
                    from backend.core.api.app.services.project_focus_routing import validated_focus_candidates_for_project
                    current = await validated_focus_candidates_for_project(
                        {"project_id": pending["project_id"], "focuses": [{
                            **selected, "description": selected.get("title", "")}]},
                        directus_service=directus_service, user_id=user_id,
                        team_id=pending.get("team_id"),
                    )
                    if any(item["focus_id"] == selected["focus_id"] and item["revision"] == selected["revision"] for item in current):
                        specialist_context = await service.authorization.validate_specialist_context(
                            user_id=user_id, chat_id=chat_id, focus_id=selected["focus_id"],
                            instruction=supplied.get("document"), item_revision=selected["revision"],
                            require_accepted=False,
                        )
                except Exception:
                    specialist_context = None
        consumed = await service.consume_decision(user_id=user_id, chat_id=chat_id,
                                                  request_id=request_id, accepted=accepted)
        if not isinstance(consumed, dict) or consumed.get("request_id") != request_id:
            raise ProjectWriteAuthorizationError("PROJECT_FOCUS_REQUEST_EXPIRED", status_code=409)
        if specialist_context:
            try:
                await service.authorization.accept_specialist_focus(
                    user_id=user_id, chat_id=chat_id, focus_id=specialist_context["focus_id"],
                    request_id=request_id,
                )
            except ProjectWriteAuthorizationError:
                specialist_context = None
        await dispatch_async_skill_continuation(
            cache_service=cache_service,
            async_task_id=pending["continuation_id"],
            completed_results=[{"project_id": pending["project_id"], "access_granted": accepted,
                                "message": "Project focus activated." if accepted else "User declined Project access. Do not ask again in this turn or access its files."}],
            project_focus_documents=[{"item_id": specialist_context["item_id"],
                                      "revision": specialist_context["item_revision"],
                                      "document": specialist_context["instruction"]}] if specialist_context else None,
            selected_specialist_focus_id=specialist_context["focus_id"] if specialist_context else None,
            selected_specialist_title=pending["selected_specialist"]["title"] if specialist_context else None,
        )
        await websocket.send_json({"type": "project_focus_decision_confirmed", "payload": {"chat_id": chat_id, "request_id": request_id}})
        if specialist_context:
            await websocket.send_json({"type": "focus_mode_activated", "payload": {
                "chat_id": chat_id, "focus_id": specialist_context["focus_id"],
                "focus_mode_name": pending["selected_specialist"]["title"],
            }})
    except ProjectWriteAuthorizationError as exc:
        await websocket.send_json({"type": "project_focus_decision_error", "payload": {"chat_id": chat_id, "request_id": request_id, "code": exc.code}})
