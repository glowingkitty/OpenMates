# backend/apps/ai/processing/plan_focus_routing.py
#
# Lightweight Plans V1 focus routing. This keeps @plan and natural-language
# planning detection deterministic before richer app-specific planners are added.

from dataclasses import dataclass
from typing import Collection


GENERIC_PLAN_FOCUS_ID = "openmates-plan"
CODE_PLAN_FOCUS_ID = "code-project_planner"

PLAN_KEYWORDS = (
    "plan",
    "planning",
    "break down",
    "tasks",
    "acceptance criteria",
    "verification",
    "roadmap",
    "project",
)

CODE_KEYWORDS = (
    "implement",
    "code",
    "software",
    "feature",
    "api",
    "database",
    "migration",
    "test",
    "pytest",
    "playwright",
    "sdk",
)


@dataclass(frozen=True)
class PlanFocusRoute:
    should_plan: bool
    active_focus_id: str | None
    reason: str


def _contains_any(text: str, words: Collection[str]) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in words)


def route_plan_focus(
    message: str,
    *,
    plan_requested: bool,
    available_focus_modes: Collection[str],
) -> PlanFocusRoute:
    """Choose the best planner focus mode for an explicit or inferred plan.

    V1 starts intentionally conservative: explicit @plan always plans, while
    natural-language auto-detection requires planning words plus multi-step
    signals. App-specific routing currently recognizes code plans and otherwise
    falls back to the generic OpenMates plan focus mode.
    """
    has_plan_intent = plan_requested or _contains_any(message, PLAN_KEYWORDS)
    if not has_plan_intent:
        return PlanFocusRoute(should_plan=False, active_focus_id=None, reason="no_plan_intent")

    if _contains_any(message, CODE_KEYWORDS) and CODE_PLAN_FOCUS_ID in available_focus_modes:
        return PlanFocusRoute(should_plan=True, active_focus_id=CODE_PLAN_FOCUS_ID, reason="matched_code_planner")

    if GENERIC_PLAN_FOCUS_ID in available_focus_modes:
        return PlanFocusRoute(should_plan=True, active_focus_id=GENERIC_PLAN_FOCUS_ID, reason="generic_plan_fallback")

    return PlanFocusRoute(should_plan=True, active_focus_id=None, reason="planner_unavailable")
