"""Wellbeing layer glue: validated history, prompt instruction, helpline card, counters.

Nothing here is stored per user: the history round-trips through the client, the
level is recomputed each request, and only anonymous daily counters are kept.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from toon_format import encode

from backend.apps.ai.processing.wellbeing_level import (
    WellbeingAssessment, compute_level, sanitize_history, sanitize_scores,
)
from backend.shared.providers.throughline.client import ThroughlineError, fetch_helplines

logger = logging.getLogger(__name__)

DIRECTORY_URL = "https://findahelpline.com"
COUNTER_TTL_SECONDS = 3 * 24 * 3600
EVENT_SCORES = "wellbeing_scores_updated"
CARD_EMBED_TYPE = "helplines"
EVENT_THRESHOLD = 0.2
_INSTRUCTIONS_FILE = Path(__file__).resolve().parents[1] / "base_instructions.yml"
EMERGENCY_NUMBERS = {
    "US": "911", "CA": "911", "GB": "999", "AU": "000", "NZ": "111", "IN": "112", "BR": "192", "JP": "119",
    **{code: "112" for code in ("DE", "FR", "ES", "IT", "NL", "PL", "SE", "CZ", "AT", "IE", "PT", "BE")},
}
DEFAULT_EMERGENCY = "112"
# Request country is not part of the inference payload, so the detected output language picks the default.
LANGUAGE_COUNTRY = {
    "en": "US", "de": "DE", "fr": "FR", "es": "ES", "it": "IT", "pt": "BR", "ja": "JP", "hi": "IN",
    "nl": "NL", "pl": "PL", "sv": "SE", "cs": "CZ",
}
_instruction_cache: dict[str, str] | None = None


def incoming_history(raw: Any) -> list[dict[str, Any]]:
    """Validate the client history; malformed input is logged without values and treated as empty."""
    history = sanitize_history(raw)
    if history is None:
        logger.warning("[WELLBEING] Ignoring malformed incoming history")
        return []
    return history


def assess(request_data: Any, preprocessing_result: Any) -> WellbeingAssessment | None:
    """Level for this request, or None when preprocessing produced no scores and no history exists."""
    history = incoming_history(getattr(request_data, "wellbeing_scores", None))
    raw = getattr(preprocessing_result, "wellbeing_scores", None)
    current = sanitize_scores(raw) if raw is not None else {}
    if current is None:
        logger.warning("[WELLBEING] Ignoring malformed current scores")
        current = {}
    if not current and not history:
        return None
    return compute_level(history, current)


def _instructions() -> dict[str, str]:
    global _instruction_cache
    if _instruction_cache is None:
        _instruction_cache = yaml.safe_load(_INSTRUCTIONS_FILE.read_text(encoding="utf-8"))["wellbeing_instructions"]
    return _instruction_cache


def instruction_for(assessment: WellbeingAssessment | None) -> str | None:
    """System-prompt text for the level; None at level 0."""
    if assessment is None or assessment.level == 0:
        return None
    texts = _instructions()
    parts = [texts[f"level_{assessment.level}"].strip()]
    if assessment.dominant_signal in {"reality_loss", "mania"}:
        parts.append(texts["grounding"].strip())
    return "\n".join(parts)


def resolve_country(language: str | None) -> str:
    return LANGUAGE_COUNTRY.get(language or "en", "US")


async def build_card(secrets_manager: Any, language: str | None) -> dict[str, Any]:
    """Helpline card payload; emergency-only when the directory key is absent or the call fails."""
    country, lang = resolve_country(language), language or "en"
    lines: list[dict[str, Any]] | None
    try:
        lines = await fetch_helplines(secrets_manager, country, lang)
    except ThroughlineError as exc:
        logger.warning("[WELLBEING] Helpline directory failed, using emergency-only card: %s", exc)
        lines = None
    return {
        "country": country, "language": lang, "lines": lines or [],
        "emergency_number": EMERGENCY_NUMBERS.get(country, DEFAULT_EMERGENCY),
        "directory_url": DIRECTORY_URL, "source": "throughline" if lines else "emergency_only",
    }


async def count_level(cache_service: Any, level: int) -> None:
    """Anonymous daily counters; no user or chat identifier."""
    if level == 0:
        return
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key = f"wellbeing:{'checkin' if level == 1 else 'card_shown'}:{day}"
    client = await cache_service.client
    if client is None:
        logger.warning("[WELLBEING] Counter skipped: cache unavailable")
        return
    await client.incr(key)
    await client.expire(key, COUNTER_TTL_SECONDS)


async def publish(cache_service: Any, request_data: Any, preprocessing_result: Any) -> WellbeingAssessment | None:
    """Emit the history update as an owner-scoped cache event and count the level; the card is an embed (create_card_embed)."""
    assessment = assess(request_data, preprocessing_result)
    if assessment is None or cache_service is None:
        return assessment
    channel = f"user_cache_events:{request_data.user_id}"
    had_history = bool(incoming_history(getattr(request_data, "wellbeing_scores", None)))
    current = sanitize_scores(getattr(preprocessing_result, "wellbeing_scores", None)) or {}
    if had_history or any(value >= EVENT_THRESHOLD for value in current.values()):
        await cache_service.publish_event(channel, {"event_type": EVENT_SCORES, "payload": {
            "chat_id": request_data.chat_id, "scores": assessment.updated_history}})
    await count_level(cache_service, assessment.level)
    logger.info("[WELLBEING] level=%d acute=%s", assessment.level, assessment.acute)
    return assessment


def card_due(assessment: WellbeingAssessment | None) -> bool:
    """The helpline card is due at level 2 and above (acute signals always reach level 3)."""
    return assessment is not None and (assessment.level >= 2 or assessment.acute)

async def create_card_embed(embed_service: Any, secrets_manager: Any, request_data: Any,
                            preprocessing_result: Any, message_id: str, user_vault_key_id: str) -> str:
    """Create the finished `helplines` embed for this answer and return its reference block.

    The block goes at the start of the assistant message ("support before the task").
    Raises RuntimeError when the embed could not be cached and delivered.
    """
    card = await build_card(secrets_manager, getattr(preprocessing_result, "output_language", None))
    embed_id = str(uuid.uuid4())
    embed_ref = embed_service._generate_direct_embed_ref(CARD_EMBED_TYPE, embed_id, {"title": "helplines"})
    content = {"type": CARD_EMBED_TYPE, "app_id": "ai", "embed_ref": embed_ref, "status": "finished", **card}
    content_toon = encode(content)
    encrypted, _ = await embed_service.encryption_service.encrypt_with_user_key(content_toon, user_vault_key_id)
    chat_id, user_id = request_data.chat_id, request_data.user_id
    user_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    now = int(datetime.now().timestamp())
    embed_data = {
        "embed_id": embed_id, "type": CARD_EMBED_TYPE, "chat_id": chat_id, "message_id": message_id,
        "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
        "hashed_message_id": hashlib.sha256(message_id.encode()).hexdigest(),
        "hashed_task_id": None, "status": "finished", "hashed_user_id": user_id_hash,
        "is_private": False, "is_shared": False, "encryption_mode": "client", "embed_ids": [],
        "encrypted_content": encrypted, "text_length_chars": len(content_toon),
        "created_at": now, "updated_at": now,
    }
    delivered = await embed_service.send_embed_data_to_client(
        embed_id=embed_id, embed_type=CARD_EMBED_TYPE, content_toon=content_toon, chat_id=chat_id,
        message_id=message_id, user_id=user_id, user_id_hash=user_id_hash, status="finished",
        embed_ids=[], text_length_chars=len(content_toon), created_at=now, updated_at=now,
        log_prefix="[WELLBEING]", check_cache_status=False, app_id="ai", skill_id=None,
        finished_cache_data=embed_data, finished_cache_vault_key_id=user_vault_key_id,
    )
    if not delivered:
        raise RuntimeError("Helpline card embed was not cached and delivered")
    embed_service._schedule_embed_persistence_fallback(embed_id)
    return "```json\n" + json.dumps({"type": CARD_EMBED_TYPE, "embed_id": embed_id}) + "\n```\n\n"

__all__ = ["assess", "build_card", "card_due", "count_level", "create_card_embed", "incoming_history", "instruction_for", "publish"]
