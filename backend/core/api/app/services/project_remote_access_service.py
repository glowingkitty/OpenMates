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
    ) -> dict[str, Any]:
        normalized = [_normalize_binding(item) for item in bindings]
        if not normalized:
            raise ProjectRemoteAccessError("source_bindings_required")
        if len({(item["project_id"], item["source_id"]) for item in normalized}) != len(normalized):
            raise ProjectRemoteAccessError("duplicate_source_binding")

        replaced_sessions: set[str] = set()
        async with self._state_lock(user_id):
            for item in normalized:
                owner = await self.cache.get(self._binding_key(user_id, item["project_id"], item["source_id"]))
                previous = owner.get("source_session_id") if isinstance(owner, dict) else None
                if previous and previous != source_session_id:
                    if not confirmed_takeover:
                        raise ProjectRemoteAccessError("takeover_confirmation_required", status_code=409)
                    replaced_sessions.add(str(previous))

            session = {
                "source_session_id": source_session_id,
                "device_fingerprint_hash": device_fingerprint_hash,
                "bindings": normalized,
                "last_heartbeat_at": now,
                "deadline_at": now + SESSION_TIMEOUT_SECONDS,
                "in_flight": [],
                "queued": [],
            }
            await self.cache.set(
                self._session_key(user_id, source_session_id),
                session,
                ttl=SESSION_TIMEOUT_SECONDS,
            )
            for item in normalized:
                await self.cache.set(
                    self._binding_key(user_id, item["project_id"], item["source_id"]),
                    {
                        "source_session_id": source_session_id,
                        "device_fingerprint_hash": device_fingerprint_hash,
                        "key_epoch": item["key_epoch"],
                        "capabilities": item["capabilities"],
                        "deadline_at": session["deadline_at"],
                    },
                    ttl=SESSION_TIMEOUT_SECONDS,
                )
            for replaced in replaced_sessions:
                replaced_session = await self.cache.get(self._session_key(user_id, replaced))
                if isinstance(replaced_session, dict):
                    for item in replaced_session.get("bindings", []):
                        owner_key = self._binding_key(user_id, item["project_id"], item["source_id"])
                        owner = await self.cache.get(owner_key)
                        if isinstance(owner, dict) and owner.get("source_session_id") == replaced:
                            await self.cache.delete(owner_key)
                await self.cache.delete(self._session_key(user_id, replaced))

        return {
            "source_session_id": source_session_id,
            "heartbeat_interval_seconds": HEARTBEAT_INTERVAL_SECONDS,
            "deadline_at": session["deadline_at"],
            "replaced_session_id": next(iter(replaced_sessions), None),
        }

    async def heartbeat_session(self, *, user_id: str, source_session_id: str, now: int) -> dict[str, Any]:
        async with self._state_lock(user_id):
            session = await self._require_session(user_id, source_session_id, now=now, allow_expired=False)
            if now - int(session["last_heartbeat_at"]) < HEARTBEAT_MIN_INTERVAL_SECONDS:
                raise ProjectRemoteAccessError("heartbeat_too_early", status_code=429)
            session["last_heartbeat_at"] = now
            session["deadline_at"] = now + SESSION_TIMEOUT_SECONDS
            await self._prune_expired_requests(user_id, session, now)
            await self._deliver_queued(user_id, session)
            await self.cache.set(self._session_key(user_id, source_session_id), session, ttl=SESSION_TIMEOUT_SECONDS)
            for item in session["bindings"]:
                owner_key = self._binding_key(user_id, item["project_id"], item["source_id"])
                owner = await self.cache.get(owner_key)
                if isinstance(owner, dict) and owner.get("source_session_id") == source_session_id:
                    owner["deadline_at"] = session["deadline_at"]
                    await self.cache.set(owner_key, owner, ttl=SESSION_TIMEOUT_SECONDS)
            return {"accepted": True, "deadline_at": session["deadline_at"]}

    async def disconnect_session(self, *, user_id: str, source_session_id: str, now: int) -> bool:
        del now
        async with self._state_lock(user_id):
            session = await self.cache.get(self._session_key(user_id, source_session_id))
            if not isinstance(session, dict):
                return False
            current = False
            for item in session.get("bindings", []):
                owner_key = self._binding_key(user_id, item["project_id"], item["source_id"])
                owner = await self.cache.get(owner_key)
                if isinstance(owner, dict) and owner.get("source_session_id") == source_session_id:
                    current = True
                    await self.cache.delete(owner_key)
            await self.cache.delete(self._session_key(user_id, source_session_id))
            return current

    async def get_active_binding(
        self,
        user_id: str,
        project_id: str,
        source_id: str,
        *,
        now: int,
    ) -> dict[str, Any]:
        owner = await self.cache.get(self._binding_key(user_id, project_id, source_id))
        if not isinstance(owner, dict) or int(owner.get("deadline_at") or 0) < now:
            raise ProjectRemoteAccessError("source_offline", status_code=404)
        session = await self.cache.get(self._session_key(user_id, str(owner.get("source_session_id") or "")))
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
    ) -> dict[str, str]:
        _validate_envelope(encrypted_envelope)
        if operation not in ALLOWED_OPERATIONS:
            raise ProjectRemoteAccessError("unsupported_operation")

        async with self._state_lock(user_id):
            binding = await self.get_active_binding(user_id, project_id, source_id, now=now)
            required_capability = "search" if operation == "search" else "read"
            if required_capability not in set(binding.get("capabilities") or []):
                raise ProjectRemoteAccessError("source_capability_denied", status_code=403)
            if int(binding.get("key_epoch") or 0) != key_epoch:
                raise ProjectRemoteAccessError("key_epoch_mismatch", status_code=409)
            await self._consume_rate_limit(user_id, now)

            request_key = self._request_key(user_id, request_id)
            if await self.cache.get(request_key) or await self.cache.get(self._tombstone_key(user_id, request_id)):
                raise ProjectRemoteAccessError("duplicate_request_id", status_code=409)
            session_id = str(binding["source_session_id"])
            session = await self._require_session(user_id, session_id, now=now, allow_expired=False)
            await self._prune_expired_requests(user_id, session, now)
            await self._deliver_queued(user_id, session)
            in_flight = list(session.get("in_flight") or [])
            queued = list(session.get("queued") or [])
            if len(in_flight) >= MAX_IN_FLIGHT and len(queued) >= MAX_QUEUED:
                raise ProjectRemoteAccessError("source_queue_full", status_code=429)

            status = "delivered" if len(in_flight) < MAX_IN_FLIGHT else "queued"
            request = {
                "request_id": request_id,
                "user_hash": _hash(user_id),
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
            await self.cache.set(self._session_key(user_id, session_id), session, ttl=SESSION_TIMEOUT_SECONDS)
            if status == "delivered":
                try:
                    await self._publish_request(user_id, request)
                except ProjectRemoteAccessError:
                    session["in_flight"] = [value for value in in_flight if value != request_id]
                    await self.cache.delete(request_key)
                    await self.cache.set(self._session_key(user_id, session_id), session, ttl=SESSION_TIMEOUT_SECONDS)
                    raise
            return {"request_id": request_id, "status": status}

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
    ) -> bool:
        _validate_envelope(encrypted_envelope)
        async with self._state_lock(user_id):
            if await self.cache.get(self._tombstone_key(user_id, request_id)):
                raise ProjectRemoteAccessError("request_already_completed", status_code=409)
            request = await self.cache.get(self._request_key(user_id, request_id))
            expected = (
                device_fingerprint_hash,
                source_session_id,
                project_id,
                source_id,
                key_epoch,
            )
            actual = (
                request.get("device_fingerprint_hash") if isinstance(request, dict) else None,
                request.get("source_session_id") if isinstance(request, dict) else None,
                request.get("project_id") if isinstance(request, dict) else None,
                request.get("source_id") if isinstance(request, dict) else None,
                request.get("key_epoch") if isinstance(request, dict) else None,
            )
            if not isinstance(request, dict) or actual != expected or int(request.get("deadline_at") or 0) < now:
                raise ProjectRemoteAccessError("request_scope_mismatch", status_code=403)

            await self.cache.set(
                self._result_key(user_id, request_id),
                {
                    "request_id": request_id,
                    "project_hash": request["project_hash"],
                    "source_id": source_id,
                    "requesting_client_id": request["requesting_client_id"],
                    "status": "completed",
                    "encrypted_envelope": encrypted_envelope,
                },
                ttl=RESULT_CACHE_TTL_SECONDS,
            )
            await self.cache.set(self._tombstone_key(user_id, request_id), True, ttl=RESULT_CACHE_TTL_SECONDS)
            await self.cache.delete(self._request_key(user_id, request_id))
            session = await self._require_session(user_id, source_session_id, now=now, allow_expired=True)
            session["in_flight"] = [value for value in session.get("in_flight", []) if value != request_id]
            await self._deliver_queued(user_id, session)
            await self.cache.set(self._session_key(user_id, source_session_id), session, ttl=SESSION_TIMEOUT_SECONDS)
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
    ) -> dict[str, str]:
        del now
        result = await self.cache.get(self._result_key(user_id, request_id))
        if not isinstance(result, dict) or (
            result.get("project_hash"),
            result.get("source_id"),
            result.get("requesting_client_id"),
        ) != (_hash(project_id), source_id, requesting_client_id):
            raise ProjectRemoteAccessError("request_not_found", status_code=404)
        return {"status": str(result["status"]), "encrypted_envelope": str(result["encrypted_envelope"])}

    async def _consume_rate_limit(self, user_id: str, now: int) -> None:
        minute = now // 60
        key = f"project_remote:rate:{_hash(user_id)}:{minute}"
        current = int(await self.cache.get(key) or 0)
        if current >= MAX_REQUESTS_PER_MINUTE:
            raise ProjectRemoteAccessError("request_rate_limited", status_code=429)
        await self.cache.set(key, current + 1, ttl=120)

    @asynccontextmanager
    async def _state_lock(self, user_id: str):
        async with self._lock:
            try:
                client = await self.cache.client
            except (AttributeError, TypeError):
                client = None
            if client is None:
                yield
                return

            key = f"project_remote:lock:{_hash(user_id)}"
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
        user_id: str,
        source_session_id: str,
        *,
        now: int,
        allow_expired: bool,
    ) -> dict[str, Any]:
        session = await self.cache.get(self._session_key(user_id, source_session_id))
        if not isinstance(session, dict) or (not allow_expired and int(session.get("deadline_at") or 0) < now):
            raise ProjectRemoteAccessError("source_offline", status_code=404)
        return session

    async def _prune_expired_requests(self, user_id: str, session: dict[str, Any], now: int) -> None:
        for field in ("in_flight", "queued"):
            active: list[str] = []
            for request_id in session.get(field, []):
                request = await self.cache.get(self._request_key(user_id, request_id))
                if isinstance(request, dict) and int(request.get("deadline_at") or 0) >= now:
                    active.append(request_id)
                    continue
                await self.cache.delete(self._request_key(user_id, request_id))
                await self.cache.set(self._tombstone_key(user_id, request_id), True, ttl=RESULT_CACHE_TTL_SECONDS)
            session[field] = active

    async def _deliver_queued(self, user_id: str, session: dict[str, Any]) -> None:
        while session.get("queued") and len(session.get("in_flight") or []) < MAX_IN_FLIGHT:
            await self._deliver_next_queued(user_id, session)

    async def _deliver_next_queued(self, user_id: str, session: dict[str, Any]) -> None:
        queued = list(session.get("queued") or [])
        if not queued or len(session.get("in_flight") or []) >= MAX_IN_FLIGHT:
            return
        request_id = queued.pop(0)
        request = await self.cache.get(self._request_key(user_id, request_id))
        session["queued"] = queued
        if not isinstance(request, dict):
            await self._deliver_next_queued(user_id, session)
            return
        request["status"] = "delivered"
        session.setdefault("in_flight", []).append(request_id)
        await self.cache.set(self._request_key(user_id, request_id), request, ttl=REQUEST_CACHE_TTL_SECONDS)
        try:
            await self._publish_request(user_id, request)
        except ProjectRemoteAccessError:
            request["status"] = "queued"
            session["in_flight"] = [value for value in session["in_flight"] if value != request_id]
            session["queued"] = [request_id, *session.get("queued", [])]
            await self.cache.set(self._request_key(user_id, request_id), request, ttl=REQUEST_CACHE_TTL_SECONDS)

    async def _publish_request(self, user_id: str, request: dict[str, Any]) -> None:
        published = await self.cache.publish_event(
            f"user_updates::{_hash(user_id)}",
            {
                "event_for_client": "project_remote_access_request",
                "user_id_uuid": user_id,
                "target_device_fingerprint_hash": request["device_fingerprint_hash"],
                "payload": {
                    "request_id": request["request_id"],
                    "project_id": request["project_id"],
                    "source_id": request["source_id"],
                    "source_session_id": request["source_session_id"],
                    "requesting_client_id": request["requesting_client_id"],
                    "operation": request["operation"],
                    "key_epoch": request["key_epoch"],
                    "encrypted_envelope": request["encrypted_envelope"],
                },
            },
        )
        if not published:
            raise ProjectRemoteAccessError("request_delivery_unavailable", status_code=503)

    @staticmethod
    def _session_key(user_id: str, source_session_id: str) -> str:
        return f"project_remote:session:{_hash(user_id)}:{source_session_id}"

    @staticmethod
    def _binding_key(user_id: str, project_id: str, source_id: str) -> str:
        return f"project_remote:binding:{_hash(user_id)}:{_hash(project_id)}:{source_id}"

    @staticmethod
    def _request_key(user_id: str, request_id: str) -> str:
        return f"project_remote:request:{_hash(user_id)}:{request_id}"

    @staticmethod
    def _result_key(user_id: str, request_id: str) -> str:
        return f"project_remote:result:{_hash(user_id)}:{request_id}"

    @staticmethod
    def _tombstone_key(user_id: str, request_id: str) -> str:
        return f"project_remote:completed:{_hash(user_id)}:{request_id}"


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
