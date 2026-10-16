"""First-party voice tool transport: only sealed private data crosses the queue.

This module intentionally imports no AI model SDK or text processor at import
time. The authenticated API owns call authority; the AI worker owns routing and
execution. A function response resumes Gemini Live, never the ordinary ask task.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import time
from typing import Any, Awaitable, Callable

TASK_NAME = "apps.ai.tasks.voice_call_request"
TRANSPORT_TTL = 300
REQUEST_TIMEOUT = 240
MAX_REQUEST_CHARS = 8_000
MAX_CONTEXT_CHARS = 64_000
MAX_RESULT_CHARS = 128_000
KEY_PREFIX = "voice:broker:v1:"


def transport_key(operation_id: str, suffix: str) -> str:
    """Validate opaque identities before constructing internal cache keys."""
    if not isinstance(operation_id, str) or len(operation_id) != 32 or any(
        char not in "0123456789abcdef" for char in operation_id
    ) or suffix not in {"result", "cancel", "decision"}:
        raise ValueError("Invalid voice broker operation")
    return f"{KEY_PREFIX}{operation_id}:{suffix}"


def bounded_context(context: Any) -> dict[str, Any]:
    """Admit conversation data without accepting model/tool authority fields."""
    if not isinstance(context, dict):
        raise ValueError("Voice context must be an object")
    admitted = {key: context[key] for key in (
        "summary", "messages", "active_focus", "app_settings_memories_metadata",
        "project_focus_candidates", "client_capabilities", "project_focus_documents",
    ) if key in context}
    if len(json.dumps(admitted, ensure_ascii=False, allow_nan=False)) > MAX_CONTEXT_CHARS:
        raise ValueError("Voice context exceeds the admitted bound")
    messages = admitted.get("messages", [])
    if not isinstance(messages, list) or len(messages) > 64:
        raise ValueError("Invalid voice history")
    if any(not isinstance(row, dict) or row.get("role") not in {"user", "assistant"}
           or not isinstance(row.get("content", row.get("text")), str) for row in messages):
        raise ValueError("Invalid voice history message")
    admitted["messages"] = [{"role": row["role"], "content": row.get("content", row.get("text"))} for row in messages]
    return admitted


async def user_vault_key(cache: Any, directus: Any, user_id: str) -> str:
    """Use the durable profile on a cache miss, as ordinary AI requests do."""
    key = await cache.get_user_vault_key_id(user_id)
    if not key:
        profile = await directus.get_user_profile(user_id)
        key = profile[1].get("vault_key_id") if profile and profile[0] else None
    if not key:
        raise PermissionError("Voice broker encryption unavailable")
    return key


async def require_binding(cache: Any, binding: dict[str, Any]) -> None:
    """A sealed transport reference grants no authority over a live call."""
    call_id = binding.get("call_id", "")
    if len(call_id) != 32 or any(char not in "0123456789abcdef" for char in call_id):
        raise PermissionError("Invalid voice call binding")
    client = await cache.client
    values = await client.hmget(f"voice:call:{call_id}", "user", "session", "chat", "state")
    values = [value.decode() if isinstance(value, bytes) else value for value in values]
    if values != [binding.get("user_id"), binding.get("session_id"), binding.get("chat_id"), "active"]:
        raise PermissionError("Voice call is no longer active")
    if binding.get("operation") != "prepare_context":
        from backend.shared.python_utils.voice_call_registry import require_active_call
        await require_active_call(cache, user_id=binding["user_id"], session_id=binding["session_id"],
            chat_id=binding["chat_id"], call_id=call_id, message_id=binding["user_message_id"], role="user")


class _MemoryManager:
    """Adapt existing encryption helper error delivery to the call transport."""
    def __init__(self, emit: Callable[[dict], Awaitable[None]]) -> None:
        self.emit = emit

    async def send_personal_message(self, message: dict, *_: Any) -> None:
        await self.emit(message)


class VoiceCallBroker:
    """Coordinate sealed worker operations and in-memory permission decisions."""
    def __init__(self, websocket: Any, binding: dict[str, str], emit_event: Any = None) -> None:
        self.websocket = websocket
        self.binding = binding
        self.cache = websocket.app.state.cache_service
        self.directus = websocket.app.state.directus_service
        self.encryption = websocket.app.state.encryption_service
        self.emit_event = emit_event or websocket.send_json
        self.operations: set[str] = set()
        self.compression_operations: set[str] = set()
        self.pending: dict[str, dict[str, Any]] = {}
        self.focus_decisions: set[str] = set()
        self.closed = False

    async def _cancel_operation(self, operation_id: str) -> None:
        client = await self.cache.client
        await client.set(transport_key(operation_id, "cancel"), "1", ex=TRANSPORT_TTL)
        for index in range(8):
            await client.set(f"cancelled_skill:{operation_id}:{index}", "1", ex=3600)

    async def _dispatch(self, data: dict[str, Any]) -> dict[str, Any]:
        if self.closed:
            raise asyncio.CancelledError
        envelope = {**self.binding, **data, "expires_at": time.time() + TRANSPORT_TTL}
        await require_binding(self.cache, envelope)
        vault_key = await user_vault_key(self.cache, self.directus, self.binding["user_id"])
        operation_id = secrets.token_hex(16)
        envelope["operation_id"] = operation_id
        ciphertext, _ = await self.encryption.encrypt_with_user_key(json.dumps(envelope), vault_key)
        if not ciphertext:
            raise RuntimeError("Voice request could not be sealed")
        from backend.core.api.app.tasks.celery_config import app
        self.operations.add(operation_id)
        received = False
        if data.get("operation") == "compress_context":
            self.compression_operations.add(operation_id)
        try:
            app.send_task(TASK_NAME, kwargs={"operation_id": operation_id,
                "user_id": self.binding["user_id"], "ciphertext": ciphertext},
                queue="app_ai", task_id=operation_id, expires=TRANSPORT_TTL)
            client = await self.cache.client
            raw = await client.blpop(transport_key(operation_id, "result"), timeout=REQUEST_TIMEOUT)
            if not raw:
                raise TimeoutError("Voice request timed out")
            await require_binding(self.cache, envelope)
            sealed = raw[1].decode() if isinstance(raw[1], bytes) else raw[1]
            opened = json.loads(await self.encryption.decrypt_with_user_key(sealed, vault_key))
            if opened.get("operation_id") != operation_id or opened.get("call_id") != self.binding["call_id"]:
                raise PermissionError("Voice result binding mismatch")
            if opened.get("error"):
                raise RuntimeError(opened["error"])
            received = True
            return opened["result"]
        finally:
            self.operations.discard(operation_id)
            self.compression_operations.discard(operation_id)
            client = await self.cache.client
            if not received:
                await self._cancel_operation(operation_id)

    async def prepare_context(self, context: dict[str, Any]) -> dict[str, Any]:
        return await self._dispatch({"operation": "prepare_context", "context": bounded_context(context)})

    async def compress_context(self, context: dict[str, Any], *, user_message_id: str | None = None) -> dict[str, Any]:
        """Compress only completed call transcripts with issued source identities."""
        messages = context.get("messages")
        if not isinstance(messages, list) or not messages or len(messages) > 128:
            raise ValueError("Invalid compression transcript")
        if len(json.dumps(context, ensure_ascii=False)) > 128_000:
            raise ValueError("Compression transcript exceeds bound")
        for row in messages:
            if not isinstance(row, dict) or row.get("role") not in {"user", "assistant"} or not isinstance(row.get("message_id"), str) or not isinstance(row.get("text", row.get("content")), str):
                raise ValueError("Compression requires completed issued transcript identities")
        return await self._dispatch({"operation": "compress_context", "context": context,
            "user_message_id": user_message_id or next(row["message_id"] for row in reversed(messages) if row["role"] == "user")})

    async def process_request(self, function_call_id: str, turn_generation: int, request: str,
                              context: dict[str, Any], *, user_message_id: str,
                              assistant_message_id: str | None = None,
                              assistant_created_at: int | None = None) -> dict[str, Any]:
        cancel_id = secrets.token_hex(16)
        self.operations.add(cancel_id)
        completed = False
        try:
            result = await self._process_request(function_call_id, turn_generation, request, context,
                user_message_id=user_message_id, assistant_message_id=assistant_message_id,
                assistant_created_at=assistant_created_at, cancel_id=cancel_id)
            completed = True
            return result
        finally:
            if not completed:
                await self._cancel_operation(cancel_id)
            self.operations.discard(cancel_id)

    async def _process_request(self, function_call_id: str, turn_generation: int, request: str,
                              context: dict[str, Any], *, user_message_id: str,
                              assistant_message_id: str | None, assistant_created_at: int | None,
                              cancel_id: str) -> dict[str, Any]:
        if not isinstance(request, str) or not 1 <= len(request.strip()) <= MAX_REQUEST_CHARS:
            raise ValueError("Invalid voice request")
        data = {"operation": "process_request", "function_call_id": function_call_id,
                "turn_generation": turn_generation, "request": request.strip(),
                "context": bounded_context(context), "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id or user_message_id}
        data["request_cancel_id"] = cancel_id
        data["assistant_created_at"] = assistant_created_at
        result = await self._dispatch(data)
        project_request = result.get("project_request")
        if project_request:
            decision_id = project_request["decision_id"]
            self.focus_decisions.add(decision_id)
            try:
                for event in result.get("events", []):
                    await self.emit_event({**event, "function_call_id": function_call_id})
                await self.emit_event({"type": "voice_focus", "function_call_id": function_call_id,
                    "payload": {"event": "focus_mode_pending", **project_request["pending_event"]}})
                client = await self.cache.client
                decision = await client.blpop(transport_key(decision_id, "decision"), timeout=REQUEST_TIMEOUT)
                if not decision:
                    raise TimeoutError("Project access decision unavailable")
                data["project_decision_made"] = True
                sealed_decision = decision[1].decode() if isinstance(decision[1], bytes) else decision[1]
                vault_key = await user_vault_key(self.cache, self.directus, self.binding["user_id"])
                opened = json.loads(await self.encryption.decrypt_with_user_key(sealed_decision, vault_key))
                if opened.get("decision_id") != decision_id or opened.get("call_id") != self.binding["call_id"]:
                    raise PermissionError("Project voice decision binding mismatch")
                data["project_accepted"] = opened["accepted"]
                specialist = opened.get("specialist")
                if specialist:
                    data["context"]["active_focus"] = {"id": specialist["focus_id"]}
                    data["context"]["project_focus_documents"] = [{"item_id": specialist["item_id"],
                        "revision": specialist["item_revision"], "document": specialist["instruction"]}]
                result = await self._dispatch(data)
            finally:
                self.focus_decisions.discard(decision_id)
        permission = result.get("memory_request")
        if permission:
            request_id = permission["request_id"]
            future = asyncio.get_running_loop().create_future()
            self.pending[request_id] = {"future": future, "function_call_id": function_call_id,
                                       "requested_keys": [name.replace("-", ":", 1) for name in permission["requested_keys"]]}
            try:
                await self.emit_event({"type": "voice_memory", "call_id": self.binding["call_id"],
                    "function_call_id": function_call_id, "payload": permission})
                approved = await asyncio.wait_for(future, timeout=REQUEST_TIMEOUT)
                data["memory_decision_made"] = True
                data["memory_approved"] = approved
                # The already validated Jev route is sealed again, avoiding another
                # decision about declined data or a second permission dialog.
                data["selection"] = result["selection"]
                result = await self._dispatch(data)
            finally:
                self.pending.pop(request_id, None)
        focus_request = result.get("focus_request")
        if focus_request:
            self.focus_decisions.add(focus_request["decision_id"])
            await self.emit_event({"type": "voice_embed", "call_id": self.binding["call_id"],
                "function_call_id": function_call_id, "payload": focus_request["artifact"]})
            await self.emit_event({"type": "voice_focus", "function_call_id": function_call_id,
                "payload": {"event": "focus_mode_pending", "focus_id": focus_request["focus_id"],
                    "embed_id": focus_request["embed_id"], "expires_at": time.time() + 4,
                    "activation_policy": "delayed"}})
            client = await self.cache.client
            decision = await client.blpop(transport_key(focus_request["decision_id"], "decision"), timeout=20)
            if not decision:
                raise TimeoutError("Focus activation decision unavailable")
            data["selection"] = result["selection"]
            data["focus_decision_made"] = True
            data["focus_accepted"] = decision[1] in ("accepted", b"accepted")
            result = await self._dispatch(data)
            self.focus_decisions.discard(focus_request["decision_id"])
        return result

    async def respond_memory(self, request_id: str, approved: bool,
                             settings_memories: list[dict], function_call_id: str | None = None) -> None:
        pending = self.pending.get(request_id)
        if not pending or pending["future"].done() or type(approved) is not bool:
            raise PermissionError("Voice memory request is no longer pending")
        if function_call_id is not None and function_call_id != pending["function_call_id"]:
            raise PermissionError("Voice memory request binding mismatch")
        if not isinstance(settings_memories, list) or len(settings_memories) > 500 or len(json.dumps(settings_memories)) > MAX_CONTEXT_CHARS:
            raise ValueError("Invalid voice memory response")
        keys = [f"{row.get('app_id')}:{row.get('item_key')}" for row in settings_memories if isinstance(row, dict)]
        if len(keys) != len(settings_memories) or any(
            key not in pending["requested_keys"] for key in keys
        ) or (not approved and settings_memories):
            raise PermissionError("Memory response contains unrequested categories")
        await require_binding(self.cache, {**self.binding, "operation": "prepare_context"})
        if approved and settings_memories:
            from backend.core.api.app.routes.handlers.websocket_handlers.app_settings_memories_confirmed_handler import _cache_app_settings_memories
            from backend.shared.python_utils.private_inference_logging import private_inference_logging
            with private_inference_logging():
                count = await _cache_app_settings_memories(self.cache, self.directus, self.encryption,
                    _MemoryManager(self.emit_event), self.binding["user_id"], self.binding["chat_id"],
                    "", settings_memories)
            if count != len(set(keys)):
                raise RuntimeError("Approved voice memories could not be encrypted")
        pending["future"].set_result(approved)

    async def invalidate(self) -> None:
        operations = (self.operations if self.closed else self.operations - self.compression_operations) | self.focus_decisions
        for operation_id in tuple(operations):
            await self._cancel_operation(operation_id)
        for pending in self.pending.values():
            pending["future"].cancel()

    async def close(self) -> None:
        self.closed = True
        await self.invalidate()


async def create_voice_call_broker(websocket: Any, *, user_id: str, user_hash: str,
                                   chat_id: str, call_id: str, session_id: str,
                                   emit_event: Any = None) -> VoiceCallBroker:
    """Build an authenticated personal-chat broker without loading model SDKs."""
    broker = VoiceCallBroker(websocket, {"user_id": user_id, "user_hash": user_hash,
        "chat_id": chat_id, "call_id": call_id, "session_id": session_id}, emit_event)
    await require_binding(broker.cache, {**broker.binding, "operation": "prepare_context"})
    return broker
