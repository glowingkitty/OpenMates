# backend/core/api/app/routes/handlers/websocket_handlers/project_sandbox_key_grant_handler.py
#
# Device answers to `project_sandbox_key_request`: a sealed Project key grant or
# a decline. The sealed grant is forwarded once, in memory, over a transient
# Redis pub/sub channel to the waiting ProjectSandboxService.ensure_ready. It is
# never logged, never put in a span and never stored. The span helper receives
# only the trace context, not the payload.
# Plan: docs/plans/hosted-project-sandbox (contracts.md section 1).

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from backend.core.api.app.services.project_sandbox_service import KEY_REQUEST_PREFIX, key_grant_channel
from backend.shared.python_utils.tracing.ws_span_helper import end_ws_handler_span, start_ws_handler_span

logger = logging.getLogger(__name__)

DECLINE_REASONS = {"no_key", "expired", "invalid"}
MAX_SEALED_GRANT_CHARS = 4096


async def _reject(manager: Any, user_id: str, device: str, code: str) -> None:
    await manager.send_personal_message({"type": "error", "payload": {"message": code}}, user_id, device)


async def handle_project_sandbox_key_answer(
    manager: Any, cache_service: Any, user_id: str, device_fingerprint_hash: str,
    payload: Dict[str, Any], *, granted: bool, user_otel_attrs: dict | None = None,
) -> None:
    trace_only = {"_traceparent": payload.get("_traceparent")} if isinstance(payload, dict) else None
    span, token = start_ws_handler_span(
        "project_sandbox_key_grant" if granted else "project_sandbox_key_decline",
        user_id, trace_only, user_otel_attrs)
    try:
        await _handle(manager, cache_service, user_id, device_fingerprint_hash, payload, granted)
    finally:
        end_ws_handler_span(span, token)


async def _handle(manager, cache_service, user_id, device, payload, granted: bool) -> None:
    request_id = payload.get("request_id")
    job_id = payload.get("job_id")
    if not isinstance(request_id, str) or not isinstance(job_id, str) or not request_id:
        await _reject(manager, user_id, device, "project_sandbox_invalid_answer")
        return
    pending = await cache_service.get(KEY_REQUEST_PREFIX + request_id)
    if isinstance(pending, str):
        try:
            pending = json.loads(pending)
        except ValueError:
            pending = None
    if not isinstance(pending, dict) or pending.get("user_id") != user_id or pending.get("job_id") != job_id:
        logger.warning("Project sandbox key answer for unknown or foreign request")
        await _reject(manager, user_id, device, "project_sandbox_request_mismatch")
        return
    if granted:
        sealed = payload.get("sealed_grant")
        if not isinstance(sealed, str) or not sealed or len(sealed) > MAX_SEALED_GRANT_CHARS:
            await _reject(manager, user_id, device, "project_sandbox_invalid_answer")
            return
        message = {"kind": "grant", "sealed_grant": sealed}
    else:
        reason = payload.get("reason")
        message = {"kind": "decline", "reason": reason if reason in DECLINE_REASONS else "invalid"}
    redis = await cache_service.client
    if not redis:
        return
    await redis.publish(key_grant_channel(request_id), json.dumps(message))
    message.clear()
