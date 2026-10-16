"""Conservatively retain Vault ciphertext for unchanged native replay history."""

import hashlib
import json
import logging
import os
from typing import Any


logger = logging.getLogger(__name__)


def _log_fixture_retention(reason: str, client_history: list[dict[str, Any]], *,
                           current_message_id: str, matched_count: int) -> None:
    """Log a fixed boundary reason only for the isolated native replay fixture."""
    if (os.getenv("CI") != "true" or os.getenv("OPENMATES_CI_ISOLATED") != "1"
            or reason not in {
                "cache_rows_invalid", "no_native_ciphertext", "id_invalid",
                "id_mismatch", "role_mismatch", "chat_mismatch",
                "sender_mismatch", "category_mismatch", "timestamp_mismatch",
                "content_mismatch", "validation_error", "matched_prefix",
            }):
        return
    if not any(
        history_message_id(row) == current_message_id
        and isinstance(row.get("content"), str)
        and "<<<TEST_LIVE_MOCK:native_cache_tools_v1" in row["content"]
        for row in client_history if isinstance(row, dict)
    ):
        return
    logger.info("Native fixture retention: reason=%s matched_count=%d", reason, matched_count)


def canonical_content_sha256(content: str) -> str:
    """Hash the original stored Markdown before inference-only transformations."""
    if not isinstance(content, str):
        raise TypeError("Canonical history content must be a string")
    serialized = json.dumps(
        content, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def canonical_history_content(message: dict[str, Any]) -> str:
    """Use the same text representation that client history stores in AI cache."""
    content = message.get("content", "")
    return json.dumps(content) if isinstance(content, dict) else content


def canonical_history_content_sha256(message: dict[str, Any]) -> str:
    """Derive the client history hash from content, ignoring claimed hashes."""
    return canonical_content_sha256(canonical_history_content(message))


def history_message_id(message: dict[str, Any]) -> Any:
    return message.get("message_id") or message.get("client_message_id") or message.get("id")


def history_sender_name(message: dict[str, Any]) -> Any:
    role = message.get("role", "user")
    return message.get("sender_name", "user" if role == "user" else "assistant")


def _matching_sender_name(message: dict[str, Any]) -> Any:
    sender = history_sender_name(message)
    if message.get("role") == "assistant" and sender in (None, "assistant"):
        # The LLM transform ignores assistant sender_name. Final assistant
        # cache rows may store None while a client history omits the field.
        return "assistant"
    return sender


async def retained_native_cache_contexts(
    client_history: list[dict[str, Any]], cached_rows: list[str], *,
    current_message_id: str, chat_id: str, encryption_service: Any, user_vault_key_id: str,
) -> dict[str, str]:
    """Keep server ciphertext only across an identical, ordered history prefix."""
    try:
        parsed_rows = [json.loads(row) for row in cached_rows]
    except (TypeError, ValueError):
        _log_fixture_retention("cache_rows_invalid", client_history,
                               current_message_id=current_message_id, matched_count=0)
        return {}
    if not any(
        isinstance(row, dict) and isinstance(row.get("encrypted_native_cache_context"), str)
        and row["encrypted_native_cache_context"] for row in parsed_rows
    ):
        _log_fixture_retention("no_native_ciphertext", client_history,
                               current_message_id=current_message_id, matched_count=0)
        return {}
    client_rows = [row for row in client_history if history_message_id(row) != current_message_id]
    retained: dict[str, str] = {}
    seen_ids: set[str] = set()
    boundary_reason = "matched_prefix"
    canonical_rows = reversed(parsed_rows)  # Redis LPUSH stores newest first.
    for client_row, cached_row in zip(client_rows, canonical_rows):
        try:
            cached_id = cached_row.get("id")
            client_id = history_message_id(client_row)
            if cached_id == current_message_id:
                break
            if not isinstance(cached_id, str) or not cached_id or cached_id in seen_ids:
                boundary_reason = "id_invalid"
                break
            if client_id != cached_id:
                boundary_reason = "id_mismatch"
                break
            if client_row.get("role") != cached_row.get("role"):
                boundary_reason = "role_mismatch"
                break
            if cached_row.get("chat_id") != chat_id:
                boundary_reason = "chat_mismatch"
                break
            if _matching_sender_name(client_row) != _matching_sender_name(cached_row):
                boundary_reason = "sender_mismatch"
                break
            if client_row.get("category") != cached_row.get("category"):
                boundary_reason = "category_mismatch"
                break
            if ("created_at" not in client_row
                    or int(client_row["created_at"]) != int(cached_row["created_at"])):
                boundary_reason = "timestamp_mismatch"
                break
            client_content = canonical_history_content(client_row)
            if not isinstance(client_content, str):
                boundary_reason = "validation_error"
                break
            cached_content = await encryption_service.decrypt_with_user_key(
                cached_row["encrypted_content"], user_vault_key_id,
            )
            if cached_content != client_content:
                boundary_reason = "content_mismatch"
                break
        except Exception:
            # A malformed row or failed Vault read starts a cold replay
            # boundary. Never log either side of the content comparison.
            boundary_reason = "validation_error"
            break
        seen_ids.add(cached_id)
        ciphertext = cached_row.get("encrypted_native_cache_context")
        if cached_row["role"] == "assistant" and isinstance(ciphertext, str) and ciphertext:
            retained[cached_id] = ciphertext
    _log_fixture_retention(boundary_reason, client_history,
                           current_message_id=current_message_id, matched_count=len(seen_ids))
    return retained


async def add_history_with_optional_native_context(
    cache_service: Any, user_id: str, chat_id: str, cached_message: Any,
    inference_message: Any,
) -> bool:
    """Retry normal AI cache admission after dropping an optional replay field."""
    try:
        admitted = await cache_service.add_message_to_chat_history(
            user_id, chat_id, cached_message.model_dump_json(),
        )
    except Exception:
        admitted = False
    if not admitted and cached_message.encrypted_native_cache_context is not None:
        cached_message.encrypted_native_cache_context = None
        inference_message.encrypted_native_cache_context = None
        admitted = await cache_service.add_message_to_chat_history(
            user_id, chat_id, cached_message.model_dump_json(),
        )
    return bool(admitted)
