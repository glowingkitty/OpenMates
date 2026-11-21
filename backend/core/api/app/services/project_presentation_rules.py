"""Server-side validation of Project presentation proposals (TASK-1807).

Contract: ``docs/plans/project-presentation/contract.md``. The server only ever
handles these values as plaintext proposals on their way to the client; the
client validates them again in the Rust core before encrypting them with the
Project key, and it alone decides which fields may be written.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

# The chat categories whose gradients the web and Apple apps already have
# (``frontend/packages/chatCategoryTheme.ts``), minus the internal
# ``openmates_official`` and ``onboarding_support`` ones.
PROJECT_CATEGORIES: tuple[str, ...] = (
    "software_development", "business_development", "medical_health", "legal_law",
    "maker_prototyping", "marketing_sales", "finance", "design", "electrical_engineering",
    "movies_tv", "history", "science", "life_coach_psychology", "cooking_food", "activism",
    "general_knowledge",
)
MAX_DESCRIPTION_CHARS = 140
MAX_ICON_CHARS = 40
_ICON_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ProjectPresentationProposal(BaseModel):
    """Normalised plaintext proposal; empty strings mean "no proposal"."""

    description: str = ""
    icon: str = ""
    category: str = ""


def normalize_description(value: Any) -> str:
    """One line, at most 140 characters, cut at a word boundary with an ellipsis."""
    text = " ".join(str(value or "").split())
    if len(text) <= MAX_DESCRIPTION_CHARS:
        return text
    cut = text[: MAX_DESCRIPTION_CHARS - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:-") + "…"


def normalize_icon(value: Any) -> str:
    """A kebab-case Lucide name or empty; anything else is dropped, never guessed."""
    icon = str(value or "").strip().lower()
    return icon if len(icon) <= MAX_ICON_CHARS and _ICON_RE.fullmatch(icon) else ""


def normalize_category(value: Any) -> str:
    """One of ``PROJECT_CATEGORIES`` or empty."""
    category = str(value or "").strip()
    return category if category in PROJECT_CATEGORIES else ""


def normalize_presentation(args: dict[str, Any] | None) -> ProjectPresentationProposal:
    """Normalise model tool arguments into a proposal; unknown keys are ignored."""
    args = args if isinstance(args, dict) else {}
    return ProjectPresentationProposal(
        description=normalize_description(args.get("description")),
        icon=normalize_icon(args.get("icon")),
        category=normalize_category(args.get("category")),
    )
