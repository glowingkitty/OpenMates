"""
Internal client for atomic chat completion recovery persistence.

The public API and workers authorize recovery operations, then this service
delegates the cross-collection transaction to the internal Directus extension.
Payloads may contain ciphertext and sealed envelopes and are never logged.
"""

from __future__ import annotations

import logging
import os
import hashlib
import hmac
import json
import asyncio
from collections.abc import Mapping
from typing import Any


logger = logging.getLogger(__name__)

RECOVERY_OPERATIONS = {
    "create_metadata_job",
    "metadata_job_admitted",
    "list_metadata_jobs",
    "claim_metadata_job",
    "persist_metadata_job",
    "prepare_preflight",
    "verify_committed_team_message",
    "enqueue_inference",
    "claim_inference",
    "mark_outbox_dispatched",
    "mark_inference_failed",
    "create_sealed_job",
    "create_sealed_output",
    "prepare_sealed_output",
    "register_output_producer",
    "register_legacy_output_producer",
    "verify_volatile_output_actor",
    "resolve_output_producer",
    "register_output_producer_child",
    "close_output_producer",
    "classify_untagged_output_producer",
    "get_producer_output",
    "get_replay_output",
    "register_authorized_rerender",
    "register_authorized_direct_skill",
    "complete_authorized_direct_skill",
    "complete_authorized_standalone_asset",
    "complete_authorized_rerender",
    "complete_authorized_direct_by_embed",
    "claim_authorized_direct_producer",
    "verify_claimed_output_producer",
    "reconcile_authorized_direct_completions",
    "list_pending_outputs",
    "get_pending_output",
    "persist_output_message",
    "persist_output_summary",
    "has_pending_chat_outputs",
    "acknowledge_output_checkpoint",
    "acknowledge_output_embed",
    "mark_child_result_delivered",
    "mark_child_parent_consumed",
    "mark_child_canonical_acknowledged",
    "list_available_jobs",
    "lease_job",
    "renew_lease",
    "persist_terminal",
    "invalidate_deletion",
    "invalidate_rewind",
    "lookup_chat_deletion_fences",
    "cleanup_expired",
    "acknowledge_failure_alert",
    "get_cutover_state",
    "set_sends_paused",
    "admit_legacy_inference",
    "bind_ordinary_legacy_dispatch",
    "claim_legacy_inference_start",
    "prepare_legacy_batch",
    "claim_legacy_batch",
    "release_legacy_inference",
    "mark_legacy_inference_completed",
    "acknowledge_legacy_persistence",
    "authorize_legacy_completion",
    "activate_protocol_epoch",
}


class ChatRecoveryProtocolError(RuntimeError):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(f"Chat recovery operation failed: {code}")


