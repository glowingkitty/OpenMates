"""Owner-scoped active reminder listing shared by REST and the sync overview.

Reminder prompts and targets are Vault-encrypted for server-side scheduling;
this helper decrypts only the target ID and a 100-character prompt preview for
the authenticated owner, exactly as GET /v1/settings/reminders always has. The
chat workspace overview (architecture.sync@2 due-soon set) reuses it so both
paths keep one implementation and the same encryption boundary.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.apps.reminder.utils import format_reminder_time

logger = logging.getLogger(__name__)

PROMPT_PREVIEW_CHARS = 100


async def build_active_reminder_items(
    reminders: list[dict[str, Any]],
    encryption_service: Any,
    *,
    include_recent_fired: bool,
    upcoming_hours: int,
    recent_hours: int,
    now: int | None = None,
) -> list[dict[str, Any]]:
    """Filter reminder rows by the requested windows and project display fields."""
    current_time = int(time.time()) if now is None else now
    upcoming_cutoff = current_time + upcoming_hours * 3600 if upcoming_hours > 0 else None
    recent_cutoff = current_time - recent_hours * 3600
    items: list[dict[str, Any]] = []
    for reminder in reminders:
        reminder_id = reminder.get("id") or reminder.get("reminder_id", "")
        vault_key_id = reminder.get("vault_key_id")
        trigger_at = reminder.get("trigger_at", 0) or 0
        target_type = reminder.get("target_type", "new_chat")
        reminder_status = reminder.get("status", "pending")
        if upcoming_cutoff is not None and reminder_status == "pending" and trigger_at > upcoming_cutoff:
            continue
        if include_recent_fired and reminder_status == "fired" and trigger_at < recent_cutoff:
            continue
        target_chat_id = None
        target_embed_id = None
        encrypted_target = reminder.get("encrypted_target_chat_id")
        if encrypted_target and vault_key_id:
            try:
                target_id = await encryption_service.decrypt_with_user_key(
                    ciphertext=encrypted_target, key_id=vault_key_id,
                )
                if target_type == "embed":
                    target_embed_id = target_id
                else:
                    target_chat_id = target_id
            except Exception as exc:  # Vault/transit failures leave the reminder listed without a target.
                logger.warning("Could not decrypt reminder target %s: %s", reminder_id, type(exc).__name__)
        prompt_preview = ""
        encrypted_prompt = reminder.get("encrypted_prompt", "")
        if encrypted_prompt and vault_key_id:
            try:
                decrypted = await encryption_service.decrypt_with_user_key(
                    ciphertext=encrypted_prompt, key_id=vault_key_id,
                )
                if decrypted:
                    prompt_preview = decrypted[:PROMPT_PREVIEW_CHARS]
                    if len(decrypted) > PROMPT_PREVIEW_CHARS:
                        prompt_preview += "..."
            except Exception as exc:  # Same fallback the settings list always used.
                logger.warning("Could not decrypt reminder prompt %s: %s", reminder_id, type(exc).__name__)
                prompt_preview = "[Encrypted]"
        items.append({
            "reminder_id": reminder_id,
            "prompt_preview": prompt_preview,
            "trigger_at": trigger_at,
            "trigger_at_formatted": format_reminder_time(trigger_at, reminder.get("timezone", "UTC")),
            "target_type": target_type,
            "target_chat_id": target_chat_id,
            "target_embed_id": target_embed_id,
            "is_repeating": reminder.get("repeat_config") is not None,
            "status": reminder_status,
        })
    items.sort(key=lambda item: item.get("trigger_at", 0))
    return items
