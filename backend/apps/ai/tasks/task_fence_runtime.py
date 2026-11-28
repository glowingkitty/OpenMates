"""Create and edit Tasks from assistant-authored ``openmates_task`` fences.

The stream consumer hands a closed fence (or a diff against a task embed) to
this module. It validates, stages the Task create/update through the existing
client-persisted task job path (never a chat system event) and writes the task
embed. Task plaintext stays inside the existing vault-encrypted working copy and
embed encryption; nothing is sent to Directus in the clear.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import replace
from typing import Any

from backend.apps.ai.processing.focus_mode_routing import SPEC_AUTHORING_FOCUS_ID
from backend.apps.ai.processing.task_runtime_tools import TASK_TOOL_CREATE, TASK_TOOL_UPDATE
from backend.apps.ai.processing.task_tool_context import TaskToolContext
from backend.apps.ai.processing.task_tool_executor import execute_task_tool_call, publish_task_tool_result
from backend.apps.ai.utils.task_fences import (
    TaskFenceContext,
    TaskFenceResult,
    task_validation_feedback,
    validate_task_fence,
)
from backend.core.api.app.services.directus.user_plan_methods import hash_id

logger = logging.getLogger(__name__)

TASK_FENCE_SOURCE_LANGUAGE = "openmates_task"


def build_task_fence_context(request_data: Any) -> TaskFenceContext:
    """Derive the validation context (Team chat, reachable Projects) from the request."""
    projects: dict[str, str] = {}
    for candidate in getattr(request_data, "project_focus_candidates", None) or []:
        if isinstance(candidate, dict) and candidate.get("project_id"):
            project_id = str(candidate["project_id"])
            projects[project_id.lower()] = project_id
            if candidate.get("name"):
                projects[str(candidate["name"]).strip().lower()] = project_id
    focus = getattr(request_data, "active_project_focus", None) or {}
    if isinstance(focus, dict) and focus.get("project_id"):
        projects.setdefault(str(focus["project_id"]).lower(), str(focus["project_id"]))
    return TaskFenceContext(is_team=bool(getattr(request_data, "team_id", None)), known_projects=projects)


def _unsupported_member_assignee(result: TaskFenceResult) -> TaskFenceResult:
    """Member assignment cannot be staged yet; report it on the card instead of dropping it."""
    errors = [{
        "field": "assignee", "code": "team_tasks_unsupported",
        "message": "Assigning a task to a Team member is not supported yet; use user or openmates.",
    }]
    return TaskFenceResult("invalid", None, result.source_json, result.title, errors, result.warnings)


def _checked(source: str, request_data: Any, *, allow_done: bool) -> TaskFenceResult:
    result = validate_task_fence(source, context=build_task_fence_context(request_data), allow_done=allow_done)
    if result.model and result.model.get("assignee_type") == "member":
        return _unsupported_member_assignee(result)
    return result


async def _resolve_spec_plan_project(
    result: TaskFenceResult, request_data: Any, directus_service: Any, cache_service: Any,
) -> TaskFenceResult:
    """Resolve a redundant Project label from the active Project and saved Plan."""
    if (
        [error["code"] for error in result.errors] != ["unknown_project"]
        or getattr(request_data, "active_focus_id", None) != SPEC_AUTHORING_FOCUS_ID
        or not getattr(request_data, "is_sub_chat_continuation", False)
        or getattr(request_data, "is_sub_chat", False)
        or getattr(request_data, "is_incognito", False)
        or getattr(request_data, "team_id", None)
        or not directus_service
        or not cache_service
    ):
        return result

    source = json.loads(result.source_json)
    plan_id = source.get("plan")
    if not isinstance(plan_id, str):
        return result
    plan = await directus_service.user_plan.get_plan(plan_id.strip(), request_data.user_id)
    if not plan or plan.get("hashed_primary_chat_id") != hash_id(request_data.chat_id):
        return result

    from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService

    focus = await ProjectWriteAuthorizationService(directus_service, cache_service).get_active_focus(
        user_id=request_data.user_id, chat_id=request_data.chat_id,
    )
    project_id = (focus or {}).get("project_id")
    if not isinstance(project_id, str) or hash_id(project_id) not in (plan.get("linked_project_hashes") or []):
        return result

    del source["project"]
    checked = _checked(json.dumps(source), request_data, allow_done=False)
    if checked.model is None:
        return checked
    return replace(checked, model={**checked.model, "project_id": project_id})


def _task_context(request_data: Any, attached: list[dict[str, Any]] | None = None) -> TaskToolContext:
    return TaskToolContext(
        user_id=request_data.user_id, chat_id=request_data.chat_id,
        team_id=getattr(request_data, "team_id", None), attached_tasks=list(attached or []),
    )


def embed_content_for(result: TaskFenceResult, *, task_id: str | None, job_id: str | None, task_version: int) -> dict[str, Any]:
    """Embed content fields per the task-inline-embeds contract (section 3)."""
    model = result.model or {}
    return {
        "type": "task", "app_id": "tasks", "task_id": task_id or "", "task_update_job_id": job_id or "",
        "task_version": task_version, "title": result.title, "description": model.get("description", ""),
        "status": model.get("status", ""), "due_date": model.get("due_date") or "",
        "assignee_type": model.get("assignee_type", ""), "assignee_name": model.get("assignee_name") or "",
        "project_name": model.get("project_name") or "", "project_id": model.get("project_id") or "",
        "validation": {"status": result.status, "errors": result.errors, "warnings": result.warnings},
    }


def _task_args(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": model["title"], "description": model["description"], "status": model["status"],
        "assignee_type": model["assignee_type"],
        **({"due_at": model["due_at"]} if model.get("due_at") else {}),
        **({"linked_project_ids": [model["project_id"]]} if model.get("project_id") else {}),
        **({"plan_id": model["plan_id"]} if model.get("plan_id") else {}),
    }


# Tasks created by fences in the reply being streamed, so a start_sub_chats Task link in the
# same reply can name a new Task by its title (the model never sees the new Task's id).
_REPLY_TASKS: "OrderedDict[tuple[str, str], dict[str, str]]" = OrderedDict()
_REPLY_TASKS_LIMIT = 256


def remember_reply_task(request_data: Any, title: str, task_id: str) -> None:
    key = (str(request_data.chat_id), str(request_data.message_id))
    _REPLY_TASKS.setdefault(key, {})[title.strip().lower()] = task_id
    _REPLY_TASKS.move_to_end(key)
    while len(_REPLY_TASKS) > _REPLY_TASKS_LIMIT:
        _REPLY_TASKS.popitem(last=False)


def reply_task_id_for_title(request_data: Any, title: str) -> str | None:
    """Task id of a task block created earlier in this reply with exactly this title."""
    tasks = _REPLY_TASKS.get((str(request_data.chat_id), str(request_data.message_id))) or {}
    return tasks.get(str(title or "").strip().lower())


async def _stage(tool_name: str, args: dict[str, Any], context: TaskToolContext, *, request_data: Any,
                 cache_service: Any, directus_service: Any, encryption_service: Any,
                 user_vault_key_id: str) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Stage a Task job; a refusal (e.g. an unknown Plan) becomes a card error instead of a crash."""
    if tool_name == TASK_TOOL_CREATE and context.team_id:
        return None, [{
            "field": "task", "code": "team_tasks_unsupported",
            "message": "The assistant can create Tasks from a Personal chat.",
        }]
    try:
        staged = await execute_task_tool_call(
            tool_name=tool_name, args=args, context=context, cache_service=cache_service,
            directus_service=directus_service, encryption_service=encryption_service,
            user_vault_key_id=user_vault_key_id, message_id=request_data.message_id,
        )
    except ValueError as exc:
        field = "plan" if "Plan" in str(exc) else "task"
        return None, [{"field": field, "code": "task_not_staged", "message": str(exc)}]
    return staged, []


