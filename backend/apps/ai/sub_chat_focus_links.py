# backend/apps/ai/sub_chat_focus_links.py
#
# Focus inheritance and Plan/Task links for start_sub_chats children
# (feature.focus-modes project-layering; plans.assumptions.investigated-before-work).
# A sub-chat inherits its parent's active Project base focus and may add one
# specific focus on top (at most two focus modes). Assumption links are written
# by the client (encrypted Plan rows); a Task link is written here because Task
# ownership is verified server-side. Tests: backend/tests/test_sub_chat_orchestration.py.

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

LINK_KINDS = {"assumption", "task"}
_BUILTIN_FOCUS_RE = re.compile(r"^[a-z0-9_]+-[a-z0-9_-]+$")


def parse_sub_chat_link(raw: Any) -> dict[str, str] | None:
    """Return a normalized {kind, plan_id, id} link or None when malformed."""
    if not isinstance(raw, dict) or raw.get("kind") not in LINK_KINDS:
        return None
    try:
        plan_id = str(uuid.UUID(str(raw.get("plan_id"))))
    except ValueError:
        return None
    link_id = raw.get("id")
    if not isinstance(link_id, str) or not link_id.strip() or len(link_id) > 128:
        return None
    return {"kind": raw["kind"], "plan_id": plan_id, "id": link_id.strip()}


async def _known_builtin_focus_ids(cache_service: Any) -> set[str]:
    getter = getattr(cache_service, "get_discovered_apps_metadata", None)
    if not callable(getter):
        return set()
    metadata = await getter() or {}
    return {
        f"{app_id}-{focus.id}"
        for app_id, app in metadata.items()
        for focus in (getattr(app, "focuses", None) or [])
    }


def validate_focus_id(
    focus_id: Any, *, known_builtin: set[str], parent_specialist_id: str | None,
) -> str | None:
    """Allow a built-in focus or exactly the parent's active Project specialist."""
    if not isinstance(focus_id, str) or not focus_id:
        return None
    if focus_id.startswith("project-focus:"):
        return focus_id if parent_specialist_id and focus_id == parent_specialist_id else None
    if focus_id.startswith("project-") or not _BUILTIN_FOCUS_RE.match(focus_id):
        return None
    return focus_id if focus_id in known_builtin else None


async def annotate_sub_chats(
    spawned_sub_chats: list[dict[str, Any]],
    *,
    request_data: Any,
    directus_service: Any,
    cache_service: Any,
    log_prefix: str,
) -> None:
    """Set focus_id, project_base and link on each child; invalid values are dropped."""
    parent_binding: dict[str, Any] | None = None
    if cache_service is not None and not request_data.is_incognito:
        from backend.core.api.app.services.project_write_authorization_service import (
            ProjectWriteAuthorizationService,
        )
        parent_binding = await ProjectWriteAuthorizationService(
            directus_service, cache_service,
        ).get_active_focus(user_id=request_data.user_id, chat_id=request_data.chat_id)
    known = await _known_builtin_focus_ids(cache_service) if cache_service is not None else set()
    specialist_id = (parent_binding or {}).get("specialist_focus_id")
    for child in spawned_sub_chats:
        raw_focus, raw_link = child.get("focus_id"), child.get("link")
        child["focus_id"] = validate_focus_id(
            raw_focus, known_builtin=known, parent_specialist_id=specialist_id,
        )
        if raw_focus and not child["focus_id"]:
            logger.warning("%s [SUB_CHAT] Dropped unknown focus_id for child %s", log_prefix, child.get("id"))
        child["link"] = parse_sub_chat_link(raw_link)
        if raw_link and not child["link"]:
            logger.warning("%s [SUB_CHAT] Dropped malformed link for child %s", log_prefix, child.get("id"))
        child["project_base"] = (
            {"project_id": parent_binding["project_id"], "focus_id": parent_binding.get("focus_id")}
            if parent_binding else None
        )


async def apply_inheritance_and_task_links(
    spawned_sub_chats: list[dict[str, Any]],
    *,
    request_data: Any,
    directus_service: Any,
    log_prefix: str,
    cache_factory: Any = None,
) -> None:
    """After child shells exist: write child focus bindings and Task links."""
    from backend.core.api.app.services.project_write_authorization_service import (
        ProjectWriteAuthorizationError, ProjectWriteAuthorizationService,
    )
    if cache_factory is None:
        from backend.core.api.app.services.cache import CacheService as cache_factory
    cache = None
    try:
        for child in spawned_sub_chats:
            if child.get("project_base"):
                cache = cache or cache_factory()
                try:
                    binding = await ProjectWriteAuthorizationService(directus_service, cache).inherit_focus_for_sub_chat(
                        user_id=request_data.user_id, parent_chat_id=request_data.chat_id,
                        child_chat_id=str(child["id"]),
                        specialist_focus_id=child.get("focus_id"),
                    )
                except ProjectWriteAuthorizationError as exc:
                    logger.warning("%s [SUB_CHAT] Focus inheritance refused for %s: %s", log_prefix, child["id"], exc)
                    binding = None
                if not binding:
                    child["project_base"] = None
            link = child.get("link")
            if link and link["kind"] == "task":
                if not await _link_task(directus_service, request_data, child, link, log_prefix):
                    child["link"] = None
    finally:
        if cache is not None and hasattr(cache, "close"):
            await cache.close()


async def _link_task(directus_service: Any, request_data: Any, child: dict[str, Any],
                     link: dict[str, str], log_prefix: str) -> bool:
    task = await directus_service.user_task.get_task(
        link["id"], request_data.user_id, getattr(request_data, "team_id", None),
    )
    if not task or (task.get("plan_id") and task["plan_id"] != link["plan_id"]):
        logger.warning("%s [SUB_CHAT] Refused Task link for child %s", log_prefix, child["id"])
        return False
    await directus_service.update_item(
        "user_tasks", task["id"], {"linked_sub_chat_id": str(child["id"])}, admin_required=True,
    )
    return True


def child_active_focus_id(sub_chat: dict[str, Any], request_data: Any) -> str | None:
    """Specific focus if given, else the inherited Project base, else the parent's."""
    if sub_chat.get("focus_id"):
        return sub_chat["focus_id"]
    base = sub_chat.get("project_base")
    if base:
        return base.get("focus_id")
    return request_data.active_focus_id
