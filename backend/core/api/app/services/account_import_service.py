"""Account Import V1 backend parsing and control-plane helpers.

This module owns provider export normalization, import preview limits, dedupe
warnings, transient scan orchestration, and completion accounting. It must never
persist plaintext private chat/message/embed content; clients persist imported
content only after local encryption through normal chat paths.
"""

from __future__ import annotations

import hashlib
import json
import uuid
import zipfile
from io import BytesIO
from typing import Any, Awaitable, Callable

import yaml


FREE_IMPORT_CHATS_PER_30_DAYS = 3
PAID_IMPORT_BATCH_LIMIT = 30
PAID_IMPORT_DEFAULT_SELECTION = 20
SUPPORTED_OPENMATES_DOMAINS = {"chats", "embeds", "referenced_uploads", "uploads"}


class ImportParseError(ValueError):
    """Raised when an import source cannot be parsed safely."""


class ImportCreditError(ValueError):
    """Raised when an import would violate strict no-debt credit rules."""


class ImportScanError(RuntimeError):
    """Raised when selected plaintext cannot be scanned safely."""


Scanner = Callable[[list[dict[str, Any]]], Awaitable[list[dict[str, Any]]] | list[dict[str, Any]]]


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
            if required_name not in names:
                raise ImportParseError(f"{source_label} is missing {required_name}")
            return archive.read(required_name).decode("utf-8")
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
        credits_per_chat_estimate: int = 1,
    ) -> None:
        self.directus_service = directus_service
        self.scanner = scanner
        self.credits_per_chat_estimate = credits_per_chat_estimate

    async def preview_import(
        self,
        *,
        user_id: str,
        source: str,
        chats: list[dict[str, Any]],
        available_credits: int,
        imported_count_last_30_days: int,
        existing_fingerprints: set[str],
    ) -> dict[str, Any]:
        del user_id, source
        free_remaining = max(FREE_IMPORT_CHATS_PER_30_DAYS - imported_count_last_30_days, 0)
        duplicate_fingerprints = [
            str(chat.get("source_fingerprint"))
            for chat in chats
            if chat.get("source_fingerprint") in existing_fingerprints
        ]
        total_chats = len(chats)
        if available_credits > 0:
            max_batch_count = min(PAID_IMPORT_BATCH_LIMIT, total_chats)
            default_selection_count = min(PAID_IMPORT_DEFAULT_SELECTION, max_batch_count)
            estimated_credits = default_selection_count * self.credits_per_chat_estimate
            can_import = available_credits >= estimated_credits
            reason = "paid_import_available" if can_import else "insufficient_credits"
        else:
            max_batch_count = min(free_remaining, total_chats)
            default_selection_count = max_batch_count
            estimated_credits = 0
            can_import = max_batch_count > 0
            reason = "free_import_allowance_remaining" if can_import else "insufficient_credits"

        return {
            "import_id": str(uuid.uuid4()),
            "free_remaining": free_remaining,
            "chat_limit": max_batch_count,
            "default_selection_count": default_selection_count,
            "max_batch_count": max_batch_count,
            "duplicate_fingerprints": duplicate_fingerprints,
            "estimated_credits": estimated_credits,
            "can_import": can_import,
            "reason": reason,
        }

    async def reserve_import_credits(
        self,
        *,
        user_id: str,
        import_id: str,
        selected_chat_count: int,
        available_credits: int,
    ) -> dict[str, Any]:
        del user_id
        required_credits = selected_chat_count * self.credits_per_chat_estimate
        if available_credits < required_credits:
            raise ImportCreditError("Insufficient credits for import without negative balance")
        return {"import_id": import_id, "credits_reserved": required_credits}

    async def scan_selected_chats(self, *, user_id: str, import_id: str, chats: list[dict[str, Any]]) -> dict[str, Any]:
        del user_id, import_id
        if self.scanner is not None:
            try:
                scanned = self.scanner(chats)
                if hasattr(scanned, "__await__"):
                    chats = await scanned  # type: ignore[assignment]
                else:
                    chats = scanned  # type: ignore[assignment]
            except Exception as exc:
                raise ImportScanError("Import scanner unavailable") from exc
        return {"chats": chats, "credits_reserved": len(chats) * self.credits_per_chat_estimate, "messages_blocked": [], "failures": []}

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
        failures = client_failures or []
        status = "partial" if failures else "complete"
        if self.directus_service is not None:
            await self.directus_service.create_item(
                "account_imports",
                {
                    "user_id": user_id,
                    "import_id": import_id,
                    "imported_chat_ids": imported_chat_ids,
                    "source_fingerprints": source_fingerprints,
                    "encrypted_record_counts": encrypted_record_counts,
                    "status": status,
                    "failures": failures,
                },
                admin_required=True,
            )
        return {
            "status": status,
            "credits_charged": 0,
            "credits_released": 0,
            "imported_count": len(imported_chat_ids),
            "failures": failures,
        }

    async def report_skipped_domains(self, *, source: str, domains: list[str]) -> dict[str, Any]:
        return {
            "source": source,
            "skipped_domains": sorted(domains),
            "reason": "unsupported_in_account_import_v1",
            "follow_up": "OPE-588",
        }