async def _publish_job(result: dict[str, Any], *, cache_service: Any, request_data: Any) -> None:
    """Publish only the persistence job; the Task chat system event is never emitted here."""
    if cache_service is None:
        return
    await publish_task_tool_result(
        cache_service=cache_service, user_id=request_data.user_id,
        user_id_hash=request_data.user_id_hash, result=result, publish_chat_event=False,
    )


async def finalize_task_fence_embed(
    *, embed_service: Any, embed_id: str, source: str, request_data: Any, cache_service: Any,
    directus_service: Any, encryption_service: Any, user_vault_key_id: str, log_prefix: str,
) -> bool:
    """Validate a closed fence, stage the Task create when valid, and finish the embed."""
    result = _checked(source, request_data, allow_done=False)
    result = await _resolve_spec_plan_project(result, request_data, directus_service, cache_service)
    task_id = job_id = None
    if result.status == "valid" and result.model:
        staged, refused = await _stage(
            TASK_TOOL_CREATE, {**_task_args(result.model), "link_to_chat": True}, _task_context(request_data),
            request_data=request_data, cache_service=cache_service, directus_service=directus_service,
            encryption_service=encryption_service, user_vault_key_id=user_vault_key_id,
        )
        if refused:
            result = TaskFenceResult("invalid", None, result.source_json, result.title, refused, result.warnings)
        else:
            job = staged.get("job") or {}
            task_id, job_id = job.get("task_id"), job.get("job_id")
            if task_id:
                remember_reply_task(request_data, result.title, str(task_id))
            await _publish_job(staged, cache_service=cache_service, request_data=request_data)
    if result.errors:
        logger.info("%s Task create block rejected with codes %s", log_prefix, [error["code"] for error in result.errors])
    return await embed_service.update_json_content_embed_content(
        embed_id=embed_id, source_json=result.source_json, chat_id=request_data.chat_id,
        user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
        user_vault_key_id=user_vault_key_id, source_language=TASK_FENCE_SOURCE_LANGUAGE,
        status="finished" if result.status == "valid" else "error", title=result.title or None,
        task_content=embed_content_for(result, task_id=task_id, job_id=job_id, task_version=1),
        log_prefix=log_prefix,
    )


