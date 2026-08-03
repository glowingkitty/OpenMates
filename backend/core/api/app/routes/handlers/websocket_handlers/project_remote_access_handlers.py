"""Authenticated WebSocket handlers for Project remote-access source sessions.

The CLI registers exact encrypted Project source bindings on its live socket.
Handlers validate ownership through Directus, then delegate opaque lifecycle and
completion state to ProjectRemoteAccessService. No filesystem plaintext or key
material is accepted by this module.

Spec: docs/specs/cli-remote-access-live-bridge/spec.yml
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from fastapi import WebSocket

from backend.core.api.app.services.project_remote_access_service import (
    ProjectRemoteAccessError,
    ProjectRemoteAccessService,
)
from backend.core.api.app.services.directus.team_methods import TeamPermissionError


IDENTIFIER_MAX_LENGTH = 128
ENCRYPTED_ENVELOPE_MAX_LENGTH = 350_000
TEAM_REMOTE_ACCESS_ROLES = {"owner", "admin", "member", "viewer"}


async def handle_project_remote_access_register(
    *,
    websocket: WebSocket,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    try:
        source_session_id = _required_string(payload, "source_session_id")
        team_id = _optional_string(payload, "team_id")
    except ProjectRemoteAccessError as exc:
        await _send_error(websocket, exc.code)
        return
    raw_bindings = payload.get("bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings or len(raw_bindings) > 16:
        await _send_error(websocket, "source_bindings_required")
        return

    bindings: list[dict[str, Any]] = []
    for raw in raw_bindings:
        if not isinstance(raw, dict):
            await _send_error(websocket, "invalid_source_binding")
            return
        try:
            project_id = _required_string(raw, "project_id")
            source_id = _required_string(raw, "source_id")
        except ProjectRemoteAccessError as exc:
            await _send_error(websocket, exc.code)
            return
        if not await _require_team_membership(websocket, directus_service, team_id, user_id):
            return
        project = await directus_service.project.get_project(project_id, user_id, team_id=team_id)
        source = await directus_service.project.get_source(
            project_id, user_id, source_id, team_id=team_id
        )
        if not project or not source or source.get("status") == "revoked":
            await _send_error(websocket, "source_not_found")
            return
        if team_id and source.get("attached_by_user_hash") != _hash_identity(user_id):
            await _send_error(websocket, "source_host_mismatch")
            return
        requested_capabilities = raw.get("capabilities")
        if not isinstance(requested_capabilities, list) or not set(requested_capabilities).issubset(
            set(source.get("capabilities") or [])
        ):
            await _send_error(websocket, "source_capability_denied")
            return
        bindings.append(
            {
                "project_id": project_id,
                "source_id": source_id,
                "capabilities": requested_capabilities,
                "key_epoch": raw.get("key_epoch"),
            }
        )

    service = ProjectRemoteAccessService(cache_service)
    try:
        result = await service.register_session(
            user_id=user_id,
            team_id=team_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=source_session_id,
            bindings=bindings,
            confirmed_takeover=payload.get("confirmed_takeover") is True,
            now=int(time.time()),
        )
    except ProjectRemoteAccessError as exc:
        await _send_error(websocket, exc.code)
        return
    await websocket.send_json({"type": "project_remote_access_registered", "payload": result})


async def handle_project_remote_access_heartbeat(
    *,
    websocket: WebSocket,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    try:
        source_session_id = _required_string(payload, "source_session_id")
        team_id = _optional_string(payload, "team_id")
    except ProjectRemoteAccessError as exc:
        await _send_error(websocket, exc.code)
        return
    if not await _require_team_membership(websocket, directus_service, team_id, user_id):
        return
    await _run_lifecycle(
        websocket,
        "project_remote_access_heartbeat_ack",
        ProjectRemoteAccessService(cache_service).heartbeat_session(
            user_id=user_id,
            team_id=team_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=source_session_id,
            now=int(time.time()),
        ),
    )


async def handle_project_remote_access_disconnect(
    *,
    websocket: WebSocket,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    try:
        source_session_id = _required_string(payload, "source_session_id")
        team_id = _optional_string(payload, "team_id")
    except ProjectRemoteAccessError as exc:
        await _send_error(websocket, exc.code)
        return
    if not await _require_team_membership(websocket, directus_service, team_id, user_id):
        return
    await _run_lifecycle(
        websocket,
        "project_remote_access_disconnected",
        ProjectRemoteAccessService(cache_service).disconnect_session(
            user_id=user_id,
            team_id=team_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=source_session_id,
            now=int(time.time()),
        ),
    )


async def handle_project_remote_access_complete(
    *,
    websocket: WebSocket,
    cache_service: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: dict[str, Any],
) -> None:
    service = ProjectRemoteAccessService(cache_service)
    try:
        team_id = _optional_string(payload, "team_id")
        if not await _require_team_membership(websocket, directus_service, team_id, user_id):
            return
        await service.complete_request(
            user_id=user_id,
            team_id=team_id,
            device_fingerprint_hash=device_fingerprint_hash,
            source_session_id=_required_string(payload, "source_session_id"),
            project_id=_required_string(payload, "project_id"),
            source_id=_required_string(payload, "source_id"),
            request_id=_required_string(payload, "request_id"),
            key_epoch=int(payload.get("key_epoch") or 0),
            encrypted_envelope=_required_string(
                payload,
                "encrypted_envelope",
                max_length=ENCRYPTED_ENVELOPE_MAX_LENGTH,
            ),
            now=int(time.time()),
        )
    except (ProjectRemoteAccessError, TypeError, ValueError) as exc:
        await _send_error(websocket, exc.code if isinstance(exc, ProjectRemoteAccessError) else "invalid_completion")
        return
    await websocket.send_json(
        {
            "type": "project_remote_access_completion_ack",
            "payload": {"request_id": payload["request_id"], "accepted": True},
        }
    )


async def _run_lifecycle(websocket: WebSocket, event_type: str, operation: Any) -> None:
    try:
        result = await operation
    except ProjectRemoteAccessError as exc:
        await _send_error(websocket, exc.code)
        return
    payload = result if isinstance(result, dict) else {"accepted": bool(result)}
    await websocket.send_json({"type": event_type, "payload": payload})


async def _send_error(websocket: WebSocket, code: str) -> None:
    await websocket.send_json({"type": "error", "payload": {"code": code, "message": "Remote access request rejected"}})


async def _require_team_membership(
    websocket: WebSocket, directus_service: Any, team_id: str | None, user_id: str
) -> bool:
    if not team_id:
        return True
    try:
        await directus_service.team.require_team_role(team_id, user_id, TEAM_REMOTE_ACCESS_ROLES)
    except TeamPermissionError:
        await _send_error(websocket, "team_membership_required")
        return False
    return True


def _required_string(
    payload: dict[str, Any],
    field: str,
    *,
    max_length: int = IDENTIFIER_MAX_LENGTH,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ProjectRemoteAccessError(f"invalid_{field}")
    return value


def _optional_string(payload: dict[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > IDENTIFIER_MAX_LENGTH:
        raise ProjectRemoteAccessError(f"invalid_{field}")
    return value


def _hash_identity(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
