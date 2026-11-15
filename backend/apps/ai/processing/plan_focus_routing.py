# backend/apps/ai/processing/plan_focus_routing.py
#
# Explicit @plan resolution for Plans V1. Natural-language plan requests are
# not detected here: the planner focus modes are ordinary preprocessing
# candidates (see their app.yml preprocessor_hint) and are offered through the
# normal activate_focus_mode countdown like every other focus mode. Only the
# explicit @plan shorthand is resolved here, because it is user consent that
# names no concrete planner focus id. `has_active_app_focus` decides whether an
# explicit @focus/@plan request must yield to a focus that is already active.

from typing import Any, Collection, Sequence

GENERIC_PLAN_FOCUS_ID = "openmates-plan"
CODE_PLAN_FOCUS_ID = "code-project_planner"
PLANNER_FOCUS_IDS = frozenset({GENERIC_PLAN_FOCUS_ID, CODE_PLAN_FOCUS_ID})


def select_explicit_plan_focus(
    candidate_focus_ids: Sequence[str],
    available_focus_ids: Collection[str],
) -> str | None:
    """Choose the planner focus for an explicit @plan request.

    The preprocessing model has already ranked focus candidates for the
    (multilingual) message; a planner it selected wins, so a coding plan routes
    to the code planner. Otherwise the generic OpenMates planner is used.
    Returns None only when no planner focus mode is available at all.
    """
    for focus_id in candidate_focus_ids:
        if focus_id in PLANNER_FOCUS_IDS and focus_id in available_focus_ids:
            return focus_id
    if GENERIC_PLAN_FOCUS_ID in available_focus_ids:
        return GENERIC_PLAN_FOCUS_ID
    return None


def has_active_app_focus(request_data: Any) -> bool:
    """Whether the chat already runs an app or private specialist focus.

    A Project's own base focus does not count: an explicit @focus or @plan in a
    Project chat activates that specialist over the base, which keeps the
    Project instructions and write context (feature.focus-modes,
    focus-modes.project-specialist-composition). Without this, the server-bound
    Project focus silently swallowed every explicit focus request (TASK-7479).
    """
    active_focus_id = getattr(request_data, "active_focus_id", None)
    if not active_focus_id:
        return False
    project_focus = getattr(request_data, "active_project_focus", None) or {}
    return active_focus_id != project_focus.get("focus_id")
