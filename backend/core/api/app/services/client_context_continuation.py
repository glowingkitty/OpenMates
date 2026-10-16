"""Authenticated turn-bound, encrypted two-phase client context handoff.

This internal first-party transport carries discovery data, never authority.
Admission registers the owner/device/Team/turn before any payload is accepted.
Only Vault ciphertext is retained, for at most 120 seconds without sliding renewal.
Normal resource ownership, revision and consent checks still apply after loading.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any

TTL_SECONDS = 120
WAIT_SECONDS = 20
MAX_PAYLOAD_BYTES = 256_000
FAILURE_REASONS = frozenset({
    "project_discovery_failed", "context_preparation_failed", "workspace_changed",
})
_SELECTION_DETAILS_ROWS = {
    "related_task_candidates": (60, {"task_id", "id", "title", "summary", "project_id", "status", "changed_at", "revision", "version", "explicit_dependency"}),
    "project_focus_catalog": (20, {"id", "title", "summary", "revision"}),
    "connected_account_directory": (100, None),
}
_ROUTING_ROWS = {
    "project_focus_candidates": (40, {"project_id", "name", "summary", "auto_selection", "focus_activation_policy", "focuses"}),
    **_SELECTION_DETAILS_ROWS,  # Legacy clients still send these with routing.
}
_DETAILS_ROWS = {
    "custom_memory_documents": (24, {"id", "source", "project_id", "document", "item_revision"}),
    "custom_rule_documents": (24, {"id", "source", "project_id", "document", "item_revision"}),
    "project_focus_documents": (8, {"item_id", "document", "revision"}),
    "project_context_documents": (20, {"item_id", "kind", "title", "description", "document", "revision"}),
    "connected_account_token_refs": (100, None),
    **_SELECTION_DETAILS_ROWS,
}
_PLAN_FIELDS = {"plan_id", "version", "approved_revision_id", "summary", "linked_task_id"}
_CROSS_PHASE_FIELDS = frozenset(_SELECTION_DETAILS_ROWS) | {"accepted_plan_context"}
_PRIVATE_METADATA_KEYS = {
    "document", "body", "access_token", "refresh_token", "private_key", "token",
    "provider_email", "email", "account_email", "provider_account_id",
    "provider_account_email", "oauth_scopes", "scopes",
}
_PUT_PHASE = """
local remaining = redis.call('ttl', KEYS[1])
if remaining <= 0 then return 0 end
if redis.call('get', KEYS[1]) ~= ARGV[2] then return -1 end
if redis.call('exists', KEYS[3]) == 1 then return -2 end
if redis.call('exists', KEYS[2]) == 1 then return 2 end
redis.call('set', KEYS[2], ARGV[1], 'EX', remaining)
return 1
"""

_PUT_FAILURE = """
local remaining = redis.call('ttl', KEYS[1])
if remaining <= 0 then return 0 end
if redis.call('get', KEYS[1]) ~= ARGV[2] then return -1 end
if redis.call('exists', KEYS[4]) == 1 then return 2 end
if redis.call('exists', KEYS[2]) == 1 and redis.call('exists', KEYS[3]) == 1 then return 3 end
redis.call('set', KEYS[4], ARGV[1], 'EX', remaining)
return 1
"""

_REBIND_DEVICE = """
if redis.call('pttl', KEYS[1]) <= 0 then return 0 end
if redis.call('get', KEYS[1]) ~= ARGV[1] then return -1 end
redis.call('set', KEYS[1], ARGV[2], 'KEEPTTL')
return 1
"""


class ClientContextUnavailable(RuntimeError):
    """Missing or invalid context must fail the turn, never become empty context."""


def _scope(*, user_id: str, chat_id: str, turn_id: str, message_id: str,
           request_id: str, team_id: str | None = None) -> dict:
    values = {"user_id": user_id, "chat_id": chat_id, "turn_id": turn_id,
              "message_id": message_id, "request_id": request_id, "team_id": team_id}
    if any(not isinstance(value, str) or not 1 <= len(value) <= 255
           for key, value in values.items() if key != "team_id"):
        raise ValueError("Invalid context identity")
    if team_id is not None and (not isinstance(team_id, str) or not 1 <= len(team_id) <= 255):
        raise ValueError("Invalid Team identity")
    if str(uuid.UUID(request_id)) != request_id:
        raise ValueError("Invalid context request UUID")
    return values


def _reference(scope: dict) -> str:
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _key(reference: str) -> str:
    return "ai:client-context:v1:" + reference


def validate_context(phase: str, context: Any) -> dict:
    rows = _ROUTING_ROWS if phase == "routing" else _DETAILS_ROWS if phase == "details" else None
    if rows is None or not isinstance(context, dict):
        raise ValueError("Invalid context phase")
    allowed = set(rows) | {"accepted_plan_context"}
    if set(context) - allowed:
        raise ValueError("Unexpected context field")
    if "custom_memory_documents" in context and "custom_rule_documents" in context:
        raise ValueError("Ambiguous Memory fields")
    encoded = json.dumps(context, ensure_ascii=True, allow_nan=False)
    if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("Context payload too large")
    for field, (maximum, fields) in rows.items():
        if field not in context:
            continue
        value = context[field]
        if not isinstance(value, list) or len(value) > maximum:
            raise ValueError("Invalid context catalogue")
        for row in value:
            if not isinstance(row, dict) or (fields is not None and set(row) - fields):
                raise ValueError("Invalid context row")
            # Routing is metadata only, including any nested Project Focus hints.
            if (phase == "routing" or field in _SELECTION_DETAILS_ROWS) and _contains_private_body(row):
                raise ValueError("Private body in selection metadata")
    plan = context.get("accepted_plan_context")
    if plan is not None and (not isinstance(plan, dict) or set(plan) - _PLAN_FIELDS):
        raise ValueError("Invalid Plan reference")
    if phase == "routing" and _contains_private_body(context):
        raise ValueError("Private body in routing metadata")
    if phase == "details" and _contains_private_body({
        field: context[field] for field in _CROSS_PHASE_FIELDS if field in context
    }):
        raise ValueError("Private body in selection metadata")
    return context


def _contains_private_body(value: Any) -> bool:
    if isinstance(value, dict):
        return any(key in _PRIVATE_METADATA_KEYS
                   or _contains_private_body(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_private_body(item) for item in value)
    return False


async def _seal(encryption: Any, vault_key_id: str, value: dict) -> str:
    ciphertext, _ = await encryption.encrypt_with_user_key(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False), vault_key_id)
    if not ciphertext:
        raise ClientContextUnavailable("Context encryption unavailable")
    return ciphertext


async def _open(encryption: Any, vault_key_id: str, ciphertext: Any) -> dict:
    if isinstance(ciphertext, bytes):
        ciphertext = ciphertext.decode()
    value = await encryption.decrypt_with_user_key(ciphertext, vault_key_id)
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ClientContextUnavailable("Invalid encrypted context")
    return result


async def _check_cross_phase_selection(*, client: Any, key: str, phase: str,
                                       scope: dict, context: dict, encryption: Any,
                                       vault_key_id: str) -> None:
    """A later phase cannot replace selection metadata committed by the other."""
    if not _CROSS_PHASE_FIELDS.intersection(context):
        return
    other_phase = "details" if phase == "routing" else "routing"
    other_sealed = await client.get(key + ":" + other_phase)
    if not other_sealed:
        return
    other = await _open(encryption, vault_key_id, other_sealed)
    if other.get("scope") != scope or other.get("phase") != other_phase:
        raise ClientContextUnavailable("Context scope mismatch")
    other_context = validate_context(other_phase, other.get("context"))
    if any(field in context and field in other_context
           and context[field] != other_context[field] for field in _CROSS_PHASE_FIELDS):
        raise ClientContextUnavailable("Conflicting cross-phase selection metadata")


async def register_client_context(*, cache_service: Any, encryption_service: Any,
                                  user_id: str, device_fingerprint_hash: str, chat_id: str,
                                  turn_id: str, message_id: str, request_id: str,
                                  team_id: str | None = None) -> str:
    """Call only after durable authenticated admission, before worker dispatch."""
    scope = _scope(user_id=user_id, chat_id=chat_id, turn_id=turn_id,
                   message_id=message_id, request_id=request_id, team_id=team_id)
    if not isinstance(device_fingerprint_hash, str) or not device_fingerprint_hash:
        raise ValueError("Missing authenticated device")
    client = await cache_service.client
    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not client or not vault_key_id:
        raise ClientContextUnavailable("Context handoff unavailable")
    reference = _reference(scope)
    record = {"scope": scope, "device": device_fingerprint_hash}
    sealed = await _seal(encryption_service, vault_key_id, record)
    if not await client.set(_key(reference), sealed, ex=TTL_SECONDS, nx=True):
        previous_sealed = await client.get(_key(reference))
        if not previous_sealed:
            raise ClientContextUnavailable("Context binding expired")
        previous = await _open(encryption_service, vault_key_id, previous_sealed)
        if previous.get("scope") != scope:
            raise ClientContextUnavailable("Context binding conflict")
        if previous != record:
            # The caller has just revalidated the exact durable admission. A
            # reconnect may replace its socket identity but never its committed
            # payload, scope or original expiration. Concurrent replays retry.
            status = await client.eval(_REBIND_DEVICE, 1, _key(reference), previous_sealed, sealed)
            if status != 1:
                raise ClientContextUnavailable("Context binding changed during replay")
    return reference


async def receive_client_context(*, cache_service: Any, encryption_service: Any,
                                 user_id: str, device_fingerprint_hash: str, chat_id: str,
                                 turn_id: str, message_id: str, request_id: str, phase: str,
                                 context: dict, team_id: str | None = None) -> str:
    scope = _scope(user_id=user_id, chat_id=chat_id, turn_id=turn_id,
                   message_id=message_id, request_id=request_id, team_id=team_id)
    validate_context(phase, context)
    client = await cache_service.client
    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not client or not vault_key_id:
        raise ClientContextUnavailable("Context handoff unavailable")
    key = _key(_reference(scope))
    sealed_binding = await client.get(key)
    if not sealed_binding:
        raise ClientContextUnavailable("No admitted context binding")
    binding = await _open(encryption_service, vault_key_id, sealed_binding)
    if binding != {"scope": scope, "device": device_fingerprint_hash}:
        raise ClientContextUnavailable("Context binding mismatch")
    await _check_cross_phase_selection(
        client=client, key=key, phase=phase, scope=scope, context=context,
        encryption=encryption_service, vault_key_id=vault_key_id,
    )
    record = {"scope": scope, "phase": phase, "context": context}
    sealed = await _seal(encryption_service, vault_key_id, record)
    status = await client.eval(_PUT_PHASE, 3, key, key + ":" + phase,
                               key + ":failed", sealed, sealed_binding)
    if status == -1:
        raise ClientContextUnavailable("Context binding changed during delivery")
    if status == 0:
        raise ClientContextUnavailable("Context binding expired")
    if status == -2:
        raise ClientContextUnavailable("Client context delivery failed")
    if status == 2:
        previous = await _open(encryption_service, vault_key_id, await client.get(key + ":" + phase))
        if previous != record:
            raise ClientContextUnavailable("Conflicting context duplicate")
    # This also catches a concurrent opposite-phase write after the first read.
    await _check_cross_phase_selection(
        client=client, key=key, phase=phase, scope=scope, context=context,
        encryption=encryption_service, vault_key_id=vault_key_id,
    )
    return "accepted" if status == 1 else "duplicate"


async def receive_client_context_failure(*, cache_service: Any, encryption_service: Any,
                                         user_id: str, device_fingerprint_hash: str, chat_id: str,
                                         turn_id: str, message_id: str, request_id: str, reason: str,
                                         team_id: str | None = None) -> str:
    """Seal a generic failure for the exact admitted turn, without extending its TTL."""
    scope = _scope(user_id=user_id, chat_id=chat_id, turn_id=turn_id,
                   message_id=message_id, request_id=request_id, team_id=team_id)
    if not isinstance(reason, str) or reason not in FAILURE_REASONS:
        raise ValueError("Invalid context failure reason")
    if not isinstance(device_fingerprint_hash, str) or not device_fingerprint_hash:
        raise ValueError("Missing authenticated device")
    client = await cache_service.client
    vault_key_id = await cache_service.get_user_vault_key_id(user_id)
    if not client or not vault_key_id:
        raise ClientContextUnavailable("Context handoff unavailable")
    key = _key(_reference(scope))
    sealed_binding = await client.get(key)
    if not sealed_binding:
        raise ClientContextUnavailable("No admitted context binding")
    binding = await _open(encryption_service, vault_key_id, sealed_binding)
    if binding != {"scope": scope, "device": device_fingerprint_hash}:
        raise ClientContextUnavailable("Context binding mismatch")
    record = {"scope": scope, "reason": reason}
    sealed = await _seal(encryption_service, vault_key_id, record)
    failed_key = key + ":failed"
    status = await client.eval(_PUT_FAILURE, 4, key, key + ":routing",
                               key + ":details", failed_key, sealed, sealed_binding)
    if status == -1:
        raise ClientContextUnavailable("Context binding changed during failure delivery")
    if status == 0:
        raise ClientContextUnavailable("Context binding expired")
    if status == 3:
        raise ClientContextUnavailable("Client context already complete")
    if status == 2:
        previous = await _open(encryption_service, vault_key_id, await client.get(failed_key))
        if previous != record:
            raise ClientContextUnavailable("Conflicting context failure duplicate")
    return "accepted" if status == 1 else "duplicate"


async def _raise_if_failed(*, client: Any, key: str, scope: dict,
                           encryption: Any, vault_key_id: str) -> None:
    sealed = await client.get(key + ":failed")
    if not sealed:
        return
    record = await _open(encryption, vault_key_id, sealed)
    if record.get("scope") != scope or record.get("reason") not in FAILURE_REASONS:
        raise ClientContextUnavailable("Invalid context failure marker")
    raise ClientContextUnavailable("Client context delivery failed")


async def await_client_context_phase(*, cache_service: Any, request: Any, phase: str,
                                     encryption_service: Any = None, timeout: float = WAIT_SECONDS) -> None:
    """Hydrate only a committed phase; timeout leaves missing context unavailable."""
    if not getattr(request, "client_context_pending", False):
        return
    if phase not in {"routing", "details"}:
        raise ValueError("Invalid context phase")
    scope = _scope(user_id=request.user_id, chat_id=request.chat_id,
                   turn_id=(getattr(request, "client_context_turn_id", None)
                            or request.recovery_turn_id), message_id=request.message_id,
                   request_id=request.client_context_request_id, team_id=request.team_id)
    reference = getattr(request, "client_context_binding_ref", None)
    if not reference or reference != _reference(scope):
        raise ClientContextUnavailable("Missing admitted context binding")
    if encryption_service is None:
        from backend.core.api.app.utils.encryption import EncryptionService
        encryption_service = EncryptionService()
    client = await cache_service.client
    vault_key_id = await cache_service.get_user_vault_key_id(request.user_id)
    if not client or not vault_key_id:
        raise ClientContextUnavailable("Context handoff unavailable")
    key = _key(reference)
    await _raise_if_failed(client=client, key=key, scope=scope,
                           encryption=encryption_service, vault_key_id=vault_key_id)
    if getattr(request, "_client_context_" + phase + "_loaded", False):
        return
    deadline = time.monotonic() + min(max(timeout, 0), WAIT_SECONDS)
    while True:
        if not await client.get(key):
            raise ClientContextUnavailable("Context binding expired")
        await _raise_if_failed(client=client, key=key, scope=scope,
                               encryption=encryption_service, vault_key_id=vault_key_id)
        sealed = await client.get(key + ":" + phase)
        if sealed:
            record = await _open(encryption_service, vault_key_id, sealed)
            if record.get("scope") != scope or record.get("phase") != phase:
                raise ClientContextUnavailable("Context scope mismatch")
            context = validate_context(phase, record.get("context"))
            await _check_cross_phase_selection(
                client=client, key=key, phase=phase, scope=scope, context=context,
                encryption=encryption_service, vault_key_id=vault_key_id,
            )
            await _raise_if_failed(client=client, key=key, scope=scope,
                                   encryption=encryption_service, vault_key_id=vault_key_id)
            for field, value in context.items():
                setattr(request, "custom_rule_documents" if field == "custom_memory_documents" else field, value)
            setattr(request, "_client_context_" + phase + "_loaded", True)
            if phase == "details" and getattr(request, "_client_context_routing_loaded", False):
                request.client_context_pending = False
                _complete_empty_admission_context(request)
            return
        if time.monotonic() >= deadline:
            raise ClientContextUnavailable("Client context delivery timed out")
        await asyncio.sleep(min(.05, max(0, deadline - time.monotonic())))


def _complete_empty_admission_context(request: Any) -> None:
    """Only finish an existing empty server snapshot; client data adds no authority."""
    admission = getattr(request, "admission_context", None)
    required = {"active_project_id", "active_project_activation_id", "active_focus_id",
                "accepted_plan_ref", "explicit_related_task_ids", "context_revision", "scope_complete"}
    if (not isinstance(admission, dict) or not required.issubset(admission)
            or admission.get("context_revision") != "server-admission-v1"):
        return
    if any(admission.get(key) for key in required - {"scope_complete", "context_revision"}):
        return
    if any(getattr(request, key, None) for key in (
        "active_project_focus", "current_project", "active_focus_id", "accepted_plan_context",
        "project_focus_documents", "project_context_documents",
        "custom_rule_documents", "mentioned_settings_memories_cleartext",
    )):
        return
    if any(isinstance(row, dict) and row.get("explicit_dependency") for row in
           (getattr(request, "related_task_candidates", None) or [])):
        return
    request.admission_context = {**admission, "scope_complete": True}
