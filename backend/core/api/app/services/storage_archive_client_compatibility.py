"""Runtime enforcement for archive-aware clients; capability never grants access.

Deployment inventory identifies the expected API processes. Actual guard and
connection proofs are published by those processes to shared Redis. Missing
inventory, stale proofs or cache failure keep automatic pruning closed.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import socket
import time
import uuid
from typing import Any

from starlette.responses import JSONResponse

REQUIRED_CAPABILITY = "agentic-storage-v2"
CAPABILITY_HEADER = "x-openmates-client-capabilities"
GUARD_REVISION = "archive-client-guards-v1"
PROOF_PREFIX = "storage:archive_client_guard:v1:"
DEPLOYMENT_INVENTORY_KEY = "storage:archive_client_guard:deployment:v1"
PROOF_TTL = 45
ROLLOUT_COLLECTIONS = ("chat_message_archive_rollout", "embed_version_archive_rollout")
SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
INSTANCE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
logger = logging.getLogger(__name__)


def declares_archive_capability(raw: str) -> bool:
    return len(raw) <= 1024 and REQUIRED_CAPABILITY in {value.strip() for value in raw.split(",")}


async def archive_phase_active(directus_service: Any) -> bool:
    """Retained reader receipts protect already-pruned data during a pause."""
    for collection in ROLLOUT_COLLECTIONS:
        rows = await directus_service.get_items(collection, params={
            "filter[id][_eq]": REQUIRED_CAPABILITY,
            "fields": "id,read_enabled,pruning_enabled,reader_receipt", "limit": 1,
        }, no_cache=True, admin_required=True, raise_on_error=True)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("Archive compatibility phase is unavailable")
        if any(row.get("read_enabled") or row.get("pruning_enabled") or row.get("reader_receipt") for row in rows):
            return True
    return False


def archive_http_path(path: str, method: str = "GET") -> bool:
    # Writes retain route authorization and their canonical protocol checks.
    if method.upper() not in {"GET", "HEAD"}:
        return False
    # Public preview crawlers do not request encrypted archive content.
    if path.endswith(("/og-metadata", "/og-image.png")):
        return False
    if path.startswith("/v1/projects"):
        return path.endswith(("/items", "/history", "/restore"))
    return any(path == prefix or path.startswith(prefix + "/") for prefix in (
        "/v1/chats", "/v1/sync", "/v1/embeds", "/v1/sdk/chats",
        "/v1/share/chat", "/v1/share/embed", "/v1/account-exports",
    ))


class StorageArchiveClientCompatibilityMiddleware:
    """First-party/public-share compatibility admission; route auth still applies."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if (scope.get("type") != "http" or scope.get("method") == "OPTIONS"
                or not archive_http_path(scope.get("path", ""), scope.get("method", ""))):
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        raw = headers.get(CAPABILITY_HEADER.encode(), b"").decode("latin1")
        if declares_archive_capability(raw):
            await self.app(scope, receive, send)
            return
        try:
            state = scope["app"].state
            async with asyncio.timeout(5):
                active = await archive_phase_active(state.directus_service)
        except Exception:
            response = JSONResponse({"detail": "Storage compatibility temporarily unavailable"}, status_code=503)
        else:
            if not active:
                await self.app(scope, receive, send)
                return
            response = JSONResponse({"detail": "update_required", "required_capability": REQUIRED_CAPABILITY}, status_code=426)
        await response(scope, receive, send)


async def _redis(directus_service: Any) -> Any:
    value = directus_service.cache.client
    client = await value if inspect.isawaitable(value) else value
    if client is None:
        raise RuntimeError("Shared runtime compatibility inventory is unavailable")
    return client


async def _expected_instances(client: Any, source: str) -> tuple[str, set[str]]:
    raw = await client.get(DEPLOYMENT_INVENTORY_KEY)
    if not raw or len(raw) > 32768:
        raise RuntimeError("Complete API deployment inventory is required")
    inventory = json.loads(raw)
    now = int(time.time())
    if (not isinstance(inventory, dict) or inventory.get("source_commit") != source
            or type(inventory.get("observed_at")) is not int
            or type(inventory.get("expires_at")) is not int
            or not inventory["observed_at"] <= now < inventory["expires_at"]
            or inventory["expires_at"] - inventory["observed_at"] > 86400):
        raise RuntimeError("API deployment inventory is stale or source-mismatched")
    inventory_id = inventory.get("inventory_id")
    try:
        nonce = uuid.UUID(inventory_id)
    except (ValueError, TypeError, AttributeError):
        raise RuntimeError("Typed deployment inventory identity is required") from None
    if nonce.version != 4 or str(nonce) != inventory_id:
        raise RuntimeError("Typed deployment inventory identity is required")
    values = inventory.get("instance_ids")
    if (not isinstance(values, list) or not 1 <= len(values) <= 128
            or any(not isinstance(value, str) or not INSTANCE_RE.fullmatch(value) for value in values)
            or len(set(values)) != len(values)):
        raise RuntimeError("Complete API deployment inventory is required")
    return inventory_id, set(values)


