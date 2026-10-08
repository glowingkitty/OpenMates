"""Directus helpers for Teams V1.

TeamMethods owns team identity, membership, invite, and key-wrapper persistence.
It deliberately keeps authorization separate from cryptographic wrapper
existence: every caller must prove active membership before team rows or wrapped
keys are returned or mutated.
"""

import hashlib
import logging
import time
import re
from uuid import uuid4
from typing import Any

logger = logging.getLogger(__name__)

TEAM_ROLES = {"owner", "admin", "member", "viewer"}
INVITE_ROLES = {"admin", "member", "viewer"}
ACTIVE_STATUS = "active"
TEAM_KEY_EPOCH_V1 = 1
PENDING_ACCESS_APPROVAL_STATUS = "pending_access_approval"
DEFAULT_SECURITY_POLICY = {
    "restrict_email_domains": False,
    "allowed_email_domains": [],
    "require_invite_link_approval": True,
    "require_strong_auth": False,
}


def hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_security_policy(policy: dict[str, Any]) -> dict[str, Any]:
    if set(policy) - set(DEFAULT_SECURITY_POLICY):
        raise ValueError("Invalid team security policy")
    result = {**DEFAULT_SECURITY_POLICY, **policy}
    for field in ("restrict_email_domains", "require_invite_link_approval", "require_strong_auth"):
        if type(result[field]) is not bool:
            raise ValueError("Invalid team security policy")
    domains = result["allowed_email_domains"]
    if not isinstance(domains, list) or len(domains) > 50:
        raise ValueError("Invalid allowed email domains")
    normalized: list[str] = []
    for domain in domains:
        if not isinstance(domain, str):
            raise ValueError("Invalid allowed email domain")
        domain = domain.strip().lower().rstrip(".")
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", domain) or ".." in domain or "." not in domain:
            raise ValueError("Invalid allowed email domain")
        normalized.append(domain)
    result["allowed_email_domains"] = sorted(set(normalized))
    return result


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
        encrypted_profile_image_metadata = payload.get("encrypted_profile_image_metadata")
        if not encrypted_profile_image_metadata:
            raise ValueError("encrypted_profile_image_metadata is required")

        team_record = {
            "team_id": team_id,
            "hashed_team_id": team_hash,
            "slug": payload.get("slug") or team_id,
            "encrypted_name": payload["encrypted_name"],
            "encrypted_description": payload.get("encrypted_description"),
            "encrypted_profile_image_metadata": encrypted_profile_image_metadata,
            "profile_image_s3_key": payload.get("profile_image_s3_key"),
            "encrypted_profile_image_aes_key": payload.get("encrypted_profile_image_aes_key"),
            "profile_image_aes_nonce": payload.get("profile_image_aes_nonce"),
            "profile_image_vault_key_id": payload.get("profile_image_vault_key_id"),
            "profile_image_updated_at": payload.get("profile_image_updated_at"),
            "encrypted_billing_profile": payload.get("encrypted_billing_profile"),
            "security_policy": dict(DEFAULT_SECURITY_POLICY),
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
            "user_id": user_id,
            "encrypted_member_profile": payload.get("encrypted_member_profile"),
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
        user_hash = hash_id(user_id)
        memberships = await self.directus_service.get_items(
            "team_memberships",
            params={
                "filter[hashed_user_id][_eq]": user_hash,
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "hashed_team_id,role,status",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(memberships, list) or not memberships:
            return []

        # Keep each Directus URL bounded, regardless of how many Teams a user has.
        # The membership query above is the authorization source; neither batch
        # can introduce a Team or wrapper outside that active membership set.
        team_hashes = list(dict.fromkeys(
            membership["hashed_team_id"] for membership in memberships
            if isinstance(membership.get("hashed_team_id"), str) and membership["hashed_team_id"]
        ))
        teams_by_hash: dict[str, dict[str, Any]] = {}
        wrappers_by_hash: dict[str, dict[str, Any]] = {}
        for offset in range(0, len(team_hashes), 64):
            chunk = team_hashes[offset:offset + 64]
            hashed_ids = ",".join(chunk)
            rows = await self.directus_service.get_items(
                "teams",
                params={
                    "filter[hashed_team_id][_in]": hashed_ids,
                    "filter[status][_eq]": ACTIVE_STATUS,
                    "fields": "id,team_id,hashed_team_id,slug,encrypted_name,encrypted_description,encrypted_profile_image_metadata,profile_image_s3_key,profile_image_updated_at,security_policy,status,created_at,updated_at",
                    "limit": -1,
                },
                no_cache=True,
                admin_required=True,
            )
            if isinstance(rows, list):
                for row in rows:
                    team_hash = row.get("hashed_team_id")
                    if team_hash in chunk and row.get("status") == ACTIVE_STATUS:
                        teams_by_hash.setdefault(team_hash, row)

            wrapper_rows = await self.directus_service.get_items(
                "team_key_wrappers",
                params={
                    "filter[hashed_team_id][_in]": hashed_ids,
                    "filter[hashed_user_id][_eq]": user_hash,
                    "filter[status][_eq]": ACTIVE_STATUS,
                    "fields": "hashed_team_id,hashed_user_id,team_key_epoch,encrypted_team_key,status",
                    "limit": -1,
                },
                no_cache=True,
                admin_required=True,
            )
            if isinstance(wrapper_rows, list):
                for wrapper in wrapper_rows:
                    team_hash = wrapper.get("hashed_team_id")
                    if team_hash in chunk and wrapper.get("hashed_user_id") == user_hash and wrapper.get("status") == ACTIVE_STATUS:
                        wrappers_by_hash.setdefault(team_hash, wrapper)

        teams: list[dict[str, Any]] = []
        for membership in memberships:
            team_hash = membership.get("hashed_team_id")
            row = teams_by_hash.get(team_hash) if isinstance(team_hash, str) else None
            if row is None:
                continue
            wrapper = wrappers_by_hash.get(team_hash, {})
            teams.append({
                **row,
                "security_policy": normalize_security_policy(row.get("security_policy") or {}),
                "role": membership.get("role"),
                **({"team_key_epoch": wrapper.get("team_key_epoch"), "encrypted_team_key": wrapper.get("encrypted_team_key")} if wrapper else {}),
            })
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
                "fields": "id,team_id,hashed_team_id,slug,encrypted_name,encrypted_description,encrypted_profile_image_metadata,profile_image_s3_key,profile_image_updated_at,encrypted_billing_profile,security_policy,status,created_at,updated_at",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if rows and isinstance(rows, list):
            wrapper = await self.get_team_key_wrapper_for_user_hash(hash_id(team_id), hash_id(user_id))
            return {**rows[0], "security_policy": normalize_security_policy(rows[0].get("security_policy") or {}), "role": membership.get("role"), **wrapper}
        return None

    async def get_team_key_wrapper_for_user_hash(self, team_hash: str, user_hash: str) -> dict[str, Any]:
        wrappers = await self.directus_service.get_items(
            "team_key_wrappers",
            params={
                "filter[hashed_team_id][_eq]": team_hash,
                "filter[hashed_user_id][_eq]": user_hash,
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "team_key_epoch,encrypted_team_key,status",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if wrappers and isinstance(wrappers, list):
            return {
                "team_key_epoch": wrappers[0].get("team_key_epoch"),
                "encrypted_team_key": wrappers[0].get("encrypted_team_key"),
            }
        return {}

    async def get_team_profile_image_private_record(self, team_id: str, user_id: str) -> dict[str, Any] | None:
        await self.require_team_role(team_id, user_id, {"owner", "admin", "member", "viewer"})
        rows = await self.directus_service.get_items(
            "teams",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "id,team_id,profile_image_s3_key,encrypted_profile_image_aes_key,profile_image_aes_nonce,profile_image_vault_key_id",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if rows and isinstance(rows, list):
            return rows[0]
        return None

    async def update_team(self, team_id: str, user_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
        await self.require_team_role(team_id, user_id, {"owner", "admin"})
        team = await self.get_team(team_id, user_id)
        if not team:
            return None
        allowed_fields = {"slug", "encrypted_name", "encrypted_description", "encrypted_profile_image_metadata", "encrypted_billing_profile", "updated_at"}
        update = {key: value for key, value in patch.items() if key in allowed_fields}
        if not update:
            return team
        return await self.directus_service.update_item("teams", team["id"], update, admin_required=True)

    async def update_security_policy(self, team_id: str, user_id: str, policy: dict[str, Any]) -> dict[str, Any] | None:
        await self.require_team_role(team_id, user_id, {"owner", "admin"})
        team = await self.get_team(team_id, user_id)
        if not team:
            return None
        normalized = normalize_security_policy({**(team.get("security_policy") or {}), **policy})
        updated = await self.directus_service.update_item("teams", team["id"], {"security_policy": normalized, "updated_at": int(time.time())}, admin_required=True)
        return normalized if updated else None

    async def process_team_profile_image(
        self,
        *,
        team_id: str,
        actor_user_id: str,
        encrypted_profile_image_metadata: str,
        s3_key: str,
        encrypted_profile_image_aes_key: str,
        profile_image_aes_nonce: str,
        profile_image_vault_key_id: str,
        updated_at: int | None = None,
    ) -> dict[str, Any]:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        team = await self.get_team(team_id, actor_user_id)
        if not team:
            raise TeamPermissionError("Team permission denied")
        now = int(updated_at or time.time())
        old_s3_key = team.get("profile_image_s3_key")
        patch = {
            "encrypted_profile_image_metadata": encrypted_profile_image_metadata,
            "profile_image_s3_key": s3_key,
            "encrypted_profile_image_aes_key": encrypted_profile_image_aes_key,
            "profile_image_aes_nonce": profile_image_aes_nonce,
            "profile_image_vault_key_id": profile_image_vault_key_id,
            "profile_image_updated_at": now,
            "updated_at": now,
        }
        updated = await self.directus_service.update_item("teams", team["id"], patch, admin_required=True)
        if not updated:
            raise RuntimeError("Failed to persist team profile image")
        return {"team": updated, "old_s3_key": old_s3_key}

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
                "fields": "id,hashed_team_id,hashed_user_id,user_id,role,status",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if response and isinstance(response, list):
            return response[0]
        return None

    async def list_active_member_hashes(self, team_id: str) -> set[str]:
        """Return active membership hashes for realtime authorization."""
        memberships = await self.directus_service.get_items(
            "team_memberships",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "hashed_user_id",
                "limit": -1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(memberships, list):
            raise RuntimeError("Failed to list active Team memberships")
        return {
            membership["hashed_user_id"]
            for membership in memberships
            if isinstance(membership, dict) and isinstance(membership.get("hashed_user_id"), str)
        }

    async def require_team_role(self, team_id: str, user_id: str, allowed_roles: set[str]) -> dict[str, Any]:
        membership = await self.get_membership(team_id, user_id)
        if not membership or membership.get("role") not in allowed_roles:
            raise TeamPermissionError("Team permission denied")
        teams = await self.directus_service.get_items(
            "teams",
            params={
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[status][_eq]": ACTIVE_STATUS,
                "fields": "id",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not isinstance(teams, list) or not teams:
            raise TeamPermissionError("Team permission denied")
        return membership

    async def get_security_policy_by_hash(self, team_hash: str) -> dict[str, Any] | None:
        rows = await self.directus_service.get_items(
            "teams", params={"filter[hashed_team_id][_eq]": team_hash, "filter[status][_eq]": ACTIVE_STATUS,
                             "fields": "security_policy", "limit": 1}, no_cache=True, admin_required=True,
        )
        return normalize_security_policy(rows[0].get("security_policy") or {}) if isinstance(rows, list) and rows else None

    async def list_members(self, team_id: str, actor_user_id: str) -> list[dict[str, Any]]:
        await self.require_team_role(team_id, actor_user_id, TEAM_ROLES)
        rows = await self.directus_service.get_items(
            "team_memberships", params={"filter[hashed_team_id][_eq]": hash_id(team_id),
                                        "filter[status][_eq]": ACTIVE_STATUS,
                                        "fields": "user_id,hashed_user_id,encrypted_member_profile,role,status,joined_at", "limit": -1},
            no_cache=True, admin_required=True,
        )
        if not isinstance(rows, list):
            raise RuntimeError("Failed to list team members")
        return [{key: row.get(key) for key in ("user_id", "hashed_user_id", "encrypted_member_profile", "role", "status", "joined_at")} for row in rows]

    async def update_own_member_profile(self, team_id: str, user_id: str, encrypted_member_profile: str) -> dict[str, Any] | None:
        membership = await self.require_team_role(team_id, user_id, TEAM_ROLES)
        updated = await self.directus_service.update_item(
            "team_memberships", membership["id"],
            {"encrypted_member_profile": encrypted_member_profile, "updated_at": int(time.time())},
            admin_required=True,
        )
        return {"user_id": user_id, "encrypted_member_profile": encrypted_member_profile} if updated else None

    async def list_invites(self, team_id: str, actor_user_id: str) -> list[dict[str, Any]]:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        rows = await self.directus_service.get_items(
            "team_invites", params={"filter[hashed_team_id][_eq]": hash_id(team_id),
                                    "fields": "invite_id,kind,role,status,encrypted_recipient_hint,expires_at,created_at", "limit": -1},
            no_cache=True, admin_required=True,
        )
        if not isinstance(rows, list):
            raise RuntimeError("Failed to list team invites")
        return [{**row, "kind": row.get("kind") or ("direct_email" if row.get("encrypted_recipient_hint") else "share_link")} for row in rows]

    async def revoke_invite(self, team_id: str, actor_user_id: str, invite_id: str) -> bool:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        rows = await self.directus_service.get_items(
            "team_invites", params={"filter[hashed_team_id][_eq]": hash_id(team_id),
                                    "filter[invite_id][_eq]": invite_id, "filter[status][_eq]": "pending",
                                    "fields": "id", "limit": 1}, no_cache=True, admin_required=True,
        )
        if not isinstance(rows, list) or not rows:
            return False
        return bool(await self.directus_service.update_item("team_invites", rows[0]["id"],
                                                           {"status": "revoked", "revoked_at": int(time.time())}, admin_required=True))

    async def create_invite(self, team_id: str, inviter_user_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        await self.require_team_role(team_id, inviter_user_id, {"owner", "admin"})
        role = payload.get("role") or "member"
        if role not in INVITE_ROLES:
            raise ValueError("Invalid invite role")
        now = int(payload.get("created_at") or time.time())
        kind = "direct_email" if payload.get("hashed_recipient_email") else "share_link"
        record = {
            "invite_id": payload["invite_id"],
            "hashed_team_id": hash_id(team_id),
            "hashed_recipient_email": payload.get("hashed_recipient_email"),
            "kind": kind,
            "encrypted_recipient_hint": payload.get("encrypted_recipient_hint"),
            "encrypted_invite_team_key": payload.get("encrypted_invite_team_key"),
            "invite_key_kdf_context": payload.get("invite_key_kdf_context"),
            "role": role,
            "status": "pending",
            "created_by_hash": hash_id(inviter_user_id),
            "one_time_token_hash": payload.get("one_time_token_hash"),
            "sent_at": payload.get("sent_at"),
            "expires_at": payload.get("expires_at") or (int(time.time()) + 86400 if kind == "share_link" else None),
            "created_at": now,
            "accepted_at": None,
            "declined_at": None,
            "revoked_at": None,
        }
        success, data = await self.directus_service.create_item("team_invites", record, admin_required=True)
        return data if success else None

    async def get_invite_for_recipient(self, invite_id: str, recipient_email_hash: str | None) -> dict[str, Any] | None:
        invites = await self.directus_service.get_items(
            "team_invites",
            params={
                "filter[invite_id][_eq]": invite_id,
                "filter[status][_eq]": "pending",
                "fields": "invite_id,hashed_team_id,hashed_recipient_email,role,status,encrypted_invite_team_key,invite_key_kdf_context,expires_at",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if invites and isinstance(invites, list) and (not invites[0].get("expires_at") or int(invites[0]["expires_at"]) > time.time()):
            invite = invites[0]
            if not invite.get("hashed_recipient_email") or invite["hashed_recipient_email"] == recipient_email_hash:
                return invite
        return None

    async def get_invite_join_context(self, invite_id: str) -> dict[str, Any] | None:
        rows = await self.directus_service.get_items(
            "team_invites", params={"filter[invite_id][_eq]": invite_id,
                                    "filter[status][_eq]": "pending",
                                    "fields": "invite_id,hashed_team_id,hashed_recipient_email,kind,expires_at", "limit": 1},
            no_cache=True, admin_required=True,
        )
        return rows[0] if isinstance(rows, list) and rows else None

    async def accept_invite(
        self,
        invite_id: str,
        user_id: str,
        accepted_at: int | None = None,
        encrypted_team_key: str | None = None,
        recipient_email_hash: str | None = None,
        encrypted_member_profile: str | None = None,
        verified_email_domain: str | None = None,
        require_approval: bool = True,
    ) -> dict[str, Any] | None:
        invite_filters: dict[str, Any] = {
            "filter[invite_id][_eq]": invite_id,
            "filter[status][_eq]": "pending",
            "fields": "id,invite_id,hashed_team_id,hashed_recipient_email,kind,role,status,expires_at",
            "limit": 1,
        }
        invites = await self.directus_service.get_items(
            "team_invites",
            params=invite_filters,
            no_cache=True,
            admin_required=True,
        )
        if not invites or not isinstance(invites, list):
            return None
        invite = invites[0]
        now = int(accepted_at or time.time())
        existing = await self.directus_service.get_items(
            "team_memberships", params={"filter[hashed_team_id][_eq]": invite["hashed_team_id"],
                                        "filter[hashed_user_id][_eq]": hash_id(user_id),
                                        "filter[status][_eq]": ACTIVE_STATUS, "fields": "id", "limit": 1},
            no_cache=True, admin_required=True,
        )
        if not isinstance(existing, list) or existing:
            return None
        if invite.get("expires_at") and int(invite["expires_at"]) <= now:
            return None
        direct_email = bool(invite.get("hashed_recipient_email"))
        if direct_email and invite.get("hashed_recipient_email") != recipient_email_hash:
            return None
        if direct_email and not encrypted_team_key:
            raise ValueError("encrypted_team_key is required")
        if direct_email or not require_approval:
            if not encrypted_team_key:
                raise ValueError("encrypted_team_key is required")
            membership = await self._create_member_from_invite(invite, user_id, encrypted_team_key, now, encrypted_member_profile)
            if not membership:
                return None
            await self.directus_service.update_item("team_invites", invite["id"], {"status": "accepted", "accepted_at": now}, admin_required=True)
            return {"membership": membership}
        access_request = {
            "access_request_id": str(uuid4()),
            "invite_id": invite_id,
            "hashed_team_id": invite["hashed_team_id"],
            "hashed_user_id": hash_id(user_id),
            "user_id": user_id,
            "encrypted_member_profile": encrypted_member_profile,
            "verified_email_domain": verified_email_domain,
            "role": invite["role"],
            "encrypted_team_key": encrypted_team_key,
            "status": PENDING_ACCESS_APPROVAL_STATUS,
            "requested_at": now,
            "approved_at": None,
            "rejected_at": None,
            "resolved_by_user_hash": None,
        }
        success, request = await self.directus_service.create_item("team_access_requests", access_request, admin_required=True)
        if not success:
            return None
        await self.directus_service.update_item("team_invites", invite["id"], {"status": "access_requested", "accepted_at": now}, admin_required=True)
        return request

    async def _create_member_from_invite(self, invite: dict[str, Any], user_id: str, encrypted_team_key: str, now: int, encrypted_member_profile: str | None) -> dict[str, Any] | None:
        membership_record = {
            "hashed_team_id": invite["hashed_team_id"], "hashed_user_id": hash_id(user_id),
            "user_id": user_id, "role": invite["role"], "status": ACTIVE_STATUS,
            "encrypted_member_profile": encrypted_member_profile,
            "invited_by_hash": None, "joined_at": now, "removed_at": None,
            "created_at": now, "updated_at": now,
        }
        wrapper_record = {
            "hashed_team_id": invite["hashed_team_id"], "hashed_user_id": hash_id(user_id),
            "team_key_epoch": TEAM_KEY_EPOCH_V1, "encrypted_team_key": encrypted_team_key,
            "status": ACTIVE_STATUS, "created_at": now, "revoked_at": None,
        }
        success, membership = await self.directus_service.create_item("team_memberships", membership_record, admin_required=True)
        if not success:
            return None
        success, _wrapper = await self.directus_service.create_item("team_key_wrappers", wrapper_record, admin_required=True)
        if not success:
            await self.directus_service.update_item("team_memberships", membership["id"], {"status": "removed", "removed_at": now}, admin_required=True)
            return None
        return membership

    async def list_access_requests(self, team_id: str, actor_user_id: str, status: str | None = PENDING_ACCESS_APPROVAL_STATUS) -> list[dict[str, Any]]:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        params: dict[str, Any] = {
            "filter[hashed_team_id][_eq]": hash_id(team_id),
                "fields": "id,access_request_id,invite_id,hashed_team_id,hashed_user_id,role,status,encrypted_team_key,requested_at,approved_at,rejected_at",
            "limit": -1,
        }
        if status:
            params["filter[status][_eq]"] = status
        requests = await self.directus_service.get_items(
            "team_access_requests",
            params=params,
            no_cache=True,
            admin_required=True,
        )
        return requests if isinstance(requests, list) else []

    async def approve_access_request(
        self,
        team_id: str,
        actor_user_id: str,
        access_request_id: str,
        encrypted_team_key: str | None = None,
        approved_at: int | None = None,
    ) -> dict[str, Any] | None:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        requests = await self.directus_service.get_items(
            "team_access_requests",
            params={
                "filter[access_request_id][_eq]": access_request_id,
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[status][_eq]": PENDING_ACCESS_APPROVAL_STATUS,
                "fields": "id,access_request_id,invite_id,hashed_team_id,hashed_user_id,user_id,encrypted_member_profile,verified_email_domain,role,status,encrypted_team_key",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not requests or not isinstance(requests, list):
            return None
        request = requests[0]
        policy = await self.get_security_policy_by_hash(request["hashed_team_id"])
        if policy is None:
            raise TeamPermissionError("Team permission denied")
        if policy["restrict_email_domains"] and request.get("verified_email_domain") not in policy["allowed_email_domains"]:
            raise TeamPermissionError("Team email domain not allowed")
        if policy["require_strong_auth"]:
            recipient_user_id = request.get("user_id")
            if not recipient_user_id:
                raise TeamPermissionError("Team strong authentication required")
            user_fields = await self.directus_service.get_user_fields_direct(recipient_user_id, ["encrypted_tfa_secret"], no_cache=True)
            if not isinstance(user_fields, dict) or not user_fields.get("encrypted_tfa_secret"):
                passkeys = await self.directus_service.get_items(
                    "user_passkeys", params={"filter[user_id][_eq]": recipient_user_id, "fields": "id", "limit": 1},
                    no_cache=True, admin_required=True,
                )
                if not isinstance(passkeys, list) or not passkeys:
                    raise TeamPermissionError("Team strong authentication required")
        existing = await self.directus_service.get_items(
            "team_memberships", params={"filter[hashed_team_id][_eq]": request["hashed_team_id"],
                                        "filter[hashed_user_id][_eq]": request["hashed_user_id"],
                                        "filter[status][_eq]": ACTIVE_STATUS, "fields": "id", "limit": 1},
            no_cache=True, admin_required=True,
        )
        if not isinstance(existing, list) or existing:
            raise TeamPermissionError("Team membership already active")
        wrapper_ciphertext = encrypted_team_key or request.get("encrypted_team_key")
        if not wrapper_ciphertext:
            raise ValueError("encrypted_team_key is required")
        now = int(approved_at or time.time())
        membership_record = {
            "hashed_team_id": request["hashed_team_id"],
            "hashed_user_id": request["hashed_user_id"],
            "user_id": request.get("user_id"),
            "encrypted_member_profile": request.get("encrypted_member_profile"),
            "role": request["role"],
            "status": ACTIVE_STATUS,
            "invited_by_hash": None,
            "joined_at": now,
            "removed_at": None,
            "created_at": now,
            "updated_at": now,
        }
        wrapper_record = {
            "hashed_team_id": request["hashed_team_id"],
            "hashed_user_id": request["hashed_user_id"],
            "team_key_epoch": TEAM_KEY_EPOCH_V1,
            "encrypted_team_key": wrapper_ciphertext,
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
        await self.directus_service.update_item(
            "team_access_requests",
            request["id"],
            {"status": "approved", "approved_at": now, "resolved_by_user_hash": hash_id(actor_user_id)},
            admin_required=True,
        )
        invites = await self.directus_service.get_items(
            "team_invites",
            params={"filter[invite_id][_eq]": request["invite_id"], "fields": "id,status", "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        if isinstance(invites, list) and invites:
            await self.directus_service.update_item("team_invites", invites[0]["id"], {"status": "accepted", "accepted_at": now}, admin_required=True)
        return membership

    async def reject_access_request(self, team_id: str, actor_user_id: str, access_request_id: str, rejected_at: int | None = None) -> bool:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        requests = await self.directus_service.get_items(
            "team_access_requests",
            params={
                "filter[access_request_id][_eq]": access_request_id,
                "filter[hashed_team_id][_eq]": hash_id(team_id),
                "filter[status][_eq]": PENDING_ACCESS_APPROVAL_STATUS,
                "fields": "id,status",
                "limit": 1,
            },
            no_cache=True,
            admin_required=True,
        )
        if not requests or not isinstance(requests, list):
            return False
        now = int(rejected_at or time.time())
        updated = await self.directus_service.update_item(
            "team_access_requests",
            requests[0]["id"],
            {"status": "rejected", "rejected_at": now, "resolved_by_user_hash": hash_id(actor_user_id)},
            admin_required=True,
        )
        return bool(updated)

    async def decline_invite(self, invite_id: str, recipient_email_hash: str | None, declined_at: int | None = None) -> bool:
        invites = await self.directus_service.get_items(
            "team_invites",
            params={"filter[invite_id][_eq]": invite_id, "filter[status][_eq]": "pending", "fields": "id,status,hashed_recipient_email", "limit": 1},
            no_cache=True,
            admin_required=True,
        )
        if not invites or not isinstance(invites, list) or not invites[0].get("hashed_recipient_email") or invites[0]["hashed_recipient_email"] != recipient_email_hash:
            return False
        now = int(declined_at or time.time())
        updated = await self.directus_service.update_item("team_invites", invites[0]["id"], {"status": "declined", "declined_at": now}, admin_required=True)
        return bool(updated)

    async def remove_member(self, team_id: str, actor_user_id: str, target_user_id: str, removed_at: int | None = None) -> bool:
        target = await self.prepare_member_removal(team_id, actor_user_id, target_user_id)
        if not target:
            return False
        now = int(removed_at or time.time())
        await self.deactivate_member(target, removed_at=now)
        await self.revoke_member_key_wrappers(team_id, target_user_id, revoked_at=now)
        return True

    async def deactivate_member(self, membership: dict[str, Any], *, removed_at: int) -> None:
        """Persist the fail-closed membership state before cache or wrapper cleanup."""
        if not await self.directus_service.update_item(
            "team_memberships",
            membership["id"],
            {"status": "removed", "removed_at": removed_at, "updated_at": removed_at},
            admin_required=True,
        ):
            raise RuntimeError("Failed to remove team membership")

    async def revoke_member_key_wrappers(
        self, team_id: str, target_user_id: str, *, revoked_at: int
    ) -> None:
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
        if not isinstance(wrappers, list):
            raise RuntimeError("Failed to list active team key wrappers")
        for wrapper in wrappers:
            if not await self.directus_service.update_item(
                "team_key_wrappers",
                wrapper["id"],
                {"status": "revoked", "revoked_at": revoked_at},
                admin_required=True,
            ):
                raise RuntimeError("Failed to revoke team key wrapper")

    async def prepare_member_removal(
        self, team_id: str, actor_user_id: str, target_user_id: str
    ) -> dict[str, Any] | None:
        """Authorize removal before callers revoke runtime access."""
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        target = await self.get_membership(team_id, target_user_id)
        if not target or target.get("role") == "owner":
            return None
        return target

    async def set_member_role(self, team_id: str, actor_user_id: str, target_user_id: str, role: str, updated_at: int | None = None) -> dict[str, Any] | None:
        await self.require_team_role(team_id, actor_user_id, {"owner", "admin"})
        if role not in TEAM_ROLES:
            raise ValueError("Invalid team role")
        target = await self.get_membership(team_id, target_user_id)
        if not target or target.get("role") == "owner" or role == "owner":
            return None
        now = int(updated_at or time.time())
        return await self.directus_service.update_item("team_memberships", target["id"], {"role": role, "updated_at": now}, admin_required=True)
