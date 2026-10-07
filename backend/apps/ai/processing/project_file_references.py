"""Reference-only chat previews of authorized Project file results.

Read contents and search snippets remain transient model context. Durable cards
contain only locations of existing hosted embeds or live remote source files.
"""

from __future__ import annotations

from typing import Any


def build_project_file_reference_preview(
    *, context: dict[str, Any], completed_results: list[dict[str, Any]], result_status: str,
) -> dict[str, Any] | None:
    """Project an accepted file completion onto a bounded storage allowlist."""
    skill_id = context.get("skill_id")
    if context.get("app_id") != "system" or skill_id not in {"project_search_files", "project_read_text"}:
        return None
    if result_status != "completed":
        return None
    request = context.get("request_data") or {}
    focus = request.get("active_project_focus") or {}
    project_id = focus.get("project_id")
    if not isinstance(project_id, str) or not project_id:
        return None
    candidate = next((row for row in request.get("project_focus_candidates", [])
                      if row.get("project_id") == project_id), {})
    project_name = str(candidate.get("name") or "Project")[:160]
    arguments = context.get("tool_arguments") or {}
    query = str(arguments.get("query") if skill_id == "project_search_files"
                else arguments.get("path") or "")[:640]
    references: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None, int | None]] = set()
    for result in completed_results:
        if result.get("status") != "completed":
            continue
        rows = result.get("matches", []) if skill_id == "project_search_files" else [result]
        if not isinstance(rows, list):
            continue
        source_id = result.get("source_id")
        for row in rows[:100]:
            if not isinstance(row, dict):
                continue
            # Remote read_text replies contain bytes/size, not a path. The
            # dispatched read path is authoritative even if a reply adds one.
            path = arguments.get("path") if skill_id == "project_read_text" else row.get("path")
            if (not isinstance(path, str) or not path or len(path) > 4096
                    or path.startswith(("/", "\\")) or "\\" in path
                    or any(part in {"", ".", ".."} for part in path.split("/"))):
                continue
            embed_id = row.get("embed_id")
            embed_id = embed_id if isinstance(embed_id, str) and 0 < len(embed_id) <= 128 else None
            source = source_id if isinstance(source_id, str) and 0 < len(source_id) <= 128 else None
            # A hosted file must point at the original saved embed; a remote
            # file must identify its executor-selected source, never a copy.
            if not source and not embed_id:
                continue
            line = row.get("line")
            line = line if isinstance(line, int) and not isinstance(line, bool) and line > 0 else None
            identity = (path, source, embed_id, line)
            if identity in seen:
                continue
            seen.add(identity)
            reference: dict[str, Any] = {"project_id": project_id, "project_name": project_name, "path": path}
            if source:
                reference["source_id"] = source
            elif embed_id:
                reference["embed_id"] = embed_id
            if line:
                reference["line"] = line
            if request.get("team_id"):
                reference["team_id"] = request["team_id"]
            references.append(reference)
    if not references:
        return None
    return {"project_id": project_id, "project_name": project_name, "query": query,
            "skill_id": "search" if skill_id == "project_search_files" else "read",
            "results": references[:100]}


async def publish_project_file_reference_preview(
    *, preview: dict[str, Any], request_data: Any, cache_service: Any, directus_service: Any,
    encryption_service: Any, user_vault_key_id: str | None, task_id: str, log_prefix: str,
) -> str | None:
    """Publish through the regular encrypted/recoverable embed pipeline."""
    from backend.core.api.app.services.embed_service import EmbedService

    focus = request_data.active_project_focus or {}
    if (not request_data.is_async_skill_continuation
            or focus.get("project_id") != preview.get("project_id")
            or not cache_service or not directus_service or not user_vault_key_id):
        return None
    # Reapply the field allowlist at publication: no model/client-supplied
    # content, snippets, keys, revision hashes or nested arbitrary metadata.
    allowed = {"project_id", "project_name", "path", "source_id", "embed_id", "line", "team_id"}
    results = [{key: value for key, value in row.items() if key in allowed}
               for row in preview.get("results", [])[:100]
               if isinstance(row, dict) and row.get("project_id") == focus["project_id"]]
    if not results or preview.get("skill_id") not in {"search", "read"}:
        return None
    # Dispatch-time fencing cannot cover time spent queued in Celery. Recheck
    # the original user turn immediately before recoverable publication.
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    from backend.shared.python_utils.chat_recovery_context import RequiredRecoveryOutputError
    from backend.shared.python_utils.recent_work_summary_client import authoritative_context_turn_id

    current_turn = await cache_service.get(
        async_skill_latest_user_turn_key(request_data.user_id, request_data.chat_id),
    )
    if current_turn != authoritative_context_turn_id(request_data):
        raise RequiredRecoveryOutputError("Project file reference belongs to a superseded user turn")
    service = EmbedService(cache_service, directus_service, encryption_service)
    created = await service.create_embeds_from_skill_results(
        app_id="projects", skill_id=preview["skill_id"], results=results,
        chat_id=request_data.chat_id, message_id=request_data.message_id,
        user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
        user_vault_key_id=user_vault_key_id, task_id=task_id, log_prefix=log_prefix,
        request_metadata={"query": preview.get("query", "")},
    )
    if not created:
        raise RuntimeError("Project file reference preview publication failed")
    return created["embed_reference"]
