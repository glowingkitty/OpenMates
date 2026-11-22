"""Reference-only chat events for applied Project file changes.

Each applied change (a file tool step or a command write-back batch) is
published as a durable ``projects``/``change`` embed at the point of the reply
stream where it happened. Only locations cross the boundary: Project-relative
paths and a full sha256 revision, never contents, diffs or snippets.
"""

from __future__ import annotations

from typing import Any

from backend.apps.ai.processing.project_file_references import _valid_revision_hash

CHANGE_TOOL_ACTIONS = {
    "project_create_file": "created", "project_update_file": "updated",
    "project_delete_file": "deleted", "project_rename_file": "renamed",
}
SANDBOX_OPERATION_ACTIONS = {
    "create_file": "created", "update_file": "updated",
    "delete_file": "deleted", "rename_file": "renamed",
}
ACTIONS = frozenset(CHANGE_TOOL_ACTIONS.values())
ORIGINS = frozenset({"file_tool", "command"})
_ALLOWED_ROW_KEYS = {"project_id", "project_name", "path", "action", "from_path", "expected_base", "team_id"}
_KIND_ACTIONS = {"created": "created", "added": "created", "create": "created",
                 "deleted": "deleted", "removed": "deleted", "delete": "deleted"}


def _valid_path(path: Any) -> str | None:
    """Same path rules as the read reference: relative, normalized, bounded."""
    if (not isinstance(path, str) or not path or len(path) > 4096
            or path.startswith(("/", "\\")) or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))):
        return None
    return path


def _row(path: Any, action: str, *, from_path: Any = None, revision: Any = None) -> dict[str, Any] | None:
    valid = _valid_path(path)
    if not valid or action not in ACTIONS:
        return None
    row: dict[str, Any] = {"path": valid, "action": action}
    if action == "renamed":
        source = _valid_path(from_path)
        if not source:
            return None
        row["from_path"] = source
    revision_hash = _valid_revision_hash(revision)
    if revision_hash and action != "deleted":
        row["expected_base"] = revision_hash
    return row


def _applied_device_result(result: Any) -> bool:
    return (isinstance(result, dict) and result.get("status") == "completed"
            and not result.get("idempotent") and not result.get("noop")
            and not result.get("refused") and not result.get("conflict"))


def device_change_rows(skill_id: str, arguments: dict[str, Any], results: list[Any]) -> list[dict[str, Any]]:
    """Rows for one completed device write tool (refused/idempotent/failed give none)."""
    action = CHANGE_TOOL_ACTIONS.get(skill_id)
    if not action or not any(_applied_device_result(r) for r in results):
        return []
    applied = next(r for r in results if _applied_device_result(r))
    revision = next((applied.get(key) for key in ("expected_base", "new_revision", "revision")
                     if _valid_revision_hash(applied.get(key))), None)
    path = arguments.get("new_path") if action == "renamed" else arguments.get("path")
    row = _row(path, action, from_path=arguments.get("path"), revision=revision)
    return [row] if row else []


