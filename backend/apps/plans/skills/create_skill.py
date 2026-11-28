# backend/apps/plans/skills/create_skill.py
#
# Plans app create skill. Plan records are client-side encrypted, so this skill
# never writes durable content server-side. It returns a pending client action
# for a capable first-party client to encrypt and apply.

from __future__ import annotations

import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.apps.base_skill import BaseSkill

logger = logging.getLogger(__name__)


PLAN_CREATE_CONTRACT = "openmates.plan_create_request"
PLAN_CREATE_CONTRACT_VERSION = 1
MAX_ASSUMPTIONS = 20
MAX_ASSUMPTION_TEXT = 2000
ASSUMPTION_REQUIRED_BEFORE = {"implementation", "task_execution", "completion"}


def _normalize_assumptions(raw: Any) -> list[dict[str, str]]:
    """Validate model-provided assumptions and mint one server-side id per row."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("assumptions must be a list")
    if len(raw) > MAX_ASSUMPTIONS:
        raise ValueError(f"At most {MAX_ASSUMPTIONS} assumptions are allowed")
    assumptions: list[dict[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Assumption {index} must be an object")
        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError(f"Assumption {index} requires text")
        if len(text) > MAX_ASSUMPTION_TEXT:
            raise ValueError(f"Assumption {index} text exceeds {MAX_ASSUMPTION_TEXT} characters")
        required_before = str(item.get("required_before") or "implementation")
        if required_before not in ASSUMPTION_REQUIRED_BEFORE:
            raise ValueError(
                f"Assumption {index} required_before must be one of {sorted(ASSUMPTION_REQUIRED_BEFORE)}"
            )
        assumptions.append(
            {"assumption_id": str(uuid.uuid4()), "text": text, "required_before": required_before}
        )
    return assumptions


def _next_step(plan_id: str, assumptions: list[dict[str, str]]) -> str | None:
    """Tell the model to check open assumptions in sub-chats before any Task."""
    if not assumptions:
        return None
    rows = "; ".join(f'{item["assumption_id"]}: {item["text"]}' for item in assumptions)
    return (
        "Before creating Tasks, call start_sub_chats with one sub-chat per assumption, "
        f'each with link {{"kind": "assumption", "plan_id": "{plan_id}", "id": <assumption id>}} '
        f"and a prompt to check that assumption. Assumptions: {rows}"
    )


async def _existing_chat_plan_id(user_id: str, chat_id: str | None, directus_service: Any | None) -> str | None:
    """Return the Plan this chat already owns, if any (one Plan per chat)."""
    if not chat_id:
        return None
    owned = directus_service is None
    if owned:
        from backend.core.api.app.services.directus.directus import DirectusService
        directus_service = DirectusService()
    try:
        plans = await directus_service.user_plan.list_plans(user_id, chat_id=chat_id, limit=1)
    finally:
        if owned:
            await directus_service.close()
    return str(plans[0]["plan_id"]) if plans and plans[0].get("plan_id") else None


class CreatePlanResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "plans"
    skill_id: str = "create"
    status: str = "waiting_for_client"
    pending_client_action: dict[str, Any] | None = None
    plan_id: str | None = None
    assumption_ids: list[str] = Field(default_factory=list)
    next_step: str | None = None
    error: str | None = None


class CreateSkill(BaseSkill):
    """Request client-side encrypted plan creation."""

    async def execute(
        self,
        title: str,
        summary: str | None = None,
        goal: str | None = None,
        user_id: str | None = None,
        chat_id: str | None = None,
        message_id: str | None = None,
        assumptions: list[dict[str, Any]] | None = None,
        specification_ref: str | None = None,
        directus_service: Any | None = None,
        **kwargs: Any,
    ) -> CreatePlanResponse:
        try:
            if not user_id:
                raise ValueError("Plan create requires an authenticated user")
            plan_title = str(title or "").strip()
            if not plan_title:
                raise ValueError("Plan create requires a title")
            existing_plan_id = await _existing_chat_plan_id(user_id, chat_id, directus_service)
            if existing_plan_id:
                # One Plan per chat (owner decision 23 Nov): a resumed turn re-creating
                # the Plan split the work across two Plans and checked new assumptions
                # instead of starting the Task sub-chats.
                return CreatePlanResponse(
                    success=False,
                    plan_id=existing_plan_id,
                    error=(
                        f"This chat already has the Plan {existing_plan_id}. Do not create another Plan: "
                        "use this plan_id for tasks create and start_sub_chats links."
                    ),
                )
            minted_assumptions = _normalize_assumptions(assumptions)
            plan_id = str(uuid.uuid4())
            return CreatePlanResponse(
                success=True,
                plan_id=plan_id,
                assumption_ids=[item["assumption_id"] for item in minted_assumptions],
                next_step=_next_step(plan_id, minted_assumptions),
                pending_client_action={
                    "contract": PLAN_CREATE_CONTRACT,
                    "version": PLAN_CREATE_CONTRACT_VERSION,
                    "request_id": f"plan-create-request-{uuid.uuid4()}",
                    "action": "create",
                    "plan_id": plan_id,
                    "title": plan_title,
                    "summary": str(summary or ""),
                    "goal": str(goal or ""),
                    "specification_ref": str(specification_ref or "") or None,
                    "assumptions": minted_assumptions,
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "notification_queued": False,
                },
            )
        except ValueError as exc:
            logger.warning("Plan create rejected: %s", exc)
            return CreatePlanResponse(success=False, error=str(exc))
        except Exception as exc:
            logger.error("Plan create skill failed: %s", exc, exc_info=True)
            return CreatePlanResponse(success=False, error=str(exc))
