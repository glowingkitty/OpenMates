"""Team billing and credit attribution service.

Teams V1 keeps personal and team credit ledgers separate. This service enforces
role checks, updates the server-side team balance, stores encrypted balance
snapshots for clients, and records per-member usage attribution.
"""

from __future__ import annotations

import logging
import time
import json
from typing import Any, Literal

from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
from backend.core.api.app.services.sub_chat_orchestration_service import (
    SubChatOrchestrationProtocolError,
    SubChatOrchestrationService,
)
from backend.core.api.app.services.llm_usage_receipt import (
    settle_public_llm_usage_receipt,
    validate_public_llm_usage_receipt,
)


TEAM_CREDIT_ACCOUNT_COLLECTION = "team_credit_accounts"
TEAM_CREDIT_EVENT_COLLECTION = "team_credit_events"
TEAM_USAGE_EVENT_COLLECTION = "team_usage_events"
TEAM_BILLING_ROLES = {"owner", "admin"}
TEAM_CREDIT_USER_ROLES = {"owner", "admin", "member"}
MAX_TEAM_BALANCE_CAS_RETRIES = 3
logger = logging.getLogger(__name__)

TeamCreditAddEvent = Literal["purchase", "personal_transfer_in"]


class TeamInsufficientCreditsError(ValueError):
    """Raised when a team credit deduction would overdraw the team account."""


