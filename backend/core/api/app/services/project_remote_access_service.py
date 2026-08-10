"""Ephemeral coordination for encrypted Project remote-access sessions.

The service stores only opaque envelopes and routing metadata in Dragonfly.
Filesystem paths, queries, snippets, file contents, and encryption keys remain
inside first-party clients. Session and request state is short-lived and scoped
to the authenticated owner, Project, source, device, and key epoch.

Spec: docs/specs/cli-remote-access-live-bridge/spec.yml
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
from typing import Any


HEARTBEAT_INTERVAL_SECONDS = 15
HEARTBEAT_MIN_INTERVAL_SECONDS = 10
SESSION_TIMEOUT_SECONDS = 45
REQUEST_TIMEOUT_SECONDS = 45
REQUEST_CACHE_TTL_SECONDS = 55
RESULT_CACHE_TTL_SECONDS = 60
MAX_ENVELOPE_BYTES = 256 * 1024
MAX_IN_FLIGHT = 4
MAX_QUEUED = 16
MAX_REQUESTS_PER_MINUTE = 60
STATE_LOCK_TTL_SECONDS = 10
STATE_LOCK_WAIT_SECONDS = 5
ALLOWED_OPERATIONS = {"list", "search", "read_text"}
RELEASE_LOCK_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


class ProjectRemoteAccessError(RuntimeError):
    """Sanitized bridge failure suitable for mapping to a public error code."""

    def __init__(self, code: str, *, status_code: int = 400) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class ProjectRemoteAccessService:
    """Coordinate source sessions without decrypting bridge payloads."""

    def __init__(self, cache_service: Any) -> None:
        self.cache = cache_service
        lock = getattr(cache_service, "_project_remote_access_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            setattr(cache_service, "_project_remote_access_lock", lock)
        self._lock = lock

    async def register_session(
        self,
        *,
        user_id: str,
        device_fingerprint_hash: str,
        source_session_id: str,
        bindings: list[dict[str, Any]],
        confirmed_takeover: bool,
        now: int,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        normalized = [_normalize_binding(item) for item in bindings]
        if not normalized:
            raise ProjectRemoteAccessError("source_bindings_required")
        if len({(item["project_id"], item["source_id"]) for item in normalized}) != len(normalized):
            raise ProjectRemoteAccessError("duplicate_source_binding")

        replaced_sessions: set[str] = set()
        context_type, context_id = _context(user_id, team_id)
        async with self._state_lock(context_type, context_id):
            for item in normalized:
                owner = await self.cache.get(
                    self._binding_key(context_id, item["project_id"], item["source_id"], context_type)
                )
                previous = owner.get("source_session_id") if isinstance(owner, dict) else None
                if previous and previous != source_session_id:
                    if not confirmed_takeover:
                        raise ProjectRemoteAccessError("takeover_confirmation_required", status_code=409)
                    replaced_sessions.add(str(previous))

            session = {
                "context_type": context_type,
                "context_id_hash": _hash(context_id),
                "source_session_id": source_session_id,
                "host_user_id": user_id,
                "host_member_hash": _hash(user_id),
                "device_fingerprint_hash": device_fingerprint_hash,
                "bindings": normalized,
                "last_heartbeat_at": now,
                "deadline_at": now + SESSION_TIMEOUT_SECONDS,
                "in_flight": [],
                "queued": [],
            }
            await self.cache.set(
                self._session_key(context_id, source_session_id, context_type),
                session,
                ttl=SESSION_TIMEOUT_SECONDS,
            )
            for item in normalized:
                await self.cache.set(
                    self._binding_key(context_id, item["project_id"], item["source_id"], context_type),
                    {
                        "source_session_id": source_session_id,
                        "host_user_id": user_id,
                        "host_member_hash": _hash(user_id),
                        "device_fingerprint_hash": device_fingerprint_hash,
                        "key_epoch": item["key_epoch"],
                        "capabilities": item["capabilities"],
                        "deadline_at": session["deadline_at"],
                    },
                    ttl=SESSION_TIMEOUT_SECONDS,
                )
            for replaced in replaced_sessions:
                replaced_session = await self.cache.get(self._session_key(context_id, replaced, context_type))
                if isinstance(replaced_session, dict):
                    for item in replaced_session.get("bindings", []):
                        owner_key = self._binding_key(
                            context_id, item["project_id"], item["source_id"], context_type
                        )
                        owner = await self.cache.get(owner_key)
                        if isinstance(owner, dict) and owner.get("source_session_id") == replaced:
                            await self.cache.delete(owner_key)
                    for request_id in [
                        *replaced_session.get("in_flight", []),
                        *replaced_session.get("queued", []),
                    ]:
                        await self._revoke_request(context_type, context_id, request_id)
                    if context_type == "team":
                        await self._remove_index_value(
                            self._member_sessions_key(
                                context_id, str(replaced_session.get("host_user_id") or "")
                            ),
                            replaced,
                        )
                        await self._remove_index_value(
                            self._team_sessions_key(context_id), replaced
                        )
                await self.cache.delete(self._session_key(context_id, replaced, context_type))
            if context_type == "team":
                await self._append_index(self._member_sessions_key(context_id, user_id), source_session_id)
                await self._append_index(self._team_sessions_key(context_id), source_session_id)

        return {
            "source_session_id": source_session_id,
            "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
            "deadline_at": session["deadline_at"],
            "replaced_session_id": next(iter(replaced_sessions), None),
        }

    async def heartbeat_session(
        self,
        *,
        user_id: str,
        source_session_id: str,
        now: int,
        team_id: str | None = None,
        device_fingerprint_hash: str | None = None,
    ) -> dict[str, Any]:
        context_type, context_id = _context(user_id, team_id)
        async with self._state_lock(context_type, context_id):
            session = await self._require_session(
                context_type, context_id, source_session_id, now=now, allow_expired=False
            )
            self._require_session_actor(session, user_id, device_fingerprint_hash)
            if now - int(session["last_heartbeat_at"]) < HEARTBEAT_MIN_INTERVAL_SECONDS:
                raise ProjectRemoteAccessError("heartbeat_too_early", status_code=429)
            session["last_heartbeat_at"] = now
            session["deadline_at"] = now + SESSION_TIMEOUT_SECONDS
            await self._prune_expired_requests(context_type, context_id, session, now)
            await self._deliver_queued(context_type, context_id, session)
            await self.cache.set(
                self._session_key(context_id, source_session_id, context_type),
                session,
                ttl=SESSION_TIMEOUT_SECONDS,
            )
            if context_type == "team":
                await self._append_index(self._member_sessions_key(context_id, user_id), source_session_id)
                await self._append_index(self._team_sessions_key(context_id), source_session_id)
            for item in session["bindings"]:
                owner_key = self._binding_key(context_id, item["project_id"], item["source_id"], context_type)
                owner = await self.cache.get(owner_key)
                if isinstance(owner, dict) and owner.get("source_session_id") == source_session_id:
                    owner["deadline_at"] = session["deadline_at"]
                    await self.cache.set(owner_key, owner, ttl=SESSION_TIMEOUT_SECONDS)
            return {"accepted": True, "deadline_at": session["deadline_at"]}

    async def disconnect_session(
        self,
        *,
        user_id: str,
        source_session_id: str,
        now: int,
        team_id: str | None = None,
        device_fingerprint_hash: str | None = None,
    ) -> bool:
        del now
        context_type, context_id = _context(user_id, team_id)
        async with self._state_lock(context_type, context_id):
            session = await self.cache.get(self._session_key(context_id, source_session_id, context_type))
            if not isinstance(session, dict):
                return False
            try:
                self._require_session_actor(session, user_id, device_fingerprint_hash)
            except ProjectRemoteAccessError:
                return False
            current = False
            for item in session.get("bindings", []):
                owner_key = self._binding_key(context_id, item["project_id"], item["source_id"], context_type)
                owner = await self.cache.get(owner_key)
                if isinstance(owner, dict) and owner.get("source_session_id") == source_session_id:
                    current = True
                    await self.cache.delete(owner_key)
            await self.cache.delete(self._session_key(context_id, source_session_id, context_type))
            if context_type == "team":
                await self._remove_index_value(self._member_sessions_key(context_id, user_id), source_session_id)
                await self._remove_index_value(self._team_sessions_key(context_id), source_session_id)
            return current

    async def revoke_source(
        self, *, user_id: str, project_id: str, source_id: str, team_id: str | None = None
    ) -> bool:
        """Invalidate a source binding and all queued or in-flight work before deletion."""
        context_type, context_id = _context(user_id, team_id)
        async with self._state_lock(context_type, context_id):
            owner_key = self._binding_key(context_id, project_id, source_id, context_type)
            owner = await self.cache.get(owner_key)
            if not isinstance(owner, dict):
                return False
            source_session_id = str(owner.get("source_session_id") or "")
            session_key = self._session_key(context_id, source_session_id, context_type)
            session = await self.cache.get(session_key)
            await self.cache.delete(owner_key)
            if not isinstance(session, dict):
                if context_type == "team":
                    await self._remove_index_value(
                        self._member_sessions_key(
                            context_id, str(owner.get("host_user_id") or "")
                        ),
                        source_session_id,
                    )
                    await self._remove_index_value(
                        self._team_sessions_key(context_id), source_session_id
                    )
                return True

            revoked_request_ids: list[str] = []
            for field in ("in_flight", "queued"):
                retained: list[str] = []
                for request_id in session.get(field, []):
                    request = await self.cache.get(self._request_key(context_id, request_id, context_type))
                    if isinstance(request, dict) and (
                        request.get("project_id"),
                        request.get("source_id"),
                    ) == (project_id, source_id):
                        revoked_request_ids.append(request_id)
                    else:
                        retained.append(request_id)
                session[field] = retained
            for request_id in revoked_request_ids:
                await self._revoke_request(context_type, context_id, request_id)

            session["bindings"] = [
                binding
                for binding in session.get("bindings", [])
                if (binding.get("project_id"), binding.get("source_id")) != (project_id, source_id)
            ]
            if session["bindings"]:
                await self.cache.set(session_key, session, ttl=SESSION_TIMEOUT_SECONDS)
            else:
                await self.cache.delete(session_key)
                if context_type == "team":
                    await self._remove_index_value(
                        self._member_sessions_key(context_id, str(session.get("host_user_id") or "")),
                        source_session_id,
                    )
                    await self._remove_index_value(
                        self._team_sessions_key(context_id), source_session_id
                    )
            return True

    async def revoke_member(self, *, team_id: str, member_user_id: str) -> bool:
        """Synchronously revoke a removed Team member's sessions and requests."""
        async with self._state_lock("team", team_id):
            revoked = await self._revoke_member_locked(team_id, member_user_id)
            if revoked:
                await self.cache.publish_event(
                    f"user_updates::{_hash(member_user_id)}",
                    {
                        "event_for_client": "project_remote_access_revoked",
                        "user_id_uuid": member_user_id,
                        "payload": {"context_type": "team", "context_id_hash": _hash(team_id)},
                    },
                )
        return revoked

    async def revoke_team(self, *, team_id: str) -> bool:
        """Invalidate all indexed sessions and requests before Team deletion."""
        revoked = False
        async with self._state_lock("team", team_id):
            for source_session_id in list(await self.cache.get(self._team_sessions_key(team_id)) or []):
                session = await self.cache.get(self._session_key(team_id, source_session_id, "team"))
                if isinstance(session, dict):
                    revoked = await self._revoke_member_locked(
                        team_id, str(session.get("host_user_id") or "")
                    ) or revoked
            for request_id in list(await self.cache.get(self._team_requests_key(team_id)) or []):
                revoked = True
                await self._revoke_request("team", team_id, request_id)
            await self.cache.delete(self._team_sessions_key(team_id))
            await self.cache.delete(self._team_requests_key(team_id))
        return revoked

    async def get_active_binding(
        self,
        user_id: str,
        project_id: str,
        source_id: str,
        *,
        now: int,
        team_id: str | None = None,
    ) -> dict[str, Any]:
        context_type, context_id = _context(user_id, team_id)
        owner = await self.cache.get(self._binding_key(context_id, project_id, source_id, context_type))
        if not isinstance(owner, dict) or int(owner.get("deadline_at") or 0) < now:
            raise ProjectRemoteAccessError("source_offline", status_code=404)
        session = await self.cache.get(
            self._session_key(context_id, str(owner.get("source_session_id") or ""), context_type)
        )
        if not isinstance(session, dict) or int(session.get("deadline_at") or 0) < now:
            raise ProjectRemoteAccessError("source_offline", status_code=404)
        return {**owner, "source_session_id": session["source_session_id"]}

    async def create_request(
        self,
        *,
        user_id: str,
        project_id: str,
        source_id: str,
        request_id: str,
        requesting_client_id: str,
        operation: str,
        key_epoch: int,
        encrypted_envelope: str,
        now: int,
        team_id: str | None = None,
        requesting_device_fingerprint_hash: str | None = None,
        validate_team_host: Callable[[str], Awaitable[bool]] | None = None,
        mark_team_host_offline: Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        _validate_envelope(encrypted_envelope)
        if operation not in ALLOWED_OPERATIONS:
            raise ProjectRemoteAccessError("unsupported_operation")

        context_type, context_id = _context(user_id, team_id)
        async with self._state_lock(context_type, context_id):
            binding = await self.get_active_binding(user_id, project_id, source_id, team_id=team_id, now=now)
            host_user_id = str(binding.get("host_user_id") or "")
            if context_type == "team" and validate_team_host and not await validate_team_host(host_user_id):
                await self._revoke_member_locked(context_id, host_user_id)
                if mark_team_host_offline:
                    await mark_team_host_offline(host_user_id)
                raise ProjectRemoteAccessError("source_offline", status_code=404)
            required_capability = "search" if operation == "search" else "read"
            if required_capability not in set(binding.get("capabilities") or []):
                raise ProjectRemoteAccessError("source_capability_denied", status_code=403)
            if int(binding.get("key_epoch") or 0) != key_epoch:
                raise ProjectRemoteAccessError("key_epoch_mismatch", status_code=409)
            await self._consume_rate_limit(user_id, now)

            request_key = self._request_key(context_id, request_id, context_type)
            if await self.cache.get(request_key) or await self.cache.get(
                self._tombstone_key(context_id, request_id, context_type)
            ):
                raise ProjectRemoteAccessError("duplicate_request_id", status_code=409)
            session_id = str(binding["source_session_id"])
            session = await self._require_session(
                context_type, context_id, session_id, now=now, allow_expired=False
            )
            await self._prune_expired_requests(context_type, context_id, session, now)
            await self._deliver_queued(context_type, context_id, session)
            in_flight = list(session.get("in_flight") or [])
            queued = list(session.get("queued") or [])
            if len(in_flight) >= MAX_IN_FLIGHT and len(queued) >= MAX_QUEUED:
                raise ProjectRemoteAccessError("source_queue_full", status_code=429)

            status = "delivered" if len(in_flight) < MAX_IN_FLIGHT else "queued"
            request = {
                "request_id": request_id,
                "context_type": context_type,
                "context_id_hash": _hash(context_id),
                "requester_user_id": user_id,
                "requester_member_hash": _hash(user_id),
                "requester_device_fingerprint_hash": requesting_device_fingerprint_hash or requesting_client_id,
                "host_user_id": binding.get("host_user_id", user_id),
                "host_member_hash": binding.get("host_member_hash", _hash(user_id)),
                "project_hash": _hash(project_id),
                "project_id": project_id,
                "source_id": source_id,
                "source_session_id": session_id,
                "device_fingerprint_hash": binding["device_fingerprint_hash"],
                "requesting_client_id": requesting_client_id,
                "operation": operation,
                "key_epoch": key_epoch,
                "encrypted_envelope": encrypted_envelope,
                "deadline_at": now + REQUEST_TIMEOUT_SECONDS,
                "status": status,
            }
            await self.cache.set(request_key, request, ttl=REQUEST_CACHE_TTL_SECONDS)
            if status == "delivered":
                in_flight.append(request_id)
            else:
                queued.append(request_id)
            session["in_flight"] = in_flight
            session["queued"] = queued
            await self.cache.set(
                self._session_key(context_id, session_id, context_type), session, ttl=SESSION_TIMEOUT_SECONDS
            )
            if context_type == "team":
                await self._append_index(self._member_requests_key(context_id, user_id), request_id)
                await self._append_index(self._team_requests_key(context_id), request_id)
            if status == "delivered":
                try:
                    await self._publish_request(request)
                except ProjectRemoteAccessError:
                    session["in_flight"] = [value for value in in_flight if value != request_id]
                    await self.cache.delete(request_key)
                    if context_type == "team":
                        await self._remove_request_indexes(context_id, user_id, request_id)
                    await self.cache.set(
                        self._session_key(context_id, session_id, context_type),
                        session,
                        ttl=SESSION_TIMEOUT_SECONDS,
                    )
                    raise
            response: dict[str, Any] = {
                "request_id": request_id,
                "status": status,
                "source_session_id": session_id,
                "key_epoch": key_epoch,
            }
            if context_type == "team":
                response["routing_identity"] = self._routing_identity(request)
            return response

    async def complete_request(
        self,
        *,
        user_id: str,
        device_fingerprint_hash: str,
        source_session_id: str,
        project_id: str,
        source_id: str,
        request_id: str,
        key_epoch: int,
        encrypted_envelope: str,
        now: int,
        team_id: str | None = None,
    ) -> bool:
        _validate_envelope(encrypted_envelope)
        context_type, context_id = _context(user_id, team_id)
        async with self._state_lock(context_type, context_id):
            if await self.cache.get(self._tombstone_key(context_id, request_id, context_type)):
                raise ProjectRemoteAccessError("request_already_completed", status_code=409)
            request = await self.cache.get(self._request_key(context_id, request_id, context_type))
            expected = (
                _hash(user_id),
                device_fingerprint_hash,
                source_session_id,
                project_id,
                source_id,
                key_epoch,
            )
            actual = (
                request.get("host_member_hash") if isinstance(request, dict) else None,
                request.get("device_fingerprint_hash") if isinstance(request, dict) else None,
                request.get("source_session_id") if isinstance(request, dict) else None,
                request.get("project_id") if isinstance(request, dict) else None,
                request.get("source_id") if isinstance(request, dict) else None,
                request.get("key_epoch") if isinstance(request, dict) else None,
            )
            if not isinstance(request, dict) or actual != expected or int(request.get("deadline_at") or 0) < now:
                raise ProjectRemoteAccessError("request_scope_mismatch", status_code=403)
            session = await self._require_session(
                context_type, context_id, source_session_id, now=now, allow_expired=False
            )
            self._require_session_actor(session, user_id, device_fingerprint_hash)

            await self.cache.set(
                self._result_key(context_id, request_id, context_type),
                {
                    "request_id": request_id,
                    "project_hash": request["project_hash"],
                    "source_id": source_id,
                    "requesting_client_id": request["requesting_client_id"],
                    "requester_user_id": request["requester_user_id"],
                    "requester_member_hash": request["requester_member_hash"],
                    "requester_device_fingerprint_hash": request["requester_device_fingerprint_hash"],
                    "status": "completed",
                    "encrypted_envelope": encrypted_envelope,
                },
                ttl=RESULT_CACHE_TTL_SECONDS,
            )
            if context_type == "team":
                await self._append_index(
                    self._member_requests_key(context_id, str(request["requester_user_id"])),
                    request_id,
                )
                await self._append_index(self._team_requests_key(context_id), request_id)
            await self.cache.set(
                self._tombstone_key(context_id, request_id, context_type),
                True,
                ttl=RESULT_CACHE_TTL_SECONDS,
            )
            await self.cache.delete(self._request_key(context_id, request_id, context_type))
            session["in_flight"] = [value for value in session.get("in_flight", []) if value != request_id]
            await self._deliver_queued(context_type, context_id, session)
            await self.cache.set(
                self._session_key(context_id, source_session_id, context_type),
                session,
                ttl=SESSION_TIMEOUT_SECONDS,
            )
            return True

    async def get_request_result(
        self,
        *,
        user_id: str,
        project_id: str,
        source_id: str,
        request_id: str,
        requesting_client_id: str,
        now: int,
        team_id: str | None = None,
        requesting_device_fingerprint_hash: str | None = None,
    ) -> dict[str, str]:
        del now
        context_type, context_id = _context(user_id, team_id)
        async with self._state_lock(context_type, context_id):
            result_key = self._result_key(context_id, request_id, context_type)
            result = await self.cache.get(result_key)
            if not isinstance(result, dict) or (
                result.get("project_hash"),
                result.get("source_id"),
                result.get("requesting_client_id"),
                result.get("requester_member_hash"),
                result.get("requester_device_fingerprint_hash"),
            ) != (
                _hash(project_id),
                source_id,
                requesting_client_id,
                _hash(user_id),
                requesting_device_fingerprint_hash or requesting_client_id,
            ):
                raise ProjectRemoteAccessError("request_not_found", status_code=404)
            response = {
                "status": str(result["status"]),
                "encrypted_envelope": str(result["encrypted_envelope"]),
            }
            await self.cache.delete(result_key)
            if context_type == "team":
                await self._remove_request_indexes(context_id, user_id, request_id)
            return response

    async def _consume_rate_limit(self, user_id: str, now: int) -> None:
        minute = now // 60
        key = f"project_remote:rate:{_hash(user_id)}:{minute}"
        current = int(await self.cache.get(key) or 0)
        if current >= MAX_REQUESTS_PER_MINUTE:
            raise ProjectRemoteAccessError("request_rate_limited", status_code=429)
        await self.cache.set(key, current + 1, ttl=120)

    @asynccontextmanager
    async def _state_lock(self, context_type: str, context_id: str):
        async with self._lock:
            try:
                client = await self.cache.client
            except (AttributeError, TypeError):
                client = None
            if client is None:
                yield
                return

            key = f"{_cache_prefix(context_type)}:lock:{_hash(context_id)}"
            token = secrets.token_urlsafe(24)
            deadline = time.monotonic() + STATE_LOCK_WAIT_SECONDS
            acquired = False
            while time.monotonic() < deadline:
                acquired = bool(await client.set(key, token, nx=True, ex=STATE_LOCK_TTL_SECONDS))
                if acquired:
                    break
                await asyncio.sleep(0.05)
            if not acquired:
                raise ProjectRemoteAccessError("bridge_busy", status_code=503)
            try:
                yield
            finally:
                await client.eval(RELEASE_LOCK_SCRIPT, 1, key, token)

    async def _require_session(
        self,
        context_type: str,
        context_id: str,
        source_session_id: str,
        *,
        now: int,
        allow_expired: bool,
    ) -> dict[str, Any]:
        session = await self.cache.get(self._session_key(context_id, source_session_id, context_type))
        if not isinstance(session, dict) or (not allow_expired and int(session.get("deadline_at") or 0) < now):
            raise ProjectRemoteAccessError("source_offline", status_code=404)
        return session

    async def _prune_expired_requests(
        self, context_type: str, context_id: str, session: dict[str, Any], now: int
    ) -> None:
        for field in ("in_flight", "queued"):
            active: list[str] = []
            for request_id in session.get(field, []):
                request = await self.cache.get(self._request_key(context_id, request_id, context_type))
                if isinstance(request, dict) and int(request.get("deadline_at") or 0) >= now:
                    active.append(request_id)
                    continue
                await self.cache.delete(self._request_key(context_id, request_id, context_type))
                if context_type == "team" and isinstance(request, dict):
                    await self._remove_request_indexes(
                        context_id, str(request.get("requester_user_id") or ""), request_id
                    )
                await self.cache.set(
                    self._tombstone_key(context_id, request_id, context_type),
                    True,
                    ttl=RESULT_CACHE_TTL_SECONDS,
                )
            session[field] = active

    async def _deliver_queued(self, context_type: str, context_id: str, session: dict[str, Any]) -> None:
        while session.get("queued") and len(session.get("in_flight") or []) < MAX_IN_FLIGHT:
            await self._deliver_next_queued(context_type, context_id, session)

    async def _deliver_next_queued(
        self, context_type: str, context_id: str, session: dict[str, Any]
    ) -> None:
        queued = list(session.get("queued") or [])
        if not queued or len(session.get("in_flight") or []) >= MAX_IN_FLIGHT:
            return
        request_id = queued.pop(0)
        request = await self.cache.get(self._request_key(context_id, request_id, context_type))
        session["queued"] = queued
        if not isinstance(request, dict):
            await self._deliver_next_queued(context_type, context_id, session)
            return
        request["status"] = "delivered"
        session.setdefault("in_flight", []).append(request_id)
        await self.cache.set(
            self._request_key(context_id, request_id, context_type), request, ttl=REQUEST_CACHE_TTL_SECONDS
        )
        try:
            await self._publish_request(request)
        except ProjectRemoteAccessError:
            request["status"] = "queued"
            session["in_flight"] = [value for value in session["in_flight"] if value != request_id]
            session["queued"] = [request_id, *session.get("queued", [])]
            await self.cache.set(
                self._request_key(context_id, request_id, context_type),
                request,
                ttl=REQUEST_CACHE_TTL_SECONDS,
            )

    async def _publish_request(self, request: dict[str, Any]) -> None:
        payload: dict[str, Any] = {
            "request_id": request["request_id"],
            "project_id": request["project_id"],
            "source_id": request["source_id"],
            "source_session_id": request["source_session_id"],
            "requesting_client_id": request["requesting_client_id"],
            "operation": request["operation"],
            "key_epoch": request["key_epoch"],
            "encrypted_envelope": request["encrypted_envelope"],
        }
        if request["context_type"] == "team":
            payload["routing_identity"] = self._routing_identity(request)
        published = await self.cache.publish_event(
            f"user_updates::{request['host_member_hash']}",
            {
                "event_for_client": "project_remote_access_request",
                "user_id_uuid": request["host_user_id"],
                "target_device_fingerprint_hash": request["device_fingerprint_hash"],
                "payload": payload,
            },
        )
        if not published:
            raise ProjectRemoteAccessError("request_delivery_unavailable", status_code=503)

    @staticmethod
    def _require_session_actor(
        session: dict[str, Any], user_id: str, device_fingerprint_hash: str | None
    ) -> None:
        host_member_hash = session.get("host_member_hash")
        legacy_personal_session = host_member_hash is None and session.get("context_type") is None
        if (not legacy_personal_session and host_member_hash != _hash(user_id)) or (
            device_fingerprint_hash is not None
            and session.get("device_fingerprint_hash") != device_fingerprint_hash
        ):
            raise ProjectRemoteAccessError("session_scope_mismatch", status_code=403)

    @staticmethod
    def _routing_identity(request: dict[str, Any]) -> dict[str, str]:
        context_hash = str(request["context_id_hash"])
        return {
            "context_type": str(request["context_type"]),
            "context_id_hash": context_hash,
            "host_member_hash": _scoped_identity(context_hash, str(request["host_member_hash"])),
            "host_device_fingerprint_hash": _scoped_identity(
                context_hash, str(request["device_fingerprint_hash"])
            ),
            "requester_member_hash": _scoped_identity(
                context_hash, str(request["requester_member_hash"])
            ),
            "requester_device_fingerprint_hash": _scoped_identity(
                context_hash, str(request["requester_device_fingerprint_hash"])
            ),
        }

    async def _append_index(self, key: str, value: str) -> None:
        values = list(await self.cache.get(key) or [])
        if value not in values:
            values.append(value)
        await self.cache.set(key, values, ttl=RESULT_CACHE_TTL_SECONDS)

    async def _remove_index_value(self, key: str, value: str) -> None:
        values = [item for item in list(await self.cache.get(key) or []) if item != value]
        if values:
            await self.cache.set(key, values, ttl=RESULT_CACHE_TTL_SECONDS)
        else:
            await self.cache.delete(key)

    async def _remove_request_indexes(
        self, team_id: str, requester_user_id: str, request_id: str
    ) -> None:
        if requester_user_id:
            await self._remove_index_value(
                self._member_requests_key(team_id, requester_user_id), request_id
            )
        await self._remove_index_value(self._team_requests_key(team_id), request_id)

    async def _revoke_member_locked(self, team_id: str, member_user_id: str) -> bool:
        revoked = False
        sessions = list(await self.cache.get(self._member_sessions_key(team_id, member_user_id)) or [])
        for source_session_id in sessions:
            session_key = self._session_key(team_id, source_session_id, "team")
            session = await self.cache.get(session_key)
            if not isinstance(session, dict):
                continue
            revoked = True
            for item in session.get("bindings", []):
                owner_key = self._binding_key(team_id, item["project_id"], item["source_id"], "team")
                owner = await self.cache.get(owner_key)
                if isinstance(owner, dict) and owner.get("source_session_id") == source_session_id:
                    await self.cache.delete(owner_key)
            for request_id in [*session.get("in_flight", []), *session.get("queued", [])]:
                await self._revoke_request("team", team_id, request_id)
            await self.cache.delete(session_key)
            await self._remove_index_value(self._team_sessions_key(team_id), source_session_id)
        await self.cache.delete(self._member_sessions_key(team_id, member_user_id))

        requests = list(await self.cache.get(self._member_requests_key(team_id, member_user_id)) or [])
        for request_id in requests:
            revoked = True
            await self._revoke_request("team", team_id, request_id)
        await self.cache.delete(self._member_requests_key(team_id, member_user_id))
        return revoked

    async def _revoke_request(self, context_type: str, context_id: str, request_id: str) -> None:
        request = await self.cache.get(self._request_key(context_id, request_id, context_type))
        result = await self.cache.get(self._result_key(context_id, request_id, context_type))
        await self.cache.delete(self._request_key(context_id, request_id, context_type))
        await self.cache.delete(self._result_key(context_id, request_id, context_type))
        if context_type == "team":
            metadata = request if isinstance(request, dict) else result
            requester_user_id = str(metadata.get("requester_user_id") or "") if isinstance(metadata, dict) else ""
            await self._remove_request_indexes(context_id, requester_user_id, request_id)
        await self.cache.set(
            self._tombstone_key(context_id, request_id, context_type),
            True,
            ttl=RESULT_CACHE_TTL_SECONDS,
        )

    @staticmethod
    def _session_key(context_id: str, source_session_id: str, context_type: str = "personal") -> str:
        return f"{_cache_prefix(context_type)}:session:{_hash(context_id)}:{source_session_id}"

    @staticmethod
    def _binding_key(
        context_id: str, project_id: str, source_id: str, context_type: str = "personal"
    ) -> str:
        return f"{_cache_prefix(context_type)}:binding:{_hash(context_id)}:{_hash(project_id)}:{source_id}"

    @staticmethod
    def _request_key(context_id: str, request_id: str, context_type: str = "personal") -> str:
        return f"{_cache_prefix(context_type)}:request:{_hash(context_id)}:{request_id}"

    @staticmethod
    def _result_key(context_id: str, request_id: str, context_type: str = "personal") -> str:
        return f"{_cache_prefix(context_type)}:result:{_hash(context_id)}:{request_id}"

    @staticmethod
    def _tombstone_key(context_id: str, request_id: str, context_type: str = "personal") -> str:
        return f"{_cache_prefix(context_type)}:completed:{_hash(context_id)}:{request_id}"

    @staticmethod
    def _member_sessions_key(team_id: str, member_user_id: str) -> str:
        return f"project_remote:team:member_sessions:{_hash(team_id)}:{_hash(member_user_id)}"

    @staticmethod
    def _member_requests_key(team_id: str, member_user_id: str) -> str:
        return f"project_remote:team:member_requests:{_hash(team_id)}:{_hash(member_user_id)}"

    @staticmethod
    def _team_sessions_key(team_id: str) -> str:
        return f"project_remote:team:sessions:{_hash(team_id)}"

    @staticmethod
    def _team_requests_key(team_id: str) -> str:
        return f"project_remote:team:requests:{_hash(team_id)}"

    @staticmethod
    def _hash_identity(value: str) -> str:
        return _hash(value)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _context(user_id: str, team_id: str | None) -> tuple[str, str]:
    return ("team", team_id) if team_id else ("personal", user_id)


def _scoped_identity(context_hash: str, value: str) -> str:
    return _hash(f"{context_hash}:{value}")


def _cache_prefix(context_type: str) -> str:
    return "project_remote" if context_type == "personal" else "project_remote:team"


def _normalize_binding(value: dict[str, Any]) -> dict[str, Any]:
    project_id = str(value.get("project_id") or "")
    source_id = str(value.get("source_id") or "")
    capabilities = sorted(set(value.get("capabilities") or []))
    key_epoch = value.get("key_epoch")
    if (
        not project_id
        or len(project_id) > 128
        or not source_id
        or len(source_id) > 128
        or not capabilities
        or not isinstance(key_epoch, int)
        or key_epoch < 1
    ):
        raise ProjectRemoteAccessError("invalid_source_binding")
    if not set(capabilities).issubset({"read", "search", "import"}):
        raise ProjectRemoteAccessError("invalid_source_capabilities")
    return {
        "project_id": project_id,
        "source_id": source_id,
        "capabilities": capabilities,
        "key_epoch": key_epoch,
    }


def _validate_envelope(value: str) -> None:
    if not value:
        raise ProjectRemoteAccessError("encrypted_envelope_required")
    if len(value.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise ProjectRemoteAccessError("payload_too_large", status_code=413)
