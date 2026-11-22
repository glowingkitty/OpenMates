"""Files the assistant writes in a cloud Project chat are normal code embeds that ARE the Project files.

The model writes a new file as a normal code fence with its Project path
(```tsx:web-app/src/App.tsx) and an edit as ```diff:web-app/src/App.tsx. The
fence streams as a normal code embed; when it closes, the file is committed
through the chat's Project sandbox (the one write path of hosted Project files,
so later commands of the turn see it). The reply then references the committed
Project file embed instead of the streamed placeholder, which is never stored.

Plan: docs/plans/project-files-as-chat-code-embeds/plan.yml.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9._@+-][A-Za-z0-9._@+ -]*$")
# A model-written inline reference to a Project file of this turn: [label](embed:web-app/src/App.tsx#L3).
_INLINE_PATH_LINK = re.compile(r"\]\(embed:([^)\s#]+)(#[^)\s]*)?\)")


def hosted_project_focus(request_data: Any) -> dict[str, Any] | None:
    """The chat's active cloud Project focus, or None (no focus, or a machine-folder source)."""
    focus = getattr(request_data, "active_project_focus", None)
    if not isinstance(focus, dict) or not focus.get("project_id") or focus.get("source_id"):
        return None
    return {"project_id": str(focus["project_id"]), "team_id": focus.get("team_id")}


def fence_project_focus(request_data: Any) -> dict[str, Any] | None:
    """The cloud Project focus whose files this turn writes as code fences (see project_code_fence_mode)."""
    return hosted_project_focus(request_data) if getattr(request_data, "project_code_fences", False) else None


async def project_code_fence_mode(request_data: Any, sources: list[dict[str, Any]] | None, directus_service: Any) -> bool:
    """Whether this chat writes Project files as code fences: a cloud Project whose user allowed the sandbox.

    Machine-folder Projects and users without E2B consent keep the Project file tools.
    """
    from backend.apps.ai.processing.project_file_tools import default_operation_source_id
    from backend.core.api.app.services import e2b_upload_consent

    if hosted_project_focus(request_data) is None or default_operation_source_id(sources or [], "write_request"):
        return False
    from fastapi import HTTPException

    try:
        decision = await e2b_upload_consent.get_decision(request_data.user_id, directus_service)
    except HTTPException as exc:
        logger.warning("Project code fences off: sandbox consent unavailable (status %s)", exc.status_code)
        return False
    return decision.get("decision") == "allowed"


def project_file_path(filename: Any) -> str | None:
    """A fence filename that names a Project file (relative, normalized, at least one folder)."""
    if not isinstance(filename, str):
        return None
    path = filename.strip()
    parts = path.split("/")
    if (len(parts) < 2 or len(path) > 1024 or path.startswith("/") or "\\" in path
            or any(part in {"", ".", ".."} or not _PATH_SEGMENT.match(part) for part in parts)):
        return None
    return path


def _committed_embed_id(envelope: dict[str, Any] | None) -> str | None:
    if not isinstance(envelope, dict) or envelope.get("status") not in (None, "completed"):
        return None
    embed_id = envelope.get("embed_id")
    return embed_id if isinstance(embed_id, str) and embed_id else None


async def _sandbox_op(request_data: Any, focus: dict[str, Any], operation: str, arguments: dict[str, Any],
                      *, cache_service: Any, directus_service: Any, log_prefix: str) -> dict[str, Any] | None:
    from backend.apps.ai.processing.project_sandbox_executor import run_project_tool_in_sandbox

    return await run_project_tool_in_sandbox(
        request_data=request_data, operation=operation, operation_arguments=arguments,
        dispatch_focus=dict(focus), cache_service=cache_service, directus_service=directus_service,
        log_prefix=log_prefix,
    )


