# backend/core/api/app/services/connected_accounts_service.py
#
# Connected account storage contracts for provider-backed user accounts.
# The persistent row is intentionally encrypted/hash-only so Directus admins and
# cold database dumps cannot identify provider accounts or read token material.
#
# Spec: docs/specs/calendar-permission-management/spec.yml

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, ClassVar


PLAINTEXT_CONNECTED_ACCOUNT_FIELDS: set[str] = {
    "provider",
    "provider_type",
    "provider_name",
    "provider_email",
    "email",
    "account_email",
    "account_label",
    "display_name",
    "oauth_scopes",
    "scopes",
    "refresh_token",
    "access_token",
    "provider_account_id",
    "bridge_password",
    "imap_password",
    "smtp_password",
    "proton_password",
    "password",
    "credential",
    "credentials",
    "secret",
}

NORMALIZED_PLAINTEXT_CONNECTED_ACCOUNT_FIELDS: set[str] = {
    "".join(character for character in field.lower() if character.isalnum())
    for field in PLAINTEXT_CONNECTED_ACCOUNT_FIELDS
}

PROTON_LOCAL_SEND_DELAY_SECONDS = 30
LOCAL_CONNECTOR_REQUEST_TIMEOUT_SECONDS = 90
LOCAL_CONNECTOR_RESULT_POLL_SECONDS = 0.25


@dataclass(frozen=True)
class LocalConnectorRequestResult:
    request_id: str
    status: str
    result: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None


_pending_local_connector_results: dict[tuple[str, str], asyncio.Future[LocalConnectorRequestResult]] = {}


def _local_connector_pending_cache_key(connector_session_id: str, request_id: str) -> str:
    return f"local_connector:pending:{connector_session_id}:{request_id}"


def _local_connector_result_cache_key(connector_session_id: str, request_id: str) -> str:
    return f"local_connector:result:{connector_session_id}:{request_id}"


@dataclass(frozen=True)
class ConnectedAccountRow:
    """Validated encrypted connected account row ready for persistence."""

    id: str
    hashed_user_id: str
    encrypted_provider_type: str
    provider_type_hash: str
    encrypted_account_label: str
    encrypted_refresh_token_bundle: str | None
    encrypted_capabilities: str
    encrypted_app_permissions: str
    provider_account_id_hash: str | None = None
    encrypted_provider_account_display: str | None = None
    encrypted_account_directory_hint: str | None = None
    server_access_enabled: bool = False
    encrypted_server_access_ref: str | None = None
    execution_mode: str = "oauth"
    connector_provider_id: str | None = None
    connector_instance_id: str | None = None
    connector_status: str | None = None
    connector_public_metadata: dict[str, Any] | None = None
    local_connector_session_id: str | None = None
    local_connector_last_heartbeat_at: int | None = None
    local_connector_deadline_at: int | None = None

    REQUIRED_ENCRYPTED_FIELDS: ClassVar[tuple[str, ...]] = (
        "encrypted_provider_type",
        "encrypted_account_label",
        "encrypted_capabilities",
        "encrypted_app_permissions",
    )
    REQUIRED_HASH_FIELDS: ClassVar[tuple[str, ...]] = (
        "id",
        "hashed_user_id",
        "provider_type_hash",
    )

    @classmethod
    def validate_for_storage(cls, payload: dict[str, Any]) -> "ConnectedAccountRow":
        """Fail closed when a connected account row contains plaintext identity."""

        plaintext_fields = find_plaintext_connected_account_fields(payload)
        if plaintext_fields:
            raise ValueError(
                "connected account payload contains plaintext provider/account fields: "
                + ", ".join(plaintext_fields)
            )

        execution_mode = str(payload.get("execution_mode") or "oauth")
        missing = [
            field
            for field in (*cls.REQUIRED_HASH_FIELDS, *cls.REQUIRED_ENCRYPTED_FIELDS)
            if not payload.get(field)
        ]
        if execution_mode != "local_connector" and not payload.get("encrypted_refresh_token_bundle"):
            missing.append("encrypted_refresh_token_bundle")
        if missing:
            raise ValueError(
                "connected account payload missing required encrypted/hash fields: "
                + ", ".join(missing)
            )

        if execution_mode == "local_connector":
            _validate_local_connector_storage(payload)
        elif execution_mode != "oauth":
            raise ValueError("connected account execution_mode must be oauth or local_connector")

        server_access_enabled = bool(payload.get("server_access_enabled", False))
        if server_access_enabled and not payload.get("encrypted_server_access_ref"):
            raise ValueError(
                "server_access_enabled requires encrypted_server_access_ref"
            )

        return cls(
            id=str(payload["id"]),
            hashed_user_id=str(payload["hashed_user_id"]),
            encrypted_provider_type=str(payload["encrypted_provider_type"]),
            provider_type_hash=str(payload["provider_type_hash"]),
            encrypted_account_label=str(payload["encrypted_account_label"]),
            encrypted_refresh_token_bundle=_optional_str(payload.get("encrypted_refresh_token_bundle")),
            encrypted_capabilities=str(payload["encrypted_capabilities"]),
            encrypted_app_permissions=str(payload["encrypted_app_permissions"]),
            provider_account_id_hash=_optional_str(payload.get("provider_account_id_hash")),
            encrypted_provider_account_display=_optional_str(
                payload.get("encrypted_provider_account_display")
            ),
            encrypted_account_directory_hint=_optional_str(
                payload.get("encrypted_account_directory_hint")
            ),
            server_access_enabled=server_access_enabled,
            encrypted_server_access_ref=_optional_str(
                payload.get("encrypted_server_access_ref")
            ),
            execution_mode=execution_mode,
            connector_provider_id=_optional_str(payload.get("connector_provider_id")),
            connector_instance_id=_optional_str(payload.get("connector_instance_id")),
            connector_status=_optional_str(payload.get("connector_status")),
            connector_public_metadata=_optional_dict(payload.get("connector_public_metadata")),
            local_connector_session_id=_optional_str(payload.get("local_connector_session_id")),
            local_connector_last_heartbeat_at=_optional_int(payload.get("local_connector_last_heartbeat_at")),
            local_connector_deadline_at=_optional_int(payload.get("local_connector_deadline_at")),
        )