class ChatRecoveryService:
    def __init__(self, directus_service: Any) -> None:
        self._directus = directus_service

    @staticmethod
    def content_commitment(canonical_content: bytes | str) -> str:
        """Bind private canonical output with an existing server-managed HMAC key."""
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("INTERNAL_API_SHARED_TOKEN is required for chat recovery commitments")
        if isinstance(canonical_content, str):
            raw = canonical_content.encode("utf-8")
        elif isinstance(canonical_content, bytes):
            raw = canonical_content
        else:
            raise TypeError("Canonical output must be bytes or text")
        return hmac.new(token.encode("utf-8"), b"openmates-recovery-output-v1\0" + raw, hashlib.sha256).hexdigest()

    async def get_producer_output(
        self, data: Mapping[str, Any], *, s3_service: Any | None = None,
    ) -> dict[str, Any]:
        """Return a status-only pre-provider probe or the first sealed receipt."""
        result = await self.execute("get_producer_output", data)
        if "content_commitment" not in data or result.get("status") != "PENDING":
            return result
        if result.get("payload_storage") != "s3":
            return result
        if s3_service is None:
            raise RuntimeError("Regional S3 is required to reuse a sealed output")
        from backend.core.api.app.services.bounded_archive_io import read_verified_bytes

        regions = result.get("payload_verified_regions")
        if isinstance(regions, str):
            regions = json.loads(regions)
        raw = await read_verified_bytes(
            s3_service, result["payload_s3_key"],
            checksum=result["sealed_payload_digest"],
            size_bytes=result["payload_size_bytes"],
            regions=regions, max_bytes=24 * 1024 * 1024,
        )
        result["sealed_payload"] = raw.decode("utf-8")
        result.pop("payload_s3_key", None)
        return result

    async def get_replay_output(
        self, data: Mapping[str, Any], *, s3_service: Any | None = None,
    ) -> dict[str, Any]:
        """Read a same-record main-context output while its preflight still runs."""
        result = await self.execute("get_replay_output", data)
        if result.get("status") != "PENDING" or result.get("payload_storage") != "s3":
            return result
        if s3_service is None:
            raise RuntimeError("Regional S3 is required to reuse a sealed output")
        from backend.core.api.app.services.bounded_archive_io import read_verified_bytes

        regions = result.get("payload_verified_regions")
        if isinstance(regions, str):
            regions = json.loads(regions)
        raw = await read_verified_bytes(
            s3_service, result["payload_s3_key"],
            checksum=result["sealed_payload_digest"],
            size_bytes=result["payload_size_bytes"],
            regions=regions, max_bytes=24 * 1024 * 1024,
        )
        result["sealed_payload"] = raw.decode("utf-8")
        result.pop("payload_s3_key", None)
        return result

    async def save_sealed_output(
        self, data: Mapping[str, Any], *, s3_service: Any | None = None,
    ) -> dict[str, Any]:
        """Verify large ciphertext in regional S3 before publishing its DB locator."""
        body = dict(data)
        payload = body.get("sealed_payload")
        if not isinstance(payload, str):
            raise ValueError("sealed output is missing")
        if body.get("producer_intent_id") is not None:
            probe = await self.get_producer_output({
                "protocol_version": body["protocol_version"],
                "producer_intent_id": body["producer_intent_id"],
                "task_name": body["producer_task_name"],
                "kwargs_binding": body["producer_kwargs_binding"],
                "ordinal": body["producer_ordinal"],
                "content_commitment": body["content_commitment"],
            }, s3_service=s3_service)
            if probe.get("status") in {"PENDING", "ACKNOWLEDGED"}:
                return probe
            if probe.get("status") != "ABSENT":
                raise RuntimeError("Sealed output upload is already being prepared")
        elif body.get("content_commitment") is not None:
            probe = await self.get_replay_output({
                "protocol_version": body["protocol_version"],
                "record_id": body["record_id"],
                "hashed_user_id": body["hashed_user_id"],
                "preflight_id": body["preflight_id"],
                "root_chat_id": body["root_chat_id"],
                "target_chat_id": body["target_chat_id"],
                "subject_id": body["subject_id"],
                "output_kind": body["output_kind"],
                "output_version": body["output_version"],
                "content_commitment": body["content_commitment"],
            }, s3_service=s3_service)
            if probe.get("status") in {"PENDING", "ACKNOWLEDGED"}:
                return probe
            if probe.get("status") != "ABSENT":
                raise RuntimeError("Sealed output upload is already being prepared")
        raw = payload.encode("utf-8")
        if len(raw) <= 256 * 1024:
            return await self.execute("create_sealed_output", body)
        if s3_service is None:
            raise RuntimeError("Large sealed output requires regional S3 before dependent work")
        from backend.core.api.app.services.bounded_archive_io import put_verified_bytes

        digest = hashlib.sha256(raw).hexdigest()
        record_id = str(body["record_id"])
        key = f"chat-recovery/v2/{digest[:2]}/{record_id}/{digest}.json"
        body.pop("sealed_payload")
        body.update({
            "payload_s3_key": key,
            "payload_size_bytes": len(raw),
            "sealed_payload_digest": digest,
        })
        prepared = await self.execute("prepare_sealed_output", body)
        if prepared.get("state") in {"PENDING", "ACKNOWLEDGED"}:
            return prepared
        if prepared.get("state") != "PREPARING":
            raise RuntimeError("Large sealed output intent was not durably prepared")
        # The PREPARING row inventories this key even if the process crashes
        # during the bounded regional upload. It is never visible to clients.
        async with asyncio.timeout(60):
            verified = await put_verified_bytes(
                s3_service, key, raw, content_type="application/json",
                metadata={"recovery-record-id": record_id},
            )
        if verified["checksum"] != digest or verified["size_bytes"] != len(raw):
            raise RuntimeError("Large sealed output regional verification mismatch")
        body["payload_verified_regions"] = verified["verified_regions"]
        return await self.execute("create_sealed_output", body)

    async def get_sealed_output(
        self, data: Mapping[str, Any], *, s3_service: Any | None = None,
    ) -> dict[str, Any]:
        """Return only an authorized, bounded, integrity-checked envelope."""
        result = await self.execute("get_pending_output", data)
        if result.get("payload_storage") != "s3":
            return result
        if s3_service is None:
            raise RuntimeError("Regional S3 is required to recover this output")
        from backend.core.api.app.services.bounded_archive_io import read_verified_bytes

        regions = result.get("payload_verified_regions")
        if isinstance(regions, str):
            regions = json.loads(regions)
        raw = await read_verified_bytes(
            s3_service, result["payload_s3_key"],
            checksum=result["sealed_payload_digest"],
            size_bytes=result["payload_size_bytes"],
            regions=regions, max_bytes=24 * 1024 * 1024,
        )
        result["sealed_payload"] = raw.decode("utf-8")
        result.pop("payload_s3_key", None)
        return result

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


async def assert_no_pending_team_account_recovery(
    *, directus_service: Any, user_id_hash: str,
) -> dict[str, Any]:
    """Atomically reject sole-copy Team recovery and fence an explicit account deletion.

    The idempotent account invalidation prevents later preflight or sealed-output
    publication. It must run before deleting authentication material, including
    when an account deletion task is invoked without the HTTP endpoint.
    """
    return await ChatRecoveryService(directus_service).execute("invalidate_deletion", {
        "protocol_version": 1, "hashed_user_id": user_id_hash, "scope": "account",
    })
