# backend/apps/ai/processing/e2b_upload_consent_request.py
#
# One-time E2B upload consent for the assistant path. Before the assistant's
# code.run tool call sends code or Project files to E2B, the account's decision
# is read. Without a decision the tool call is paused (connected-account
# permission pattern): the pending context is stored vault-encrypted, the
# request is published to the user's devices and the turn ends without any
# upload. The answer handler records the decision and continues the turn.
#
# Spec: specifications/features/app-skills/code-run/specification.yml
#       (assertion code-run.e2b.upload-consent)
# Plan: docs/plans/e2b-upload-consent/plan.yml (package C2)

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from backend.core.api.app.services import e2b_upload_consent as consent

logger = logging.getLogger(__name__)

PENDING_E2B_UPLOAD_CONSENT_TTL_SECONDS = 86400
PRIVACY_POLICY_URL = "https://openmates.org/privacy"
REMOTE_ACCESS_COMMAND = "openmates remote-access"

DECLINED_INSTRUCTION = (
    "The user chose not to send files to E2B, the cloud sandbox, so this code cannot be run "
    "there and nothing was uploaded. Do not retry this tool call. Offer to run it on the "
    "user's own connected machine (the user connects one with `openmates remote-access`) "
    "or tell the user they can change the choice in settings."
)


@dataclass(frozen=True)
class E2bConsentGate:
    """Outcome of the pre-dispatch consent check."""

    kind: str  # "allowed" | "declined" | "paused"
    request_id: str | None = None


def declined_tool_result(app_id: str = "code", skill_id: str = "run") -> dict[str, Any]:
    """Tool result for the model when the account declined E2B uploads."""
    return {
        "status": "e2b_consent_declined",
        "reason": DECLINED_INSTRUCTION,
        "app_id": app_id,
        "skill_id": skill_id,
    }


def pending_key(chat_id: str) -> str:
    return f"pending_e2b_upload_consent:{chat_id}"


async def store_pending_context(
    *, cache_service: Any, encryption_service: Any, vault_key_id: str, chat_id: str, context: dict[str, Any]
) -> bool:
    """Store the paused tool call vault-encrypted for 24 hours."""
    client = await cache_service.client
    if not client:
        return False
    ciphertext, _version = await encryption_service.encrypt_with_user_key(json.dumps(context), vault_key_id)
    await client.set(pending_key(chat_id), ciphertext, ex=PENDING_E2B_UPLOAD_CONSENT_TTL_SECONDS)
    return True


async def load_pending_context(
    *, cache_service: Any, encryption_service: Any, vault_key_id: str, chat_id: str
) -> dict[str, Any] | None:
    """Return the decrypted pending context, or None when missing or expired."""
    client = await cache_service.client
    if not client:
        return None
    data = await client.get(pending_key(chat_id))
    if not data:
        return None
    ciphertext = data.decode("utf-8") if isinstance(data, bytes) else data
    plaintext = await encryption_service.decrypt_with_user_key(ciphertext, vault_key_id)
    if not plaintext:
        return None
    return json.loads(plaintext)


async def delete_pending_context(*, cache_service: Any, chat_id: str) -> None:
    client = await cache_service.client
    if client:
        await client.delete(pending_key(chat_id))


async def publish_user_event(*, cache_service: Any, user_id: str, event_type: str, payload: dict[str, Any]) -> bool:
    """Publish an event to the user's devices through the user_cache_events fan-out."""
    client = await cache_service.client
    if not client:
        return False
    await client.publish(
        f"user_cache_events:{user_id}",
        json.dumps({"event_type": event_type, "payload": payload}),
    )
    return True


async def gate_e2b_upload_before_skill(
    *,
    request_data: Any,
    cache_service: Any,
    encryption_service: Any,
    directus_service: Any,
    user_vault_key_id: str,
    task_id: str,
) -> E2bConsentGate:
    """Read the decision before the assistant sends anything to E2B; pause when none exists."""
    state = await consent.get_decision(request_data.user_id, directus_service)
    if state["decision"] == "allowed":
        return E2bConsentGate("allowed")
    if state["decision"] == "declined":
        return E2bConsentGate("declined")

    request_id = str(uuid.uuid4())
    chat_id = str(request_data.chat_id)
    context = {
        "request_id": request_id,
        "chat_id": chat_id,
        "message_id": request_data.message_id,
        "user_id": request_data.user_id,
        "user_id_hash": request_data.user_id_hash,
        "task_id": task_id,
        "preprocessing_resume_ref": getattr(request_data, "preprocessing_resume_ref", None),
        "team_id": getattr(request_data, "team_id", None),
        "team_role": getattr(request_data, "team_role", None),
    }
    stored = await store_pending_context(
        cache_service=cache_service,
        encryption_service=encryption_service,
        vault_key_id=user_vault_key_id,
        chat_id=chat_id,
        context=context,
    )
    if not stored:
        raise RuntimeError(f"Failed to store E2B upload consent request {request_id}")
    published = await publish_user_event(
        cache_service=cache_service,
        user_id=request_data.user_id,
        event_type="send_e2b_upload_consent_request",
        payload={"request_id": request_id, "chat_id": chat_id, "version": consent.E2B_UPLOAD_CONSENT_VERSION},
    )
    if not published:
        logger.warning("Stored E2B upload consent request %s but could not publish it", request_id)
    return E2bConsentGate("paused", request_id)