async def _reject_task_diff(
    current: dict[str, Any], errors: list[dict[str, str]], warnings: list[dict[str, str]], *, embed_id: str,
    request_data: Any, embed_service: Any, user_vault_key_id: str, log_prefix: str,
) -> str:
    """Keep the Task and the embed source; mark the card invalid and return the note for the assistant."""
    kept = {**{k: v for k, v in current.items() if k not in ("task_source", "validation")},
            "validation": {"status": "invalid", "errors": errors, "warnings": warnings}}
    await embed_service.update_json_content_embed_content(
        embed_id=embed_id, source_json=str(current.get("task_source") or ""), chat_id=request_data.chat_id,
        user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
        user_vault_key_id=user_vault_key_id, source_language=TASK_FENCE_SOURCE_LANGUAGE,
        status="error", task_content=kept, log_prefix=log_prefix,
    )
    logger.info("%s [TASK_DIFF] Edit rejected (was %s): %s", log_prefix,
                (current.get("validation") or {}).get("status"), [e["code"] for e in errors])
    return "task edit not applied: " + "; ".join(e["message"] for e in errors)


async def apply_task_embed_diff(
    *, embed_id: str, current: dict[str, Any], new_source: str, new_version: int,
    version_history_rows: list[dict[str, Any]], content_hash: str, request_data: Any,
    embed_service: Any, cache_service: Any, directus_service: Any, encryption_service: Any,
    user_vault_key_id: str, log_prefix: str,
) -> str | None:
    """Apply a patched ``task_source``; return a short note when it is not applied."""
    result = _checked(new_source, request_data, allow_done=True)
    task_id = str(current.get("task_id") or "")
    if result.status != "valid" or not result.model:
        return await _reject_task_diff(current, result.errors, result.warnings, embed_id=embed_id,
                                       request_data=request_data, embed_service=embed_service,
                                       user_vault_key_id=user_vault_key_id, log_prefix=log_prefix)

    staging = dict(request_data=request_data, cache_service=cache_service, directus_service=directus_service,
                   encryption_service=encryption_service, user_vault_key_id=user_vault_key_id)
    if task_id:
        version = int(current.get("task_version") or 1)
        args = {**_task_args(result.model), "task_id": task_id, "expected_version": version,
                "due_at": result.model.get("due_at")}
        staged, refused = await _stage(
            TASK_TOOL_UPDATE, args, _task_context(request_data, [{"task_id": task_id, "version": version,
                                                                 "status": current.get("status") or "todo"}]),
            **staging,
        )
    else:
        # The first version was invalid, so no Task exists yet: the fixing diff creates it.
        version = 0
        staged, refused = await _stage(
            TASK_TOOL_CREATE, {**_task_args(result.model), "link_to_chat": True}, _task_context(request_data),
            **staging,
        )
    if refused:
        return await _reject_task_diff(current, refused, result.warnings, embed_id=embed_id,
                                       request_data=request_data, embed_service=embed_service,
                                       user_vault_key_id=user_vault_key_id, log_prefix=log_prefix)
    job = staged.get("job") or {}
    task_id = task_id or str(job.get("task_id") or "")
    await _publish_job(staged, cache_service=cache_service, request_data=request_data)
    await embed_service.update_json_content_embed_content(
        embed_id=embed_id, source_json=result.source_json, chat_id=request_data.chat_id,
        user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
        user_vault_key_id=user_vault_key_id, source_language=TASK_FENCE_SOURCE_LANGUAGE,
        status="finished", title=result.title, version_number=new_version, content_hash=content_hash,
        version_history_rows=version_history_rows,
        task_content=embed_content_for(result, task_id=task_id, job_id=job.get("job_id"), task_version=version + 1),
        log_prefix=log_prefix,
    )
    return None


def task_embed_history_text(content: dict[str, Any], embed_ref: str = "") -> str:
    """Text a task embed contributes to the next turn's history (diff target or fixable errors)."""
    validation = content.get("validation") or {}
    ref = f" {embed_ref}" if embed_ref else ""
    if validation.get("status") == "invalid":
        return (f"Task embed{ref} was NOT applied. Fix it with a diff against its task_source:\n"
                f"{task_validation_feedback(validation.get('errors') or [])}\n"
                f"task_source:\n{content.get('task_source', '')}")
    return f"Task embed{ref} task_source (edit with a diff):\n{content.get('task_source', '')}"
