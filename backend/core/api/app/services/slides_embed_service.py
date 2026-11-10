"""Deck embed (type="deck") creation and update for ```slides fences.

Mixed into EmbedService so the large embed_service.py only gains the base-class
reference. Content is always the normalised markup produced by
backend.shared.python_utils.slides_markup; nothing un-normalised is stored.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from toon_format import decode, encode

from backend.shared.python_utils.slides_markup import NormalisedDeck

logger = logging.getLogger(__name__)


def deck_embed_content(deck: NormalisedDeck, embed_ref: Optional[str], status: str) -> Dict[str, Any]:
    """Stored/streamed TOON payload for a deck embed."""
    return {
        "type": "deck",
        "app_id": "slides",
        "skill_id": "deck",
        "slides_markup": deck.markup,
        "title": deck.title,
        "slide_count": deck.slide_count,
        "aspect": deck.aspect,
        "embed_ref": embed_ref,
        "status": status,
    }


class SlidesEmbedMixin:
    """Deck embed methods; relies on EmbedService caching/send helpers."""

    async def create_deck_embed(
        self,
        chat_id: str,
        message_id: str,
        user_id: str,
        user_id_hash: str,
        user_vault_key_id: str,
        deck: NormalisedDeck,
        task_id: Optional[str] = None,
        log_prefix: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Create a finished deck embed from a complete, normalised deck.

        Returns {"embed_id", "embed_reference"} or None when creation failed.
        """
        embed_id = str(uuid.uuid4())
        embed_ref = self._generate_direct_embed_ref("deck", embed_id, {"title": deck.title})
        placeholder_toon = encode(deck_embed_content(deck, embed_ref, "processing"))
        encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
            placeholder_toon, user_vault_key_id
        )
        now = int(datetime.now().timestamp())
        embed_data = {
            "embed_id": embed_id,
            "type": "deck",
            "chat_id": chat_id,
            "message_id": message_id,
            "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
            "hashed_message_id": hashlib.sha256(message_id.encode()).hexdigest(),
            "hashed_task_id": hashlib.sha256(task_id.encode()).hexdigest() if task_id else None,
            "status": "processing",
            "hashed_user_id": user_id_hash,
            "is_private": False,
            "is_shared": False,
            "encryption_mode": "client",
            "embed_ids": None,
            "encrypted_content": encrypted_content,
            "created_at": now,
            "updated_at": now,
        }
        await self._cache_embed(embed_id, embed_data, chat_id, user_id_hash, user_vault_key_id, user_id)
        await self.send_embed_data_to_client(
            embed_id=embed_id, embed_type="deck", content_toon=placeholder_toon,
            chat_id=chat_id, message_id=message_id, user_id=user_id,
            user_id_hash=user_id_hash, status="processing", task_id=task_id,
            is_private=False, is_shared=False, created_at=now, updated_at=now,
            log_prefix=log_prefix,
        )
        updated = await self.update_deck_embed_content(
            embed_id=embed_id, deck=deck, chat_id=chat_id, user_id=user_id,
            user_id_hash=user_id_hash, user_vault_key_id=user_vault_key_id,
            status="finished", log_prefix=log_prefix,
        )
        if not updated:
            return None
        return {
            "embed_id": embed_id,
            "embed_reference": '{"type": "deck", "embed_id": "%s"}' % embed_id,
        }

    async def update_deck_embed_content(
        self,
        embed_id: str,
        deck: NormalisedDeck,
        chat_id: str,
        user_id: str,
        user_id_hash: str,
        user_vault_key_id: str,
        status: str = "finished",
        version_number: Optional[int] = None,
        content_hash: Optional[str] = None,
        version_history_rows: Optional[List[Dict[str, Any]]] = None,
        log_prefix: str = "",
    ) -> bool:
        """Store new normalised deck content and notify clients."""
        cached_embed = await self._get_cached_embed(embed_id, user_vault_key_id, log_prefix)
        if not cached_embed:
            logger.warning(f"{log_prefix} Deck embed {embed_id} not found in cache, cannot update")
            return False
        existing_ref = None
        existing_toon = await self._get_cached_embed_toon(embed_id, user_vault_key_id, log_prefix)
        if existing_toon:
            existing_ref = (decode(existing_toon) or {}).get("embed_ref")
        embed_ref = existing_ref or self._generate_direct_embed_ref("deck", embed_id, {"title": deck.title})

        updated_toon = encode(deck_embed_content(deck, embed_ref, status))
        encrypted_content, _ = await self.encryption_service.encrypt_with_user_key(
            updated_toon, user_vault_key_id
        )
        updated_embed_data = {
            **cached_embed,
            "encrypted_content": encrypted_content,
            "status": status,
            "updated_at": int(datetime.now().timestamp()),
        }
        if version_number is not None:
            updated_embed_data["version_number"] = version_number
        if content_hash is not None:
            updated_embed_data["content_hash"] = content_hash

        await self.send_embed_data_to_client(
            embed_id=embed_id, embed_type="deck", content_toon=updated_toon,
            chat_id=chat_id, message_id=cached_embed.get("message_id", ""),
            user_id=user_id, user_id_hash=user_id_hash, status=status,
            task_id=cached_embed.get("hashed_task_id"),
            is_private=cached_embed.get("is_private", False),
            is_shared=cached_embed.get("is_shared", False),
            version_number=version_number, content_hash=content_hash,
            version_history_rows=version_history_rows,
            created_at=cached_embed.get("created_at"),
            updated_at=updated_embed_data["updated_at"], log_prefix=log_prefix,
            check_cache_status=False,
            finished_cache_data=updated_embed_data if status == "finished" else None,
            finished_cache_vault_key_id=user_vault_key_id,
        )
        if status == "finished":
            self._schedule_embed_persistence_fallback(embed_id)
        else:
            await self._cache_embed(embed_id, updated_embed_data, chat_id, user_id_hash, user_vault_key_id, user_id)
        return True
