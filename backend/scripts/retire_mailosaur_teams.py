"""Dry-run-first normal Team deletion for confirmed obsolete dev test accounts.

Only the exact retired Mailosaur server is eligible. Every owner and active
member must freshly decrypt/hash-verify a mandatory confirmed account contact.
Normal Team lifecycle cancellation/offlining/deletion retains Team tombstones,
memberships and storage; this tool never physically purges those records.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import logging
import os
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.scripts.retire_mailosaur_accounts import (  # noqa: E402
    RETIRED_DOMAIN,
    _rows,
    recipient_hash,
    require_development,
    write_receipt,
)


def _hash_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def verified_retired_users(
    directus, encryption, user_ids: set[str] | None = None
) -> dict[str, dict]:
    """Return only identities linked to a current verified mandatory contact."""
    filters = {"purpose": {"_eq": "account_lifecycle"}, "verified_at": {"_nnull": True}}
    if user_ids is not None:
        filters["user_id"] = {"_in": sorted(user_ids)}
    contacts = await _rows(
        directus,
        "account_contact_emails",
        filters=filters,
        fields="id,user_id,hashed_email,encrypted_email_address,purpose,verified_at",
    )
    protected = {
        value.strip().lower()
        for key, value in os.environ.items()
        if key in {"DATABASE_ADMIN_EMAIL", "ADMIN_NOTIFY_EMAIL"}
    }
    users = {}
    for contact in contacts:
        if contact.get("purpose") != "account_lifecycle" or not contact.get(
            "verified_at"
        ):
            raise RuntimeError("Mandatory contact verification metadata is unavailable")
        email = await encryption.decrypt_account_contact_email(
            contact["encrypted_email_address"]
        )
        if not isinstance(email, str):
            raise RuntimeError("Mandatory contact could not be decrypted")
        email = email.strip().lower()
        if email.count("@") != 1 or email.rsplit("@", 1)[1] != RETIRED_DOMAIN:
            continue
        if email in protected:
            raise RuntimeError("Retired contact is a protected administrator")
        digest = recipient_hash(email)
        if digest != contact.get("hashed_email"):
            raise RuntimeError("Retired mandatory contact hash does not match")
        current = await _rows(
            directus,
            "users",
            filters={"id": {"_eq": contact["user_id"]}},
            fields="id,hashed_email,status",
        )
        if not current:
            continue
        if len(current) != 1 or current[0].get("hashed_email") != digest:
            raise RuntimeError("Retired contact is not the current account identity")
        user = current[0]
        hashed_user = _hash_id(user["id"])
        if hashed_user in users:
            raise RuntimeError("Retired account has ambiguous mandatory contacts")
        users[hashed_user] = {"user_id": user["id"], "recipient_hash": digest}
    return users


async def _team(directus, team_hash: str) -> dict:
    rows = await _rows(
        directus,
        "teams",
        filters={"hashed_team_id": {"_eq": team_hash}},
        fields="id,team_id,hashed_team_id,status",
    )
    if len(rows) != 1 or rows[0].get("hashed_team_id") != team_hash:
        raise RuntimeError("Owned Team identity is unavailable or ambiguous")
    row = rows[0]
    if not row.get("team_id") or _hash_id(row["team_id"]) != team_hash:
        raise RuntimeError("Owned Team identity does not match its hash")
    return row


async def validate_team(
    directus, encryption, team_hash: str, user_ids: set[str] | None = None
) -> dict:
    """Recheck membership and mandatory contacts immediately before lifecycle work."""
    team = await _team(directus, team_hash)
    if team["status"] == "deleted":
        return {
            "team": team,
            "already_deleted": True,
            "active_members": 0,
            "blocker": None,
        }
    if team["status"] != "active":
        raise RuntimeError("Owned Team lifecycle state is not eligible for deletion")
    members = await _rows(
        directus,
        "team_memberships",
        filters={
            "hashed_team_id": {"_eq": team_hash},
            "status": {"_eq": "active"},
        },
        fields="id,hashed_team_id,hashed_user_id,role,status",
    )
    users = await verified_retired_users(directus, encryption, user_ids)
    if not members or any(
        row.get("hashed_team_id") != team_hash
        or row.get("status") != "active"
        or row.get("hashed_user_id") not in users
        for row in members
    ):
        return {
            "team": team,
            "already_deleted": False,
            "active_members": len(members),
            "blocker": "unverified_or_external_member",
        }
    owners = [row for row in members if row.get("role") == "owner"]
    if not owners:
        return {
            "team": team,
            "already_deleted": False,
            "active_members": len(members),
            "blocker": "current_owner_missing",
        }
    profiles = await _rows(
        directus,
        "billing_profiles",
        filters={
            "owner_kind": {"_eq": "team"},
            "owner_hash": {"_eq": team_hash},
        },
        fields="id,monthly_subscription_id,monthly_subscription_status",
    )
    if len(profiles) > 1:
        raise RuntimeError("Team billing identity is ambiguous")
    paid_subscription = any(
        row.get("monthly_subscription_id")
        and row.get("monthly_subscription_status") != "canceled"
        for row in profiles
    )
    return {
        "team": team,
        "already_deleted": False,
        "active_members": len(members),
        "owner_user_id": users[owners[0]["hashed_user_id"]]["user_id"],
        "blocker": "recurring_subscription_requires_normal_cancellation"
        if paid_subscription
        else None,
    }


async def prepare_teams(directus, encryption) -> tuple[list[dict], dict]:
    users = await verified_retired_users(directus, encryption)
    if not users:
        return [], {"candidate_accounts": 0, "deleted_team_tombstones": 0}
    memberships = await _rows(
        directus,
        "team_memberships",
        filters={
            "hashed_user_id": {"_in": sorted(users)},
            "role": {"_eq": "owner"},
            "status": {"_eq": "active"},
        },
        fields="id,hashed_team_id,hashed_user_id,role,status",
    )
    hashes = set()
    for membership in memberships:
        if (
            membership.get("hashed_user_id") not in users
            or membership.get("role") != "owner"
            or membership.get("status") != "active"
            or not membership.get("hashed_team_id")
        ):
            raise RuntimeError("Retired Team ownership discovery changed")
        hashes.add(membership["hashed_team_id"])
    candidates = []
    tombstones = 0
    for team_hash in sorted(hashes):
        team = await _team(directus, team_hash)
        if team["status"] == "deleted":
            tombstones += 1
            continue
        user_ids = {user["user_id"] for user in users.values()}
        candidate = await validate_team(directus, encryption, team_hash, user_ids)
        candidate["retired_user_ids"] = sorted(user_ids)
        candidates.append(candidate)
    return candidates, {
        "candidate_accounts": len(users),
        "deleted_team_tombstones": tombstones,
    }


async def normal_team_deletion(
    directus, cache, encryption, *, team_id: str, owner_user_id: str
) -> None:
    """Reuse the full normal lifecycle; no direct status update or storage purge."""
    from fastapi import Request, Response
    from backend.core.api.app.routes.teams import delete_team

    request = Request(
        {
            "type": "http",
            "method": "DELETE",
            "path": f"/v1/teams/{team_id}",
            "headers": [],
            "app": SimpleNamespace(state=SimpleNamespace(cache_service=cache)),
        }
    )
    # This administrative invocation has no public HTTP request/rate-limiter.
    # The normal handler still performs its own current owner permission check.
    result = await inspect.unwrap(delete_team)(
        request=request,
        response=Response(),
        team_id=team_id,
        current_user=SimpleNamespace(id=owner_user_id),
        directus_service=directus,
        encryption_service=encryption,
        payment_service=None,
    )
    if result != {"success": True}:
        raise RuntimeError("Normal Team deletion did not report success")


async def retire_team(
    directus, cache, encryption, candidate: dict, lifecycle=normal_team_deletion
) -> bool:
    user_ids = (
        set(candidate["retired_user_ids"]) if "retired_user_ids" in candidate else None
    )
    fresh = await validate_team(
        directus,
        encryption,
        candidate["team"]["hashed_team_id"],
        user_ids,
    )
    if fresh["already_deleted"]:
        return False
    if fresh["blocker"]:
        raise RuntimeError(
            "Team acquired an unsafe member, owner, or billing state; deletion stopped"
        )
    await lifecycle(
        directus,
        cache,
        encryption,
        team_id=fresh["team"]["team_id"],
        owner_user_id=fresh["owner_user_id"],
    )
    final = await _team(directus, fresh["team"]["hashed_team_id"])
    if final["status"] != "deleted":
        raise RuntimeError(
            "Normal Team deletion did not persist its lifecycle tombstone"
        )
    return True


async def run(args) -> dict:
    require_development()
    from backend.scripts.delete_user_account import initialize_services

    cache, encryption, directus = await initialize_services()
    receipt = {
        "domain": RETIRED_DOMAIN,
        "dry_run": not args.apply,
        "deleted_teams": 0,
        "normal_deletion_retains_memberships_and_storage": True,
    }
    try:
        if not await encryption.initialize():
            raise RuntimeError("Cannot establish mandatory contact decryption")
        candidates, counts = await prepare_teams(directus, encryption)
        receipt.update(
            counts,
            active_teams=len(candidates),
            active_memberships=sum(row["active_members"] for row in candidates),
            blocked_teams=sum(bool(row["blocker"]) for row in candidates),
        )
        receipt["blockers"] = sorted(
            {row["blocker"] for row in candidates if row["blocker"]}
        )
        write_receipt(args.receipt, receipt)
        if args.apply:
            if receipt["blocked_teams"]:
                raise RuntimeError(
                    "Team dry-run identified blockers; no Team deletion was started"
                )
            for candidate in candidates:
                receipt["deleted_teams"] += await retire_team(
                    directus, cache, encryption, candidate
                )
                write_receipt(args.receipt, receipt)
        return receipt
    except Exception:
        receipt["stopped"] = True
        write_receipt(args.receipt, receipt)
        raise
    finally:
        await directus.close()
        await encryption.close()
        await cache.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete only freshly reverified eligible Teams through normal lifecycle",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        required=True,
        help="Private counters-only receipt outside the repository",
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        print(json.dumps(asyncio.run(run(args))))
    except Exception as exc:
        raise SystemExit(
            f"Team retirement stopped ({type(exc).__name__}); inspect the private counters receipt"
        ) from None


if __name__ == "__main__":
    main()