def sandbox_change_rows(operation: str, arguments: dict[str, Any], envelope: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows for a write applied inline in the hosted sandbox (only what was committed/merged)."""
    action = SANDBOX_OPERATION_ACTIONS.get(operation)
    write_back = envelope.get("write_back") if isinstance(envelope, dict) else None
    if not action or envelope.get("status") != "completed" or not isinstance(write_back, dict):
        return []
    applied = {p for key in ("committed", "merged") for p in (write_back.get(key) or []) if isinstance(p, str)}
    path = arguments.get("new_path") if action == "renamed" else arguments.get("path")
    if path not in applied:
        return []
    revision = next((envelope.get(key) for key in ("expected_base", "new_revision", "revision")
                     if _valid_revision_hash(envelope.get(key))), None)
    row = _row(path, action, from_path=arguments.get("path"), revision=revision)
    return [row] if row else []


def command_change_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Rows for the committed/merged paths of one command's write-back summary."""
    write_back = result.get("write_back") if isinstance(result, dict) else None
    if not isinstance(write_back, dict):
        return []
    kinds = {c.get("path"): c.get("kind") for c in result.get("changed_files") or [] if isinstance(c, dict)}
    rows: list[dict[str, Any]] = []
    for path in dict.fromkeys(p for key in ("committed", "merged") for p in (write_back.get(key) or [])):
        row = _row(path, _KIND_ACTIONS.get(str(kinds.get(path)), "updated"))
        if row:
            rows.append(row)
    return rows


def build_project_file_change_preview(
    *, context: dict[str, Any], completed_results: list[dict[str, Any]], result_status: str,
) -> dict[str, Any] | None:
    """Project an applied device file write or command write-back onto the change allowlist."""
    # Device file jobs complete as "completed"; code.run commands finish as "finished".
    if result_status not in {"completed", "finished"}:
        return None
    request = context.get("request_data") or {}
    focus = request.get("active_project_focus") or {}
    project_id = focus.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        return None
    skill_id = context.get("skill_id")
    if context.get("app_id") == "system" and skill_id in CHANGE_TOOL_ACTIONS:
        origin = "file_tool"
        rows = device_change_rows(skill_id, context.get("tool_arguments") or {}, completed_results)
    else:
        origin = "command"
        rows = [row for result in completed_results for row in command_change_rows(result)]
    return build_change_preview(
        origin=origin, project_id=project_id, rows=rows,
        project_name=next((c.get("name") for c in request.get("project_focus_candidates", [])
                           if c.get("project_id") == project_id), None),
        team_id=request.get("team_id") or focus.get("team_id"),
    )


def build_change_preview(
    *, origin: str, project_id: str, rows: list[dict[str, Any]], project_name: Any = None, team_id: Any = None,
) -> dict[str, Any] | None:
    """Attach project identity to rows; None when nothing was applied."""
    if origin not in ORIGINS or not rows:
        return None
    name = str(project_name or "Project")[:160]
    results = []
    for row in rows[:100]:
        item = {"project_id": project_id, "project_name": name, **row}
        if team_id:
            item["team_id"] = team_id
        results.append(item)
    return {"project_id": project_id, "origin": origin, "results": results}


async def publish_project_file_change_preview(
    *, preview: dict[str, Any], request_data: Any, cache_service: Any, directus_service: Any,
    encryption_service: Any, user_vault_key_id: str | None, task_id: str, log_prefix: str,
) -> str | None:
    """Publish through the regular encrypted/recoverable embed pipeline."""
    from backend.core.api.app.services.embed_service import EmbedService

    focus = request_data.active_project_focus or {}
    if (focus.get("project_id") != preview.get("project_id") or preview.get("origin") not in ORIGINS
            or not cache_service or not directus_service or not user_vault_key_id):
        return None
    results = []
    for row in preview.get("results", [])[:100]:
        if not isinstance(row, dict) or row.get("project_id") != focus["project_id"]:
            continue
        clean = _row(row.get("path"), row.get("action"), from_path=row.get("from_path"),
                     revision=row.get("expected_base"))
        if not clean:
            continue
        results.append({**{k: v for k, v in row.items() if k in {"project_id", "project_name", "team_id"}}, **clean})
    if not results:
        return None
    if request_data.is_async_skill_continuation:
        # Recheck the original user turn right before recoverable publication.
        from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
        from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError
        from backend.shared.python_utils.recent_work_summary_client import authoritative_context_turn_id

        current_turn = await cache_service.get(
            async_skill_latest_user_turn_key(request_data.user_id, request_data.chat_id))
        if current_turn != authoritative_context_turn_id(request_data):
            raise RequiredRecoveryOutputError("Project file change belongs to a superseded user turn")
    service = EmbedService(cache_service, directus_service, encryption_service)
    created = await service.create_embeds_from_skill_results(
        app_id="projects", skill_id="change", results=results,
        chat_id=request_data.chat_id, message_id=request_data.message_id,
        user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
        user_vault_key_id=user_vault_key_id, task_id=task_id, log_prefix=log_prefix,
        request_metadata={"origin": preview["origin"]},
    )
    if not created:
        raise RuntimeError("Project file change publication failed")
    return created["embed_reference"]


async def publish_inline_project_file_change(
    *, request_data: Any, operation: str, operation_arguments: dict[str, Any], envelope: dict[str, Any],
    dispatch_focus: dict[str, Any], cache_service: Any, directus_service: Any, encryption_service: Any,
    user_vault_key_id: str | None, task_id: str, log_prefix: str,
) -> str | None:
    """Publish the change embed of a write the hosted sandbox applied inline; None when nothing applied."""
    rows = sandbox_change_rows(operation, operation_arguments, envelope)
    focus = request_data.active_project_focus or {}
    if not rows or focus.get("project_id") != dispatch_focus.get("project_id"):
        return None
    candidates = getattr(request_data, "project_focus_candidates", None) or []
    preview = build_change_preview(
        origin="file_tool", project_id=focus["project_id"], rows=rows,
        project_name=next((c.get("name") for c in candidates
                           if isinstance(c, dict) and c.get("project_id") == focus["project_id"]), None),
        team_id=dispatch_focus.get("team_id"),
    )
    return await publish_project_file_change_preview(
        preview=preview, request_data=request_data, cache_service=cache_service,
        directus_service=directus_service, encryption_service=encryption_service,
        user_vault_key_id=user_vault_key_id, task_id=task_id, log_prefix=log_prefix,
    )
