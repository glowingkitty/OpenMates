"""Incremental chat sync feed for first-party clients (architecture.sync@2).

Capability-gated (`chat_sync_feed_v1`): sockets and requests without it are
untouched. Each page comes from one internal chat-sync Directus call (a fixed
number of batched queries over the durable change log) and is hydrated here
with encrypted metadata only: no messages, embeds, embed keys or plaintext.
Removal entries (deleted, moved, revoked) carry only the hashed chat ID.
Committed-change hints arrive via Redis `chat_sync:<scope>` and are fanned out
to the authorized sockets registered for that scope as content-free
`chat_sync_hint` events; clients debounce and pull from their cursor.
Spec: specifications/architecture/sync/specification.yml.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
import weakref
from dataclasses import dataclass
from typing import Any

from backend.core.api.app.services.active_reminder_listing import build_active_reminder_items
from backend.core.api.app.services.direct_chat_access import is_direct_chat, project_direct_chat_metadata
from backend.core.api.app.services.directus.chat_key_wrapper_methods import select_sync_wrapper_window

logger = logging.getLogger(__name__)

CAPABILITY = "chat_sync_feed_v1"
HINT_CHANNEL_PREFIX = "chat_sync:"
DEFAULT_LIMIT = 100
MAX_LIMIT = 200
MAX_CURSOR_LENGTH = 160
TEAM_ROLES = {"owner", "admin", "member", "viewer"}
REMOVAL_KINDS = ("deleted", "revoked", "moved")
# Existing welcome-overview windows: the client classifies with its 24 h / 12 h
# rules; the server ships every pending reminder within the API's maximum
# 168 h lookahead so a cached set stays valid while time passes.
DUE_SOON_PENDING_LOOKAHEAD_HOURS = 168
DUE_SOON_FIRED_LOOKBACK_HOURS = 12
DUE_SOON_REMINDER_LIMIT = 100
HINT_DELAY_SECONDS = 0.1
WS_REQUEST_WINDOW_SECONDS = 10.0
WS_REQUEST_LIMIT = 30
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_HINT_SCOPE = re.compile(r"^(?:personal|team|user):[0-9a-f]{64}$")


class ChatSyncFeedError(Exception):
    """Typed feed failure mapped to a stable client code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def scope_keys(user_id: str, team_id: str | None) -> tuple[str, str]:
    """(account or Team scope, user lane) for an authorized caller."""
    scope = f"team:{_sha(team_id)}" if team_id else f"personal:{_sha(user_id)}"
    return scope, f"user:{_sha(user_id)}"


def socket_has_capability(websocket: Any) -> bool:
    query = getattr(websocket, "query_params", None) or {}
    raw = query.get("client_capabilities", "") if hasattr(query, "get") else ""
    return CAPABILITY in {item.strip() for item in str(raw).split(",") if item.strip()}


def parse_last_opened(value: Any) -> str | None:
    """`/chat/<uuid>` or `<uuid>` -> lower-case chat id; signup paths and `new` -> None."""
    if not isinstance(value, str) or not value:
        return None
    candidate = value.rsplit("/", 1)[-1]
    return candidate.lower() if _UUID.match(candidate) else None


