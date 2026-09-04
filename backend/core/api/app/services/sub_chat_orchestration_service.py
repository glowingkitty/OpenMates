"""
Internal client for durable sub-chat orchestration transactions.

The API and workers authorize first-party chat operations, then this service
delegates root limits and atomic child preparation to Directus. Payloads contain
identifiers and counters only; private prompts, titles, summaries, and keys are
forbidden by the transaction extension and are never logged here.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any


logger = logging.getLogger(__name__)

ORCHESTRATION_OPERATIONS = {
    "health_check",
    "create_root",
    "approve_root_limits",
    "prepare_batch",
    "claim_child",
    "transition_child",
    "transition_root",
    "claim_parent_continuation",
    "mark_parent_continuation_dispatched",
    "get_root_state",
    "reserve_operation",
    "fail_operation",
    "cleanup_expired_reservations",
    "commit_personal_charge",
    "commit_personal_refund",
    "get_personal_charge",
    "create_or_reuse_pending_settlement",
    "get_pending_settlement",
    "replay_pending_settlement",
    "complete_pending_settlement",
    "transition_pending_settlement_to_manual_review",
    "commit_team_charge",
    "commit_team_credit_add",
}


class SubChatOrchestrationProtocolError(RuntimeError):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Sub-chat orchestration operation failed: {code}")


class SubChatOrchestrationService:
    def __init__(self, directus_service: Any) -> None:
        self._directus = directus_service

    async def execute(self, operation: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if operation not in ORCHESTRATION_OPERATIONS:
            raise ValueError("Unsupported sub-chat orchestration operation")
        if not isinstance(data, Mapping):
            raise TypeError("Sub-chat orchestration operation data must be a mapping")
        internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not internal_token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for sub-chat orchestration")

        response = await self._directus._make_api_request(
            "POST",
            f"{self._directus.base_url.rstrip('/')}/sub-chat-orchestration-transaction",
            headers={"X-Internal-Service-Token": internal_token},
            json={"operation": operation, "data": dict(data)},
        )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Sub-chat orchestration extension returned malformed JSON") from exc

        if response.status_code != 200:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            safe_code = code if isinstance(code, str) and code else "transaction_failed"
            logger.warning(
                "Sub-chat orchestration rejected: operation=%s code=%s status=%s",
                operation,
                safe_code,
                response.status_code,
            )
            raise SubChatOrchestrationProtocolError(response.status_code, safe_code)

        result = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("Sub-chat orchestration extension returned malformed success data")
        return result
