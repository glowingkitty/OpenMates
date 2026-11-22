# backend/core/api/app/services/project_sandbox_service.py
#
# Lifecycle of the per-(user, chat, Project) E2B sandbox that runs the hosted
# Project agent. ensure_ready finds or creates the sandbox, obtains the sealed
# Project key grant from one of the user's devices, relays it to the daemon in
# memory only, and syncs the Project's ciphertext heads in. The server never
# handles the Project key: the grant is sealed to the sandbox's own key.
#
# Key safety: the grant travels device -> WebSocket handler -> Redis pub/sub
# (transient, never SET) -> this process -> POST /v1/key. It is not logged, not
# put in spans and not stored. The cache record holds ids, timestamps and the
# daemon's access tokens only.
# Plan: docs/plans/hosted-project-sandbox (contracts.md sections 1-3).

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from fastapi import HTTPException

from backend.shared.providers import e2b_project_sandbox as sandbox_provider
from backend.shared.providers.e2b_project_sandbox import (
    ProjectSandboxClient,
    ProjectSandboxConnection,
    ProjectSandboxError,
)

logger = logging.getLogger(__name__)

SANDBOX_RECORD_PREFIX = "project_sandbox:"
KEY_REQUEST_PREFIX = "project_sandbox_key_request:"
KEY_GRANT_CHANNEL_PREFIX = "project_sandbox_key_grant:"
KEY_REQUEST_EVENT = "send_project_sandbox_key_request"
KEY_GRANT_WAIT_SECONDS = 30.0
KEY_REQUEST_TTL_SECONDS = 120
DEFAULT_MAX_LIFETIME_SECONDS = 4 * 3600
OPT_IN_MAX_LIFETIME_SECONDS = 24 * 3600
ORPHAN_GRACE_SECONDS = 300
SYNC_BATCH_SIZE = 20
SANDBOX_CREDITS_PER_SECOND = "0.05"  # code app: 3 credits per minute, billed per second
RECORD_FIELDS = (
    "sandbox_id", "job_id", "team_id", "created_at", "last_active_at", "max_lifetime_seconds",
    "sandbox_host", "bearer_token", "traffic_access_token",
)


