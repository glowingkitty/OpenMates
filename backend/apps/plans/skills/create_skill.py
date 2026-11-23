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


class CreatePlanResponse(BaseModel):
    success: bool = Field(default=False)
    app_id: str = "plans"
    skill_id: str = "create"
    status: str = "waiting_for_client"
    pending_client_action: dict[str, Any] | None = None
    plan_id: str | None = None
    assumption_ids: list[str] = Field(default_factory=list)
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
        **kwargs: Any,
    ) -> CreatePlanResponse:
        try:
            if not user_id:
                raise ValueError("Plan create requires an authenticated user")
            plan_title = str(title or "").strip()
            if not plan_title:
                raise ValueError("Plan create requires a title")
            minted_assumptions = _normalize_assumptions(assumptions)
            plan_id = str(uuid.uuid4())
            return CreatePlanResponse(
                success=True,
                plan_id=plan_id,
                assumption_ids=[item["assumption_id"] for item in minted_assumptions],
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
