# backend/core/api/app/services/user_plan_share_bundle.py
#
# Pure helper for adding encrypted plan records to shared chat bundles. Shared
# chat links carry decrypt authority in the URL fragment, so this helper returns
# only encrypted plan rows and existing chat-scoped wrappers.
#
# Spec: docs/specs/plans-v1/spec.yml

import hashlib
from typing import Any


SHARED_PLAN_FIELDS = (
    "plan_id,status,primary_chat_id,hashed_primary_chat_id,current_phase_id,current_step_id,"
    "current_task_id,continuation_state,approval_state,planner_focus_id,version,created_at,"
    "updated_at,completed_at,encrypted_plan_key,encrypted_title,encrypted_summary,encrypted_goal,"
    "encrypted_scope_in,encrypted_scope_out,encrypted_user_flows,encrypted_current_focus,"
    "encrypted_assumptions,encrypted_open_questions,encrypted_constraints,encrypted_decisions,"
    "encrypted_risks,encrypted_reference_patterns,encrypted_context,encrypted_continuation_policy"
)
SHARED_PLAN_KEY_WRAPPER_FIELDS = "hashed_plan_id,key_type,hashed_chat_id,encrypted_plan_key,created_at,expires_at,wrapper_version"
CHAT_SHARE_PLAN_STATUSES = ["active", "executing", "running_checks", "blocked"]


async def get_shared_chat_plans(
    chat_id: str,
    hashed_chat_id: str,
    directus_service: Any,
) -> dict[str, list[dict[str, Any]]]:
    plans = await directus_service.get_items(
        "user_plans",
        params={
            "filter[hashed_primary_chat_id][_eq]": hashed_chat_id,
            "filter[status][_in]": CHAT_SHARE_PLAN_STATUSES,
            "fields": SHARED_PLAN_FIELDS,
            "sort": "-updated_at",
            "limit": -1,
        },
        admin_required=True,
    ) or []
    plan_key_wrappers: list[dict[str, Any]] = []
    for plan in plans:
        if plan.get("primary_chat_id") not in {None, chat_id}:
            continue
        plan_id = plan.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            continue
        hashed_plan_id = hashlib.sha256(plan_id.encode()).hexdigest()
        wrappers = await directus_service.get_items(
            "user_plan_key_wrappers",
            params={
                "filter[hashed_plan_id][_eq]": hashed_plan_id,
                "filter[key_type][_eq]": "chat",
                "filter[hashed_chat_id][_eq]": hashed_chat_id,
                "fields": SHARED_PLAN_KEY_WRAPPER_FIELDS,
                "limit": -1,
            },
            admin_required=True,
        ) or []
        plan_key_wrappers.extend(wrappers)
    return {"plans": plans, "plan_key_wrappers": plan_key_wrappers}
