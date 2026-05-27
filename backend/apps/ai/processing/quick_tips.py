# backend/apps/ai/processing/quick_tips.py
# Registry and deterministic selection rules for product quick tips.
#
# Quick tips are post-response product nudges shown in the colorful chat card.
# The backend only emits stable slugs; UI copy lives in frontend i18n sources.
# This keeps product wording translated, reviewable, and safe from LLM drift.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


LONG_CHAT_MESSAGE_THRESHOLD = 10


@dataclass(frozen=True)
class QuickTipDefinition:
    slug: str
    description: str
    app_id: Optional[str] = None


QUICK_TIP_DEFINITIONS: tuple[QuickTipDefinition, ...] = (
    QuickTipDefinition(
        slug="shorter-chats-equal-better-responses",
        description=(
            "Use when the chat has become long or contains several unrelated topics. "
            "Explains that shorter topic-specific chats improve answer quality and reduce credits."
        ),
    ),
    QuickTipDefinition(
        slug="search-current-info-next-time",
        description=(
            "Use when a search-capable next step would help with current facts, prices, events, "
            "news, or recent product details. Do not use for a search action the user already completed."
        ),
        app_id="web",
    ),
    QuickTipDefinition(
        slug="travel-can-add-local-context",
        description=(
            "Use when the user is already discussing travel and a related next step would help, "
            "such as local places, events, stays, routes, or practical trip details."
        ),
        app_id="travel",
    ),
    QuickTipDefinition(
        slug="use-apps-for-better-results",
        description=(
            "Use when a specialized OpenMates app would clearly improve a likely next step but no "
            "more specific quick tip fits. Do not use for an app/tool already used in the current task."
        ),
    ),
)

VALID_QUICK_TIP_SLUGS = {definition.slug for definition in QUICK_TIP_DEFINITIONS}


def build_quick_tip_context(available_app_ids: List[str]) -> str:
    """Return compact prompt context describing selectable quick-tip slugs."""

    available_apps = set(available_app_ids)
    lines = []
    for definition in QUICK_TIP_DEFINITIONS:
        if definition.app_id and definition.app_id not in available_apps:
            continue
        lines.append(f"- {definition.slug}: {definition.description}")

    if not lines:
        return ""

    return (
        "\n\nAvailable quick_tip_slug values for product education tips:\n"
        + "\n".join(lines)
        + "\nReturn exactly one slug only when a tip would be timely and useful. "
        "Return an empty string when no tip fits. Never invent slugs."
    )


def select_hardcoded_quick_tip_slug(message_history: List[Dict[str, Any]]) -> Optional[str]:
    """Select deterministic quick tips that should not depend on LLM judgment."""

    chat_message_count = sum(
        1
        for message in message_history
        if message.get("role") in {"user", "assistant"} and message.get("content")
    )
    if chat_message_count > LONG_CHAT_MESSAGE_THRESHOLD:
        return "shorter-chats-equal-better-responses"

    return None


def sanitize_quick_tip_slug(raw_slug: Any, available_app_ids: List[str], task_id: str, logger) -> str:
    """Validate an LLM-selected quick-tip slug against the registry and available apps."""

    if not isinstance(raw_slug, str):
        return ""

    slug = raw_slug.strip()
    if not slug:
        return ""
    if slug not in VALID_QUICK_TIP_SLUGS:
        logger.warning(
            "[Task ID: %s] [PostProcessor] Dropped unknown quick_tip_slug '%s'",
            task_id,
            slug,
        )
        return ""

    available_apps = set(available_app_ids)
    definition = next((item for item in QUICK_TIP_DEFINITIONS if item.slug == slug), None)
    if definition and definition.app_id and definition.app_id not in available_apps:
        logger.warning(
            "[Task ID: %s] [PostProcessor] Dropped quick_tip_slug '%s' because app '%s' is unavailable",
            task_id,
            slug,
            definition.app_id,
        )
        return ""

    return slug
