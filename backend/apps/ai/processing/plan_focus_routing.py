# backend/apps/ai/processing/plan_focus_routing.py
#
# Explicit @plan resolution for Plans V1. Natural-language plan requests are
# not detected here: the planner focus modes are ordinary preprocessing
# candidates (see their app.yml preprocessor_hint) and are offered through the
# normal activate_focus_mode countdown like every other focus mode. Only the
# explicit @plan shorthand is resolved here, because it is user consent that
# names no concrete planner focus id.

from typing import Collection, Sequence

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
