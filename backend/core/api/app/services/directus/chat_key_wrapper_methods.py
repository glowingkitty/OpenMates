"""
Directus helpers for chat key wrapper rows.

This module owns the backend-only chat key wrapper migration slice. It copies
existing master-wrapped chat key ciphertext into wrapper rows without decrypting
or logging it, and keeps authorization checks separate from wrapper existence.
Future client-facing routes can reuse these helpers for wrapper-first reads.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any


if False:  # TYPE_CHECKING
    from .directus import DirectusService


logger = logging.getLogger(__name__)

CHAT_KEY_WRAPPERS_COLLECTION = "chat_key_wrappers"
CHAT_COLLECTION = "chats"
CHAT_WRAPPER_FIELDS = (
    "id,hashed_chat_id,hashed_user_id,key_type,hashed_project_id,hashed_plan_id,"
    "hashed_team_id,team_key_epoch,encrypted_chat_key,wrapper_version,expires_at,created_at"
)
CHAT_BACKFILL_FIELDS = "id,hashed_user_id,encrypted_chat_key"
MASTER_KEY_TYPE = "master"
WRAPPER_VERSION = 1


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class ChatKeyWrapperMethods:
    def __init__(self, directus_service_instance: "DirectusService") -> None:
        self.directus_service = directus_service_instance

    async def list_authorized_wrappers(
        self,
        chat_id: str,
        user_id: str,
        *,
        key_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return chat wrappers only after verifying chat ownership."""
        if not await self.directus_service.chat.check_chat_ownership(chat_id, user_id):
            logger.warning("Denied chat wrapper read for unauthorized chat access")
            return []

        params: dict[str, Any] = {
            "filter[hashed_chat_id][_eq]": _hash_identifier(chat_id),
            "filter[hashed_user_id][_eq]": _hash_identifier(user_id),
            "fields": CHAT_WRAPPER_FIELDS,
            "limit": -1,
        }
        if key_type:
            params["filter[key_type][_eq]"] = key_type

        wrappers = await self.directus_service.get_items(
            CHAT_KEY_WRAPPERS_COLLECTION,
            params=params,
            no_cache=True,
            admin_required=True,
        )
        if not wrappers or not isinstance(wrappers, list):
            return []
        return wrappers

    async def get_wrappers_by_hashed_chat_ids_batch(
        self,
        hashed_chat_ids: list[str],
        *,
        hashed_user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch wrapper rows for already-authorized chat IDs."""
        if not hashed_chat_ids:
            return []

        rows: list[dict[str, Any]] = []
        batch_size = 20
        for i in range(0, len(hashed_chat_ids), batch_size):
            chunk = hashed_chat_ids[i:i + batch_size]
            params: dict[str, Any] = {
                "filter[hashed_chat_id][_in]": ",".join(chunk),
                "fields": CHAT_WRAPPER_FIELDS,
                "limit": -1,
            }
            if hashed_user_id:
                params["filter[hashed_user_id][_eq]"] = hashed_user_id
            batch = await self.directus_service.get_items(
                CHAT_KEY_WRAPPERS_COLLECTION,
                params=params,
                no_cache=True,
                admin_required=True,
            )
            if batch and isinstance(batch, list):
                rows.extend(batch)
        return rows

    async def ensure_master_wrapper_for_chat(
        self,
        *,
        chat_id: str,
        hashed_user_id: str,
        encrypted_chat_key: str,
    ) -> bool:
        """Ensure a master wrapper exists for a chat row-level fallback key."""
        if not chat_id or not hashed_user_id or not encrypted_chat_key:
            return False

        hashed_chat_id = _hash_identifier(chat_id)
        existing = await self._get_existing_master_wrapper(
            hashed_chat_id=hashed_chat_id,
            hashed_user_id=hashed_user_id,
        )
        if existing:
            return True

        return await self._create_master_wrapper(
            hashed_chat_id=hashed_chat_id,
            hashed_user_id=hashed_user_id,
            encrypted_chat_key=encrypted_chat_key,
        )

    async def backfill_master_wrappers(
        self,
        *,
        limit: int = 500,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Copy existing row-level master-wrapped chat keys into wrapper rows."""
        result = {"checked": 0, "created": 0, "skipped": 0, "failed": 0}
        chats = await self.directus_service.get_items(
            CHAT_COLLECTION,
            params={
                "fields": CHAT_BACKFILL_FIELDS,
                "limit": limit,
            },
            no_cache=True,
            admin_required=True,
        )
        if not chats or not isinstance(chats, list):
            return result

        for chat in chats:
            result["checked"] += 1
            chat_id = chat.get("id")
            hashed_user_id = chat.get("hashed_user_id")
            encrypted_chat_key = chat.get("encrypted_chat_key")
            if not chat_id or not hashed_user_id or not encrypted_chat_key:
                result["skipped"] += 1
                logger.info("Skipped chat wrapper backfill row with missing required migration fields")
                continue

            hashed_chat_id = _hash_identifier(str(chat_id))
            existing = await self._get_existing_master_wrapper(
                hashed_chat_id=hashed_chat_id,
                hashed_user_id=str(hashed_user_id),
            )
            if existing:
                result["skipped"] += 1
                continue

            result["created"] += 1
            if dry_run:
                continue

            created = await self._create_master_wrapper(
                hashed_chat_id=hashed_chat_id,
                hashed_user_id=str(hashed_user_id),
                encrypted_chat_key=str(encrypted_chat_key),
            )
            if not created:
                result["created"] -= 1
                result["failed"] += 1

        logger.info(
            "Chat key wrapper backfill completed: checked=%s created=%s skipped=%s failed=%s dry_run=%s",
            result["checked"],
            result["created"],
            result["skipped"],
            result["failed"],
            dry_run,
        )
        return result

    async def _get_existing_master_wrapper(
        self,
        *,
        hashed_chat_id: str,
        hashed_user_id: str,
    ) -> dict[str, Any] | None:
        rows = await self.directus_service.get_items(
            CHAT_KEY_WRAPPERS_COLLECTION,
            params={
                "filter[hashed_chat_id][_eq]": hashed_chat_id,
                "filter[hashed_user_id][_eq]": hashed_user_id,
                "filter[key_type][_eq]": MASTER_KEY_TYPE,
                "fields": "id",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if rows and isinstance(rows, list):
            return rows[0]
        return None

    async def _create_master_wrapper(
        self,
        *,
        hashed_chat_id: str,
        hashed_user_id: str,
        encrypted_chat_key: str,
    ) -> bool:
        payload = {
            "hashed_chat_id": hashed_chat_id,
            "hashed_user_id": hashed_user_id,
            "key_type": MASTER_KEY_TYPE,
            "encrypted_chat_key": encrypted_chat_key,
            "wrapper_version": WRAPPER_VERSION,
            "created_at": int(time.time()),
        }
        success, _created = await self.directus_service.create_item(
            CHAT_KEY_WRAPPERS_COLLECTION,
            payload,
            admin_required=True,
        )
        if not success:
            logger.error("Failed to create chat key wrapper row")
        return bool(success)