def incompatible_connections(manager: Any) -> list[Any]:
    result = []
    for user_id, connections in manager.active_connections.items():
        for device, websocket in connections.items():
            if not manager.storage_archive_capability.get((user_id, device), False):
                result.append(websocket)
    return result


async def invalidate_runtime_proof(app: Any) -> None:
    """A new legacy admission must invalidate the preceding zero-session proof."""
    client = await _redis(app.state.directus_service)
    instance = f"{socket.gethostname()}:{os.getpid()}"
    await client.delete(PROOF_PREFIX + instance)


async def publish_runtime_proof(app: Any) -> None:
    """Publish actual installed guards and current incompatible session count."""
    instance = f"{socket.gethostname()}:{os.getpid()}"
    source = os.getenv("BUILD_COMMIT_SHA") or os.getenv("OPENMATES_BUILD_SHA") or ""
    if not INSTANCE_RE.fullmatch(instance) or not SOURCE_RE.fullmatch(source):
        raise RuntimeError("Exact API runtime identity and source are required")
    manager = app.state.connection_manager
    http_guard = any(item.cls is StorageArchiveClientCompatibilityMiddleware for item in app.user_middleware)
    if not http_guard or not getattr(manager, "storage_archive_dispatch_guard_installed", False):
        raise RuntimeError("Actual HTTP and WebSocket guards are required")
    client = await _redis(app.state.directus_service)
    inventory_id, expected = await _expected_instances(client, source)
    if instance not in expected:
        raise RuntimeError("API process is outside the complete deployment inventory")
    proof = {"inventory_id": inventory_id, "source_commit": source, "guard_revision": GUARD_REVISION,
             "instance_id": instance, "observed_at": int(time.time()),
             "incompatible_sessions": len(incompatible_connections(manager))}
    await client.set(PROOF_PREFIX + instance, json.dumps(proof), ex=PROOF_TTL)


async def runtime_compatibility_status(directus_service: Any, *, source_commit: str) -> dict[str, Any]:
    """Verify every expected API instance through bounded shared runtime proof."""
    result = {"enforced": False, "minimum_capability": REQUIRED_CAPABILITY,
              "source_commit": source_commit, "incompatible_sessions": None}
    try:
        if not SOURCE_RE.fullmatch(source_commit):
            raise RuntimeError("Exact runtime source is required")
        client = await _redis(directus_service)
        inventory_id, expected = await _expected_instances(client, source_commit)
        keys = []
        async for key in client.scan_iter(match=PROOF_PREFIX + "*", count=128):
            keys.append(key.decode() if isinstance(key, bytes) else key)
            if len(keys) > 128:
                raise RuntimeError("API runtime inventory exceeds its bound")
        if set(keys) != {PROOF_PREFIX + instance for instance in expected}:
            raise RuntimeError("API runtime inventory is incomplete or changed")
        values = await client.mget(keys)
        incompatible = 0
        now = int(time.time())
        for key, value in zip(keys, values, strict=True):
            if not value or len(value) > 4096:
                raise RuntimeError("API runtime proof is missing")
            proof = json.loads(value)
            if (not isinstance(proof, dict) or proof.get("source_commit") != source_commit
                    or proof.get("guard_revision") != GUARD_REVISION
                    or proof.get("inventory_id") != inventory_id
                    or PROOF_PREFIX + str(proof.get("instance_id")) != key
                    or type(proof.get("observed_at")) is not int
                    or not 0 <= now - proof["observed_at"] < PROOF_TTL
                    or type(proof.get("incompatible_sessions")) is not int
                    or proof["incompatible_sessions"] < 0):
                raise RuntimeError("API runtime proof is stale or incompatible")
            incompatible += proof["incompatible_sessions"]
        if await _expected_instances(client, source_commit) != (inventory_id, expected):
            raise RuntimeError("API deployment inventory changed during verification")
        result.update(enforced=True, incompatible_sessions=incompatible, inventory_id=inventory_id)
    except Exception:
        result["reason"] = "runtime_compatibility_unverified"
    return result


async def runtime_proof_loop(app: Any) -> None:
    """Refresh live proof and retire legacy sessions when archive readers activate."""
    while True:
        try:
            async with asyncio.timeout(10):
                manager = app.state.connection_manager
                if await archive_phase_active(app.state.directus_service):
                    for websocket in incompatible_connections(manager):
                        try:
                            await websocket.send_json({"type": "update_required", "payload": {
                                "required_capability": REQUIRED_CAPABILITY}})
                            await websocket.close(code=4406)
                        except Exception:
                            pass
                await publish_runtime_proof(app)
        except Exception:
            logger.debug("Storage runtime compatibility proof is unavailable")
        await asyncio.sleep(10)
