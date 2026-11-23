"""Server-held marker for call turns whose text was pasted, not typed or spoken.

The call WebSocket records the user message id when the client flags a text
submit as pasted. The AI pipeline reads the marker for the call turn, so the
flag cannot be forged through the ordinary chat message payload and needs no
extra field on the turn request.
"""
from __future__ import annotations

from typing import Any

PASTED_TTL_SECONDS = 6 * 3600
MAX_PASTED_PER_CALL = 256

PASTED_TEXT_INSTRUCTION = (
    "The user pasted the text of their latest message into the call instead of "
    "speaking or typing it. Do not read the pasted text aloud and do not quote it "
    "in your spoken reply. Summarise it briefly or refer to it (for example 'the "
    "text you pasted'), then answer what the user needs."
)


def _key(call_id: str) -> str:
    return f"voice:call:{call_id}:pasted"


async def mark_pasted(cache: Any, call_id: str, message_id: str) -> None:
    """Remember that the call turn with this user message id carries pasted text."""
    client = await cache.client
    if client is None:
        raise RuntimeError("Voice call authority unavailable")
    key = _key(call_id)
    if await client.scard(key) >= MAX_PASTED_PER_CALL:
        raise ValueError("Too many pasted turns")
    await client.sadd(key, message_id)
    await client.expire(key, PASTED_TTL_SECONDS)


async def is_pasted(cache: Any, call_id: str | None, message_id: str | None) -> bool:
    """True when the call turn was marked pasted; False for any other turn."""
    if not call_id or not message_id:
        return False
    client = await cache.client
    if client is None:
        raise RuntimeError("Voice call authority unavailable")
    return bool(await client.sismember(_key(call_id), message_id))


def pasted_text_context(pasted: bool) -> str:
    return PASTED_TEXT_INSTRUCTION if pasted else ""
