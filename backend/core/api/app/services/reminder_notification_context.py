"""Bounded, user-addressed email context; never a general chat decryption path."""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import re
import secrets
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_METADATA_BYTES = 8192
MAX_IMAGE_BASE64_BYTES = 160 * 1024
PREVIEW_RETENTION_SECONDS = 90 * 86400
PREVIEW_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
KINDS = {"chat", "event", "appointment", "travel_connection", "travel_stay", "home_listing", "embed"}
TEXT_LIMITS = {
    "title": 200, "description": 2000, "summary": 500, "icon": 64,
    "category": 64, "app_id": 64, "starts_at": 80, "ends_at": 80,
    "timezone": 64, "location": 1000,
}


def normalize_notification_context(value: Any) -> dict[str, Any] | None:
    """Validate allowlisted facts without echoing private input in errors."""
    if value is None:
        return None
    allowed = {"version", "kind", "facts", "image_base64", *TEXT_LIMITS}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError("Invalid reminder notification context")
    if (type(value.get("version")) is not int or value["version"] != 1
            or not isinstance(value.get("kind"), str) or value["kind"] not in KINDS):
        raise ValueError("Invalid reminder notification context version or kind")
    result: dict[str, Any] = {"version": 1, "kind": value["kind"]}
    for field, limit in TEXT_LIMITS.items():
        text = value.get(field)
        if text is None:
            continue
        if not isinstance(text, str) or len(text) > limit or "\x00" in text:
            raise ValueError("Invalid reminder notification context field")
        if field == "description":
            text = html.unescape(re.sub(r"<[^>]*>", "", text))
        result[field] = text.strip()
    if not result.get("title"):
        raise ValueError("Reminder notification context requires a title")
    for field in ("starts_at", "ends_at"):
        if result.get(field):
            try:
                datetime.fromisoformat(result[field].replace("Z", "+00:00"))
            except ValueError:
                raise ValueError("Invalid reminder notification date") from None
    if result.get("timezone"):
        try:
            ZoneInfo(result["timezone"])
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Invalid reminder notification timezone") from None
    facts = value.get("facts", [])
    if not isinstance(facts, list) or len(facts) > 8:
        raise ValueError("Invalid reminder notification facts")
    result["facts"] = []
    for fact in facts:
        if (not isinstance(fact, dict) or set(fact) != {"label", "value"}
                or not isinstance(fact["label"], str) or len(fact["label"]) > 64
                or not isinstance(fact["value"], str) or len(fact["value"]) > 512):
            raise ValueError("Invalid reminder notification fact")
        result["facts"].append({"label": fact["label"].strip(), "value": fact["value"].strip()})
    if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_METADATA_BYTES:
        raise ValueError("Reminder notification context is too large")
    image = value.get("image_base64")
    if image:
        if not isinstance(image, str) or len(image) > MAX_IMAGE_BASE64_BYTES:
            raise ValueError("Reminder notification image is too large")
        try:
            from PIL import Image

            data = base64.b64decode(image, validate=True)
            with Image.open(io.BytesIO(data)) as decoded:
                if decoded.format not in {"PNG", "JPEG"} or decoded.width * decoded.height > 2_000_000:
                    raise ValueError("Invalid reminder notification image")
                decoded.verify()
        except Exception:
            raise ValueError("Invalid reminder notification image") from None
        result["image_base64"] = image
    return result


def create_preview_token() -> tuple[str, str]:
    """Keep only the digest queryable; the bearer stays inside Vault ciphertext."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def reminder_email_content_allowed(profile: dict[str, Any]) -> bool:
    """Rich reminder defaults do not override a deliberate hide-content choice."""
    choices = profile.get("email_notification_preference_choices") or {}
    if isinstance(choices, str):
        try:
            choices = json.loads(choices)
        except ValueError:
            return False
    if not isinstance(choices, dict):
        return False
    choice = choices.get("includeContent")
    return not (isinstance(choice, dict) and choice.get("source") == "user" and choice.get("value") is False)


async def resolve_reminder_source_chat(
    directus: Any, user_id: str, *, chat_id: str | None = None, embed_id: str | None = None,
) -> str | None:
    """Resolve a Personal target using fresh owner/source checks, including legacy embeds."""
    owner = hashlib.sha256(user_id.encode()).hexdigest()
    embed = None
    if embed_id:
        embed = await directus.embed.get_embed_by_id(embed_id)
        if not embed:
            # Public calendar events are registered server-side and remain guest
            # destinations. Arbitrary missing/private IDs never gain this exemption.
            from backend.shared.python_utils.openmates_event_registry import load_openmates_events

            public_events = load_openmates_events().get("events", [])
            if any(item.get("id") == embed_id and item.get("status") == "published" for item in public_events):
                return None
            raise ValueError("Reminder target unavailable")
        if embed.get("hashed_user_id") != owner or embed.get("hashed_team_id"):
            raise ValueError("Reminder target unavailable")
        source_hash = embed.get("hashed_chat_id")
        if not source_hash:
            raise ValueError("Reminder source unavailable")
        if chat_id and hashlib.sha256(chat_id.encode()).hexdigest() != source_hash:
            raise ValueError("Reminder source unavailable")
        if not chat_id:
            candidates = await directus.chat.get_chat_activity_candidates(user_id)
            chat_id = next((row["id"] for row in candidates
                            if isinstance(row, dict) and isinstance(row.get("id"), str)
                            and hashlib.sha256(row["id"].encode()).hexdigest() == source_hash), None)
    if not chat_id:
        raise ValueError("Reminder source unavailable")
    chat = await directus.chat.get_chat_metadata(chat_id, admin_required=True)
    if (not chat or chat.get("hashed_user_id") != owner or chat.get("hashed_team_id")
            or chat.get("storage_state") == "deleting"):
        raise ValueError("Reminder target unavailable")
    if embed and embed.get("parent_embed_id"):
        parent_id = embed["parent_embed_id"]
        parent = await directus.embed.get_embed_by_id(parent_id)
        if (not parent or parent.get("hashed_user_id") != owner
                or parent.get("hashed_chat_id") != embed.get("hashed_chat_id")
                or parent.get("hashed_team_id") or parent.get("parent_embed_id")
                or (embed.get("root_embed_id") and embed.get("root_embed_id") != parent_id)):
            raise ValueError("Reminder target unavailable")
    return chat_id
