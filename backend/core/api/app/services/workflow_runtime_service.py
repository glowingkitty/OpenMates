"""
Internal client for atomic Workflow runtime transactions.

Workers authorize Workflow operations, then this client delegates claims and
event acceptance to Directus so the database, rather than process memory,
enforces idempotency. Trigger ciphertext is never logged by this boundary.

Spec: docs/specs/workflows-v1/spec.yml
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any


logger = logging.getLogger(__name__)
WORKFLOW_RUNTIME_OPERATIONS = frozenset(
    {
        "claim_due_trigger",
        "start_claimed_run",
        "advance_claimed_trigger",
        "accept_event_trigger",
    }
)


class WorkflowRuntimeProtocolError(RuntimeError):
    """Typed rejection returned by the atomic Workflow Directus endpoint."""

    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Workflow runtime operation failed: {code}")


class WorkflowRuntimeService:
    """Delegates durable Workflow claims and receipts to Directus."""

    def __init__(self, directus_service: Any) -> None:
        self._directus = directus_service

    async def execute(self, operation: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if operation not in WORKFLOW_RUNTIME_OPERATIONS:
            raise ValueError("Unsupported workflow runtime operation")
        if not isinstance(data, Mapping):
            raise TypeError("Workflow runtime operation data must be a mapping")

        internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not internal_token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for workflow runtime transactions")

        response = await self._directus._make_api_request(
            "POST",
            f"{self._directus.base_url.rstrip('/')}/workflow-runtime-transaction",
            headers={"X-Internal-Service-Token": internal_token},
            json={"operation": operation, "data": {"protocol_version": 1, **dict(data)}},
        )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Workflow runtime extension returned malformed JSON") from exc

        if response.status_code != 200:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            safe_code = code if isinstance(code, str) and code else "transaction_failed"
            logger.warning(
                "Workflow runtime transaction rejected: operation=%s code=%s status=%s",
                operation,
                safe_code,
                response.status_code,
            )
            raise WorkflowRuntimeProtocolError(response.status_code, safe_code)

        result = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("Workflow runtime extension returned malformed success data")
        return result
