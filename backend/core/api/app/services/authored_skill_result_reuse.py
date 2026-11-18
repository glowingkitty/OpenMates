"""Reuse of skill result cards inside an assistant-authored results block.

A skill (for example travel ``search_connections``) already produced complete
result cards: legs, stations with coordinates, platforms, provider and booking
link. When the answer then presents some of those results in an
``openmates_embeds`` block, re-authoring them creates thin copies without that
data (no map, no booking provider, raw times). Two paths prevent this:

* an explicit ``{"id", "existing": "<embed_ref>"}`` item may name a skill
  result card of this chat (``skill_result_card_kind``), and
* a newly written ``researched`` item whose identity facts match a skill result
  card of this chat is bound to that card instead (``SkillResultMatcher``).

Candidates come only from the chat's authorized embed_ref index (refs handed to
this turn: history embeds and this turn's skill results); a guessed id never
reaches storage. A candidate must belong to the same owner and chat, be
finished, and its decrypted content must carry the producing skill's identity.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from toon_format import decode

from backend.apps.ai.utils.authored_result_fences import get_authoring_definitions
from backend.core.api.app.services.authored_existing_cards import record_in_chat

logger = logging.getLogger(__name__)

# Bounds the per-carrier lookup work; the index itself holds at most 256 refs.
MAX_SKILL_RESULT_CANDIDATES = 120


def skill_result_card_kind(record: Mapping[str, Any], content: Any) -> str | None:
    """Return the admitted kind of a skill-produced result card, else None.

    Authored cards carry an ``authoring`` block and are handled by
    ``authored_card_kind``; this accepts only plain skill results whose stored
    type and decrypted producer identity match one admitted kind definition.
    """
    if not isinstance(content, dict) or isinstance(content.get("authoring"), dict):
        return None
    for kind, definition in get_authoring_definitions().items():
        if (definition["backend_type"] == record.get("type") == content.get("type")
                and content.get("app_id") == definition["app_id"]
                and content.get("skill_id") == definition["skill_id"]):
            return kind
    return None


def _instant(value: Any) -> str | None:
    """Normalize an ISO timestamp with offset to a comparable UTC instant."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="minutes")


def _connection_key(content: Mapping[str, Any]) -> tuple[str, str] | None:
    """A connection is identified by its exact departure and arrival instants."""
    departure, arrival = _instant(content.get("departure")), _instant(content.get("arrival"))
    if departure is None or arrival is None:
        legs = content.get("legs")
        if isinstance(legs, list) and legs and isinstance(legs[0], dict) and isinstance(legs[-1], dict):
            departure = departure or _instant(legs[0].get("departure"))
            arrival = arrival or _instant(legs[-1].get("arrival"))
    return (departure, arrival) if departure and arrival else None


# Kinds whose researched items can duplicate a skill result, with their identity key.
IDENTITY_KEYS: dict[str, Callable[[Mapping[str, Any]], tuple[str, ...] | None]] = {
    "travel.connection": _connection_key,
}


class SkillResultMatcher:
    """Lazily indexed skill result cards of one chat, keyed per kind by identity facts."""

    def __init__(self, service: Any, index: Mapping[str, Any] | None, *, chat_id: str,
                 user_id_hash: str, user_vault_key_id: str, log_prefix: str = "") -> None:
        self._service = service
        self._index = index if isinstance(index, Mapping) else {}
        self._chat_id = chat_id
        self._user_id_hash = user_id_hash
        self._user_vault_key_id = user_vault_key_id
        self._log_prefix = log_prefix
        self._keys: dict[str, dict[tuple[str, ...], str]] | None = None

    async def _load(self) -> dict[str, dict[tuple[str, ...], str]]:
        keys: dict[str, dict[tuple[str, ...], str]] = {}
        embed_ids = list(dict.fromkeys(v for v in self._index.values() if isinstance(v, str) and v))
        for embed_id in embed_ids[-MAX_SKILL_RESULT_CANDIDATES:]:
            record = await self._service._get_cached_embed(embed_id, self._user_vault_key_id, self._log_prefix)
            if (not isinstance(record, dict) or record.get("hashed_user_id") != self._user_id_hash
                    or record.get("status") != "finished" or not record_in_chat(record, self._chat_id)):
                continue
            toon = await self._service._get_cached_embed_toon(embed_id, self._user_vault_key_id, self._log_prefix)
            content = decode(toon) if toon else None
            kind = skill_result_card_kind(record, content)
            identity = IDENTITY_KEYS.get(kind) if kind else None
            key = identity(content) if identity else None
            if key is not None:
                # The first (oldest) card with a given identity wins; later duplicates are equal.
                keys.setdefault(kind, {}).setdefault(key, embed_id)
        return keys

    async def match(self, kind: str, content: Mapping[str, Any]) -> str | None:
        """Return the embed id of the skill result card this researched item repeats."""
        identity = IDENTITY_KEYS.get(kind)
        authoring = content.get("authoring")
        origin = authoring.get("origin") if isinstance(authoring, dict) else None
        if identity is None or origin != "researched" or not self._index:
            return None
        key = identity(content)
        if key is None:
            return None
        if self._keys is None:
            self._keys = await self._load()
        embed_id = self._keys.get(kind, {}).get(key)
        if embed_id:
            logger.info("%s Authored %s item reuses the matching skill result card", self._log_prefix, kind)
        return embed_id
