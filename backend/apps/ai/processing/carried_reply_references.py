# backend/apps/ai/processing/carried_reply_references.py
#
# Earlier steps of one assistant reply stay visible across continuations.
#
# An async skill continuation (cloud command, recorded test run) and a
# same-turn resume stream under the reply's logical message id and rewrite that
# reply from empty; the client replaces the message with the new stream. Every
# skill card the earlier streams showed (Run, Read files, file changes, the
# created-Project activation) therefore vanished while the next step streamed.
#
# At the end of each stream the reply's embed references are remembered under
# a short-lived key per user, chat and logical message id; the next stream of
# the same reply re-emits them first, in their original order. Only reference
# ids cross this boundary (type, embed_id, app_id, skill_id): never text,
# queries, file contents or results. The embeds themselves stay encrypted.

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

REPLY_REFERENCES_TTL_SECONDS = 2 * 60 * 60
MAX_CARRIED_REFERENCES = 80
_REFERENCE_KEYS = ("type", "embed_id", "app_id", "skill_id")
_FENCE = re.compile(r"```json\s*\n(\{.*?\})\s*\n```", re.DOTALL)
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def reply_references_key(user_id: str, chat_id: str, message_id: str) -> str:
    return f"reply_embed_references:{user_id}:{chat_id}:{message_id}"


def _clean_reference(raw: Any) -> dict[str, str] | None:
    """Ids-only form of one embed reference, or None for anything else."""
    if not isinstance(raw, dict):
        return None
    clean = {key: raw[key] for key in _REFERENCE_KEYS if isinstance(raw.get(key), str)}
    if not clean.get("type") or not clean.get("embed_id"):
        return None
    if not all(_SAFE_VALUE.match(value) for value in clean.values()):
        return None
    return clean


def extract_reply_references(text: str | None) -> list[dict[str, str]]:
    """Embed references of a reply in order of appearance, deduplicated by embed id."""
    references: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _FENCE.finditer(text or ""):
        try:
            clean = _clean_reference(json.loads(match.group(1)))
        except ValueError:
            continue
        if clean and clean["embed_id"] not in seen:
            seen.add(clean["embed_id"])
            references.append(clean)
    return references[:MAX_CARRIED_REFERENCES]


def reference_embed_id(raw_reference: str) -> str | None:
    """The embed id of one serialized reference, or None when it is not one."""
    try:
        clean = _clean_reference(json.loads(raw_reference))
    except ValueError:
        return None
    return clean["embed_id"] if clean else None


def reference_block(reference: dict[str, str]) -> str:
    return f"```json\n{json.dumps(reference)}\n```\n\n"


async def store_reply_references(
    cache_service: Any, *, user_id: str, chat_id: str, message_id: str, text: str | None,
) -> None:
    """Remember the finished stream's references for a later continuation of the same reply."""
    if not cache_service or not user_id or not chat_id or not message_id:
        return
    references = extract_reply_references(text)
    key = reply_references_key(user_id, chat_id, message_id)
    if not references:
        return
    await cache_service.set(key, references, ttl=REPLY_REFERENCES_TTL_SECONDS)


async def load_reply_references(
    cache_service: Any, *, user_id: str, chat_id: str, message_id: str,
) -> list[dict[str, str]]:
    """References earlier streams of this reply showed; empty for a reply's first stream."""
    if not cache_service or not user_id or not chat_id or not message_id:
        return []
    stored = await cache_service.get(reply_references_key(user_id, chat_id, message_id))
    if not isinstance(stored, list):
        return []
    references = [clean for raw in stored if (clean := _clean_reference(raw))]
    return references[:MAX_CARRIED_REFERENCES]
