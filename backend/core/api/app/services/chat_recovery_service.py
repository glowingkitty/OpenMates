"""
Internal client for atomic chat completion recovery persistence.

The public API and workers authorize recovery operations, then this service
delegates the cross-collection transaction to the internal Directus extension.
Payloads may contain ciphertext and sealed envelopes and are never logged.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any


logger = logging.getLogger(__name__)

RECOVERY_OPERATIONS = {
    "prepare_preflight",
    "enqueue_inference",
    "claim_inference",
    "mark_outbox_dispatched",
    "mark_inference_failed",
    "create_sealed_job",
    "list_available_jobs",
    "lease_job",
    "renew_lease",
    "persist_terminal",
    "invalidate_deletion",
    "cleanup_expired",
}


class ChatRecoveryProtocolError(RuntimeError):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Chat recovery operation failed: {code}")


class ChatRecoveryService:
    def __init__(self, directus_service: Any) -> None:
        self._directus = directus_service

    async def execute(self, operation: str, data: Mapping[str, Any]) -> dict[str, Any]:
        if operation not in RECOVERY_OPERATIONS:
            raise ValueError("Unsupported chat recovery operation")
        if not isinstance(data, Mapping):
            raise TypeError("Chat recovery operation data must be a mapping")
        internal_token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not internal_token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for chat recovery transactions")

        response = await self._directus._make_api_request(
            "POST",
            f"{self._directus.base_url.rstrip('/')}/chat-recovery-transaction",
            headers={"X-Internal-Service-Token": internal_token},
            json={"operation": operation, "data": dict(data)},
        )
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Chat recovery extension returned malformed JSON") from exc

        if response.status_code != 200:
            error = payload.get("error") if isinstance(payload, dict) else None
            code = error.get("code") if isinstance(error, dict) else None
            safe_code = code if isinstance(code, str) and code else "transaction_failed"
            logger.warning(
                "Chat recovery transaction rejected: operation=%s code=%s status=%s",
                operation,
                safe_code,
                response.status_code,
            )
            raise ChatRecoveryProtocolError(response.status_code, safe_code)

        result = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            raise RuntimeError("Chat recovery extension returned malformed success data")
        return result