class ProjectSandboxUnavailable(Exception):
    """The hosted sandbox cannot be used; ``reason`` is no_device, declined, template_missing or create_failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class ProjectSandboxHandle:
    sandbox_id: str
    job_id: str
    client: ProjectSandboxClient


def sandbox_record_key(user_id: str, chat_id: str, project_id: str) -> str:
    return f"{SANDBOX_RECORD_PREFIX}{user_id}:{chat_id}:{project_id}"


def key_grant_channel(request_id: str) -> str:
    return f"{KEY_GRANT_CHANNEL_PREFIX}{request_id}"


class ProjectSandboxService:
    def __init__(self, cache_service: Any, directus_service: Any, connection_manager: Any = None, *,
                 secrets_manager: Any = None, transport: Optional[httpx.AsyncBaseTransport] = None,
                 grant_wait_seconds: float = KEY_GRANT_WAIT_SECONDS, head_loader: Any = None) -> None:
        self.cache = cache_service
        self.directus = directus_service
        # The AI task runs in a Celery worker without live sockets; events reach devices over
        # the user_cache_events fan-out. The manager is only used when the caller has one.
        self.connection_manager = connection_manager
        self.secrets_manager = secrets_manager
        self.transport = transport
        self.grant_wait_seconds = grant_wait_seconds
        self._head_loader = head_loader

    # -- public API -------------------------------------------------------------------

    async def ensure_ready(self, *, user_id: str, chat_id: str, project_id: str, team_id: Optional[str],
                           max_lifetime_seconds: int = DEFAULT_MAX_LIFETIME_SECONDS) -> ProjectSandboxHandle:
        if not 0 < max_lifetime_seconds <= OPT_IN_MAX_LIFETIME_SECONDS:
            raise ValueError("max_lifetime_seconds must be between 1 and 86400")
        record_key = sandbox_record_key(user_id, chat_id, project_id)
        record = _clean_record(await self.cache.get(record_key))
        if record and time.time() - record["created_at"] >= record["max_lifetime_seconds"]:
            await self.kill(user_id=user_id, chat_id=chat_id, project_id=project_id, reason="max_lifetime")
            record = None
        if record:
            client = self._client(record)
            try:
                hello = await client.call("/v1/hello", timeout=10.0)
            except ProjectSandboxError:
                await self.kill(user_id=user_id, chat_id=chat_id, project_id=project_id, reason="unreachable")
                record = None
            else:
                if hello.get("has_key"):
                    await self.touch(user_id=user_id, chat_id=chat_id, project_id=project_id)
                    return ProjectSandboxHandle(record["sandbox_id"], record["job_id"], client)
        if record is None:
            record, hello = await self._create(user_id, chat_id, project_id, team_id, max_lifetime_seconds)
            client = self._client(record)
        try:
            await self._request_and_relay_key(user_id, chat_id, project_id, record, hello, client)
            await self._sync_in(user_id, project_id, team_id, client)
        except (ProjectSandboxUnavailable, ProjectSandboxError, HTTPException):
            await self.kill(user_id=user_id, chat_id=chat_id, project_id=project_id, reason="setup_failed")
            raise
        return ProjectSandboxHandle(record["sandbox_id"], record["job_id"], client)

    async def touch(self, *, user_id: str, chat_id: str, project_id: str) -> None:
        record_key = sandbox_record_key(user_id, chat_id, project_id)
        record = _clean_record(await self.cache.get(record_key))
        if not record:
            return
        try:
            sandbox = await sandbox_provider.connect_project_sandbox(
                record["sandbox_id"], secrets_manager=self.secrets_manager)
            await sandbox_provider.extend_idle(sandbox)
        except ProjectSandboxError:
            logger.warning("Project sandbox %s could not renew its idle timeout", record["sandbox_id"])
        record["last_active_at"] = time.time()
        await self._store(record_key, record)

    async def kill(self, *, user_id: str, chat_id: str, project_id: str, reason: str) -> None:
        record_key = sandbox_record_key(user_id, chat_id, project_id)
        record = _clean_record(await self.cache.get(record_key))
        await self.cache.delete(record_key)
        if not record:
            return
        await self.kill_record(user_id, record, reason)

    async def kill_record(self, user_id: str, record: dict, reason: str) -> None:
        """Kill the sandbox of ``record`` and bill its lifetime per second."""
        try:
            await sandbox_provider.kill_project_sandbox(record["sandbox_id"], secrets_manager=self.secrets_manager)
        except ProjectSandboxError as exc:
            logger.error("Project sandbox %s kill failed: %s", record["sandbox_id"], exc.code)
        except RuntimeError as exc:
            logger.error("Project sandbox %s kill failed: %s", record["sandbox_id"], type(exc).__name__)
        logger.info("Project sandbox %s killed (%s)", record["sandbox_id"], reason)
        await self._bill(user_id, record)

    # -- creation, key relay, sync ----------------------------------------------------

    async def _create(self, user_id, chat_id, project_id, team_id, max_lifetime_seconds):
        job_id = str(uuid.uuid4())
        try:
            connection, hello = await sandbox_provider.create_project_sandbox(
                project_id=project_id, job_id=job_id, chat_id=chat_id, team_id=team_id,
                secrets_manager=self.secrets_manager,
                transport=self.transport)
        except ProjectSandboxError as exc:
            reason = "template_missing" if exc.code == "template_missing" else "create_failed"
            raise ProjectSandboxUnavailable(reason) from exc
        now = time.time()
        record = {
            "sandbox_id": connection.sandbox_id, "job_id": job_id, "team_id": team_id, "created_at": now,
            "last_active_at": now, "max_lifetime_seconds": max_lifetime_seconds,
            "sandbox_host": connection.sandbox_host, "bearer_token": connection.bearer_token,
            "traffic_access_token": connection.traffic_access_token,
        }
        await self._store(sandbox_record_key(user_id, chat_id, project_id), record)
        return record, hello

    def _client(self, record: dict) -> ProjectSandboxClient:
        return sandbox_provider.client_for(ProjectSandboxConnection(
            record["sandbox_id"], record["sandbox_host"], record["traffic_access_token"],
            record["bearer_token"]), self.transport)

    async def _store(self, key: str, record: dict) -> None:
        ttl = int(record["max_lifetime_seconds"] + 600)
        await self.cache.set(key, {name: record.get(name) for name in RECORD_FIELDS}, ttl=ttl)

    async def _request_and_relay_key(self, user_id, chat_id, project_id, record, hello, client) -> None:
        request_id = str(uuid.uuid4())
        expires_at = int(record["created_at"] + record["max_lifetime_seconds"])
        redis = await self.cache.client
        if not redis:
            raise ProjectSandboxUnavailable("no_device")
        await self.cache.set(KEY_REQUEST_PREFIX + request_id, {
            "user_id": user_id, "job_id": record["job_id"], "sandbox_id": record["sandbox_id"],
            "chat_id": chat_id, "project_id": project_id}, ttl=KEY_REQUEST_TTL_SECONDS)
        pubsub = redis.pubsub()
        await pubsub.subscribe(key_grant_channel(request_id))  # before asking, so no answer is missed
        try:
            await redis.publish(f"user_cache_events:{user_id}", json.dumps({
                "event_type": KEY_REQUEST_EVENT,
                "payload": {
                    "request_id": request_id, "job_id": record["job_id"], "sandbox_id": record["sandbox_id"],
                    "project_id": project_id, "chat_id": chat_id,
                    "sandbox_public_key": hello["sandbox_public_key"], "expires_at": expires_at},
            }))
            answer = await self._wait_for_answer(pubsub)
        finally:
            await pubsub.unsubscribe(key_grant_channel(request_id))
            await pubsub.aclose()
            await self.cache.delete(KEY_REQUEST_PREFIX + request_id)
        if answer is None:
            raise ProjectSandboxUnavailable("no_device")
        if answer.get("kind") != "grant":
            raise ProjectSandboxUnavailable("declined")
        try:
            await client.call("/v1/key", {"sealed_grant": answer["sealed_grant"]})
        finally:
            answer.clear()

    async def _wait_for_answer(self, pubsub) -> Optional[dict]:
        deadline = time.monotonic() + self.grant_wait_seconds
        while time.monotonic() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if not message:
                continue
            data = message["data"]
            try:
                parsed = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
            except (ValueError, UnicodeDecodeError):
                continue
            if isinstance(parsed, dict) and parsed.get("kind") in ("grant", "decline"):
                if parsed["kind"] == "decline" and parsed.get("reason") in ("no_key", "invalid"):
                    # This device lacks the key or the chat's Project focus;
                    # another device of the user may still answer.
                    continue
                return parsed
        return None

    async def _sync_in(self, user_id, project_id, team_id, client) -> None:
        build_project_embed_head = self._head_loader
        if build_project_embed_head is None:
            from backend.core.api.app.routes.embeds_api import build_project_embed_head

        items = await self.directus.project.list_items(project_id, user_id, team_id=team_id)
        # Only the sandbox can read the encrypted item rows, so it names the file embeds to fetch.
        file_ids = (await client.call("/v1/file-ids", {"items": items})).get("embed_ids") or []
        heads: list[dict] = []
        unknown = 0
        for embed_id in file_ids:
            try:
                heads.append(await build_project_embed_head(
                    directus_service=self.directus, user_id=user_id, project_id=project_id,
                    embed_id=str(embed_id), team_id=team_id))
            except HTTPException as exc:
                logger.info("Sandbox sync-in skipped one file head (status %s)", exc.status_code)
        for start in range(0, len(heads), SYNC_BATCH_SIZE):
            answer = await client.call("/v1/sync-in", {"heads": heads[start:start + SYNC_BATCH_SIZE]},
                                       timeout=120.0)
            unknown += sum(1 for f in answer.get("failed") or []
                           if isinstance(f, dict) and f.get("reason") == "unknown_embed")
        if unknown:
            logger.info("Sandbox sync-in: %d heads were not known to the sandbox", unknown)
        await client.call("/v1/baseline", {}, timeout=120.0)

    async def _bill(self, user_id: str, record: dict) -> None:
        from backend.shared.python_utils.metered_author_billing import code_execution_credits, post_skill_charge

        seconds = max(0.0, min(time.time(), record["created_at"] + record["max_lifetime_seconds"] + 900)
                      - record["created_at"])
        credits = code_execution_credits(seconds, SANDBOX_CREDITS_PER_SECOND)
        if credits <= 0:
            return
        payload = {
            "user_id": user_id, "user_id_hash": hashlib.sha256(user_id.encode("utf-8")).hexdigest(),
            "credits": credits, "skill_id": "project_sandbox", "app_id": "code",
            "api_key_hash": None, "device_hash": None,
            "usage_details": {"sandbox_id": record["sandbox_id"], "duration_seconds": round(seconds, 3),
                              "credits_per_second": SANDBOX_CREDITS_PER_SECOND},
        }
        try:
            await post_skill_charge(payload, team_id=record.get("team_id"),
                                    event_id=f"project-sandbox:{record['sandbox_id']}")
        except httpx.HTTPError as exc:
            logger.error("Project sandbox %s billing failed: %s", record["sandbox_id"], type(exc).__name__)


def _clean_record(value: Any) -> Optional[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if not isinstance(value, dict) or not value.get("sandbox_id"):
        return None
    return {name: value.get(name) for name in RECORD_FIELDS}


async def reap_project_sandboxes(cache_service: Any, *, secrets_manager: Any = None,
                                 now: Optional[float] = None) -> dict:
    """Kill sandboxes past their hard maximum or without a cache record; drop records of dead sandboxes."""
    now = now if now is not None else time.time()
    running = await sandbox_provider.list_project_sandbox_ids(secrets_manager=secrets_manager)
    redis = await cache_service.client
    service = ProjectSandboxService(cache_service, None, None, secrets_manager=secrets_manager)
    known: set[str] = set()
    killed = orphaned = dropped = 0
    async for raw_key in redis.scan_iter(match=f"{SANDBOX_RECORD_PREFIX}*"):
        key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
        record = _clean_record(await cache_service.get(key))
        if not record:
            continue
        known.add(record["sandbox_id"])
        user_id = key[len(SANDBOX_RECORD_PREFIX):].split(":", 1)[0]
        if record["sandbox_id"] not in running:
            await cache_service.delete(key)
            dropped += 1
        elif now - record["created_at"] >= record["max_lifetime_seconds"]:
            await cache_service.delete(key)
            await service.kill_record(user_id, record, "reaper_max_lifetime")
            killed += 1
    for sandbox_id, started_at in running.items():
        if sandbox_id in known or now - started_at < ORPHAN_GRACE_SECONDS:
            continue  # a sandbox being created has no record yet
        await sandbox_provider.kill_project_sandbox(sandbox_id, secrets_manager=secrets_manager)
        orphaned += 1
    return {"killed_expired": killed, "killed_orphaned": orphaned, "dropped_records": dropped}

