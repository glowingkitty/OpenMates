"""Team billing and credit attribution service.

Teams V1 keeps personal and team credit ledgers separate. This service enforces
role checks, updates the server-side team balance, stores encrypted balance
snapshots for clients, and records per-member usage attribution.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id


TEAM_CREDIT_ACCOUNT_COLLECTION = "team_credit_accounts"
TEAM_CREDIT_EVENT_COLLECTION = "team_credit_events"
TEAM_USAGE_EVENT_COLLECTION = "team_usage_events"
TEAM_BILLING_ROLES = {"owner", "admin"}
TEAM_CREDIT_USER_ROLES = {"owner", "admin", "member"}

TeamCreditAddEvent = Literal["purchase", "personal_transfer_in"]


class TeamInsufficientCreditsError(ValueError):
    """Raised when a team credit deduction would overdraw the team account."""


class TeamBillingService:
    def __init__(self, directus_service: Any) -> None:
        self.directus = directus_service

    async def get_billing_summary(self, team_id: str, actor_user_id: str) -> dict[str, Any]:
        await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_CREDIT_USER_ROLES)
        return await self._require_credit_account(team_id)

    async def add_credits(
        self,
        *,
        team_id: str,
        actor_user_id: str,
        event_id: str,
        credits: int,
        encrypted_balance: str | None = None,
        event_type: TeamCreditAddEvent = "purchase",
        encrypted_metadata: str | None = None,
        occurred_at: int | None = None,
    ) -> dict[str, Any]:
        await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_BILLING_ROLES)
        if event_type not in {"purchase", "personal_transfer_in"}:
            raise ValueError("Invalid team credit add event type")
        credits = _require_positive_credits(credits)
        account = await self._require_credit_account(team_id)
        now = int(occurred_at or time.time())
        updated_account = await self._update_account(
            account,
            balance_credits=_safe_int(account.get("balance_credits")) + credits,
            encrypted_balance=encrypted_balance or account.get("encrypted_balance") or "",
            updated_at=now,
        )
        event = await self._create_credit_event(
            team_id=team_id,
            actor_user_id=actor_user_id,
            event_id=event_id,
            event_type=event_type,
            amount=credits,
            encrypted_metadata=encrypted_metadata,
            created_at=now,
        )
        return {"account": updated_account, "credit_event": event}

    async def charge_team_credits(
        self,
        *,
        team_id: str,
        actor_user_id: str,
        event_id: str,
        credits: int,
        encrypted_balance: str | None = None,
        workspace_type: str,
        object_id_hash: str | None = None,
        encrypted_metadata: str | None = None,
        occurred_at: int | None = None,
    ) -> dict[str, Any]:
        await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_CREDIT_USER_ROLES)
        credits = _require_positive_credits(credits)
        if not workspace_type:
            raise ValueError("workspace_type is required")
        account = await self._require_credit_account(team_id)
        current_balance = _safe_int(account.get("balance_credits"))
        if current_balance < credits:
            raise TeamInsufficientCreditsError("Insufficient team credits")
        now = int(occurred_at or time.time())
        updated_account = await self._update_account(
            account,
            balance_credits=current_balance - credits,
            encrypted_balance=encrypted_balance or account.get("encrypted_balance") or "",
            updated_at=now,
        )
        credit_event = await self._create_credit_event(
            team_id=team_id,
            actor_user_id=actor_user_id,
            event_id=event_id,
            event_type="deduction",
            amount=-credits,
            encrypted_metadata=encrypted_metadata,
            created_at=now,
        )
        success, usage_event = await self.directus.create_item(
            TEAM_USAGE_EVENT_COLLECTION,
            {
                "event_id": event_id,
                "hashed_team_id": hash_id(team_id),
                "actor_user_hash": hash_id(actor_user_id),
                "workspace_type": workspace_type,
                "object_id_hash": object_id_hash,
                "credit_amount": credits,
                "created_at": now,
            },
            admin_required=True,
        )
        if not success:
            raise RuntimeError("Failed to create team usage event")
        return {"account": updated_account, "credit_event": credit_event, "usage_event": usage_event}

    async def list_usage(self, team_id: str, actor_user_id: str, member_user_id: str | None = None) -> list[dict[str, Any]]:
        membership = await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_CREDIT_USER_ROLES)
        role = membership.get("role")
        if role not in TEAM_BILLING_ROLES:
            if member_user_id and member_user_id != actor_user_id:
                raise TeamPermissionError("Team permission denied")
            member_user_id = actor_user_id

        params: dict[str, Any] = {
            "filter[hashed_team_id][_eq]": hash_id(team_id),
            "fields": "id,event_id,hashed_team_id,actor_user_hash,workspace_type,object_id_hash,credit_amount,created_at",
            "limit": -1,
        }
        if member_user_id:
            params["filter[actor_user_hash][_eq]"] = hash_id(member_user_id)
        rows = await self.directus.get_items(TEAM_USAGE_EVENT_COLLECTION, params=params, no_cache=True, admin_required=True)
        return rows if isinstance(rows, list) else []

    async def _require_credit_account(self, team_id: str) -> dict[str, Any]:
        rows = await self.directus.get_items(
            TEAM_CREDIT_ACCOUNT_COLLECTION,
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "fields": "id,hashed_team_id,encrypted_balance,balance_credits,version,updated_at",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not rows or not isinstance(rows, list):
            raise RuntimeError("Team credit account not found")
        return rows[0]

    async def _update_account(self, account: dict[str, Any], *, balance_credits: int, encrypted_balance: str, updated_at: int) -> dict[str, Any]:
        updated = await self.directus.update_item(
            TEAM_CREDIT_ACCOUNT_COLLECTION,
            account["id"],
            {
                "encrypted_balance": encrypted_balance,
                "balance_credits": balance_credits,
                "version": _safe_int(account.get("version")) + 1,
                "updated_at": updated_at,
            },
            admin_required=True,
        )
        if not updated:
            raise RuntimeError("Failed to update team credit account")
        return updated

    async def _create_credit_event(
        self,
        *,
        team_id: str,
        actor_user_id: str,
        event_id: str,
        event_type: str,
        amount: int,
        encrypted_metadata: str | None,
        created_at: int,
    ) -> dict[str, Any]:
        success, event = await self.directus.create_item(
            TEAM_CREDIT_EVENT_COLLECTION,
            {
                "event_id": event_id,
                "hashed_team_id": hash_id(team_id),
                "actor_user_hash": hash_id(actor_user_id),
                "event_type": event_type,
                "amount": amount,
                "encrypted_metadata": encrypted_metadata,
                "created_at": created_at,
            },
            admin_required=True,
        )
        if not success:
            raise RuntimeError("Failed to create team credit event")
        return event


def _require_positive_credits(credits: int) -> int:
    if not isinstance(credits, int) or credits <= 0:
        raise ValueError("credits must be a positive integer")
    return credits


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
