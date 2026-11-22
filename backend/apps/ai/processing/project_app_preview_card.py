# backend/apps/ai/processing/project_app_preview_card.py
#
# The application card of a Project app: when a production build passed in
# the chat's hosted Project sandbox, the turn shows one application card per
# built folder. The card carries only the Project id/name and the folder; its
# preview runs that folder's dev server in the same sandbox
# (backend/apps/code/project_sandbox_preview.py), so nothing is built twice.
# Spec: code-run.cloud.project-preview. Plan: docs/plans/project-sandbox-preview.

from __future__ import annotations

import re
from typing import Any

from backend.apps.code.project_sandbox_preview import ProjectPreviewError, normalize_preview_folder

BUILD_COMMAND = re.compile(r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?build\b|\bvite\s+build\b")
MAX_CARDS_PER_TURN = 3


def built_app_folders(results: Any) -> list[str]:
    """Folders of sandbox commands that ran a production build and exited 0, in run order."""
    folders: list[str] = []
    for result in results if isinstance(results, list) else []:
        # write_back is present only for commands that ran in the Project sandbox.
        if not isinstance(result, dict) or not isinstance(result.get("write_back"), dict):
            continue
        if result.get("status") != "finished" or result.get("exit_code") != 0:
            continue
        if not BUILD_COMMAND.search(str(result.get("command") or "")):
            continue
        try:
            folder = normalize_preview_folder(str(result.get("cwd") or ""))
        except ProjectPreviewError:
            continue
        if folder not in folders:
            folders.append(folder)
    return folders[:MAX_CARDS_PER_TURN]


async def publish_project_app_cards(
    *, request_data: Any, folders: list[str], cache_service: Any, directus_service: Any,
    encryption_service: Any, user_vault_key_id: str | None, task_id: str, log_prefix: str,
) -> list[str]:
    """Publish one application card per built folder; return their embed references."""
    from backend.core.api.app.services.embed_service import EmbedService

    focus = getattr(request_data, "active_project_focus", None) or {}
    project_id = focus.get("project_id")
    if not folders or not isinstance(project_id, str) or not project_id or not user_vault_key_id:
        return []
    project_name = next((str(c.get("name")) for c in getattr(request_data, "project_focus_candidates", None) or []
                         if isinstance(c, dict) and c.get("project_id") == project_id and c.get("name")), "Project")
    team_id = getattr(request_data, "team_id", None) or focus.get("team_id")
    service = EmbedService(cache_service, directus_service, encryption_service)
    references: list[str] = []
    for folder in folders[:MAX_CARDS_PER_TURN]:
        created = await service.create_application_embed(
            name=folder.rsplit("/", 1)[-1] if folder else project_name[:160], framework="web", runtime="node",
            file_refs=[], entrypoints=[], chat_id=request_data.chat_id, message_id=request_data.message_id,
            user_id=request_data.user_id, user_id_hash=request_data.user_id_hash,
            user_vault_key_id=user_vault_key_id, task_id=task_id, log_prefix=log_prefix,
            project_source={"project_id": project_id, "project_name": project_name[:160], "cwd": folder,
                            **({"team_id": team_id} if isinstance(team_id, str) else {})},
        )
        if not created:
            raise RuntimeError("Project application card publication failed")
        references.append(created["embed_reference"])
    return references
