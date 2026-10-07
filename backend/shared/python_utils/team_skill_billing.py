"""Select the existing Personal or Team credit ledger for an app skill charge."""

from __future__ import annotations

import hashlib
from typing import Any


async def ensure_team_skill_credit_headroom(
    directus_service: Any,
    team_id: str,
    user_id: str,
    estimated_credits: int,
) -> None:
    from backend.core.api.app.services.team_billing_service import TeamBillingService

    if not await TeamBillingService(directus_service).has_spending_headroom(
        team_id, user_id, estimated_credits
    ):
        raise ValueError("INSUFFICIENT_TEAM_CREDITS")


def skill_billing_request(
    payload: dict[str, Any],
    team_id: str | None,
    *,
    event_id: str,
) -> tuple[str, dict[str, Any]]:
    """Return the internal billing path and payload for one completed skill job.

    Only the route supplies Team context to dispatched jobs. Team charges use the
    same role-checked ledger as chat and carry one stable event ID per job.
    """
    if not team_id:
        return "/internal/billing/charge", payload
    user_id = str(payload["user_id"])
    usage_details = dict(payload.get("usage_details") or {})
    usage_details["workspace_type"] = "apps"
    if not event_id:
        raise ValueError("Team app skill billing requires an event ID")
    idempotency_key = f"app-skill:{event_id}"
    if len(idempotency_key) > 255:
        idempotency_key = f"app-skill:{hashlib.sha256(event_id.encode()).hexdigest()}"
    return "/internal/billing/team/charge", {
        "team_id": team_id,
        "actor_user_id": user_id,
        "credits": payload["credits"],
        "skill_id": payload["skill_id"],
        "app_id": payload["app_id"],
        "idempotency_key": idempotency_key,
        "usage_details": usage_details,
    }
