"""Use-case model routing: specialised answer models for recognised request kinds.

The preprocessing decision model classifies each request into at most one use
case from ``USE_CASE_PROFILES``. A recognised use case replaces the automatic
tier default with that profile's ordered model list (primary first, then
fallbacks); the tier's own recovery chain stays behind it. An exact chat model
or a saved tier preference always wins, so this applies to automatic
selection only.

No use case is registered at present: vector graphics are handled by the
``images-generate`` app skill, so the main chat model stays the normal tier
default and the decision question is not asked while the registry is empty.

Adding a use case means adding one ``UseCaseProfile`` entry: the decision
question, validation and routing are all derived from the registry.

Output length is intentionally not part of a profile. The answer limit stays
the selected model's catalogue ``max_output_tokens`` fitted to the user's
available credits, so a use case can never truncate or over-reserve output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NO_USE_CASE = "none"
USE_CASE_QUESTION_KEY = "use_case"


@dataclass(frozen=True)
class UseCaseProfile:
    """Routing policy for one recognised kind of request.

    ``models`` is ordered: the first usable entry answers, later entries are
    fallbacks. ``thinking_level`` applies to the first entry only; fallbacks
    keep their own defaults.
    """

    id: str
    criterion: str
    models: tuple[str, ...]
    thinking_level: str | None = None


USE_CASE_PROFILES: dict[str, UseCaseProfile] = {}


def use_case_question() -> dict[str, Any] | None:
    """Build the optional decision question from the registry, or None when it is empty."""
    if not USE_CASE_PROFILES:
        return None
    criteria = {NO_USE_CASE: "None of the other options clearly applies. This is the answer for most requests."}
    criteria.update({profile.id: profile.criterion for profile in USE_CASE_PROFILES.values()})
    return {
        "type": "choice",
        "instructions": (
            "Does the latest user request, read in the context of the conversation, clearly belong to one of "
            "these specialised use cases? Choose none unless one clearly applies."
        ),
        "criteria": criteria,
    }


def normalize_use_case(value: Any) -> str | None:
    """Return a registered use-case id; anything else means no use case."""
    return value if isinstance(value, str) and value in USE_CASE_PROFILES else None


def use_case_model_candidates(use_case: Any) -> list[str]:
    """Return the ordered models for a use case, or an empty list."""
    normalized = normalize_use_case(use_case)
    return list(USE_CASE_PROFILES[normalized].models) if normalized else []


def use_case_thinking_level(use_case: Any, model_id: str | None) -> str | None:
    """Return the profile reasoning level when its primary model was selected."""
    normalized = normalize_use_case(use_case)
    if not normalized:
        return None
    profile = USE_CASE_PROFILES[normalized]
    return profile.thinking_level if profile.models and model_id == profile.models[0] else None
