"""Client-executed Plan creation requests (contract openmates.plan_create_request v1).

Plans are client-side encrypted, so the server can only *ask* a capable
first-party client to create one. This module owns the transient Redis record
of the request, the event published to connected clients and validation of the
client's completion report. Contract:
``docs/plans/spec-sub-chats/contracts/plan-create-request.md``; keep both in sync.

Plan text (title, summary, goal, assumptions) lives only in the event the model
call already produced; the Redis record holds ids only and nothing here logs it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

PLAN_CREATE_CONTRACT = "openmates.plan_create_request"
PLAN_CREATE_CONTRACT_VERSION = 1
PLAN_CREATE_CAPABILITY = "plan_create_requests"
PLAN_CREATE_EVENT = "plan_create_requested"
PLAN_CREATE_RESULT_MESSAGE = "plan_create_result"
PLAN_CREATE_REQUEST_TTL = 10 * 60
PLAN_CREATE_RESULT_STATUSES = frozenset({"created", "failed"})
_REQUEST_ID_RE = re.compile(r"^plan-create-request-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_FAILURE_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def plan_create_record_key(user_id: str, request_id: str) -> str:
    return f"plan_create_request:v1:{_hash(user_id)}:{request_id}"


def outbound_plan_create_event(payload: Any) -> dict[str, Any] | None:
    """Re-validate a pub/sub event before it is forwarded to a client socket."""
    if not isinstance(payload, dict):
        return None
    action, request_id = payload.get("pending_client_action"), payload.get("request_id")
    if (not isinstance(action, dict) or not isinstance(request_id, str)
            or not _REQUEST_ID_RE.fullmatch(request_id) or action.get("request_id") != request_id
            or action.get("contract") != PLAN_CREATE_CONTRACT):
        return None
    return {"chat_id": payload.get("chat_id"), "request_id": request_id, "pending_client_action": action}


async def publish_plan_create_request(*, cache_service: Any, user_id: str, action: dict[str, Any]) -> bool:
    """Store the request record and publish the event; marks the action as queued.

    Returns False (action unchanged, ``notification_queued`` stays false) when
    the cache or Redis is unavailable, so the caller can still return the action.
    """
    now = time.time()
    action["expires_at"] = int(now + PLAN_CREATE_REQUEST_TTL)
    client = await cache_service.client if cache_service else None
    if not client:
        logger.warning("Plan create request not published request=%s: cache unavailable", action.get("request_id"))
        return False
    record = {
        "request_id": action["request_id"], "user_hash": _hash(user_id), "chat_id": action.get("chat_id"),
        "plan_id": action["plan_id"],
        "assumption_ids": [item["assumption_id"] for item in action.get("assumptions", [])],
        "expires_at": action["expires_at"],
    }
    if not await cache_service.set(plan_create_record_key(user_id, action["request_id"]), record,
                                   ttl=PLAN_CREATE_REQUEST_TTL):
        logger.warning("Plan create request record not stored request=%s", action["request_id"])
        return False
    action["notification_queued"] = True
    await client.publish(f"user_cache_events:{user_id}", json.dumps({
        "event_type": PLAN_CREATE_EVENT,
        "payload": {"chat_id": action.get("chat_id"), "request_id": action["request_id"],
                    "pending_client_action": action},
    }))
    return True


def parse_plan_create_result(payload: Any) -> dict[str, Any] | None:
    """Validate the report shape; None when malformed."""
    if not isinstance(payload, dict):
        return None
    request_id, status, plan_id = payload.get("request_id"), payload.get("status"), payload.get("plan_id")
    if (not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id)
            or status not in PLAN_CREATE_RESULT_STATUSES or not isinstance(plan_id, str)
            or not 0 < len(plan_id) <= 128):
        return None
    code = payload.get("error_code")
    return {"request_id": request_id, "status": status, "plan_id": plan_id,
            "error_code": code if isinstance(code, str) and _FAILURE_CODE_RE.fullmatch(code) else None}


async def handle_plan_create_result(
    *, manager: Any, cache_service: Any, user_id: str, device_fingerprint_hash: str, payload: Any,
) -> bool:
    """Accept a completion report for this owner's live request; ignore anything else."""
    report = parse_plan_create_result(payload)
    if report is None:
        logger.warning("Plan create result ignored: malformed")
        return False
    if not manager.can_execute_plan_create(user_id, device_fingerprint_hash):
        logger.warning("Plan create result ignored request=%s: device lacks capability", report["request_id"])
        return False
    key = plan_create_record_key(user_id, report["request_id"])
    record = await cache_service.get(key)
    if (not isinstance(record, dict) or record.get("user_hash") != _hash(user_id)
            or time.time() >= record.get("expires_at", 0)):
        logger.warning("Plan create result ignored request=%s: unknown or expired", report["request_id"])
        return False
    if record.get("plan_id") != report["plan_id"]:
        logger.warning("Plan create result ignored request=%s: plan id mismatch", report["request_id"])
        return False
    await cache_service.delete(key)
    logger.info("Plan create result request=%s plan=%s status=%s error_code=%s", report["request_id"],
                report["plan_id"], report["status"], report["error_code"])
    return True
