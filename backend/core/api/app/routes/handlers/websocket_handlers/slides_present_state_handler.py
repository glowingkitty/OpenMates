"""Relay one client-encrypted slides presentation-remote frame to the user's other devices.

Pure relay (feature.slides, slides.present.remote-relay-private): the server
checks the sender owns the embed, bounds and rate-limits the frame, then forwards
the opaque ciphertext unchanged. Nothing is persisted and the payload is never
logged.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

MAX_CIPHERTEXT_CHARS = 1024
BURST_FRAMES = 20
WINDOW_SECONDS = 1.0
ACCESS_TTL_SECONDS = 30.0
_MAX_TRACKED_KEYS = 4096
_EMBED_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# In-process state only (per worker): frame timestamps and recent allow verdicts.
_frames: dict[tuple[str, str], list[float]] = {}
_allowed: dict[tuple[str, str], float] = {}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _rate_limited(key: tuple[str, str], now: float) -> bool:
    recent = [t for t in _frames.get(key, []) if now - t < WINDOW_SECONDS]
    if len(recent) >= BURST_FRAMES:
        _frames[key] = recent
        return True
    recent.append(now)
    _frames[key] = recent
    if len(_frames) > _MAX_TRACKED_KEYS:
        for stale in [k for k, v in _frames.items() if not v or now - v[-1] >= WINDOW_SECONDS]:
            _frames.pop(stale, None)
    return False


async def _owns_embed(directus_service: Any, user_id: str, embed_id: str, now: float) -> bool:
    key = (user_id, embed_id)
    if now - _allowed.get(key, -ACCESS_TTL_SECONDS) < ACCESS_TTL_SECONDS:
        return True
    embed = await directus_service.embed.get_embed_by_id(embed_id)
    if not embed or embed.get("hashed_user_id") != _hash(user_id):
        _allowed.pop(key, None)
        return False
    if len(_allowed) > _MAX_TRACKED_KEYS:
        _allowed.clear()
    _allowed[key] = now
    return True


async def handle_slides_present_state(
    *,
    manager: Any,
    directus_service: Any,
    user_id: str,
    device_fingerprint_hash: str,
    payload: Any,
) -> None:
    payload = payload if isinstance(payload, dict) else {}
    embed_id = payload.get("embed_id")
    ciphertext = payload.get("ciphertext")

    async def reject(code: str) -> None:
        await manager.send_personal_message(
            {
                "type": "slides_present_state_rejected",
                "payload": {
                    "embed_id": embed_id if isinstance(embed_id, str) and len(embed_id) <= 128 else None,
                    "code": code,
                },
            },
            user_id,
            device_fingerprint_hash,
        )

    if not isinstance(embed_id, str) or not _EMBED_ID.fullmatch(embed_id) or not isinstance(ciphertext, str) or not ciphertext:
        await reject("invalid")
        return
    if len(ciphertext) > MAX_CIPHERTEXT_CHARS:
        await reject("too_large")
        return
    now = time.monotonic()
    if _rate_limited((user_id, embed_id), now):
        await reject("rate_limited")
        return
    if not await _owns_embed(directus_service, user_id, embed_id, now):
        await reject("forbidden")
        return

    logger.debug("slides_present_state relay embed_hash=%s ciphertext_len=%d", _hash(embed_id)[:12], len(ciphertext))
    await manager.broadcast_to_user(
        message={"type": "slides_present_state", "payload": {"embed_id": embed_id, "ciphertext": ciphertext}},
        user_id=user_id,
        exclude_device_hash=device_fingerprint_hash,
    )
