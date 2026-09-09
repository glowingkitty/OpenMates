"""First-party Project Task sync over the existing remote-access socket.

One Redis subscription per API process fans committed hints into scoped reads.
Devices receive encrypted records; title/content decryption remains client-side.
Database cursors and snapshots survive missed hints, restarts and removals.
No API-key endpoint or model invocation is introduced by this service.
See docs/plans/codex-tasks-orchestration/codex-rebuild-architecture.md.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
import uuid
import weakref
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)
MAX_PROJECTS = 16
RECONCILE_SECONDS = 60
RECORDS_PER_FRAME = 20
TEAM_ROLES = {"owner", "admin", "member", "viewer"}


def scope_key(user_id: str, team_id: str | None) -> str:
    digest = hashlib.sha256((team_id or user_id).encode()).hexdigest()
    return f"{'team' if team_id else 'personal'}:{digest}"


@dataclass
class Subscription:
    user_id: str
    team_id: str | None
    source_id: str
    project_id: str
    cursor: str | None
    checked_at: float = 0
    dirty: bool = False
    delivery: asyncio.Task | None = None


class ProjectTaskSyncService:
    def __init__(self, directus: Any, cache: Any):
        self.directus = directus
        self.cache = cache
        self.subscriptions: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.scope_sockets: dict[str, weakref.WeakSet] = {}

    async def _authorize(self, subscription: Subscription) -> bool:
        if subscription.team_id:
            await self.directus.team.require_team_role(subscription.team_id, subscription.user_id, TEAM_ROLES)
        project = await self.directus.project.get_project(
            subscription.project_id, subscription.user_id, team_id=subscription.team_id)
        source = await self.directus.project.get_source(
            subscription.project_id, subscription.user_id, subscription.source_id, team_id=subscription.team_id)
        return bool(project and source and source.get("status") != "revoked")

    async def subscribe(self, websocket: Any, user_id: str, payload: dict) -> None:
        bindings = payload.get("bindings")
        team_id = payload.get("team_id")
        if team_id is not None and (not isinstance(team_id, str) or not team_id or len(team_id) > 128):
            raise ValueError("invalid_task_sync_team")
        if not isinstance(bindings, list) or not 0 < len(bindings) <= MAX_PROJECTS:
            raise ValueError("invalid_task_sync_bindings")
        if websocket in self.subscriptions:
            raise ValueError("task_sync_already_subscribed")
        selected = {}
        for binding in bindings:
            if not isinstance(binding, dict):
                raise ValueError("invalid_task_sync_binding")
            for field in ("project_id", "source_id"):
                if not isinstance(binding.get(field), str) or not 0 < len(binding[field]) <= 128:
                    raise ValueError("invalid_task_sync_binding")
            cursor = binding.get("cursor")
            if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 128):
                raise ValueError("invalid_task_sync_cursor")
            item = Subscription(user_id, team_id, binding["source_id"], binding["project_id"], cursor)
            if not await self._authorize(item):
                raise PermissionError("task_sync_project_unavailable")
            selected[item.project_id] = item
        self.subscriptions[websocket] = selected
        self.scope_sockets.setdefault(scope_key(user_id, team_id), weakref.WeakSet()).add(websocket)
        for item in selected.values():
            self._schedule(websocket, item)

    def disconnect(self, websocket: Any) -> None:
        for item in self.subscriptions.pop(websocket, {}).values():
            scope = scope_key(item.user_id, item.team_id)
            sockets = self.scope_sockets.get(scope)
            if sockets is not None:
                sockets.discard(websocket)
                if not sockets:
                    self.scope_sockets.pop(scope, None)
            if item.delivery and item.delivery is not asyncio.current_task():
                item.delivery.cancel()

    def reconcile(self, websocket: Any) -> None:
        for item in self.subscriptions.get(websocket, {}).values():
            if time.monotonic() - item.checked_at >= RECONCILE_SECONDS:
                self._schedule(websocket, item)

    def _schedule(self, websocket: Any, item: Subscription) -> None:
        item.dirty = True
        if item.delivery is None or item.delivery.done():
            item.delivery = asyncio.create_task(self._deliver(websocket, item))

    async def unlink_deleted_external_chat(self, user_id: str, lookup_hash: str, event_id: str, team_id: str | None = None) -> dict:
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("Task sync internal authentication unavailable")
        response = await self.directus._make_api_request(
            "POST", f"{self.directus.base_url.rstrip('/')}/project-task-sync/external-chat-deleted",
            headers={"X-Internal-Service-Token": token}, json={
                "scope": scope_key(user_id, team_id), "provider": "codex",
                "lookup_hash": lookup_hash, "event_id": event_id,
            })
        if response.status_code != 200:
            raise RuntimeError("Task chat deletion reconciliation temporarily unavailable")
        result = response.json().get("data")
        if not isinstance(result, dict) or result.get("event_id") != event_id:
            raise RuntimeError("Task deletion acknowledgement identity mismatch")
        return result

    async def _read(self, item: Subscription) -> dict:
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise RuntimeError("Task sync internal authentication unavailable")
        response = await self.directus._make_api_request(
            "POST", f"{self.directus.base_url.rstrip('/')}/project-task-sync",
            headers={"X-Internal-Service-Token": token}, json={
                "scope": scope_key(item.user_id, item.team_id),
                "project_hash": hashlib.sha256(item.project_id.encode()).hexdigest(),
                "cursor": item.cursor,
            })
        if response.status_code != 200:
            raise RuntimeError("Task sync snapshot temporarily unavailable")
        result = response.json().get("data")
        if not isinstance(result, dict) or not isinstance(result.get("tasks"), list) or not isinstance(result.get("cursor"), str):
            raise RuntimeError("Invalid Task sync snapshot")
        return result

    async def _deliver(self, websocket: Any, item: Subscription) -> None:
        try:
            while item.dirty:
                item.dirty = False
                if not await self._authorize(item):
                    raise PermissionError("task_sync_project_unavailable")
                result = await self._read(item)
                batch_id = str(uuid.uuid4())
                records = result["tasks"]
                count = max(1, (len(records) + RECORDS_PER_FRAME - 1) // RECORDS_PER_FRAME)
                for index in range(count):
                    await websocket.send_json({"type": "project_task_sync", "payload": {
                        "project_id": item.project_id, "batch_id": batch_id,
                        "part": index, "final": index == count - 1,
                        "reset": result["reset"], "cursor": result["cursor"],
                        "tasks": records[index * RECORDS_PER_FRAME:(index + 1) * RECORDS_PER_FRAME],
                        "removed_task_ids": result.get("removed_task_ids", []) if index == 0 else [],
                    }})
                item.cursor = result["cursor"]
                item.checked_at = time.monotonic()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The next heartbeat reconciles transient failures, without a model run.
            permanent = isinstance(exc, PermissionError) or type(exc).__name__ == "TeamPermissionError"
            logger.warning("Project Task sync delivery deferred: %s", type(exc).__name__)
            if permanent:
                self.subscriptions.get(websocket, {}).pop(item.project_id, None)
            try:
                await websocket.send_json({"type": "project_task_sync_error", "payload": {
                    "project_id": item.project_id,
                    "code": "access_revoked" if permanent else "sync_deferred",
                }})
            except Exception:
                self.disconnect(websocket)

    def notify_scope(self, scope: str) -> None:
        # Each commit touches only devices in its workspace, not every connected
        # user's sockets. One Redis listener is still shared by the API process.
        sockets = self.scope_sockets.get(scope)
        if sockets is None:
            return
        for websocket in list(sockets):
            for item in self.subscriptions.get(websocket, {}).values():
                self._schedule(websocket, item)
        if not sockets:
            self.scope_sockets.pop(scope, None)

    async def listen(self) -> None:
        while True:
            try:
                async for event in self.cache.subscribe_to_channel("project_task_sync:*"):
                    channel = event.get("channel", "")
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    scope = channel.removeprefix("project_task_sync:")
                    self.notify_scope(scope)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Project Task sync listener reconnecting: %s", type(exc).__name__)
                await asyncio.sleep(2)