def validate_request(payload: dict[str, Any]) -> tuple[str | None, str | None, int]:
    team_id = payload.get("team_id")
    if team_id is not None and (not isinstance(team_id, str) or not team_id or len(team_id) > 128):
        raise ChatSyncFeedError("invalid_team")
    cursor = payload.get("cursor")
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > MAX_CURSOR_LENGTH):
        raise ChatSyncFeedError("invalid_cursor")
    limit = payload.get("limit", DEFAULT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ChatSyncFeedError("invalid_limit")
    return team_id or None, cursor, limit


def _chat_builders():
    # Lazy: the phased sync module is large and imports this package's peers.
    from backend.core.api.app.routes.handlers.websocket_handlers.phased_sync_handler import (
        _apply_authoritative_draft_metadata,
        _build_chat_details_from_directus_metadata,
        _effective_metadata_v,
    )
    return _build_chat_details_from_directus_metadata, _apply_authoritative_draft_metadata, _effective_metadata_v


def _project_visible(row: dict[str, Any], user_id: str) -> dict[str, Any] | None:
    """Caller-safe chat row, or None when a direct chat no longer includes the caller.

    Team membership was verified for the whole request, so only participant
    projection remains per chat (no per-chat queries).
    """
    if not is_direct_chat(row):
        return row
    try:
        return dict(project_direct_chat_metadata(row, user_id))
    except (PermissionError, ValueError):
        return None


def _draft_payload(draft_row: dict[str, Any] | None) -> dict[str, Any]:
    if draft_row and draft_row.get("encrypted_content") and int(draft_row.get("version") or 0) > 0:
        return {"draft_v": int(draft_row["version"]), "encrypted_draft_md": draft_row["encrypted_content"],
                "encrypted_draft_preview": None}
    return {"draft_v": 0, "encrypted_draft_md": None, "encrypted_draft_preview": None}


def _wrapper_windows(wrappers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in wrappers:
        clean = {key: value for key, value in row.items() if key != "window_position"}
        grouped.setdefault(str(row.get("hashed_chat_id")), []).append(clean)
    return {chat_hash: select_sync_wrapper_window(rows) for chat_hash, rows in grouped.items()}


def hydrate_page(raw: dict[str, Any], user_id: str, team_id: str | None) -> dict[str, Any]:
    """Turn one extension page into the client feed page (pure, no IO)."""
    if raw.get("reset"):
        return {"reset": True, "has_more": False, "next_cursor": None, "changes": [], "overview": None}
    build_details, apply_draft, effective_metadata_v = _chat_builders()
    visible: dict[str, dict[str, Any]] = {}
    hidden: set[str] = set()
    for row in raw.get("chats") or []:
        chat_id = str(row.get("id"))
        projected = _project_visible(row, user_id)
        if projected is None:
            hidden.add(chat_id)
        else:
            visible[chat_id] = projected
    drafts = {str(row.get("chat_id")): row for row in raw.get("drafts") or []}
    windows = _wrapper_windows(raw.get("wrappers") or [])
    existing_elsewhere = set(raw.get("existing_chat_ids") or [])
    entries: dict[str, dict[str, Any]] = {}

    def visible_entry(chat_id: str, kinds: list[str]) -> dict[str, Any]:
        entry = entries.get(chat_id)
        if entry is None:
            row = visible[chat_id]
            details = build_details(row, chat_id)
            for field in ("hashed_team_id", "chat_visibility", "participant_user_hashes"):
                details[field] = row.get(field)
            apply_draft(details, None)
            draft = drafts.get(chat_id)
            if draft is not None:
                payload = _draft_payload(draft)
                details.update(payload)
            entry = {"chat_id": chat_id, "hashed_chat_id": _sha(chat_id), "kinds": [], "chat_details": details,
                     "versions": {"messages_v": int(row.get("messages_v") or 0), "title_v": int(row.get("title_v") or 0),
                                  "metadata_v": effective_metadata_v(details), "draft_v": details.get("draft_v", 0),
                                  "last_edited_overall_timestamp": row.get("last_edited_overall_timestamp")}}
            entries[chat_id] = entry
        entry["kinds"] = sorted(set(entry["kinds"]) | set(kinds))
        return entry

    for change in raw.get("changes") or []:
        chat_id = change.get("chat_id")
        kinds = list(change.get("kinds") or [])
        if change.get("lane") == "user":
            if "draft" not in kinds or not isinstance(chat_id, str) or not _UUID.match(chat_id):
                continue
            if chat_id in visible:
                entry = visible_entry(chat_id, ["draft"])
                entry["draft"] = _draft_payload(drafts.get(chat_id))
            elif not team_id and chat_id not in existing_elsewhere and chat_id not in hidden:
                # Draft-only personal chat; never discovered in a Team context.
                entries[chat_id] = {"chat_id": chat_id, "hashed_chat_id": _sha(chat_id), "kinds": ["draft"],
                                    "draft": _draft_payload(drafts.get(chat_id))}
            continue
        if isinstance(chat_id, str) and chat_id in visible:
            entry = visible_entry(chat_id, kinds)
            if set(kinds) & {"keys", "metadata"} and not is_direct_chat(visible[chat_id]):
                window = windows.get(_sha(chat_id))
                if window is not None:
                    entry["chat_key_wrappers"] = window["wrappers"]
                    entry["chat_key_wrapper_window"] = {k: window[k] for k in ("has_more_before", "start_cursor", "oversized_wrapper_id")}
            continue
        removal = [kind for kind in kinds if kind in REMOVAL_KINDS]
        if isinstance(chat_id, str) and chat_id in hidden:
            removal = sorted(set(removal) | {"revoked"})
        if removal:
            key = f"#{change.get('hashed_chat_id')}"
            entries[key] = {"hashed_chat_id": change.get("hashed_chat_id"), "kinds": removal}
        # A non-removal entry whose row is gone is superseded by a later
        # deleted/moved entry in this or a following page.

    overview: dict[str, Any] | None = None
    last_opened = raw.get("last_opened")
    if isinstance(last_opened, dict):
        opened = last_opened.get("chat_id")
        opened = opened if isinstance(opened, str) and opened in visible else None
        if opened:
            visible_entry(opened, ["last_opened"])
        overview = {"last_opened_chat_id": opened}
    return {"reset": False, "has_more": bool(raw.get("has_more")), "next_cursor": raw.get("next_cursor"),
            "changes": list(entries.values()), "overview": overview}


@dataclass
class _SocketContext:
    user_id: str
    team_id: str | None
    scopes: tuple[str, str]
    revision: int = 0
    hint_task: asyncio.Task | None = None


class ChatSyncFeedService:
    def __init__(self, directus: Any, cache: Any, encryption_service: Any):
        self.directus = directus
        self.cache = cache
        self.encryption_service = encryption_service
        self.contexts: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.scope_sockets: dict[str, weakref.WeakSet] = {}
        self.request_times: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self.ws_requests: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()

    async def _call(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = os.getenv("INTERNAL_API_SHARED_TOKEN")
        if not token:
            raise ChatSyncFeedError("sync_unavailable")
        response = await self.directus._make_api_request(
            "POST", f"{self.directus.base_url.rstrip('/')}/chat-sync/{path}",
            headers={"X-Internal-Service-Token": token}, json=body,
        )
        if response.status_code != 200:
            raise ChatSyncFeedError("sync_deferred")
        data = response.json().get("data")
        if not isinstance(data, dict):
            raise ChatSyncFeedError("sync_deferred")
        return data

    async def authorize(self, user_id: str, team_id: str | None) -> None:
        if team_id:
            try:
                await self.directus.team.require_team_role(team_id, user_id, TEAM_ROLES)
            except PermissionError as exc:
                raise ChatSyncFeedError("team_access_revoked") from exc
            except Exception as exc:
                if type(exc).__name__ == "TeamPermissionError":
                    raise ChatSyncFeedError("team_access_revoked") from exc
                raise

    async def cold_start_cursor(self, user_id: str, team_id: str | None) -> str:
        """Clock read for a cold start; call it before any snapshot read."""
        scope, user_scope = scope_keys(user_id, team_id)
        data = await self._call("clock", {"scope": scope, "user_scope": user_scope})
        cursor = data.get("cursor")
        if not isinstance(cursor, str):
            raise ChatSyncFeedError("sync_deferred")
        return cursor

    async def read_page(self, user_id: str, team_id: str | None, cursor: str | None, limit: int) -> dict[str, Any]:
        await self.authorize(user_id, team_id)
        if cursor is None:
            return hydrate_page({"reset": True}, user_id, team_id)
        scope, user_scope = scope_keys(user_id, team_id)
        raw = await self._call("changes", {"scope": scope, "user_scope": user_scope, "cursor": cursor, "limit": limit})
        page = hydrate_page(raw, user_id, team_id)
        if raw.get("due_soon_changed") and not team_id:
            due_soon = await self.due_soon_set(user_id, raw.get("saved_items") or [])
            page["overview"] = {**(page["overview"] or {}), "due_soon": due_soon}
        return page

    async def due_soon_set(self, user_id: str, saved_items: list[dict[str, Any]]) -> dict[str, Any]:
        hashed_user = _sha(user_id)
        rows: list[dict[str, Any]] = []
        for status in ("pending", "fired"):
            rows.extend(await self.directus.reminder.get_user_reminders(
                hashed_user_id=hashed_user, status_filter=status, limit=1000,
            ))
        reminders = await build_active_reminder_items(
            rows, self.encryption_service, include_recent_fired=True,
            upcoming_hours=DUE_SOON_PENDING_LOOKAHEAD_HOURS, recent_hours=DUE_SOON_FIRED_LOOKBACK_HOURS,
        )
        # Fired reminders older than the lookback are dropped by the helper;
        # keep the soonest bounded set.
        return {"reminders": reminders[:DUE_SOON_REMINDER_LIMIT], "saved_items": saved_items,
                "generated_at": int(time.time())}

    async def build_overview(self, user_id: str, team_id: str | None, last_opened: Any) -> dict[str, Any]:
        """Cold-start overview: last opened chat (even outside the recent window) and due-soon set."""
        scope, user_scope = scope_keys(user_id, team_id)
        opened = parse_last_opened(last_opened)
        data = await self._call("overview", {"scope": scope, "user_scope": user_scope, "last_opened_chat_id": opened})
        chat_details = None
        row = data.get("chat")
        if isinstance(row, dict):
            projected = _project_visible(row, user_id)
            if projected is not None:
                build_details, apply_draft, _ = _chat_builders()
                chat_details = build_details(projected, str(row.get("id")))
                apply_draft(chat_details, None)
        due_soon = None if team_id else await self.due_soon_set(user_id, data.get("saved_items") or [])
        return {"last_opened_chat_id": opened if chat_details else None, "chat_details": chat_details,
                "due_soon": due_soon}

    # --- WebSocket transport -------------------------------------------------

    def allow_request(self, websocket: Any) -> bool:
        now = time.monotonic()
        recent = [stamp for stamp in self.request_times.get(websocket, []) if now - stamp < WS_REQUEST_WINDOW_SECONDS]
        if len(recent) >= WS_REQUEST_LIMIT:
            self.request_times[websocket] = recent
            return False
        recent.append(now)
        self.request_times[websocket] = recent
        return True

    def schedule_ws_request(self, websocket: Any, user_id: str, payload: dict[str, Any]) -> asyncio.Task:
        """Serve a request off the receive loop, one at a time per socket, in order."""
        previous = self.ws_requests.get(websocket)

        async def run() -> None:
            if previous is not None and not previous.done():
                await asyncio.wait({previous})
            await self.handle_ws_request(websocket, user_id, payload)

        task = asyncio.create_task(run())
        self.ws_requests[websocket] = task
        return task

    async def handle_ws_request(self, websocket: Any, user_id: str, payload: dict[str, Any]) -> None:
        context_epoch = payload.get("context_epoch")
        team_id = payload.get("team_id") if isinstance(payload.get("team_id"), str) else None
        try:
            if not socket_has_capability(websocket):
                raise ChatSyncFeedError("capability_required")
            if not self.allow_request(websocket):
                raise ChatSyncFeedError("rate_limited")
            team_id, cursor, limit = validate_request(payload)
            page = await self.read_page(user_id, team_id, cursor, limit)
        except ChatSyncFeedError as exc:
            if exc.code == "team_access_revoked":
                self.unregister(websocket)
            await self._send_error(websocket, exc.code, team_id, context_epoch)
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # Transport boundary: log and return a typed retryable error.
            logger.warning("Chat sync page deferred: %s", type(exc).__name__)
            await self._send_error(websocket, "sync_deferred", team_id, context_epoch)
            return
        self.register(websocket, user_id, team_id)
        await websocket.send_json({"type": "chat_sync_delta", "payload": {
            **page, "team_id": team_id, "context_epoch": context_epoch}})

    async def _send_error(self, websocket: Any, code: str, team_id: str | None, context_epoch: Any) -> None:
        await websocket.send_json({"type": "chat_sync_delta_error", "payload": {
            "code": code, "team_id": team_id, "context_epoch": context_epoch}})

    def register(self, websocket: Any, user_id: str, team_id: str | None) -> None:
        if not socket_has_capability(websocket):
            return
        scopes = scope_keys(user_id, team_id)
        current = self.contexts.get(websocket)
        if current is not None and current.scopes == scopes:
            return
        self.unregister(websocket)
        self.contexts[websocket] = _SocketContext(user_id, team_id, scopes)
        for scope in scopes:
            self.scope_sockets.setdefault(scope, weakref.WeakSet()).add(websocket)

    def unregister(self, websocket: Any) -> None:
        context = self.contexts.pop(websocket, None)
        if context is None:
            return
        if context.hint_task is not None and context.hint_task is not asyncio.current_task():
            context.hint_task.cancel()
        for scope in context.scopes:
            sockets = self.scope_sockets.get(scope)
            if sockets is not None:
                sockets.discard(websocket)
                if not sockets:
                    self.scope_sockets.pop(scope, None)

    def disconnect(self, websocket: Any) -> None:
        self.unregister(websocket)
        self.request_times.pop(websocket, None)
        pending = self.ws_requests.pop(websocket, None)
        if pending is not None and pending is not asyncio.current_task():
            pending.cancel()

    def notify(self, scope: str, revision: int) -> None:
        for websocket in list(self.scope_sockets.get(scope, ())):
            context = self.contexts.get(websocket)
            if context is None:
                continue
            context.revision = max(context.revision, revision)
            if context.hint_task is None or context.hint_task.done():
                context.hint_task = asyncio.create_task(self._send_hint(websocket, context))

    async def _send_hint(self, websocket: Any, context: _SocketContext) -> None:
        await asyncio.sleep(HINT_DELAY_SECONDS)  # coalesce bursts per socket
        try:
            await websocket.send_json({"type": "chat_sync_hint", "payload": {
                "team_id": context.team_id, "revision": context.revision}})
        except (RuntimeError, ConnectionError) as exc:
            logger.debug("Chat sync hint not delivered: %s", type(exc).__name__)
            self.disconnect(websocket)

    async def publish_hints(self, hints: list[dict[str, Any]]) -> None:
        for hint in hints:
            if not await self.cache.publish_event(f"{HINT_CHANNEL_PREFIX}{hint['scope']}", {"revision": hint["revision"]}):
                raise ChatSyncFeedError("hint_deferred")

    async def listen(self) -> None:
        while True:
            try:
                async for event in self.cache.subscribe_to_channel(f"{HINT_CHANNEL_PREFIX}*"):
                    channel = event.get("channel", "")
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    scope = channel.removeprefix(HINT_CHANNEL_PREFIX)
                    data = event.get("data")
                    revision = data.get("revision") if isinstance(data, dict) else None
                    if _HINT_SCOPE.match(scope) and isinstance(revision, int):
                        self.notify(scope, revision)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # Redis transport: reconnect; durable cursors cover missed hints.
                logger.warning("Chat sync hint listener reconnecting: %s", type(exc).__name__)
                await asyncio.sleep(2)
