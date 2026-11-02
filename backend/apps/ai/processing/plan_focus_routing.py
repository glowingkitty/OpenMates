# backend/apps/ai/processing/plan_focus_routing.py
#
# Lightweight Plans V1 focus routing. This keeps @plan and natural-language
# planning detection deterministic before richer app-specific planners are added.

import re
from dataclasses import dataclass
from typing import Collection


GENERIC_PLAN_FOCUS_ID = "openmates-plan"
CODE_PLAN_FOCUS_ID = "code-project_planner"

# Inferred (non-@plan) planning needs an actual request for a plan. Plain
# keyword substrings activated the planner for "explanation", "doesn't plan to",
# "projects" or "Do not create Tasks" and silently changed the answer's focus
# mode without the client showing it (issue BMKRJ).
_PLAN_OBJECT = r"(?:a|an|the|my|our|this|that|it|out|how|for)\b"
PLAN_REQUEST_PATTERNS = (
    # "Plan a workshop", "Please plan my week", "Help me plan out the launch".
    re.compile(
        r"(?:^|[.!?:]\s+|\b(?:please|can\s+you|could\s+you|would\s+you|help\s+me|"
        r"i\s+(?:need|want)\s+(?:you\s+)?to|let'?s)\s+)"
        r"(?:plan|break\s+down|map\s+out)\s+" + _PLAN_OBJECT,
        re.IGNORECASE,
    ),
    # "Make me a project plan", "I need a roadmap", "Create a task list".
    re.compile(
        r"\b(?:make|create|write|draft|build|give|prepare|put\s+together|outline|need|want)\s+"
        r"(?:me\s+|us\s+)?(?:a|an|the|my|our)\s+(?:[\w-]+\s+){0,3}?"
        r"(?:plan|roadmap|task\s+list|step-by-step\s+plan|breakdown)\b",
        re.IGNORECASE,
    ),
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
    # Leading word boundary only: "tests" and "implementing" match, "latest" does not.
    return any(re.search(rf"\b{re.escape(word)}", text, re.IGNORECASE) for word in words)


def route_plan_focus(
    message: str,
    *,
    plan_requested: bool,
    available_focus_modes: Collection[str],
) -> PlanFocusRoute:
    """Choose the best planner focus mode for an explicit or inferred plan.

    V1 starts intentionally conservative: explicit @plan always plans, while
    natural-language auto-detection requires an explicit request for a plan
    (see PLAN_REQUEST_PATTERNS), never a bare planning word. App-specific routing currently recognizes code plans and otherwise
    falls back to the generic OpenMates plan focus mode.
    """
    has_plan_intent = plan_requested or any(pattern.search(message) for pattern in PLAN_REQUEST_PATTERNS)
    if not has_plan_intent:
        return PlanFocusRoute(should_plan=False, active_focus_id=None, reason="no_plan_intent")

    if _contains_any(message, CODE_KEYWORDS) and CODE_PLAN_FOCUS_ID in available_focus_modes:
        return PlanFocusRoute(should_plan=True, active_focus_id=CODE_PLAN_FOCUS_ID, reason="matched_code_planner")

    if GENERIC_PLAN_FOCUS_ID in available_focus_modes:
        return PlanFocusRoute(should_plan=True, active_focus_id=GENERIC_PLAN_FOCUS_ID, reason="generic_plan_fallback")

    return PlanFocusRoute(should_plan=True, active_focus_id=None, reason="planner_unavailable")
