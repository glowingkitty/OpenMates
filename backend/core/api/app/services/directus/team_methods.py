"""Directus helpers for Teams V1.

TeamMethods owns team identity, membership, invite, and key-wrapper persistence.
It deliberately keeps authorization separate from cryptographic wrapper
existence: every caller must prove active membership before team rows or wrapped
keys are returned or mutated.
"""

import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

TEAM_ROLES = {"owner", "admin", "member", "viewer"}
INVITE_ROLES = {"admin", "member", "viewer"}
ACTIVE_STATUS = "active"
TEAM_KEY_EPOCH_V1 = 1


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class TeamPermissionError(PermissionError):
    """Raised when a user does not have the required team role."""


class TeamMethods:
    def __init__(self, directus_service):
        self.directus_service = directus_service

    async def create_team(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        now = int(payload.get("created_at") or time.time())
        team_id = str(payload["team_id"])
        owner_hash = hash_id(user_id)
        team_hash = hash_id(team_id)
        encrypted_team_key = payload.get("encrypted_team_key")
        if not encrypted_team_key:
            raise ValueError("encrypted_team_key is required")

        team_record = {
            "team_id": team_id,
            "hashed_team_id": team_hash,
            "slug": payload.get("slug") or team_id,
            "encrypted_name": payload["encrypted_name"],
            "encrypted_description": payload.get("encrypted_description"),
            "encrypted_billing_profile": payload.get("encrypted_billing_profile"),
            "created_by_user_hash": owner_hash,
            "status": ACTIVE_STATUS,
            "created_at": now,
            "updated_at": int(payload.get("updated_at") or now),
        }
        success, team = await self.directus_service.create_item("teams", team_record, admin_required=True)
        if not success:
            logger.error("Failed to create team metadata for hashed_team_id %s", team_hash)
            return None

        membership_record = {
            "hashed_team_id": team_hash,
            "hashed_user_id": owner_hash,
            "role": "owner",
            "status": ACTIVE_STATUS,
            "invited_by_hash": None,
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        wrapper_record = {
            "hashed_team_id": team_hash,
            "hashed_user_id": owner_hash,
            "team_key_epoch": TEAM_KEY_EPOCH_V1,
            "encrypted_team_key": encrypted_team_key,
            "status": ACTIVE_STATUS,
            "created_at": now,
            "revoked_at": None,
        }
        credit_record = {
            "hashed_team_id": team_hash,
            "encrypted_balance": payload.get("encrypted_initial_balance") or payload.get("encrypted_zero_balance") or "0",
            "balance_credits": int(payload.get("initial_balance_credits") or 0),
            "version": 1,
            "updated_at": now,
        }
        for collection, record in (
            ("team_memberships", membership_record),
            ("team_key_wrappers", wrapper_record),
            ("team_credit_accounts", credit_record),
        ):
            created, _data = await self.directus_service.create_item(collection, record, admin_required=True)
            if not created:
                logger.error("Failed to create %s for hashed_team_id %s", collection, team_hash)
                return None
        return team

    async def list_teams(self, user_id: str) -> list[dict[str, Any]]:
        memberships = await self.directus_service.get_items(
            "team_memberships",
            params={
                "filter[hashed_user_id][_eq]": hash_id(user_id),
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "hashed_team_id,role,status",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(memberships, list) or not memberships:
            return []
        teams: list[dict[str, Any]] = []
        for membership in memberships:
            team_hash = membership.get("hashed_team_id")
            rows = await self.directus_service.get_items(
                "teams",
                params={
                    "filter[hashed_team_id][_eq]": team_hash,
                    "filter[status][_eq]": ACTIVE_STATUS,
                    "fields": "id,team_id,hashed_team_id,slug,encrypted_name,encrypted_description,status,created_at,updated_at",
                    "limit": 1,
                },
                no_cache=True,
                admin_required=True,
            )
            if isinstance(rows, list):
                teams.extend({**row, "role": membership.get("role")} for row in rows)
        return teams

    async def get_team(self, team_id: str, user_id: str) -> dict[str, Any] | None:
        membership = await self.get_membership(team_id, user_id)
        if not membership:
            return None
        rows = await self.directus_service.get_items(
            "teams",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "id,team_id,hashed_team_id,slug,encrypted_name,encrypted_description,encrypted_billing_profile,status,created_at,updated_at",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if rows and isinstance(rows, list):
            return {**rows[0], "role": membership.get("role")}
        return None

    async def update_team(self, team_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        await self.require_team_role(team_id, user_id, {"owner", "admin"})
        team = await self.get_team(team_id, user_id)
        if not team:
            return None
        allowed_fields = {"slug", "encrypted_name", "encrypted_description", "encrypted_billing_profile", "updated_at"}
        update = {key: value for key, value in patch.items() if key in allowed_fields}
        if not update:
            return team
        return await self.directus_service.update_item("teams", team["id"], update, admin_required=True)

    async def delete_team(self, team_id: str, user_id: str, deleted_at: int | None = None) -> bool:
        await self.require_team_role(team_id, user_id, {"owner"})
        team = await self.get_team(team_id, user_id)
        if not team:
            return False
        now = int(deleted_at or time.time())
        updated = await self.directus_service.update_item("teams", team["id"], {"status": "deleted", "updated_at": now}, admin_required=True)
        return bool(updated)

    async def get_membership(self, team_id: str, user_id: str) -> dict[str, Any] | None:
        response = await self.directus_service.get_items(
            "team_memberships",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[hashed_user_id][_eq]": hash_id(user_id),
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "id,hashed_team_id,hashed_user_id,role,status",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if response and isinstance(response, list):
            return response[0]
        return None

    async def require_team_role(self, team_id: str, user_id: str, allowed_roles: set[str]) -> dict[str, Any]:
        membership = await self.get_membership(team_id, user_id)
        if not membership or membership.get("role") not in allowed_roles:
            raise TeamPermissionError("Team permission denied")
        return membership

    async def create_invite(self, team_id: str, inviter_user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        await self.require_team_role(team_id, inviter_user_id, {"owner", "admin"})
        role = payload.get("role") or "member"
        if role not in INVITE_ROLES:
            raise ValueError("Invalid invite role")
        now = int(payload.get("created_at") or time.time())
        record = {
            "invite_id": payload["invite_id"],
            "hashed_team_id": hash_id(team_id),
            "encrypted_recipient_hint": payload.get("encrypted_recipient_hint"),
            "role": role,
            "status": "pending",
            "created_by_hash": hash_id(inviter_user_id),
            "expires_at": payload.get("expires_at"),
            "created_at": now,
            "accepted_at": None,
        }
        success, data = await self.directus_service.create_item("team_invites", record, admin_required=True)
        return data if success else None

    async def accept_invite(self, invite_id: str, user_id: str, encrypted_team_key: str, accepted_at: int | None = None) -> dict[str, Any] | None:
        invites = await self.directus_service.get_items(
            "team_invites",
            params={
                "filter[invite_id][_eq]": invite_id,
                "filter[status][_eq]": "pending",
                "fields": "id,invite_id,hashed_team_id,role,status",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not invites or not isinstance(invites, list):
            return None
        invite = invites[0]
        now = int(accepted_at or time.time())
        membership_record = {
            "hashed_team_id": invite["hashed_team_id"],
            "hashed_user_id": hash_id(user_id),
            "role": invite["role"],
            "status": ACTIVE_STATUS,
            "invited_by_hash": None,
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        wrapper_record = {
            "hashed_team_id": invite["hashed_team_id"],
            "hashed_user_id": hash_id(user_id),
            "team_key_epoch": TEAM_KEY_EPOCH_V1,
            "encrypted_team_key": encrypted_team_key,
            "status": ACTIVE_STATUS,
            "created_at": now,
            "revoked_at": None,
        }
        success, membership = await self.directus_service.create_item("team_memberships", membership_record, admin_required=True)
        if not success:
            return None
        success, _wrapper = await self.directus_service.create_item("team_key_wrappers", wrapper_record, admin_required=True)
        if not success:
            return None
        await self.directus_service.update_item("team_invites", invite["id"], {"status": "accepted", "accepted_at": now}, admin_required=True)
        return membership

    async def remove_member(self, team_id: str, actor_user_id: str, target_user_id: str, removed_at: int | None = None) -> bool:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        target = await self.get_membership(team_id, target_user_id)
        if not target or target.get("role") == "owner":
            return False
        now = int(removed_at or time.time())
        await self.directus_service.update_item("team_memberships", target["id"], {"status": "removed", "removed_at": now, "updated_at": now}, admin_required=True)
        wrappers = await self.directus_service.get_items(
            "team_key_wrappers",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[hashed_user_id][_eq]": hash_id(target_user_id),
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "id,status",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        if isinstance(wrappers, list):
            for wrapper in wrappers:
                await self.directus_service.update_item("team_key_wrappers", wrapper["id"], {"status": "revoked", "revoked_at": now}, admin_required=True)
        return True

    async def set_member_role(self, team_id: str, actor_user_id: str, target_user_id: str, role: str, updated_at: int | None = None) -> dict[str, Any] | None:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        if role not in TEAM_ROLES:
            raise ValueError("Invalid team role")
        target = await self.get_membership(team_id, target_user_id)
        if not target or target.get("role") == "owner" or role == "owner":
            return None
        now = int(updated_at or time.time())
        return await self.directus_service.update_item("team_memberships", target["id"], {"role": role, "updated_at": now}, admin_required=True)
