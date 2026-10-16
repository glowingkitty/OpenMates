"""Dry-run-first retirement of obsolete development Mailosaur accounts.

Only the confirmed retired inbox server is eligible. Suppress mail and stop
personal schedules before using the normal account-deletion task. No email
addresses or secrets appear in output or receipts.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from copy import deepcopy
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
import uuid
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
RETIRED_DOMAIN = "ae20drx9.mailosaur.net"


def require_development(environ=None) -> None:
    values = os.environ if environ is None else environ
    if values.get("SERVER_ENVIRONMENT") != "development" or values.get("CMS_URL") != "http://cms:8055":
        raise RuntimeError("Retirement requires the registered development CMS")
    if values.get("OPENMATES_CI_ISOLATED") == "1":
        raise RuntimeError("Retirement is not an isolated CI operation")


def recipient_hash(email: str) -> str:
    email = email.strip().lower()
    if email.count("@") != 1 or email.rsplit("@", 1)[1] != RETIRED_DOMAIN:
        raise ValueError("Only the confirmed retired Mailosaur server is eligible")
    return base64.b64encode(hashlib.sha256(email.encode()).digest()).decode()


async def _rows(directus, collection: str, *, filters: dict, fields: str) -> list[dict]:
    result = []
    for offset in range(0, 100_000, 500):
        page = await directus.get_items(collection, params={"filter": filters,
            "fields": fields, "sort": "id", "limit": 500, "offset": offset},
            admin_required=True, raise_on_error=True, no_cache=True)
        if not isinstance(page, list):
            raise RuntimeError("Candidate lookup did not return records")
        result.extend(page)
        if len(page) < 500:
            return result
    raise RuntimeError("Candidate lookup exceeded its safety bound")


async def discover_emails(directus, encryption) -> set[str]:
    contacts = await _rows(directus, "account_contact_emails", filters={},
                          fields="id,hashed_email,encrypted_email_address")
    emails = set()
    for row in contacts:
        email = await encryption.decrypt_account_contact_email(row["encrypted_email_address"])
        if isinstance(email, str) and email.lower().strip().endswith("@" + RETIRED_DOMAIN):
            if recipient_hash(email) != row["hashed_email"]:
                raise RuntimeError("Retired contact identity does not match its hash")
            emails.add(email.lower().strip())
    # Legacy configured slots may predate the account-contact backfill.
    for key, email in os.environ.items():
        if key.startswith("OPENMATES_TEST_ACCOUNT") and key.endswith("EMAIL") and email.lower().strip().endswith("@" + RETIRED_DOMAIN):
            emails.add(email.lower().strip())
    return emails


async def has_non_deleted_team_ownership(directus, memberships: list[dict], workflows: list[dict]) -> bool:
    """Deleted Team tombstones do not grant current ownership; ambiguity blocks."""
    hashes = set()
    for membership in memberships:
        team_hash = membership.get("hashed_team_id")
        if not isinstance(team_hash, str) or len(team_hash) != 64:
            raise RuntimeError("Team ownership metadata is unavailable; preserve the account")
        hashes.add(team_hash)
    hashes.update(row["hashed_team_id"] for row in workflows
                  if row.get("hashed_team_id") and row["status"] != "deleted")
    for team_hash in hashes:
        teams = await _rows(directus, "teams", filters={"hashed_team_id": {"_eq": team_hash}},
                            fields="id,hashed_team_id,status")
        if len(teams) != 1 or teams[0].get("hashed_team_id") != team_hash:
            raise RuntimeError("Team ownership target is unavailable; preserve the account")
        if teams[0].get("status") != "deleted":
            return True
    return False


def validated_workflow_record(row: dict, workflow_id: str, user_id: str) -> dict:
    """Read legacy JSON with its authoritative version, without repairing DB rows."""
    owner_hash = "user_sha256:" + hashlib.sha256(user_id.encode()).hexdigest()
    record = row.get("record_json")
    if (not isinstance(record, dict) or row.get("id") != workflow_id
            or row.get("workflow_id") != workflow_id or record.get("id") != workflow_id
            or row.get("hashed_user_id") != owner_hash or record.get("owner_hash") != owner_hash
            or row.get("hashed_team_id") or record.get("hashed_team_id")
            or not isinstance(row.get("status"), str) or record.get("status") != row["status"]
            or type(row.get("enabled")) is not bool or record.get("enabled") != row["enabled"]):
        raise RuntimeError("Retirement workflow identity or personal context does not match")
    version = row.get("version")
    if type(version) is not int or version < 1:
        raise RuntimeError("Retirement workflow authoritative version is unavailable")
    if "version" in record and (type(record["version"]) is not int or record["version"] != version):
        raise RuntimeError("Retirement workflow JSON version disagrees with its authoritative row")
    normalized = deepcopy(record)
    normalized["version"] = version
    return normalized


def create_retirement_workflow_repository():
    """Keep legacy compatibility scoped to this administrative normal-delete path."""
    from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository

    class RetirementWorkflowRepository(DirectusWorkflowRepository):
        def _retirement_record(self, workflow_id: str, user_id: str, team_id=None):
            if team_id is not None:
                raise RuntimeError("Retirement never changes Team workflows")
            owner_hash = "user_sha256:" + hashlib.sha256(user_id.encode()).hexdigest()
            row = self._find_one(self.WORKFLOWS, {"_and": [
                {"id": {"_eq": workflow_id}},
                {"hashed_user_id": {"_eq": owner_hash}, "hashed_team_id": {"_null": True}},
            ]}, fields="id,workflow_id,hashed_user_id,hashed_team_id,status,enabled,version,record_json")
            if row is None:
                return None
            return validated_workflow_record(row, workflow_id, user_id)

        def get_workflow(self, workflow_id: str, user_id: str, team_id=None):
            record = self._retirement_record(workflow_id, user_id, team_id)
            return record if record and record["status"] != "deleted" else None

        def get_workflow_including_deleted(self, workflow_id: str, user_id: str, team_id=None):
            return self._retirement_record(workflow_id, user_id, team_id)

    return RetirementWorkflowRepository()


def workflow_retirement_transaction(record: dict, *, operation_id: str | None = None, now: int | None = None) -> dict:
    """Normal atomic delete publication without decrypting an old edit snapshot."""
    operation_id = operation_id or str(uuid.uuid4())
    expected = record["version"]
    deleted = deepcopy(record)
    deleted.update(status="deleted", enabled=False, version=expected + 1,
                   updated_at=max(int(now if now is not None else time.time()), int(record["updated_at"])))
    payload = {
        "owner_hash": record["owner_hash"], "hashed_team_id": None,
        "operation_id": operation_id, "session_id": None, "undo_of_operation_id": None,
        "writes": [{"workflow_id": record["id"], "expected_version": expected, "record": deleted, "trigger": None}],
        "blobs": [], "obsolete_refs": [],
        "mutations": [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"retired-workflow:{operation_id}")),
            "operation_id": operation_id, "session_id": None, "hashed_user_id": record["owner_hash"],
            "type": "delete_workflow", "target_type": "workflow", "target_id": record["id"],
            "encrypted_before_ref": None, "encrypted_before_checksum": None,
            "encrypted_after_ref": None, "encrypted_after_checksum": None,
            "undone_at": None, "created_at": deleted["updated_at"]}],
        "outcomes": [{"workflow_id": record["id"], "version": expected + 1, "after_ref": None}],
    }
    identity = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["request_hash"] = "sha256:" + hashlib.sha256(identity).hexdigest()
    return payload


def create_retirement_workflow_service(repository):
    """Administrative caller of the same private owner/version/blob-fenced commit."""
    from backend.core.api.app.services.workflow_service import WorkflowService

    class RetirementWorkflowService(WorkflowService):
        def delete_workflow(self, workflow_id: str, user_id: str, team_id=None) -> bool:
            if team_id is not None:
                raise RuntimeError("Retirement never changes Team workflows")
            record = self.repository.get_workflow(workflow_id, user_id)
            if record is None:
                raise RuntimeError("Retirement workflow changed before its atomic delete")
            payload = workflow_retirement_transaction(record)
            # The same normal authoring endpoint locks/rechecks current owner,
            # personal context/version, verifies immutable encrypted references,
            # removes the trigger, and fences undelivered run/chat output.
            result = self.repository.authoring_request("POST", "/", payload=payload)
            if (result.get("owner_hash") != payload["owner_hash"]
                    or result.get("operation_id") != payload["operation_id"]
                    or result.get("request_hash") != payload["request_hash"]
                    or result.get("outcomes") != payload["outcomes"]):
                raise RuntimeError("Atomic workflow retirement receipt is unavailable")
            final = self.repository.get_workflow_including_deleted(workflow_id, user_id)
            if (not final or final.get("status") != "deleted" or final.get("enabled") is not False
                    or final.get("version") != record["version"] + 1):
                raise RuntimeError("Atomic workflow retirement did not persist a checked tombstone")
            return True

    return RetirementWorkflowService(repository=repository)


async def prepare_candidates(directus, emails: set[str]) -> list[dict]:
    candidates = []
    protected = {value.strip().lower() for key, value in os.environ.items()
                 if key in {"DATABASE_ADMIN_EMAIL", "ADMIN_NOTIFY_EMAIL"}}
    for email in sorted(emails):
        hashed = recipient_hash(email)
        if email in protected:
            raise RuntimeError("A protected administrator uses the retired inbox server")
        users = await _rows(directus, "users", filters={"hashed_email": {"_eq": hashed}},
                           fields="id,hashed_email,status,email_notifications_enabled")
        if len(users) > 1:
            raise RuntimeError("Retired address maps to multiple users")
        if not users:
            continue
        user = users[0]
        if user.get("hashed_email") != hashed:
            raise RuntimeError("Retired user identity changed during discovery")
        owner_hash = hashlib.sha256(user["id"].encode()).hexdigest()
        reminders = await _rows(directus, "reminders", filters={"hashed_user_id": {"_eq": owner_hash}},
                                fields="id,status")
        workflows = await _rows(directus, "workflows",
            filters={"hashed_user_id": {"_in": [owner_hash, "user_sha256:" + owner_hash]}},
            fields="id,workflow_id,status,enabled,hashed_team_id")
        memberships = await _rows(directus, "team_memberships", filters={"hashed_user_id": {"_eq": owner_hash},
            "status": {"_eq": "active"}, "role": {"_eq": "owner"}}, fields="id,hashed_team_id")
        candidates.append({"user": user, "recipient_hash": hashed,
                           "reminders": reminders, "workflows": workflows,
                           "blocked_reason": "team_ownership" if await has_non_deleted_team_ownership(
                               directus, memberships, workflows) else None})
    return candidates


async def owner_schedules(directus, user_id: str) -> tuple[list[dict], list[dict]]:
    """Recheck current schedules and ownership, including at worker dispatch."""
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    reminders = await _rows(directus, "reminders", filters={"hashed_user_id": {"_eq": owner_hash}}, fields="id,status")
    workflows = await _rows(directus, "workflows", filters={"hashed_user_id": {"_in": [owner_hash, "user_sha256:" + owner_hash]}},
                           fields="id,workflow_id,status,enabled,hashed_team_id")
    memberships = await _rows(directus, "team_memberships", filters={"hashed_user_id": {"_eq": owner_hash},
        "status": {"_eq": "active"}, "role": {"_eq": "owner"}}, fields="id,hashed_team_id")
    if await has_non_deleted_team_ownership(directus, memberships, workflows):
        raise RuntimeError("Retired account has Team ownership; preserve it for explicit review")
    return reminders, workflows


async def assert_retirement_ready(directus, user_id: str) -> None:
    reminders, workflows = await owner_schedules(directus, user_id)
    if any(row["status"] == "pending" for row in reminders) or any(row.get("enabled") for row in workflows):
        raise RuntimeError("Retired account acquired another active schedule; preserve it for review")


async def retire_candidate(directus, cache, workflow_service, candidate: dict, enqueue) -> dict:
    """Every checked step precedes deletion; any failure keeps the account."""
    user = candidate["user"]
    user_id = user["id"]
    # Recheck identity immediately before changing this particular account.
    current = await _rows(directus, "users", filters={"id": {"_eq": user_id}}, fields="id,hashed_email")
    if len(current) != 1 or current[0].get("hashed_email") != candidate["recipient_hash"]:
        raise RuntimeError("Retirement candidate is stale")
    # Discovery snapshots are never permission to delete a newly acquired Team.
    reminders, workflows = await owner_schedules(directus, user_id)
    ignored = await _rows(directus, "ignored_emails",
        filters={"hashed_email": {"_eq": candidate["recipient_hash"]}}, fields="id")
    if not ignored:
        success, _ = await directus.create_item("ignored_emails", {
            "hashed_email": candidate["recipient_hash"], "reason": "retired_mailosaur_test_inbox"}, admin_required=True)
        if not success:
            raise RuntimeError("Could not suppress retired test mail")
    if not await directus.update_user(user_id, {"email_notifications_enabled": False, "status": "suspended"}):
        raise RuntimeError("Could not suspend retired account admission")
    if not await directus.revoke_user_api_keys(user_id):
        raise RuntimeError("Could not revoke retired account API admission")
    if not await cache.delete_user_cache(user_id):
        # Redis DEL=0 means this obsolete account was already cold, whereas an
        # unavailable connection cannot prove that admission state is absent.
        try:
            client = await cache.client
            if client is None or await client.exists(f"{cache.USER_KEY_PREFIX}{user_id}"):
                raise RuntimeError("Retired account cache is still present")
        except Exception as exc:
            raise RuntimeError("Could not verify retired account cache absence") from exc
    cancelled = 0
    for reminder in reminders:
        if reminder["status"] == "pending":
            changed = await directus.update_item("reminders", reminder["id"], {"status": "cancelled"}, admin_required=True)
            if not changed:
                raise RuntimeError("Could not cancel retired account reminder")
            cancelled += 1
        if not await cache.remove_reminder_from_cache(reminder["id"]):
            raise RuntimeError("Could not remove retired account reminder from hot cache")
    deleted_workflows = 0
    for workflow in workflows:
        if workflow["status"] != "deleted":
            await asyncio.to_thread(workflow_service.delete_workflow, workflow["id"], user_id)
            deleted_workflows += 1
    await assert_retirement_ready(directus, user_id)
    task_id = enqueue(user_id, "admin_action", "Retire obsolete Mailosaur development test account", True)
    return {"user_id": user_id, "recipient_hash": candidate["recipient_hash"],
            "reminders_cancelled": cancelled, "workflows_retired": deleted_workflows,
            "deletion_task_id": task_id, "status": "queued"}


def write_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as out:
        json.dump(receipt, out, indent=2)


async def run(args) -> dict[str, Any]:
    require_development()
    from backend.scripts.delete_user_account import initialize_services, trigger_deletion_task
    cache, encryption, directus = await initialize_services()
    workflow_repository = None
    try:
        if not await encryption.initialize():
            raise RuntimeError("Cannot establish the contact-email decryption context")
        candidates = await prepare_candidates(directus, await discover_emails(directus, encryption))
        receipt = {"domain": RETIRED_DOMAIN, "dry_run": not args.apply, "candidate_count": len(candidates),
                   "protected_team_accounts": sum(bool(item["blocked_reason"]) for item in candidates),
                   "pending_reminders": sum(row["status"] == "pending" for item in candidates for row in item["reminders"]),
                   "enabled_workflows": sum(row["enabled"] is True for item in candidates for row in item["workflows"]),
                   "accounts": []}
        if args.apply:
            workflow_repository = create_retirement_workflow_repository()
            workflow_service = create_retirement_workflow_service(workflow_repository)
            for candidate in candidates:
                if candidate["blocked_reason"]:
                    receipt["accounts"].append({"user_id": candidate["user"]["id"], "recipient_hash": candidate["recipient_hash"],
                                                "status": "protected", "reason": candidate["blocked_reason"]})
                    continue
                receipt["accounts"].append(await retire_candidate(directus, cache, workflow_service, candidate, trigger_deletion_task))
                write_receipt(args.receipt, receipt)
        else:
            receipt["accounts"] = [{"user_id": item["user"]["id"], "recipient_hash": item["recipient_hash"],
                                     "blocked_reason": item["blocked_reason"]} for item in candidates]
        write_receipt(args.receipt, receipt)
        return {key: value for key, value in receipt.items() if key != "accounts"} | {
            "queued": sum(item.get("status") == "queued" for item in receipt["accounts"]) if args.apply else 0}
    finally:
        if workflow_repository:
            workflow_repository._client.close()
        await directus.close()
        await encryption.close()
        await cache.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Suppress, retire schedules, and queue normal account deletion")
    parser.add_argument("--receipt", type=Path, required=True, help="Private receipt path outside the repository")
    args = parser.parse_args()
    # This administrative command reports bounded counters rather than library
    # logs that can include identifiers or raw decryption/provider errors.
    logging.disable(logging.CRITICAL)
    try:
        print(json.dumps(asyncio.run(run(args))))
    except Exception as exc:
        raise SystemExit(f"Retirement stopped ({type(exc).__name__}); preserve the private receipt for review") from None


if __name__ == "__main__":
    main()