async def commit_code_fence(
    request_data: Any, *, path: str, content: str, cache_service: Any, directus_service: Any, log_prefix: str,
) -> dict[str, Any] | None:
    """Create (or, when it exists, replace) a Project file from a closed code fence.

    Returns {"embed_id", "path", "created"} of the committed Project file embed, or None when the
    chat has no usable Project sandbox or the commit was refused (the fence then stays a chat embed).
    """
    focus = fence_project_focus(request_data)
    if focus is None:
        return None
    created = await _sandbox_op(request_data, focus, "create_file",
                                {"path": path, "expected_base": None, "content": content},
                                cache_service=cache_service, directus_service=directus_service,
                                log_prefix=log_prefix)
    embed_id = _committed_embed_id(created)
    if embed_id:
        _remember(request_data, path, embed_id)
        return {"embed_id": embed_id, "path": path, "created": True}
    if not isinstance(created, dict) or created.get("code") != "file_exists":
        logger.warning("%s [PROJECT_FENCE] create of a Project file was not committed: %s",
                       log_prefix, (created or {}).get("code") or "no sandbox")
        return None
    # The model rewrote an existing file in full: commit it as a whole-file update of that file.
    current = await _sandbox_op(request_data, focus, "read_text", {"path": path},
                                cache_service=cache_service, directus_service=directus_service,
                                log_prefix=log_prefix)
    if not isinstance(current, dict) or not isinstance(current.get("content"), str):
        logger.warning("%s [PROJECT_FENCE] existing Project file could not be read for replacement", log_prefix)
        return None
    if current["content"] == content and isinstance(current.get("embed_id"), str):
        _remember(request_data, path, current["embed_id"])
        return {"embed_id": current["embed_id"], "path": path, "created": False}
    patch = "".join(difflib.unified_diff(
        current["content"].splitlines(keepends=True), content.splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}",
    ))
    return await _update(request_data, focus, path, patch, current.get("expected_base"),
                         cache_service=cache_service, directus_service=directus_service, log_prefix=log_prefix)


async def apply_project_diff_fence(
    request_data: Any, *, path: str, patch: str, cache_service: Any, directus_service: Any, log_prefix: str,
) -> dict[str, Any] | None:
    """Apply a ```diff:<Project path> fence to that Project file; None when it could not be applied."""
    focus = fence_project_focus(request_data)
    if focus is None:
        return None
    current = await _sandbox_op(request_data, focus, "read_text", {"path": path},
                                cache_service=cache_service, directus_service=directus_service,
                                log_prefix=log_prefix)
    if not isinstance(current, dict) or not isinstance(current.get("expected_base"), str):
        logger.warning("%s [PROJECT_FENCE] diff target is not a readable Project file", log_prefix)
        return None
    return await _update(request_data, focus, path, patch, current["expected_base"],
                         cache_service=cache_service, directus_service=directus_service, log_prefix=log_prefix)


async def _update(request_data: Any, focus: dict[str, Any], path: str, patch: str, expected_base: Any,
                  *, cache_service: Any, directus_service: Any, log_prefix: str) -> dict[str, Any] | None:
    updated = await _sandbox_op(request_data, focus, "update_file",
                                {"path": path, "expected_base": expected_base, "patch": patch},
                                cache_service=cache_service, directus_service=directus_service,
                                log_prefix=log_prefix)
    embed_id = _committed_embed_id(updated)
    if not embed_id:
        logger.warning("%s [PROJECT_FENCE] update of a Project file was not committed: %s",
                       log_prefix, (updated or {}).get("code") or "no sandbox")
        return None
    _remember(request_data, path, embed_id)
    return {"embed_id": embed_id, "path": path, "created": False}


def _remember(request_data: Any, path: str, embed_id: str) -> None:
    committed = dict(getattr(request_data, "project_fence_files", None) or {})
    committed[path] = embed_id
    request_data.project_fence_files = committed


def code_reference(embed_id: str) -> str:
    """The normal message reference of a code embed."""
    return f"```json\n{json.dumps({'type': 'code', 'embed_id': embed_id})}\n```\n\n"


def swap_streamed_code_reference(chunks: list[str], *, old_embed_id: str, new_embed_id: str) -> bool:
    """Point an already-streamed code reference at the committed Project file embed instead."""
    old = f'"embed_id": "{old_embed_id}"'
    for index in range(len(chunks) - 1, -1, -1):
        if old in chunks[index]:
            chunks[index] = chunks[index].replace(old, f'"embed_id": "{new_embed_id}"')
            return True
    return False


def link_project_file_references(text: str, files: dict[str, str] | None) -> str:
    """Rewrite [label](embed:<Project path>) to the committed file embed of this turn."""
    if not files or "](embed:" not in text:
        return text

    def replace(match: re.Match[str]) -> str:
        embed_id = files.get(match.group(1))
        return f"](embed:{embed_id}{match.group(2) or ''})" if embed_id else match.group(0)

    return _INLINE_PATH_LINK.sub(replace, text)
