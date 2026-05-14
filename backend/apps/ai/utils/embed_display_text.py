# backend/apps/ai/utils/embed_display_text.py
#
# Utilities for turning technical embed_ref slugs into user-facing inline labels.
# The stream consumer calls these during final response cleanup, while frontend
# rendering remains the primary safety net for already-persisted chats.
# Keep this module pure: no cache, Directus, encryption, or stream dependencies.

import re
from typing import Any, Dict


EMBED_REF_SUFFIX_PATTERN = re.compile(r"-[a-zA-Z0-9]{2,4}$")


def is_bad_embed_display_text(display_text: str, embed_ref: str) -> bool:
    """
    Detect whether visible inline embed link text exposes a technical embed_ref.
    """
    dt = display_text.strip()
    ref = embed_ref.strip()

    if not ref:
        return False

    # [!](embed:ref) is the intentional large-preview card syntax, not a bad
    # inline label. Empty text (five chars: [](embed:ref)) is bad for inline links
    # and must be replaced before it can fall back to the raw technical ref.
    if dt == "!":
        return False
    if not dt:
        return True

    if dt == ref:
        return True

    suffix_match = EMBED_REF_SUFFIX_PATTERN.search(ref)
    if suffix_match:
        suffix_without_dash = suffix_match.group(0)[1:]
        if dt == suffix_without_dash:
            return True

        if "." in dt and EMBED_REF_SUFFIX_PATTERN.search(dt):
            dt_base = EMBED_REF_SUFFIX_PATTERN.sub("", dt)
            ref_base = EMBED_REF_SUFFIX_PATTERN.sub("", ref)
            if dt_base == ref_base:
                return True

        ref_base = EMBED_REF_SUFFIX_PATTERN.sub("", ref)
        if dt == ref_base:
            return True

    return False


def string_value(value: Any) -> str:
    """Return a compact string from scalar or first list value."""
    if value is None:
        return ""
    if isinstance(value, list):
        for item in value:
            text = string_value(item)
            if text:
                return text
        return ""
    text = str(value).strip()
    return text if text and text.lower() not in {"none", "null", "undefined"} else ""


def format_embed_time(value: Any) -> str:
    """Format ISO/plain HH:MM/HHMM values for compact inline labels."""
    text = string_value(value)
    if not text:
        return ""
    if "T" in text:
        text = text.split("T", 1)[1]
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    match = re.search(r"\b(\d{1,2})(\d{2})\b", text)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)}"
    return ""


def format_embed_carrier(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    known = {
        "db": "DB",
        "ice": "ICE",
        "ic": "IC",
        "ec": "EC",
        "flixtrain": "FlixTrain",
        "flixzug": "FlixTrain",
    }
    lower = text.lower()
    if lower in known:
        return known[lower]
    if len(text) <= 4:
        return text.upper()
    return " ".join(part.capitalize() for part in re.split(r"[-_\s]+", text) if part)


def derive_display_text_from_embed_ref(embed_ref: str) -> str:
    """Create a safe user-facing fallback label without exposing the raw ref."""
    ref = embed_ref.strip()
    if not ref:
        return "Open result"

    domain_match = re.match(
        r"^([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)",
        ref,
    )
    if domain_match:
        return domain_match.group(1)

    base = EMBED_REF_SUFFIX_PATTERN.sub("", ref).strip()
    base = re.sub(r"\s*\(\d+\)$", "", base).strip()

    connection_match = re.match(r"^([a-zA-Z][a-zA-Z0-9_-]*)-(\d{4})$", base)
    if connection_match:
        carrier = format_embed_carrier(connection_match.group(1))
        depart = format_embed_time(connection_match.group(2))
        if carrier and depart:
            return f"{carrier} {depart}"

    words = [part for part in re.split(r"[-_]+", base) if part]
    if words and base.lower() not in {"result", "item", "embed"}:
        return " ".join(format_embed_carrier(word) for word in words[:4])

    return "Open result"


def derive_embed_display_title(child_decoded: Dict[str, Any], embed_ref: str) -> str:
    """Choose the best user-facing inline label from child embed content."""
    for key in (
        "title",
        "name",
        "route_display",
        "display_name",
        "summary",
        "filename",
        "file_name",
    ):
        value = string_value(child_decoded.get(key))
        if value and not is_bad_embed_display_text(value, embed_ref):
            return value

    carrier = string_value(
        child_decoded.get("carrier")
        or child_decoded.get("operator")
        or child_decoded.get("airline")
        or child_decoded.get("train")
        or child_decoded.get("carriers")
    )
    depart = format_embed_time(
        child_decoded.get("departure")
        or child_decoded.get("departure_time")
        or child_decoded.get("departs_at")
        or child_decoded.get("start_time")
    )
    arrive = format_embed_time(
        child_decoded.get("arrival")
        or child_decoded.get("arrival_time")
        or child_decoded.get("arrives_at")
        or child_decoded.get("end_time")
    )

    if carrier and depart and arrive:
        return f"{format_embed_carrier(carrier)} {depart}-{arrive}"
    if carrier and depart:
        return f"{format_embed_carrier(carrier)} {depart}"

    return derive_display_text_from_embed_ref(embed_ref)