def assert_local_connector_online(row: dict[str, Any]) -> None:
    if row.get("execution_mode") != "local_connector" or row.get("connector_status") != "online":
        raise PermissionError("connector_offline")
    deadline = _optional_int(row.get("local_connector_deadline_at"))
    if deadline is not None:
        import time

        if deadline < int(time.time()):
            raise PermissionError("connector_offline")


def find_plaintext_connected_account_fields(value: Any, *, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            normalized_key = "".join(character for character in key_text.lower() if character.isalnum())
            if key_text in PLAINTEXT_CONNECTED_ACCOUNT_FIELDS or normalized_key in NORMALIZED_PLAINTEXT_CONNECTED_ACCOUNT_FIELDS:
                found.append(path)
            found.extend(find_plaintext_connected_account_fields(child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_plaintext_connected_account_fields(child, prefix=f"{prefix}[{index}]"))
    return sorted(set(found))


def build_local_connector_mail_read_request(
    *,
    row: dict[str, Any],
    request_id: str,
    query: str,
    mailbox: str | None,
    limit: int,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    assert_local_connector_online(row)
    if row.get("connector_provider_id") != "protonmail_bridge":
        raise PermissionError("unsupported_local_connector_provider")
    connector_session_id = _optional_str(row.get("local_connector_session_id"))
    connected_account_id = _optional_str(row.get("id"))
    if not connector_session_id or not connected_account_id:
        raise PermissionError("connector_offline")
    return {
        "type": "local_connector_request",
        "request_id": request_id,
        "connector_session_id": connector_session_id,
        "connected_account_id": connected_account_id,
        "action": "mail.search",
        "arguments": {
            "query": query,
            "mailbox": mailbox,
            "start_date": start_date,
            "end_date": end_date,
            "limit": max(1, min(int(limit), 50)),
        },
    }


async def dispatch_local_connector_request(
    *,
    user_id: str,
    request: dict[str, Any],
    timeout_seconds: int = LOCAL_CONNECTOR_REQUEST_TIMEOUT_SECONDS,
) -> LocalConnectorRequestResult:
    """Broadcast a local connector request and wait for its REST completion."""

    plaintext_fields = find_plaintext_connected_account_fields(request)
    if plaintext_fields:
        raise ValueError("local connector request contains forbidden credential fields: " + ", ".join(plaintext_fields))
    connector_session_id = _optional_str(request.get("connector_session_id"))
    request_id = _optional_str(request.get("request_id"))
    if not connector_session_id or not request_id:
        raise ValueError("local connector request requires connector_session_id and request_id")
    key = (connector_session_id, request_id)
    loop = asyncio.get_running_loop()
    future: asyncio.Future[LocalConnectorRequestResult] = loop.create_future()
    if key in _pending_local_connector_results:
        raise ValueError("duplicate local connector request id")
    _pending_local_connector_results[key] = future
    pending_cache_key = _local_connector_pending_cache_key(connector_session_id, request_id)
    result_cache_key = _local_connector_result_cache_key(connector_session_id, request_id)
    cache_service = None
    cache_available = False
    try:
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.routes.websockets import manager

        cache_service = CacheService()
        pending_stored = await cache_service.set(
            pending_cache_key,
            {
                "user_id": user_id,
                "connector_session_id": connector_session_id,
                "request_id": request_id,
                "connected_account_id": request.get("connected_account_id"),
                "action": request.get("action"),
            },
            ttl=timeout_seconds + 10,
        )
        cache_available = bool(pending_stored)
        if cache_available:
            await cache_service.delete(result_cache_key)
        await manager.broadcast_to_user_specific_event(
            user_id=user_id,
            event_name="local_connector_request",
            payload=request,
        )
        deadline = loop.time() + timeout_seconds
        while True:
            if future.done():
                return future.result()
            if cache_available:
                cached_result = await cache_service.get(result_cache_key)
                if isinstance(cached_result, dict):
                    return LocalConnectorRequestResult(
                        request_id=str(cached_result.get("request_id") or request_id),
                        status=str(cached_result.get("status") or "error"),
                        result=cached_result.get("result") if isinstance(cached_result.get("result"), dict) else {},
                        error_code=_optional_str(cached_result.get("error_code")),
                        error_message=_optional_str(cached_result.get("error_message")),
                    )
            if loop.time() >= deadline:
                raise TimeoutError("local_connector_request_timeout")
            await asyncio.sleep(LOCAL_CONNECTOR_RESULT_POLL_SECONDS)
    finally:
        if _pending_local_connector_results.get(key) is future:
            _pending_local_connector_results.pop(key, None)
        if cache_service is not None and cache_available:
            await cache_service.delete(pending_cache_key)
            await cache_service.delete(result_cache_key)


async def complete_pending_local_connector_request(
    *,
    connector_session_id: str,
    request_id: str,
    status: str,
    result: dict[str, Any],
    error_code: str | None,
    error_message: str | None,
) -> bool:
    plaintext_fields = find_plaintext_connected_account_fields(result)
    if plaintext_fields:
        raise ValueError("local connector result contains forbidden credential fields: " + ", ".join(plaintext_fields))
    key = (connector_session_id, request_id)
    pending_cache_key = _local_connector_pending_cache_key(connector_session_id, request_id)
    result_cache_key = _local_connector_result_cache_key(connector_session_id, request_id)
    future = _pending_local_connector_results.get(key)
    from backend.core.api.app.services.cache import CacheService

    cache_service = CacheService()
    pending = await cache_service.get(pending_cache_key)
    if not pending and (not future or future.done()):
        return False
    completed = LocalConnectorRequestResult(
        request_id=request_id,
        status=status,
        result=result,
        error_code=error_code,
        error_message=error_message,
    )
    if future and not future.done():
        future.set_result(completed)
    await cache_service.set(
        result_cache_key,
        {
            "request_id": request_id,
            "status": status,
            "result": result,
            "error_code": error_code,
            "error_message": error_message,
        },
        ttl=60,
    )
    await cache_service.delete(pending_cache_key)
    return True


def build_proton_local_delayed_send_job(
    *,
    row: dict[str, Any],
    payload: dict[str, Any],
    approved: bool,
    now: int,
) -> dict[str, Any]:
    assert_local_connector_online(row)
    if row.get("connector_provider_id") != "protonmail_bridge":
        raise PermissionError("unsupported_local_connector_provider")
    capabilities = _local_connector_capabilities(row)
    if "write" not in capabilities:
        raise PermissionError("Proton local connector requires write capability")
    if not approved:
        raise PermissionError("Proton send requires user approval")
    plaintext_fields = find_plaintext_connected_account_fields(payload)
    if plaintext_fields:
        raise ValueError("plaintext connected account fields are not allowed in Proton send payload: " + ", ".join(plaintext_fields))
    return {
        "status": "pending_send",
        "action": "mail.send",
        "connected_account_id": row.get("id"),
        "connector_session_id": row.get("local_connector_session_id"),
        "payload": payload,
        "delay_seconds": PROTON_LOCAL_SEND_DELAY_SECONDS,
        "deliver_after": now + PROTON_LOCAL_SEND_DELAY_SECONDS,
        "undo_available": True,
    }


def cancel_proton_local_delayed_send_job(job: dict[str, Any], *, now: int) -> dict[str, Any]:
    deliver_after = int(job.get("deliver_after") or 0)
    if job.get("status") == "pending_send" and now < deliver_after:
        return job | {
            "status": "cancelled",
            "payload": None,
            "undo_available": False,
            "decision": "user_cancelled",
        }
    return job | {
        "undo_available": False,
        "payload": None,
        "undo_disabled_reason": "OpenMates cannot recall Proton Mail after SMTP delivery.",
    }


def complete_proton_local_delayed_send_job(
    job: dict[str, Any],
    *,
    delivery_result: dict[str, Any],
    now: int,
) -> dict[str, Any]:
    plaintext_fields = find_plaintext_connected_account_fields(delivery_result)
    if plaintext_fields:
        raise ValueError("plaintext connected account fields are not allowed in Proton send receipt: " + ", ".join(plaintext_fields))
    return job | {
        "status": "delivered",
        "delivered_at": now,
        "payload": None,
        "undo_available": False,
        "undo_disabled_reason": "OpenMates cannot recall Proton Mail after SMTP delivery.",
        "receipt": {
            "provider": "protonmail_bridge",
            "message_id": delivery_result.get("message_id"),
            "delivered_at": now,
        },
    }


def mark_expired_local_connectors_offline(rows: list[dict[str, Any]], *, now: int) -> list[str]:
    expired: list[str] = []
    for row in rows:
        if row.get("execution_mode") != "local_connector" or row.get("connector_status") != "online":
            continue
        deadline = _optional_int(row.get("local_connector_deadline_at"))
        if deadline is not None and deadline < now:
            row["connector_status"] = "offline"
            expired.append(str(row.get("id")))
    return expired


def _validate_local_connector_storage(payload: dict[str, Any]) -> None:
    if payload.get("connector_provider_id") != "protonmail_bridge":
        raise ValueError("unsupported local connector provider")
    if not payload.get("connector_instance_id"):
        raise ValueError("local connector requires connector_instance_id")
    if payload.get("connector_status") not in {"online", "offline", "setup_required", "revoked"}:
        raise ValueError("local connector connector_status is invalid")
    public_metadata = payload.get("connector_public_metadata") or {}
    if not isinstance(public_metadata, dict):
        raise ValueError("local connector public metadata must be an object")
    bridge_host = public_metadata.get("bridge_host")
    if bridge_host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("local connector bridge_host must be localhost")
    capabilities = public_metadata.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise ValueError("local connector public metadata must include capabilities")
    allowed_capabilities = {"read", "write"}
    normalized_capabilities = {str(capability) for capability in capabilities}
    if not normalized_capabilities.issubset(allowed_capabilities):
        raise ValueError("local connector capabilities are invalid")


def _local_connector_capabilities(row: dict[str, Any]) -> set[str]:
    public_metadata = row.get("connector_public_metadata") or {}
    if not isinstance(public_metadata, dict):
        return set()
    capabilities = public_metadata.get("capabilities") or []
    if not isinstance(capabilities, list):
        return set()
    return {str(capability) for capability in capabilities}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("expected object")
    return value
