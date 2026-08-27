"""Account Import V1 backend parsing and control-plane helpers.

This module owns provider export normalization, import preview limits, dedupe
warnings, transient scan orchestration, and completion accounting. It must never
persist plaintext private chat/message/embed content; clients persist imported
content only after local encryption through normal chat paths.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import asyncio
import math
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol

import yaml


FREE_IMPORT_CHATS_PER_30_DAYS = 3
FREE_IMPORT_CHAT_TOKEN_CAP = 100_000
FREE_IMPORT_RESERVATION_MINUTES = 30
PAID_IMPORT_BATCH_LIMIT = 30
PAID_IMPORT_DEFAULT_SELECTION = 20
DEFAULT_MAX_IMPORT_BATCH_MESSAGES = 1_000
SUPPORTED_OPENMATES_DOMAINS = {"chats", "embeds", "referenced_uploads", "uploads"}


class ImportParseError(ValueError):
    """Raised when an import source cannot be parsed safely."""


class ImportCreditError(ValueError):
    """Raised when an import would violate strict no-debt credit rules."""


class ImportScanError(RuntimeError):
    """Raised when selected plaintext cannot be scanned safely."""


class ImportSequenceError(ValueError):
    """Raised when a resumable batch cursor is invalid."""


class ImportCompressionError(RuntimeError):
    """Raised when compression cannot prove its input was sanitized."""


class ImportPersistenceError(RuntimeError):
    """Raised when encrypted persistence is attempted before processing gates."""


Scanner = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]
Compressor = Callable[..., Awaitable[Any] | Any]


class ImportBilling(Protocol):
    """Strict no-debt reservation and idempotent settlement boundary."""

    async def reserve(self, *, user_id: str, import_id: str, estimated_credits: int) -> dict[str, int]: ...

    async def settle(
        self, *, user_id: str, import_id: str, reserved_credits: int, measured_credits: int
    ) -> dict[str, int]: ...


class ImportJobStore(Protocol):
    """Metadata-only durable state required for resumable processing."""

    async def get(self, *, user_id: str, import_id: str) -> dict[str, Any] | None: ...

    async def save(self, *, user_id: str, import_id: str, metadata: dict[str, Any]) -> None: ...

    async def list_user(self, *, user_id: str) -> list[dict[str, Any]]: ...


class ImportLock(Protocol):
    """Distributed serialization boundary for import state and billing writes."""

    def hold(self, *, user_id: str, import_id: str) -> Any: ...


class InMemoryImportJobStore:
    """Test-only metadata store implementing the production repository contract."""

    def __init__(self) -> None:
        self.records: dict[tuple[str, str], dict[str, Any]] = {}

    async def get(self, *, user_id: str, import_id: str) -> dict[str, Any] | None:
        record = self.records.get((user_id, import_id))
        return dict(record) if record is not None else None

    async def save(self, *, user_id: str, import_id: str, metadata: dict[str, Any]) -> None:
        record = dict(metadata)
        record.setdefault("created_at", datetime.now(UTC).isoformat())
        self.records[(user_id, import_id)] = record

    async def list_user(self, *, user_id: str) -> list[dict[str, Any]]:
        return [dict(record) for (owner, _), record in self.records.items() if owner == user_id]


class InMemoryImportLock:
    """Process-local lock for deterministic unit tests."""

    def __init__(self) -> None:
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @asynccontextmanager
    async def hold(self, *, user_id: str, import_id: str) -> AsyncIterator[None]:
        lock = self._locks.setdefault((user_id, import_id), asyncio.Lock())
        async with lock:
            yield


class RedisImportLock:
    """Fail-closed Redis SET-NX lock used by production import operations."""

    LOCK_SECONDS = 120

    def __init__(self, cache_service: Any) -> None:
        self.cache_service = cache_service

    @asynccontextmanager
    async def hold(self, *, user_id: str, import_id: str) -> AsyncIterator[None]:
        client = await self.cache_service.client
        if not client:
            raise RuntimeError("Account import lock backend unavailable")
        token = str(uuid.uuid4())
        key = f"account-import:lock:{hashlib.sha256(user_id.encode()).hexdigest()}:{import_id}"
        if not await client.set(key, token, nx=True, ex=self.LOCK_SECONDS):
            raise ImportSequenceError("Account import operation already in progress")
        stop_renewal = asyncio.Event()
        lock_lost = False

        async def renew() -> None:
            nonlocal lock_lost
            while not stop_renewal.is_set():
                try:
                    await asyncio.wait_for(stop_renewal.wait(), timeout=self.LOCK_SECONDS / 3)
                    return
                except TimeoutError:
                    renewed = await client.eval(
                        "if redis.call('get', KEYS[1]) == ARGV[1] then "
                        "return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
                        1,
                        key,
                        token,
                        self.LOCK_SECONDS,
                    )
                    if not renewed:
                        lock_lost = True
                        return
        renewal_task = asyncio.create_task(renew())
        operation_error: BaseException | None = None
        operation_traceback: Any = None
        try:
            yield
        except BaseException as exc:
            operation_error = exc
            operation_traceback = exc.__traceback__
        finally:
            stop_renewal.set()
            renewal_error: BaseException | None = None
            cleanup_error: BaseException | None = None
            try:
                await renewal_task
            except BaseException as exc:
                renewal_error = exc
            try:
                await client.eval(
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end",
                    1,
                    key,
                    token,
                )
            except BaseException as exc:
                cleanup_error = exc
        if operation_error is not None:
            raise operation_error.with_traceback(operation_traceback)
        if lock_lost:
            raise RuntimeError("Account import distributed lock was lost") from cleanup_error or renewal_error
        if renewal_error is not None:
            raise RuntimeError("Account import distributed lock renewal failed") from renewal_error
        if cleanup_error is not None:
            raise RuntimeError("Account import distributed lock cleanup failed") from cleanup_error


class BillingServiceImportBilling:
    """Strict reservation adapter over the shipped charge/refund billing service."""

    APP_ID = "account_import"
    SKILL_ID = "process"

    def __init__(self, billing_service: Any) -> None:
        self.billing_service = billing_service

    async def reserve(self, *, user_id: str, import_id: str, estimated_credits: int) -> dict[str, int]:
        user = await self.billing_service.cache_service.get_user_by_id(user_id)
        if user is None:
            profile_success, user_profile, _ = await self.billing_service.directus_service.get_user_profile(user_id)
            if not profile_success or not user_profile:
                raise ImportCreditError("Account import billing profile unavailable")
            await self.billing_service.cache_service.set_user(user_profile, user_id=user_id)
            user = user_profile
        balance = int((user or {}).get("credits") or 0)
        if balance < estimated_credits:
            raise ImportCreditError("Insufficient credits for import without negative balance")
        user_hash = hashlib.sha256(user_id.encode()).hexdigest()
        await self.billing_service.charge_user_credits(
            user_id=user_id,
            credits_to_deduct=estimated_credits,
            user_id_hash=user_hash,
            app_id=self.APP_ID,
            skill_id=self.SKILL_ID,
            idempotency_key=f"account-import:{hashlib.sha256(import_id.encode()).hexdigest()}:reserve",
            usage_details={"import_id_hash": hashlib.sha256(import_id.encode()).hexdigest()},
        )
        updated_user = await self.billing_service.cache_service.get_user_by_id(user_id)
        if int((updated_user or {}).get("credits") or 0) < 0:
            await self.billing_service.refund_user_credits(
                user_id=user_id,
                credits_to_refund=estimated_credits,
                user_id_hash=user_hash,
                app_id=self.APP_ID,
                skill_id=self.SKILL_ID,
                idempotency_key=f"account-import:{hashlib.sha256(import_id.encode()).hexdigest()}:reserve-refund",
                reason="Account import reservation rejected by strict no-debt guard",
            )
            raise ImportCreditError("Account import reservation would create debt")
        return {"credits_reserved": estimated_credits}

    async def settle(
        self, *, user_id: str, import_id: str, reserved_credits: int, measured_credits: int
    ) -> dict[str, int]:
        released = reserved_credits - measured_credits
        if released < 0:
            raise ImportCreditError("Measured import usage exceeds reserved credits")
        if released:
            await self.billing_service.refund_user_credits(
                user_id=user_id,
                credits_to_refund=released,
                user_id_hash=hashlib.sha256(user_id.encode()).hexdigest(),
                app_id=self.APP_ID,
                skill_id=self.SKILL_ID,
                idempotency_key=f"account-import:{hashlib.sha256(import_id.encode()).hexdigest()}:settlement-refund",
                reason=f"Unused account import reservation {hashlib.sha256(import_id.encode()).hexdigest()[:12]}",
            )
        user = await self.billing_service.cache_service.get_user_by_id(user_id)
        return {
            "credits_charged": measured_credits,
            "credits_released": released,
            "balance": int((user or {}).get("credits") or 0),
        }


class DirectusImportJobStore:
    """Directus-backed metadata repository; plaintext is never accepted."""

    def __init__(self, directus_service: Any) -> None:
        self.directus_service = directus_service

    async def get(self, *, user_id: str, import_id: str) -> dict[str, Any] | None:
        rows = await self.directus_service.get_items(
            "account_imports",
            params={
                "filter[user_id][_eq]": user_id,
                "filter[import_id][_eq]": import_id,
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        return dict(rows[0]) if rows else None

    async def save(self, *, user_id: str, import_id: str, metadata: dict[str, Any]) -> None:
        existing = await self.get(user_id=user_id, import_id=import_id)
        payload = {"user_id": user_id, "import_id": import_id, **metadata}
        if existing:
            updated = await self.directus_service.update_item(
                "account_imports", existing["id"], payload, admin_required=True
            )
            if not updated:
                raise RuntimeError("Failed to update account import metadata")
            return
        success, _ = await self.directus_service.create_item(
            "account_imports",
            {
                "id": str(uuid.uuid4()),
                "imported_chat_ids": [],
                "source_fingerprints": [],
                "encrypted_record_counts": {},
                "failures": [],
                **payload,
            },
            admin_required=True,
        )
        if not success:
            raise RuntimeError("Failed to create account import metadata")

    async def list_user(self, *, user_id: str) -> list[dict[str, Any]]:
        rows = await self.directus_service.get_items(
            "account_imports",
            params={"filter[user_id][_eq]": user_id, "limit": -1},
            no_cache=True,
            admin_required=True,
        )
        return [dict(row) for row in rows]


def _default_job() -> dict[str, Any]:
    return {
        "status": "pending",
        "last_scan_sequence": -1,
        "last_scan_batch_id": None,
        "last_scan_request_hash": None,
        "last_sanitized_hash": None,
        "last_compression_sequence": -1,
        "last_compression_batch_id": None,
        "last_compression_request_hash": None,
        "compression_summary_hashes": {},
        "usage": {"credits": 0},
        "credits_reserved": 0,
        "retryable_failure": None,
        "billing_finalized": False,
        "completion_result": None,
        "selected_fingerprints": [],
        "preview_fingerprints": [],
        "estimated_credits": 0,
        "reservation_expires_at": None,
        "estimated_tokens_by_fingerprint": {},
        "chat_scan_state": {},
        "scan_batch_state": {},
        "compression_acknowledged_fingerprints": [],
        "compression_required": {},
        "persisted_chat_ids": [],
        "persisted_fingerprints": [],
        "reserved_chat_count": 0,
        "server_content_fingerprints": {},
        "server_duplicate_fingerprints": [],
    }


def _content_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _await_if_needed(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _message_chain(messages: list[dict[str, Any]], initial: str = "") -> str:
    digest = initial
    for message in messages:
        digest = hashlib.sha256(f"{digest}:{_content_hash(message)}".encode()).hexdigest()
    return digest


def _estimated_message_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(4 + len(str(message.get("content") or "")) // 4 for message in messages)


def _stable_fingerprint(provider: str, source_chat_id: str, messages: list[dict[str, Any]]) -> str:
    fingerprint_input = {
        "provider": provider,
        "source_chat_id": source_chat_id,
        "messages": [
            {
                "role": message.get("role"),
                "source_message_id": message.get("source_message_id"),
                "content": message.get("content", ""),
            }
            for message in messages
        ],
    }
    encoded = json.dumps(fingerprint_input, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_zip_text(payload: bytes, required_name: str, source_label: str) -> str:
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            names = {
                name
                for name in archive.namelist()
                if not name.startswith("__MACOSX/") and not name.endswith(".DS_Store") and "/._" not in name and not name.startswith("._")
            }
            resolved_name = required_name if required_name in names else next(
                (name for name in names if name.rsplit("/", 1)[-1] == required_name),
                None,
            )
            if resolved_name is None:
                raise ImportParseError(f"{source_label} is missing {required_name}")
            return archive.read(resolved_name).decode("utf-8")
    except ImportParseError:
        raise
    except zipfile.BadZipFile as exc:
        raise ImportParseError(f"{source_label} is not a valid zip archive") from exc
    except UnicodeDecodeError as exc:
        raise ImportParseError(f"{source_label} contains non-UTF-8 {required_name}") from exc


def _claude_content_text(message: dict[str, Any]) -> tuple[str, list[str]]:
    block_types: list[str] = []
    text_parts: list[str] = []
    for block in message.get("content") or []:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "unknown")
        block_types.append(block_type)
        if block_type == "text" and block.get("text"):
            text_parts.append(str(block["text"]))
        elif block_type == "tool_result" and block.get("content"):
            text_parts.append(str(block["content"]))
    if text_parts:
        return "\n".join(text_parts), block_types
    return str(message.get("text") or ""), block_types


def _claude_uploads(message: dict[str, Any]) -> list[dict[str, Any]]:
    uploads: list[dict[str, Any]] = []
    for index, item in enumerate((message.get("attachments") or []) + (message.get("files") or [])):
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file_name") or item.get("name") or f"attachment-{index + 1}")
        uploads.append({
            "source_upload_id": str(item.get("uuid") or item.get("id") or file_name),
            "file_name": file_name,
            "mime_type": item.get("mime_type") or item.get("file_type"),
            "bytes": item.get("file_size") or item.get("bytes"),
            "content_ref": str(item.get("file_name") or item.get("name") or ""),
        })
    return uploads


def parse_claude_export_bytes(payload: bytes, *, source_name: str) -> list[dict[str, Any]]:
    """Parse Claude official export JSON or ZIP bytes into normalized chats."""

    try:
        if zipfile.is_zipfile(BytesIO(payload)):
            raw = _read_zip_text(payload, "conversations.json", "Claude export")
            conversations = json.loads(raw)
        else:
            conversations = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ImportParseError(f"Claude export {source_name} could not be parsed") from exc

    if isinstance(conversations, dict):
        conversations = conversations.get("conversations")
    if not isinstance(conversations, list):
        raise ImportParseError("Claude export conversations must be a list")

    normalized: list[dict[str, Any]] = []
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        source_chat_id = str(conversation.get("uuid") or "")
        if not source_chat_id:
            raise ImportParseError("Claude export conversation is missing uuid")

        messages: list[dict[str, Any]] = []
        uploads: list[dict[str, Any]] = []
        for raw_message in conversation.get("chat_messages") or []:
            if not isinstance(raw_message, dict):
                continue
            sender = raw_message.get("sender")
            role = "user" if sender == "human" else "assistant" if sender == "assistant" else "system"
            content, block_types = _claude_content_text(raw_message)
            messages.append({
                "role": role,
                "content": content,
                "created_at": raw_message.get("created_at"),
                "source_message_id": raw_message.get("uuid"),
                "provider_metadata": {"content_block_types": block_types},
            })
            uploads.extend(_claude_uploads(raw_message))

        normalized.append({
            "provider": "claude",
            "source_chat_id": source_chat_id,
            "source_fingerprint": _stable_fingerprint("claude", source_chat_id, messages),
            "title": conversation.get("name"),
            "created_at": conversation.get("created_at"),
            "updated_at": conversation.get("updated_at"),
            "messages": messages,
            "embeds": [],
            "uploads": uploads,
            "provider_labels": ["claude"],
            "source_metadata": {"source_name": source_name, "message_count": len(messages)},
        })
    return normalized


def _chatgpt_timestamp(value: Any) -> str | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")


def _chatgpt_content_text(content: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    content_type = str(content.get("content_type") or "unknown")
    text_parts: list[str] = []
    asset_count = 0
    raw_parts = content.get("parts")
    if isinstance(raw_parts, list):
        for part in raw_parts:
            if isinstance(part, str) and part.strip():
                text_parts.append(part)
            elif isinstance(part, dict) and part.get("asset_pointer"):
                asset_count += 1
    elif isinstance(content.get("content"), str):
        text_parts.append(str(content["content"]))
    return "\n".join(text_parts), {"content_type": content_type, "asset_count": asset_count}


def _chatgpt_active_nodes(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = conversation.get("mapping")
    if not isinstance(mapping, dict):
        raise ImportParseError("ChatGPT export conversation is missing mapping")
    current_node = str(conversation.get("current_node") or "")
    if current_node in mapping:
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        node_id = current_node
        while node_id and node_id in mapping and node_id not in seen:
            seen.add(node_id)
            node = mapping[node_id]
            if isinstance(node, dict):
                ordered.append(node)
                node_id = str(node.get("parent") or "")
            else:
                break
        return list(reversed(ordered))
    return sorted(
        [node for node in mapping.values() if isinstance(node, dict)],
        key=lambda node: ((node.get("message") or {}).get("create_time") if isinstance(node.get("message"), dict) else 0) or 0,
    )


def parse_chatgpt_export_bytes(payload: bytes, *, source_name: str) -> list[dict[str, Any]]:
    """Parse ChatGPT official export JSON or ZIP bytes into normalized chats."""

    try:
        if zipfile.is_zipfile(BytesIO(payload)):
            raw = _read_zip_text(payload, "conversations.json", "ChatGPT export")
            conversations = json.loads(raw)
        else:
            conversations = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile) as exc:
        raise ImportParseError(f"ChatGPT export {source_name} could not be parsed") from exc

    if isinstance(conversations, dict):
        conversations = conversations.get("conversations")
    if not isinstance(conversations, list):
        raise ImportParseError("ChatGPT export conversations must be a list")

    normalized: list[dict[str, Any]] = []
    for conversation in conversations:
        if not isinstance(conversation, dict):
            continue
        source_chat_id = str(conversation.get("conversation_id") or conversation.get("id") or "")
        if not source_chat_id:
            raise ImportParseError("ChatGPT export conversation is missing id")

        messages: list[dict[str, Any]] = []
        for node in _chatgpt_active_nodes(conversation):
            raw_message = node.get("message")
            if not isinstance(raw_message, dict):
                continue
            author = raw_message.get("author")
            role = str(author.get("role") if isinstance(author, dict) else "")
            if role not in {"user", "assistant", "system"}:
                continue
            content = raw_message.get("content")
            if not isinstance(content, dict):
                continue
            text, metadata = _chatgpt_content_text(content)
            if not text.strip():
                continue
            messages.append({
                "role": role,
                "content": text,
                "created_at": _chatgpt_timestamp(raw_message.get("create_time")),
                "source_message_id": raw_message.get("id"),
                "provider_metadata": metadata,
            })

        normalized.append({
            "provider": "chatgpt",
            "source_chat_id": source_chat_id,
            "source_fingerprint": _stable_fingerprint("chatgpt", source_chat_id, messages),
            "title": conversation.get("title"),
            "created_at": _chatgpt_timestamp(conversation.get("create_time")),
            "updated_at": _chatgpt_timestamp(conversation.get("update_time")),
            "messages": messages,
            "embeds": [],
            "uploads": [],
            "provider_labels": ["chatgpt"],
            "source_metadata": {"source_name": source_name, "message_count": len(messages)},
        })
    return normalized


def _opencode_timestamp(value: Any) -> str | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    return datetime.fromtimestamp(float(value) / 1000, UTC).isoformat().replace("+00:00", "Z")


def parse_opencode_export_bytes(payload: bytes, *, source_name: str) -> list[dict[str, Any]]:
    """Parse JSON emitted by `opencode export` into one normalized chat."""

    try:
        transcript = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ImportParseError(f"OpenCode transcript export {source_name} could not be parsed") from exc
    if not isinstance(transcript, dict):
        raise ImportParseError("OpenCode transcript export must be an object")
    info = transcript.get("info")
    raw_messages = transcript.get("messages")
    if not isinstance(info, dict) or not isinstance(raw_messages, list) or not info.get("id"):
        raise ImportParseError("OpenCode transcript export is missing info.id or messages")

    messages: list[dict[str, Any]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        message_info = item.get("info") if isinstance(item.get("info"), dict) else {}
        role = str(message_info.get("role") or "")
        if role not in {"user", "assistant"}:
            continue
        parts = [part for part in item.get("parts") or [] if isinstance(part, dict)]
        text_parts = [
            part for part in parts
            if part.get("type") == "text" and part.get("ignored") is not True and isinstance(part.get("text"), str)
        ]
        content = "\n".join(str(part["text"]) for part in text_parts if str(part["text"]).strip())
        if content.strip():
            time = message_info.get("time") if isinstance(message_info.get("time"), dict) else {}
            messages.append({
                "role": role,
                "content": content,
                "created_at": _opencode_timestamp(time.get("created")),
                "source_message_id": message_info.get("id") if isinstance(message_info.get("id"), str) else None,
                "provider_metadata": {
                    "part_types": [str(part.get("type") or "unknown") for part in parts],
                    "text_part_count": len(text_parts),
                },
            })
    source_chat_id = str(info["id"])
    time = info.get("time") if isinstance(info.get("time"), dict) else {}
    return [{
        "provider": "opencode",
        "source_chat_id": source_chat_id,
        "source_fingerprint": _stable_fingerprint("opencode", source_chat_id, messages),
        "title": info.get("title") if isinstance(info.get("title"), str) else None,
        "created_at": _opencode_timestamp(time.get("created")),
        "updated_at": _opencode_timestamp(time.get("updated")),
        "messages": messages,
        "embeds": [],
        "uploads": [],
        "provider_labels": ["opencode"],
        "source_metadata": {"source_name": source_name, "message_count": len(messages)},
    }]


def _load_openmates_archive(payload: bytes) -> dict[str, str]:
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            return {name: archive.read(name).decode("utf-8") for name in archive.namelist() if not name.endswith("/")}
    except zipfile.BadZipFile as exc:
        raise ImportParseError("OpenMates Export V1 archive is not a valid zip") from exc
    except UnicodeDecodeError as exc:
        raise ImportParseError("OpenMates Export V1 archive contains non-UTF-8 metadata") from exc


def parse_openmates_export_bytes(payload: bytes, *, source_name: str) -> dict[str, Any]:
    """Parse an OpenMates Export V1 archive into V1-importable chat records."""

    files = _load_openmates_archive(payload)
    if "manifest.yml" not in files:
        raise ImportParseError("OpenMates Export V1 archive is missing manifest.yml")
    manifest = yaml.safe_load(files["manifest.yml"]) or {}
    if str(manifest.get("version")) != "1" or manifest.get("format") != "openmates-account-export":
        raise ImportParseError("OpenMates Export V1 archive has an unsupported format or version")

    domains = set((manifest.get("domains") or {}).keys())
    skipped_domains = sorted(domains - SUPPORTED_OPENMATES_DOMAINS)
    embeds_by_id = {
        str((yaml.safe_load(content) or {}).get("id")): yaml.safe_load(content) or {}
        for name, content in files.items()
        if name.startswith("embeds/") and name.endswith(('.yml', '.yaml'))
    }
    uploads_by_id = {
        str((yaml.safe_load(content) or {}).get("id")): yaml.safe_load(content) or {}
        for name, content in files.items()
        if name.startswith("uploads/") and name.endswith(('.yml', '.yaml'))
    }

    chats: list[dict[str, Any]] = []
    for name, content in sorted(files.items()):
        if not name.startswith("chats/") or not name.endswith(('.yml', '.yaml')):
            continue
        chat_data = yaml.safe_load(content) or {}
        source_chat_id = str(chat_data.get("id") or "")
        if not source_chat_id:
            raise ImportParseError("OpenMates Export V1 chat YAML is missing id")
        messages = [
            {
                "role": message.get("role"),
                "content": message.get("content", ""),
                "created_at": message.get("created_at"),
                "source_message_id": message.get("id"),
                "provider_metadata": {"embed_refs": message.get("embed_refs") or []},
            }
            for message in chat_data.get("messages") or []
            if isinstance(message, dict)
        ]
        embed_refs = [str(ref) for ref in chat_data.get("embed_refs") or []]
        upload_refs = [str(ref) for ref in chat_data.get("upload_refs") or []]
        embeds = [
            {
                "source_embed_id": embed_id,
                "type": embeds_by_id.get(embed_id, {}).get("type", "unknown"),
                "content": embeds_by_id.get(embed_id, {}).get("content", {}),
                "referenced_upload_ids": embeds_by_id.get(embed_id, {}).get("referenced_upload_ids") or [],
            }
            for embed_id in embed_refs
        ]
        uploads = [
            {
                "source_upload_id": upload_id,
                "file_name": uploads_by_id.get(upload_id, {}).get("file_name", upload_id),
                "mime_type": uploads_by_id.get(upload_id, {}).get("mime_type"),
                "bytes": uploads_by_id.get(upload_id, {}).get("bytes"),
                "content_ref": uploads_by_id.get(upload_id, {}).get("path", ""),
            }
            for upload_id in upload_refs
        ]
        chats.append({
            "provider": "openmates",
            "source_chat_id": source_chat_id,
            "source_fingerprint": _stable_fingerprint("openmates", source_chat_id, messages),
            "title": chat_data.get("title"),
            "created_at": chat_data.get("created_at"),
            "updated_at": chat_data.get("updated_at"),
            "messages": messages,
            "embeds": embeds,
            "uploads": uploads,
            "provider_labels": ["openmates"],
            "source_metadata": {"source_name": source_name},
        })
    if not chats:
        raise ImportParseError("OpenMates Export V1 archive contains no chat YAML files")
    return {"source": "openmates", "skipped_domains": skipped_domains, "chats": chats}


class AccountImportService:
    """Service for Account Import V1 preview, scan, and completion state."""

    def __init__(
        self,
        *,
        directus_service: Any | None = None,
        scanner: Scanner | None = None,
        compressor: Compressor | None = None,
        billing: ImportBilling | None = None,
        job_store: ImportJobStore | None = None,
        import_lock: ImportLock | None = None,
        usage_pricer: Callable[[str, int, int], int] | None = None,
        credits_per_chat_estimate: int = 1,
        max_batch_messages: int = DEFAULT_MAX_IMPORT_BATCH_MESSAGES,
        require_billing_for_paid: bool = False,
    ) -> None:
        self.directus_service = directus_service
        self.scanner = scanner
        self.compressor = compressor
        self.billing = billing
        self.job_store = job_store or InMemoryImportJobStore()
        self.import_lock = import_lock or InMemoryImportLock()
        self.usage_pricer = usage_pricer or (lambda _model_id, _input_tokens, _output_tokens: 0)
        self.credits_per_chat_estimate = credits_per_chat_estimate
        self.max_batch_messages = max_batch_messages
        self.require_billing_for_paid = require_billing_for_paid

    async def preview_import(
        self,
        *,
        user_id: str,
        source: str,
        chats: list[dict[str, Any]],
        available_credits: int,
        imported_count_last_30_days: int,
        existing_fingerprints: set[str],
        estimated_credits: int | None = None,
    ) -> dict[str, Any]:
        async with self.import_lock.hold(user_id=user_id, import_id="preview"):
            history = await self.job_store.list_user(user_id=user_id)
            cutoff = datetime.now(UTC) - timedelta(days=30)
            recent_free = 0
            durable_fingerprints = set(existing_fingerprints)
            durable_content_fingerprints: set[str] = set()
            for record in history:
                created_at = record.get("created_at")
                try:
                    created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    created = datetime.now(UTC)
                if record.get("status") in {"complete", "partial", "persisted"}:
                    durable_fingerprints.update(record.get("source_fingerprints") or record.get("persisted_fingerprints") or [])
                    durable_content_fingerprints.update((record.get("server_content_fingerprints") or {}).values())
                reservation_expires_at = record.get("reservation_expires_at")
                try:
                    reservation_expires = datetime.fromisoformat(str(reservation_expires_at).replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    reservation_expires = None
                active_free_reservation = (
                    record.get("processing_mode") == "free"
                    and record.get("status") == "confirmed"
                    and reservation_expires is not None
                    and reservation_expires > datetime.now(UTC)
                )
                completed_free_import = (
                    record.get("processing_mode") == "free"
                    and record.get("status") in {"complete", "partial", "persisted", "scanning", "scanned", "compressing", "processed"}
                )
                if (active_free_reservation or completed_free_import) and created >= cutoff:
                    recent_free += len(record.get("selected_fingerprints") or record.get("source_fingerprints") or [])
                    if record.get("reserved_chat_count") is not None:
                        recent_free -= len(record.get("selected_fingerprints") or record.get("source_fingerprints") or [])
                        recent_free += int(record.get("reserved_chat_count") or 0)
            free_remaining = max(FREE_IMPORT_CHATS_PER_30_DAYS - max(imported_count_last_30_days, recent_free), 0)
            fingerprints = [str(chat.get("source_fingerprint") or "") for chat in chats]
            if any(not fingerprint for fingerprint in fingerprints) or len(set(fingerprints)) != len(fingerprints):
                raise ImportScanError("Preview requires unique source fingerprints")
            duplicate_fingerprints = [fingerprint for fingerprint in fingerprints if fingerprint in durable_fingerprints]
            total_chats = len(chats)
            if available_credits > 0:
                max_batch_count = min(PAID_IMPORT_BATCH_LIMIT, total_chats)
                default_selection_count = min(PAID_IMPORT_DEFAULT_SELECTION, max_batch_count)
                required_credits = estimated_credits if estimated_credits is not None else default_selection_count * self.credits_per_chat_estimate
                can_import = required_credits > 0 and available_credits >= required_credits and self.billing is not None
                reason = "paid_import_available" if can_import else "insufficient_credits"
            else:
                eligible_free_chats = [
                    chat for chat in chats
                    if int(chat.get("estimated_input_tokens") or 0) <= FREE_IMPORT_CHAT_TOKEN_CAP
                ]
                max_batch_count = min(free_remaining, len(eligible_free_chats))
                default_selection_count = max_batch_count
                required_credits = 0
                can_import = max_batch_count > 0
                reason = "free_import_allowance_remaining" if can_import else (
                    "paid_credits_required_for_token_cap" if free_remaining and chats else "insufficient_credits"
                )
            if not self.require_billing_for_paid and available_credits > 0 and self.billing is None:
                can_import = available_credits >= required_credits
                reason = "paid_import_available" if can_import else "insufficient_credits"

            import_id = str(uuid.uuid4())
            result = {
                "import_id": import_id,
                "free_remaining": free_remaining,
                "chat_limit": max_batch_count,
                "default_selection_count": default_selection_count,
                "max_batch_count": max_batch_count,
                "duplicate_fingerprints": duplicate_fingerprints,
                "estimated_credits": required_credits,
                "can_import": can_import,
                "reason": reason,
            }
            if self.require_billing_for_paid:
                job = _default_job()
                job.update({
                    "status": "previewed" if can_import else "blocked",
                    "processing_mode": "free_pending" if available_credits <= 0 and can_import else "paid_pending",
                    "source": source,
                    "preview_fingerprints": fingerprints,
                    "estimated_credits": required_credits,
                    "estimated_tokens_by_fingerprint": {
                        fingerprint: int(chat.get("estimated_input_tokens") or 0)
                        for fingerprint, chat in zip(fingerprints, chats, strict=True)
                    },
                    "reserved_chat_count": 0,
                    "prior_server_content_fingerprints": sorted(durable_content_fingerprints),
                })
                await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
            return result

    async def confirm_import(
        self,
        *,
        user_id: str,
        import_id: str,
        selected_fingerprints: list[str],
        available_credits: int,
    ) -> dict[str, Any]:
        """Confirm the exact preview selection and reserve its processing budget."""

        async with self.import_lock.hold(user_id=user_id, import_id="preview"):
            job = await self._get_job(user_id=user_id, import_id=import_id)
            selected = list(dict.fromkeys(selected_fingerprints))
            previewed = set(job.get("preview_fingerprints") or [])
            if not selected or len(selected) != len(selected_fingerprints) or not set(selected).issubset(previewed):
                raise ImportScanError("Confirmation does not match the authoritative preview contract")
            if len(selected) > len(previewed):
                raise ImportCreditError("Confirmation exceeds the preview chat allowance")
            if job.get("status") in {"confirmed", "reserved"}:
                if selected != list(job.get("selected_fingerprints") or []):
                    raise ImportSequenceError("Confirmed import retry changed the selection")
                return {"import_id": import_id, "status": "confirmed", "selected_fingerprints": selected}

            job["selected_fingerprints"] = selected
            job["reserved_chat_count"] = len(selected)
            if job.get("processing_mode") == "paid_pending":
                preview_count = len(previewed)
                selected_estimate = math.ceil(
                    int(job.get("estimated_credits") or 0) * len(selected) / preview_count
                )
                await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
                await self._reserve_import_credits_unlocked(
                    user_id=user_id,
                    import_id=import_id,
                    selected_chat_count=len(selected),
                    available_credits=available_credits,
                    estimated_credits=selected_estimate,
                )
            elif job.get("processing_mode") == "free_pending":
                history = await self.job_store.list_user(user_id=user_id)
                now = datetime.now(UTC)
                cutoff = now - timedelta(days=30)
                consumed = 0
                for record in history:
                    if record.get("import_id") == import_id or record.get("processing_mode") != "free":
                        continue
                    try:
                        created = datetime.fromisoformat(str(record.get("created_at")).replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        continue
                    if created < cutoff:
                        continue
                    try:
                        expires = datetime.fromisoformat(str(record.get("reservation_expires_at")).replace("Z", "+00:00"))
                    except (TypeError, ValueError):
                        expires = None
                    if record.get("status") == "confirmed" and expires and expires > now:
                        consumed += int(record.get("reserved_chat_count") or 0)
                    elif record.get("status") in {"complete", "partial", "persisted", "scanning", "scanned", "compressing", "processed"}:
                        consumed += int(record.get("reserved_chat_count") or len(record.get("selected_fingerprints") or []))
                if consumed + len(selected) > FREE_IMPORT_CHATS_PER_30_DAYS:
                    raise ImportCreditError("Free import allowance is no longer available")
                estimates = job.get("estimated_tokens_by_fingerprint") or {}
                if any(int(estimates.get(fingerprint) or 0) > FREE_IMPORT_CHAT_TOKEN_CAP for fingerprint in selected):
                    raise ImportCreditError("Free imported chats are limited to 100000 estimated input tokens")
                job.update({
                    "status": "confirmed",
                    "processing_mode": "free",
                    "reservation_expires_at": (now + timedelta(minutes=FREE_IMPORT_RESERVATION_MINUTES)).isoformat(),
                })
                await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
            else:
                raise ImportCreditError("Import preview is not eligible for confirmation")
            return {"import_id": import_id, "status": "confirmed", "selected_fingerprints": selected}

    async def reserve_import_credits(
        self,
        *,
        user_id: str,
        import_id: str,
        selected_chat_count: int,
        available_credits: int,
        estimated_credits: int | None = None,
    ) -> dict[str, Any]:
        async with self.import_lock.hold(user_id=user_id, import_id=import_id):
            return await self._reserve_import_credits_unlocked(
                user_id=user_id,
                import_id=import_id,
                selected_chat_count=selected_chat_count,
                available_credits=available_credits,
                estimated_credits=estimated_credits,
            )

    async def _reserve_import_credits_unlocked(
        self,
        *,
        user_id: str,
        import_id: str,
        selected_chat_count: int,
        available_credits: int,
        estimated_credits: int | None,
    ) -> dict[str, Any]:
        required_credits = estimated_credits if estimated_credits is not None else selected_chat_count * self.credits_per_chat_estimate
        job = await self._get_job(user_id=user_id, import_id=import_id)
        if int(job.get("credits_reserved") or 0):
            if int(job["credits_reserved"]) != required_credits:
                raise ImportCreditError("Import reservation retry changed the estimate")
            return {"import_id": import_id, "credits_reserved": required_credits}
        if job.get("status") == "reserving":
            raise ImportCreditError("Import reservation outcome requires reconciliation")
        if available_credits < required_credits:
            raise ImportCreditError("Insufficient credits for import without negative balance")
        if required_credits > 0 and self.billing is None:
            if estimated_credits is not None or self.require_billing_for_paid:
                raise ImportCreditError("Account import billing unavailable; paid processing is disabled")
            return {"import_id": import_id, "credits_reserved": required_credits}
        job["status"] = "reserving"
        await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
        try:
            reservation = await self.billing.reserve(
                user_id=user_id,
                import_id=import_id,
                estimated_credits=required_credits,
            ) if self.billing else {"credits_reserved": required_credits}
        except Exception:
            job["status"] = "blocked"
            await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
            raise
        reserved = required_credits
        try:
            reserved = int(reservation.get("credits_reserved") or 0)
            if reserved != required_credits or reserved > available_credits:
                raise ImportCreditError("Billing reservation did not preserve strict no-debt limits")
            job["credits_reserved"] = reserved
            job["status"] = "reserved"
            job["processing_mode"] = "paid_reserved"
            await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
        except Exception:
            compensation_credits = reserved or required_credits
            try:
                settlement = await self.billing.settle(
                    user_id=user_id,
                    import_id=import_id,
                    reserved_credits=compensation_credits,
                    measured_credits=0,
                ) if self.billing else {
                    "credits_charged": 0,
                    "credits_released": compensation_credits,
                    "balance": available_credits,
                }
                if (
                    int(settlement.get("credits_charged") or 0) != 0
                    or int(settlement.get("credits_released") or 0) != compensation_credits
                    or int(settlement.get("balance") or 0) < 0
                ):
                    raise ImportCreditError("Reservation compensation returned invalid accounting")
            except Exception as refund_error:
                job.update({
                    "status": "reservation_reconciliation_required",
                    "credits_reserved": compensation_credits,
                    "retryable_failure": "reservation_refund_failed",
                })
                await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
                raise ImportCreditError("Paid import reservation requires billing reconciliation") from refund_error
            job.update({
                "status": "blocked",
                "credits_reserved": 0,
                "processing_mode": "paid_pending",
                "retryable_failure": None,
            })
            await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
            raise
        return {"import_id": import_id, "credits_reserved": required_credits}

    async def scan_selected_chats(self, *, user_id: str, import_id: str, chats: list[dict[str, Any]]) -> dict[str, Any]:
        result = await self.scan_import_batch(
            user_id=user_id,
            import_id=import_id,
            batch_id="legacy-single-batch",
            sequence=0,
            final_batch=True,
            chats=chats,
        )
        return {
            "chats": result["chats"],
            "credits_reserved": result["credits_reserved"],
            "messages_blocked": [],
            "failures": result["failures"],
        }

    async def _get_job(self, *, user_id: str, import_id: str) -> dict[str, Any]:
        stored = await self.job_store.get(user_id=user_id, import_id=import_id)
        return {**_default_job(), **stored} if stored else _default_job()

    def lock_operation(self, *, user_id: str, import_id: str) -> Any:
        """Expose the import lock so encrypted writes and metadata update stay serialized."""

        return self.import_lock.hold(user_id=user_id, import_id=import_id)

    async def scan_import_batch(
        self,
        *,
        user_id: str,
        import_id: str,
        batch_id: str,
        sequence: int,
        final_batch: bool,
        chats: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Scan each non-empty message and persist only bounded acknowledgement metadata."""

        async with self.import_lock.hold(user_id=user_id, import_id=import_id):
            try:
                return await self._scan_import_batch_unlocked(
                    user_id=user_id,
                    import_id=import_id,
                    batch_id=batch_id,
                    sequence=sequence,
                    final_batch=final_batch,
                    chats=chats,
                )
            except ImportCreditError:
                raise
            except ImportScanError:
                job = await self._get_job(user_id=user_id, import_id=import_id)
                job["retryable_failure"] = "scanner_unavailable"
                await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
                raise

    async def _scan_import_batch_unlocked(
        self,
        *,
        user_id: str,
        import_id: str,
        batch_id: str,
        sequence: int,
        final_batch: bool,
        chats: list[dict[str, Any]],
    ) -> dict[str, Any]:

        if self.scanner is None:
            raise ImportScanError("Import scanner unavailable; retryable")
        message_count = sum(len(chat.get("messages") or []) for chat in chats)
        if message_count > self.max_batch_messages:
            raise ValueError(f"Import scan batches support at most {self.max_batch_messages} messages")
        request_hash = _content_hash(chats)
        job = await self._get_job(user_id=user_id, import_id=import_id)
        if self.require_billing_for_paid and job.get("processing_mode") not in {"free", "paid_reserved"}:
            raise ImportCreditError("Import processing requires a valid free allowance or paid reservation")
        if job.get("processing_mode") == "free" and job.get("status") == "confirmed":
            try:
                reservation_expires = datetime.fromisoformat(str(job.get("reservation_expires_at")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                reservation_expires = None
            if reservation_expires is None or reservation_expires <= datetime.now(UTC):
                job["status"] = "expired"
                await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
                raise ImportCreditError("Free import reservation expired")
        selected_fingerprints = set(job.get("selected_fingerprints") or [])
        batch_fingerprints = [str(chat.get("source_fingerprint") or "") for chat in chats]
        if selected_fingerprints and (
            any(not fingerprint or fingerprint not in selected_fingerprints for fingerprint in batch_fingerprints)
            or len(batch_fingerprints) != len(set(batch_fingerprints))
        ):
            raise ImportScanError("Scan batch does not match the authoritative preview contract")
        seen_fingerprints = set((job.get("chat_scan_state") or {}).keys())
        if len(seen_fingerprints | set(batch_fingerprints)) > int(job.get("reserved_chat_count") or len(selected_fingerprints) or len(batch_fingerprints)):
            raise ImportCreditError("Scan batch exceeds the authoritative preview chat allowance")
        last_sequence = int(job.get("last_scan_sequence", -1))
        if sequence == last_sequence:
            if batch_id != job.get("last_scan_batch_id") or request_hash != job.get("last_scan_request_hash"):
                raise ImportSequenceError("Acknowledged sequence was retried with different content")
            return {
                "batch_id": batch_id,
                "sequence": sequence,
                "status": "acknowledged",
                "already_acknowledged": True,
                "chats": [],
                "sanitized_hash": job.get("last_sanitized_hash"),
                "usage": {"credits": 0},
                "credits_reserved": int(job.get("credits_reserved") or 0),
                "messages_blocked": [],
                "failures": [],
            }
        expected_sequence = last_sequence + 1
        if sequence != expected_sequence:
            raise ImportSequenceError(f"Invalid scan cursor: expected sequence {expected_sequence}")

        sanitized_chats: list[dict[str, Any]] = []
        batch_credits = 0
        batch_input_tokens = 0
        batch_output_tokens = 0
        raw_tokens_by_fingerprint: dict[str, int] = {}
        try:
            for chat_index, chat in enumerate(chats):
                fingerprint = str(chat.get("source_fingerprint") or "")
                raw_tokens_by_fingerprint[fingerprint] = _estimated_message_tokens(list(chat.get("messages") or []))
                sanitized_messages: list[dict[str, Any]] = []
                for message_index, message in enumerate(chat.get("messages") or []):
                    sanitized_message = dict(message)
                    content = message.get("content")
                    if isinstance(content, str) and content.strip():
                        scan_result = await _await_if_needed(self.scanner(
                            content,
                            role=str(message.get("role") or ""),
                            task_id=f"account_import_{import_id}_{sequence}_{chat_index}_{message_index}",
                        ))
                        if not isinstance(scan_result, dict) or not isinstance(scan_result.get("content"), str):
                            raise ImportScanError("Import scanner returned a malformed result; retryable")
                        usage = scan_result.get("usage", {})
                        if not isinstance(usage, dict):
                            raise ImportScanError("Import scanner returned malformed usage; retryable")
                        sanitized_message["content"] = scan_result["content"]
                        input_tokens = int(usage.get("input_tokens") or 0)
                        output_tokens = int(usage.get("output_tokens") or 0)
                        model_id = str(usage.get("model_id") or "")
                        if self.require_billing_for_paid and (not model_id or input_tokens <= 0):
                            raise ImportScanError("Import scanner did not return measured token usage; retryable")
                        credits = usage.get("credits")
                        usage_calls = usage.get("calls")
                        if credits is None and isinstance(usage_calls, list) and usage_calls:
                            credits = sum(
                                self.usage_pricer(
                                    str(call.get("model_id") or ""),
                                    int(call.get("input_tokens") or 0),
                                    int(call.get("output_tokens") or 0),
                                )
                                for call in usage_calls
                                if isinstance(call, dict)
                            )
                        if credits is None:
                            if not model_id or input_tokens < 0 or output_tokens < 0:
                                raise ImportScanError("Import scanner returned malformed usage; retryable")
                            credits = self.usage_pricer(model_id, input_tokens, output_tokens)
                        if not isinstance(credits, int) or credits < 0:
                            raise ImportScanError("Import scanner returned malformed usage; retryable")
                        batch_credits += credits
                        batch_input_tokens += input_tokens
                        batch_output_tokens += output_tokens
                    sanitized_messages.append(sanitized_message)
                sanitized_chat = dict(chat)
                sanitized_chat["messages"] = sanitized_messages
                sanitized_chats.append(sanitized_chat)
        except ImportScanError:
            raise
        except Exception as exc:
            raise ImportScanError("Import scanner unavailable; retryable") from exc

        sanitized_messages = [message for chat in sanitized_chats for message in chat.get("messages") or []]
        sanitized_hash = _content_hash(sanitized_messages)
        prior_usage = job.get("usage") or {}
        total_usage = int(prior_usage.get("credits") or 0) + batch_credits
        total_input_tokens = int(prior_usage.get("input_tokens") or 0) + batch_input_tokens
        total_output_tokens = int(prior_usage.get("output_tokens") or 0) + batch_output_tokens
        if job.get("processing_mode") == "paid_reserved" and total_usage > int(job.get("credits_reserved") or 0):
            job["retryable_failure"] = "reservation_exhausted"
            await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
            raise ImportCreditError("Measured usage exceeds reserved credits")
        chat_scan_state = dict(job.get("chat_scan_state") or {})
        server_content_fingerprints = dict(job.get("server_content_fingerprints") or {})
        server_duplicates = set(job.get("server_duplicate_fingerprints") or [])
        prior_server_fingerprints = set(job.get("prior_server_content_fingerprints") or [])
        from backend.apps.ai.processing.chat_compressor import (
            DEFAULT_COMPRESSION_TRIGGER_THRESHOLD,
            ESTIMATED_SYSTEM_PROMPT_OVERHEAD,
        )

        compression_required = dict(job.get("compression_required") or {})
        compression_acknowledged = set(job.get("compression_acknowledged_fingerprints") or [])
        for chat in sanitized_chats:
            fingerprint = str(chat.get("source_fingerprint") or "")
            messages = list(chat.get("messages") or [])
            state = dict(chat_scan_state.get(fingerprint) or {})
            state["digest"] = _message_chain(messages, str(state.get("digest") or ""))
            state["message_count"] = int(state.get("message_count") or 0) + len(messages)
            state["estimated_input_tokens"] = int(state.get("estimated_input_tokens") or 0) + raw_tokens_by_fingerprint.get(
                fingerprint,
                0,
            )
            state["scan_complete"] = False
            if job.get("processing_mode") == "free" and state["estimated_input_tokens"] > FREE_IMPORT_CHAT_TOKEN_CAP:
                job["retryable_failure"] = "free_token_cap_exceeded"
                await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
                raise ImportCreditError("Free imported chats are limited to 100000 estimated input tokens")
            chat_scan_state[fingerprint] = state
            required = (
                int(state.get("estimated_input_tokens") or 0) + ESTIMATED_SYSTEM_PROMPT_OVERHEAD
                >= DEFAULT_COMPRESSION_TRIGGER_THRESHOLD
            )
            compression_required[fingerprint] = required
            if required:
                compression_acknowledged.discard(fingerprint)
        scan_batch_state = dict(job.get("scan_batch_state") or {})
        scan_batch_state[str(sequence)] = {
            str(chat.get("source_fingerprint") or ""): {
                "digest": _message_chain(list(chat.get("messages") or [])),
                "message_count": len(chat.get("messages") or []),
            }
            for chat in sanitized_chats
        }
        if final_batch:
            for fingerprint, state in chat_scan_state.items():
                state["scan_complete"] = True
                server_content_fingerprints[fingerprint] = str(state["digest"])
                if state["digest"] in prior_server_fingerprints:
                    server_duplicates.add(fingerprint)
                required = (
                    int(state.get("estimated_input_tokens") or 0) + ESTIMATED_SYSTEM_PROMPT_OVERHEAD
                    >= DEFAULT_COMPRESSION_TRIGGER_THRESHOLD
                )
                compression_required[fingerprint] = required
                if not required:
                    compression_acknowledged.add(fingerprint)
                else:
                    compression_acknowledged.discard(fingerprint)
            job["compression_required"] = compression_required
            job["compression_acknowledged_fingerprints"] = sorted(compression_acknowledged)
        job.update({
            "status": "scanned" if final_batch else "scanning",
            "last_scan_sequence": sequence,
            "last_scan_batch_id": batch_id,
            "last_scan_request_hash": request_hash,
            "last_sanitized_hash": sanitized_hash,
            "usage": {
                "credits": total_usage,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
            },
            "chat_scan_state": chat_scan_state,
            "scan_batch_state": scan_batch_state,
            "compression_required": compression_required,
            "compression_acknowledged_fingerprints": sorted(compression_acknowledged),
            "server_content_fingerprints": server_content_fingerprints,
            "server_duplicate_fingerprints": sorted(server_duplicates),
            "retryable_failure": None,
        })
        await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
        return {
            "batch_id": batch_id,
            "sequence": sequence,
            "status": "acknowledged",
            "already_acknowledged": False,
            "chats": sanitized_chats,
            "sanitized_hash": sanitized_hash,
            "usage": {
                "credits": batch_credits,
                "input_tokens": batch_input_tokens,
                "output_tokens": batch_output_tokens,
            },
            "credits_reserved": int(job.get("credits_reserved") or 0),
            "messages_blocked": [],
            "failures": [],
            "duplicate_fingerprints": sorted(server_duplicates),
        }

    async def compress_import_batch(
        self,
        *,
        user_id: str,
        import_id: str,
        batch_id: str,
        sequence: int,
        final_batch: bool,
        scan_sequence: int,
        sanitized_messages: list[dict[str, Any]],
        source_fingerprint: str | None = None,
        prior_summary: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate compression from the complete acknowledged sanitized chat."""

        async with self.import_lock.hold(user_id=user_id, import_id=import_id):
            try:
                return await self._compress_import_batch_unlocked(
                    user_id=user_id,
                    import_id=import_id,
                    batch_id=batch_id,
                    sequence=sequence,
                    final_batch=final_batch,
                    scan_sequence=scan_sequence,
                    sanitized_messages=sanitized_messages,
                    source_fingerprint=source_fingerprint,
                    prior_summary=prior_summary,
                )
            except ImportCompressionError:
                job = await self._get_job(user_id=user_id, import_id=import_id)
                job["retryable_failure"] = "compressor_unavailable"
                await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
                raise

    async def _compress_import_batch_unlocked(
        self,
        *,
        user_id: str,
        import_id: str,
        batch_id: str,
        sequence: int,
        final_batch: bool,
        scan_sequence: int,
        sanitized_messages: list[dict[str, Any]],
        source_fingerprint: str | None,
        prior_summary: str | None,
    ) -> dict[str, Any]:

        job = await self._get_job(user_id=user_id, import_id=import_id)
        if scan_sequence > int(job.get("last_scan_sequence", -1)):
            raise ImportCompressionError("Compression requires an acknowledged sanitized batch")
        scan_batch_state = dict(job.get("scan_batch_state") or {}).get(str(scan_sequence), {})
        if source_fingerprint is None:
            if len(scan_batch_state) != 1:
                raise ImportCompressionError("Compression requires a source fingerprint")
            source_fingerprint = next(iter(scan_batch_state))
        state = scan_batch_state.get(source_fingerprint)
        if not isinstance(state, dict):
            raise ImportCompressionError("Compression requires an acknowledged scanned batch")
        if (
            len(sanitized_messages) != int(state.get("message_count") or 0)
            or _message_chain(sanitized_messages) != state.get("digest")
        ):
            raise ImportCompressionError("Compression input does not match the acknowledged scanned batch")
        prior_summary_hash = _content_hash(prior_summary) if prior_summary is not None else None
        summary_hashes = dict(job.get("compression_summary_hashes") or {})
        expected_prior_summary_hash = summary_hashes.get(source_fingerprint)
        if expected_prior_summary_hash != prior_summary_hash:
            raise ImportCompressionError("Compression prior summary does not match the previous acknowledgement")
        request_hash = _content_hash({
            "scan_sequence": scan_sequence,
            "source_fingerprint": source_fingerprint,
            "messages": sanitized_messages,
            "prior_summary_hash": prior_summary_hash,
        })
        last_sequence = int(job.get("last_compression_sequence", -1))
        if sequence == last_sequence:
            if batch_id != job.get("last_compression_batch_id") or request_hash != job.get("last_compression_request_hash"):
                raise ImportSequenceError("Acknowledged compression sequence was retried with different content")
            return {"batch_id": batch_id, "sequence": sequence, "status": "acknowledged", "summary": None,
                    "usage": {"credits": 0}, "already_acknowledged": True, "failures": []}
        if sequence != last_sequence + 1:
            raise ImportSequenceError(f"Invalid compression cursor: expected sequence {last_sequence + 1}")

        summary: str | None = None
        compression_credits = 0
        compression_input_tokens = 0
        compression_output_tokens = 0
        required_by_chat = dict(job.get("compression_required") or {})
        compression_required = bool(required_by_chat.get(source_fingerprint))
        generate_summary = compression_required or not final_batch or prior_summary is not None
        if generate_summary:
            if self.compressor is None:
                raise ImportCompressionError("Import compressor unavailable; retryable")
            compression_result = await _await_if_needed(self.compressor(
                sanitized_messages,
                task_id=f"account_import_{import_id}_compression_{sequence}",
                prior_summary=prior_summary,
                force=True,
            ))
            if getattr(compression_result, "error", None):
                raise ImportCompressionError("Import compressor failed; retryable")
            summary_content = getattr(compression_result, "summary_content", None)
            if (
                not getattr(compression_result, "was_compressed", False)
                or not isinstance(summary_content, str)
                or not summary_content.strip()
            ):
                raise ImportCompressionError("Import compressor returned a malformed result; retryable")
            summary = summary_content
            compression_input_tokens = int(getattr(compression_result, "input_tokens", 0) or 0)
            compression_output_tokens = int(getattr(compression_result, "output_tokens", 0) or 0)
            model_id = str(getattr(compression_result, "model_id", "") or "")
            if self.require_billing_for_paid and (not model_id or compression_input_tokens <= 0):
                raise ImportCompressionError("Import compressor did not return measured token usage; retryable")
            explicit_credits = getattr(compression_result, "credits", None)
            compression_credits = int(explicit_credits) if explicit_credits is not None else self.usage_pricer(
                model_id, compression_input_tokens, compression_output_tokens
            )

        prior_usage = job.get("usage") or {}
        total_usage = int(prior_usage.get("credits") or 0) + compression_credits
        if job.get("processing_mode") == "paid_reserved" and total_usage > int(job.get("credits_reserved") or 0):
            raise ImportCreditError("Measured usage exceeds the conservative reservation")
        acknowledged = set(job.get("compression_acknowledged_fingerprints") or [])
        if final_batch and (not compression_required or summary is not None):
            acknowledged.add(source_fingerprint)
        summary_hashes[source_fingerprint] = _content_hash(summary) if summary is not None else prior_summary_hash
        job.update({
            "status": "processed" if final_batch else "compressing",
            "last_compression_sequence": sequence,
            "last_compression_batch_id": batch_id,
            "last_compression_request_hash": request_hash,
            "compression_summary_hashes": summary_hashes,
            "usage": {
                "credits": total_usage,
                "input_tokens": int(prior_usage.get("input_tokens") or 0) + compression_input_tokens,
                "output_tokens": int(prior_usage.get("output_tokens") or 0) + compression_output_tokens,
            },
            "compression_acknowledged_fingerprints": sorted(acknowledged),
            "compression_required": required_by_chat,
            "retryable_failure": None,
        })
        await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
        return {
            "batch_id": batch_id,
            "sequence": sequence,
            "status": "acknowledged",
            "summary": summary,
            "usage": {
                "credits": compression_credits,
                "input_tokens": compression_input_tokens,
                "output_tokens": compression_output_tokens,
            },
            "already_acknowledged": False,
            "failures": [],
        }

    async def get_import_status(self, *, user_id: str, import_id: str) -> dict[str, Any]:
        job = await self._get_job(user_id=user_id, import_id=import_id)
        return {
            "status": job["status"],
            "last_scan_sequence": int(job["last_scan_sequence"]),
            "last_compression_sequence": int(job["last_compression_sequence"]),
            "usage": dict(job["usage"]),
            "credits_reserved": int(job["credits_reserved"]),
            "retryable_failure": job.get("retryable_failure"),
        }

    async def validate_encrypted_persistence(
        self,
        *,
        user_id: str,
        import_id: str,
        source_fingerprints: list[str],
    ) -> None:
        job = await self._get_job(user_id=user_id, import_id=import_id)
        selected = set(job.get("selected_fingerprints") or [])
        requested = set(source_fingerprints)
        scanned = {
            fingerprint
            for fingerprint, state in (job.get("chat_scan_state") or {}).items()
            if isinstance(state, dict) and state.get("scan_complete")
        }
        compressed = set(job.get("compression_acknowledged_fingerprints") or [])
        if not requested or not requested.issubset(selected) or not requested.issubset(scanned & compressed):
            raise ImportPersistenceError("Encrypted persistence requires scan and compression acknowledgements")
        if requested & set(job.get("persisted_fingerprints") or []):
            raise ImportPersistenceError("Encrypted persistence batch was already acknowledged")

    async def record_encrypted_persistence(
        self,
        *,
        user_id: str,
        import_id: str,
        chat_ids: list[str],
        source_fingerprints: list[str],
    ) -> None:
        if not chat_ids:
            return
        job = await self._get_job(user_id=user_id, import_id=import_id)
        persisted_ids = list(dict.fromkeys([*(job.get("persisted_chat_ids") or []), *chat_ids]))
        persisted_fingerprints = list(dict.fromkeys([
            *(job.get("persisted_fingerprints") or []), *source_fingerprints,
        ]))
        job.update({
            "status": "persisted",
            "persisted_chat_ids": persisted_ids,
            "persisted_fingerprints": persisted_fingerprints,
        })
        await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)

    async def complete_import(
        self,
        *,
        user_id: str,
        import_id: str,
        imported_chat_ids: list[str],
        source_fingerprints: list[str],
        encrypted_record_counts: dict[str, int],
        client_failures: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        async with self.import_lock.hold(user_id=user_id, import_id=import_id):
            return await self._complete_import_unlocked(
                user_id=user_id,
                import_id=import_id,
                imported_chat_ids=imported_chat_ids,
                source_fingerprints=source_fingerprints,
                encrypted_record_counts=encrypted_record_counts,
                client_failures=client_failures,
            )

    async def _complete_import_unlocked(
        self,
        *,
        user_id: str,
        import_id: str,
        imported_chat_ids: list[str],
        source_fingerprints: list[str],
        encrypted_record_counts: dict[str, int],
        client_failures: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        job = await self._get_job(user_id=user_id, import_id=import_id)
        if job.get("completion_result"):
            return dict(job["completion_result"])
        if self.require_billing_for_paid or job.get("selected_fingerprints"):
            if set(imported_chat_ids) != set(job.get("persisted_chat_ids") or []) or set(source_fingerprints) != set(
                job.get("persisted_fingerprints") or []
            ):
                raise ImportPersistenceError("Completion does not match acknowledged encrypted persistence")
        failures = client_failures or []
        if job.get("selected_fingerprints") and not imported_chat_ids and not failures:
            raise ImportPersistenceError("Completion cannot report success before any chat was imported")
        status = "partial" if failures else "complete"
        reserved = int(job.get("credits_reserved") or 0)
        measured = int((job.get("usage") or {}).get("credits") or 0)
        if measured > reserved and reserved > 0:
            raise ImportCreditError("Measured import usage exceeds reserved credits; settlement blocked to prevent debt")
        credits_charged = 0
        credits_released = 0
        if reserved:
            if self.billing is None:
                raise ImportCreditError("Account import billing unavailable; settlement blocked")
            if job.get("status") == "settling":
                raise ImportCreditError("Import settlement outcome requires reconciliation")
            job["status"] = "settling"
            await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
            settlement = await self.billing.settle(
                user_id=user_id,
                import_id=import_id,
                reserved_credits=reserved,
                measured_credits=measured,
            )
            credits_charged = int(settlement.get("credits_charged") or 0)
            credits_released = int(settlement.get("credits_released") or 0)
            if credits_charged != measured or credits_released != reserved - measured or int(settlement.get("balance") or 0) < 0:
                raise ImportCreditError("Billing settlement violated strict no-debt accounting")
        result = {
            "status": status,
            "credits_charged": credits_charged,
            "credits_released": credits_released,
            "imported_count": len(imported_chat_ids),
            "failures": failures,
        }
        job.update({
            "status": status,
            "imported_chat_ids": imported_chat_ids,
            "source_fingerprints": source_fingerprints,
            "encrypted_record_counts": encrypted_record_counts,
            "failures": failures,
            "credits_charged": credits_charged,
            "credits_released": credits_released,
            "billing_finalized": True,
            "completion_result": result,
        })
        await self.job_store.save(user_id=user_id, import_id=import_id, metadata=job)
        return result

    async def report_skipped_domains(self, *, source: str, domains: list[str]) -> dict[str, Any]:
        return {
            "source": source,
            "skipped_domains": sorted(domains),
            "reason": "unsupported_in_account_import_v1",
            "follow_up": "OPE-588",
        }
