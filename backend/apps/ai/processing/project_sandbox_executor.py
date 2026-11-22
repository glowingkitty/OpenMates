"""Run Project file tools inline in the chat's hosted E2B sandbox (users who allowed E2B only)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import HTTPException

from backend.core.api.app.services import e2b_upload_consent
from backend.core.api.app.services.project_sandbox_service import (
    ProjectSandboxService,
    ProjectSandboxUnavailable,
)
from backend.core.api.app.services.project_sandbox_writeback import commit_revisions
from backend.shared.providers.e2b_project_sandbox import ProjectSandboxError

logger = logging.getLogger(__name__)


# Operations the sandbox runs itself (openmates-sandbox-host `/v1/op`). Others, such as
# `commit` (a Project Timeline commit), keep the device path (projects.sandbox.jobs).
SANDBOX_OPERATIONS = frozenset(
    {"list", "search", "read_text", "create_file", "update_file", "rename_file", "delete_file"}
)


async def run_project_tool_in_sandbox(
    *, request_data: Any, operation: str, operation_arguments: dict, dispatch_focus: dict,
    cache_service: Any, directus_service: Any, log_prefix: str,
    sandbox_service: Optional[ProjectSandboxService] = None, head_loader: Any = None,
) -> Optional[dict]:
    """Return the model-facing tool result, or None when the device path must handle the operation."""
    if dispatch_focus.get("source_id"):
        return None  # connected-machine sources stay on their own executor
    if operation not in SANDBOX_OPERATIONS:
        return None
    user_id, chat_id = request_data.user_id, request_data.chat_id
    try:
        consent = await e2b_upload_consent.get_decision(user_id, directus_service)
    except HTTPException as exc:
        logger.warning("%s Sandbox skipped: consent unavailable (status %s)", log_prefix, exc.status_code)
        return None
    if consent.get("decision") != "allowed":
        return None
    project_id = str(dispatch_focus["project_id"])
    team_id = dispatch_focus.get("team_id")
    service = sandbox_service or ProjectSandboxService(cache_service, directus_service)
    try:
        handle = await service.ensure_ready(user_id=user_id, chat_id=chat_id, project_id=project_id,
                                            team_id=team_id)
    except ProjectSandboxUnavailable as exc:
        logger.warning("%s Project sandbox unavailable: %s", log_prefix, exc.reason)
        return None
    except (ProjectSandboxError, HTTPException) as exc:
        logger.warning("%s Project sandbox setup failed: %s", log_prefix,
                       getattr(exc, "code", None) or getattr(exc, "status_code", "error"))
        return None
    operation_id = str(uuid.uuid4())
    try:
        answer = await handle.client.call(
            "/v1/op", {"operation": operation, "arguments": operation_arguments}, timeout=300.0)
    except ProjectSandboxError as exc:
        logger.warning("%s Project sandbox operation failed: %s", log_prefix, exc.code)
        return {"status": "rejected", "operation_id": operation_id, "operation": operation,
                "reason": "Project sandbox operation failed.", "code": exc.code}
    result = answer.get("result") if isinstance(answer.get("result"), dict) else {}
    write_back = None
    revisions = answer.get("revisions") or []
    if revisions:
        outcome = await commit_revisions(
            handle, revisions, user_id=user_id, chat_id=chat_id, project_id=project_id, team_id=team_id,
            operation_id=operation_id, directus_service=directus_service, cache_service=cache_service,
            head_loader=head_loader)
        write_back = outcome.summary()
    await service.touch(user_id=user_id, chat_id=chat_id, project_id=project_id)
    envelope = {**result, "operation_id": operation_id, "operation": operation,
                "status": result.get("status", "completed")}
    if write_back is not None:
        envelope["write_back"] = write_back
    return envelope