class TeamBillingService:
    def __init__(self, directus_service: Any) -> None:
        self.directus = directus_service

    async def get_billing_summary(self, team_id: str, actor_user_id: str) -> dict[str, Any]:
        await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_BILLING_ROLES)
        return await self._require_credit_account(team_id)

    async def reserve_team_credits(
        self, *, team_id: str, actor_user_id: str, charge_id: str,
        quoted_credits: int, app_id: str, skill_id: str,
    ) -> dict[str, Any]:
        """Hold a cumulative quote on the team ledger after member authorization."""
        await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_CREDIT_USER_ROLES)
        if not isinstance(quoted_credits, int) or quoted_credits <= 0:
            raise ValueError("quoted_credits must be positive")
        return await SubChatOrchestrationService(self.directus).execute(
            "reserve_team_credits",
            {
                "protocol_version": 1,
                "charge_id": charge_id,
                "hashed_team_id": hash_id(team_id),
                "actor_user_hash": hash_id(actor_user_id),
                "app_id": app_id,
                "skill_id": skill_id,
                "quoted_credits": quoted_credits,
            },
        )

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
        _cas_retry_count: int = 0,
        _verified_paid_settlement: bool = False,
    ) -> dict[str, Any]:
        # A provider-confirmed payment must still credit the Team if its payer
        # loses membership between checkout and webhook delivery.
        if not _verified_paid_settlement:
            await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_BILLING_ROLES)
        if event_type not in {"purchase", "personal_transfer_in"}:
            raise ValueError("Invalid team credit add event type")
        credits = _require_positive_credits(credits)
        account = await self._require_credit_account(team_id, include_holds=False)
        now = int(occurred_at or time.time())
        if hasattr(self.directus, "_make_api_request"):
            try:
                return await SubChatOrchestrationService(self.directus).execute(
                    "commit_team_credit_add",
                    {
                        "protocol_version": 1,
                        "event_id": event_id,
                        "hashed_team_id": hash_id(team_id),
                        "actor_user_hash": hash_id(actor_user_id),
                        "credits": credits,
                        "expected_version": _safe_int(account.get("version")),
                        "encrypted_balance": encrypted_balance or account.get("encrypted_balance") or "",
                        "event_type": event_type,
                        "encrypted_metadata": encrypted_metadata,
                        "occurred_at": now,
                    },
                )
            except SubChatOrchestrationProtocolError as exc:
                if exc.code == "stale_team_credit_balance" and _cas_retry_count < MAX_TEAM_BALANCE_CAS_RETRIES:
                    return await self.add_credits(
                        team_id=team_id,
                        actor_user_id=actor_user_id,
                        event_id=event_id,
                        credits=credits,
                        encrypted_balance=encrypted_balance,
                        event_type=event_type,
                        encrypted_metadata=encrypted_metadata,
                        occurred_at=occurred_at,
                        _cas_retry_count=_cas_retry_count + 1,
                        _verified_paid_settlement=_verified_paid_settlement,
                    )
                raise
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
        usage_details: dict[str, Any] | None = None,
        occurred_at: int | None = None,
        _cas_retry_count: int = 0,
    ) -> dict[str, Any]:
        await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_CREDIT_USER_ROLES)
        credits = _require_positive_credits(credits)
        if not workspace_type:
            raise ValueError("workspace_type is required")
        account = await self._require_credit_account(team_id, include_holds=False)
        current_balance = _safe_int(account.get("balance_credits"))
        now = int(occurred_at or time.time())
        encrypted_llm_usage_breakdown = None
        llm_usage_vault_key_id = None
        receipt = (usage_details or {}).get("llm_usage_breakdown")
        if receipt is not None:
            receipt = settle_public_llm_usage_receipt(receipt, credits)
            actor_fields = await self.directus.get_user_fields_direct(
                actor_user_id, ["vault_key_id"], no_cache=True
            )
            if not actor_fields or actor_fields.get("id") != actor_user_id or not actor_fields.get("vault_key_id"):
                raise ValueError("Actor vault key unavailable for team usage receipt")
            llm_usage_vault_key_id = actor_fields["vault_key_id"]
            encryption = self.directus.usage.encryption_service
            encrypted_llm_usage_breakdown, _ = await encryption.encrypt_with_user_key(
                plaintext=json.dumps(receipt, separators=(",", ":"), sort_keys=True),
                key_id=llm_usage_vault_key_id,
            )
            if not encrypted_llm_usage_breakdown:
                raise ValueError("Failed to encrypt team usage receipt")
        if hasattr(self.directus, "_make_api_request"):
            try:
                result = await SubChatOrchestrationService(self.directus).execute(
                    "commit_team_charge",
                    {
                        "protocol_version": 1,
                        "event_id": event_id,
                        "hashed_team_id": hash_id(team_id),
                        "actor_user_hash": hash_id(actor_user_id),
                        "credits": credits,
                        "expected_version": _safe_int(account.get("version")),
                        "encrypted_balance": encrypted_balance or account.get("encrypted_balance") or "",
                        "workspace_type": workspace_type,
                        "object_id_hash": object_id_hash,
                        "encrypted_metadata": encrypted_metadata,
                        "encrypted_llm_usage_breakdown": encrypted_llm_usage_breakdown,
                        "llm_usage_vault_key_id": llm_usage_vault_key_id,
                        "orchestration_id": (usage_details or {}).get("orchestration_id"),
                        "reservation_required": (usage_details or {}).get("reservation_required") is True,
                        "occurred_at": now,
                    },
                )
                await self._queue_auto_topup_if_needed(team_id, event_id, result.get("account"))
                return result
            except SubChatOrchestrationProtocolError as exc:
                if exc.code == "insufficient_team_credits":
                    raise TeamInsufficientCreditsError("Insufficient team credits") from exc
                if exc.code == "stale_team_credit_balance" and _cas_retry_count < MAX_TEAM_BALANCE_CAS_RETRIES:
                    return await self.charge_team_credits(
                        team_id=team_id,
                        actor_user_id=actor_user_id,
                        event_id=event_id,
                        credits=credits,
                        encrypted_balance=encrypted_balance,
                        workspace_type=workspace_type,
                        object_id_hash=object_id_hash,
                        encrypted_metadata=encrypted_metadata,
                        usage_details=usage_details,
                        occurred_at=occurred_at,
                        _cas_retry_count=_cas_retry_count + 1,
                    )
                raise
        if current_balance < credits:
            raise TeamInsufficientCreditsError("Insufficient team credits")
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
                "encrypted_llm_usage_breakdown": encrypted_llm_usage_breakdown,
                "llm_usage_vault_key_id": llm_usage_vault_key_id,
                "created_at": now,
            },
            admin_required=True,
        )
        if not success:
            raise RuntimeError("Failed to create team usage event")
        await self._queue_auto_topup_if_needed(team_id, event_id, updated_account)
        return {"account": updated_account, "credit_event": credit_event, "usage_event": usage_event}

    async def _queue_auto_topup_if_needed(self, team_id: str, event_id: str, account: dict[str, Any] | None) -> None:
        if not account or _safe_int(account.get("balance_credits")) > 100:
            return
        try:
            rows = await self.directus.get_items(
                "billing_profiles",
                params={"filter": {"owner_kind": {"_eq": "team"}, "owner_hash": {"_eq": hash_id(team_id)}}, "limit": 1},
                no_cache=True, admin_required=True,
            )
            if rows and rows[0].get("auto_topup_enabled"):
                from backend.core.api.app.tasks.celery_config import app

                app.send_task(
                    "billing.team_auto_topup",
                    kwargs={"team_id": team_id, "charge_event_id": event_id},
                    queue="persistence",
                )
        except Exception:
            logger.exception("Failed to enqueue Team auto top-up after credit charge")

    async def list_usage(self, team_id: str, actor_user_id: str, member_user_id: str | None = None) -> list[dict[str, Any]]:
        membership = await self.directus.team.require_team_role(team_id, actor_user_id, TEAM_CREDIT_USER_ROLES)
        role = membership.get("role")
        if role not in TEAM_BILLING_ROLES:
            if member_user_id and member_user_id != actor_user_id:
                raise TeamPermissionError("Team permission denied")
            member_user_id = actor_user_id

        params: dict[str, Any] = {
            "filter[hashed_team_id][_eq]": hash_id(team_id),
            "fields": "id,event_id,hashed_team_id,actor_user_hash,workspace_type,object_id_hash,credit_amount,encrypted_llm_usage_breakdown,llm_usage_vault_key_id,created_at",
            "limit": -1,
        }
        if member_user_id:
            params["filter[actor_user_hash][_eq]"] = hash_id(member_user_id)
        rows = await self.directus.get_items(TEAM_USAGE_EVENT_COLLECTION, params=params, no_cache=True, admin_required=True)
        if not isinstance(rows, list):
            return []
        result = []
        for row in rows:
            public_row = {key: value for key, value in row.items() if key not in {
                "encrypted_llm_usage_breakdown", "llm_usage_vault_key_id",
            }}
            ciphertext = row.get("encrypted_llm_usage_breakdown")
            key_id = row.get("llm_usage_vault_key_id")
            if ciphertext and key_id:
                try:
                    plaintext = await self.directus.usage.encryption_service.decrypt_with_user_key(
                        ciphertext, key_id
                    )
                    receipt = json.loads(plaintext) if plaintext else None
                    validate_public_llm_usage_receipt(receipt)
                    if receipt["credits_charged"] == row.get("credit_amount"):
                        public_row["llm_usage_breakdown"] = receipt
                except Exception:  # noqa: BLE001 - corrupt receipt must not hide the ledger event
                    # A damaged historic receipt must not hide the ledger event.
                    logger.warning("Failed to decrypt team usage receipt for event %s", row.get("id"))
            result.append(public_row)
        return result

    async def _require_credit_account(self, team_id: str, *, include_holds: bool = True) -> dict[str, Any]:
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
        if not include_holds:
            return rows[0]
        reservation_rows = await self.directus.get_items(
            "billing_reservations",
            params={
                "filter[subject_kind][_eq]": "team",
                "filter[subject_hash][_eq]": hash_id(team_id),
                "filter[state][_eq]": "reserved",
                "fields": "quoted_credits,review_requested_at",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        )
        if not isinstance(reservation_rows, list):
            raise RuntimeError("Team billing reservation summary unavailable")
        return {
            **rows[0],
            "held_credits": sum(int(row["quoted_credits"]) for row in reservation_rows),
            "review_required_credits": sum(
                int(row["quoted_credits"]) for row in reservation_rows if row.get("review_requested_at")
            ),
        }

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
