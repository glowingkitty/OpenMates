"""Isolated, disposable PG/S3 storage-metering fixture for selected CI specs.

The selector and detailed receipt stay in a 0600 runner-private bind. Stdout has
only pass flags and measured byte totals; it never contains user IDs or object keys.
No credit, email, provider, or production operation is performed here.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
import uuid
from typing import Any

SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
PREFIX_RE = re.compile(r"^ci-storage-billing/([0-9a-f-]{36})$")
PRIVATE_DIR = Path("/app/ci-storage-billing")
SELECTOR_SCHEMA = "storage-billing-selector-v1"
RECEIPT_SCHEMA = "storage-billing-receipt-v1"
FREE_BYTES = 1_073_741_824
WEEK = 7 * 24 * 60 * 60


def require_expiry_profile(environ: dict[str, str], selector: dict[str, str]) -> None:
    """Destructive probes require logical CI and a generated private namespace."""
    source = require_isolated_profile(environ)
    if (environ.get("STORAGE_LOGICAL_S3_BILLING_ENABLED") != "1"
            or selector.get("source_commit") != source
            or not PREFIX_RE.fullmatch(selector.get("fixture_prefix", ""))):
        raise ValueError("storage_billing_expiry_isolated_logical_profile_required")


async def _billing_operation(directus: Any, operation: str, user_id: str,
                             **fields: Any) -> dict[str, Any]:
    response = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/sub-chat-orchestration-transaction",
        headers={"X-Internal-Service-Token": os.environ["INTERNAL_API_SHARED_TOKEN"]},
        json={"operation": operation, "data": {
            "protocol_version": 1, "user_id": user_id,
            "hashed_user_id": hashlib.sha256(user_id.encode()).hexdigest(), **fields,
        }},
    )
    if response.status_code != 200 or not isinstance(response.json().get("data"), dict):
        raise RuntimeError("storage_billing_expiry_operation_failed:" + operation)
    return response.json()["data"]


def require_isolated_profile(environ: dict[str, str]) -> str:
    required = {
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "CHAT_MESSAGE_ARCHIVE_READS_ENABLED": "1",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
        "SERVER_ENVIRONMENT": "development",
    }
    if any(environ.get(key) != value for key, value in required.items()):
        raise ValueError("storage_billing_isolated_profile_required")
    source = environ.get("BUILD_COMMIT_SHA", "")
    if not SOURCE_RE.fullmatch(source) or not environ.get("INTERNAL_API_SHARED_TOKEN"):
        raise ValueError("storage_billing_source_or_authority_missing")
    return source


def load_selector(path: Path, source: str) -> dict[str, str]:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 4096:
        raise ValueError("storage_billing_selector_not_private_or_bounded")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or set(value) != {
        "schema", "source_commit", "user_id", "fixture_prefix",
    } or value.get("schema") != SELECTOR_SCHEMA or value.get("source_commit") != source:
        raise ValueError("storage_billing_selector_mismatch")
    try:
        user_id = str(uuid.UUID(value["user_id"], version=4))
        prefix_match = PREFIX_RE.fullmatch(value["fixture_prefix"])
        prefix_id = str(uuid.UUID(prefix_match[1], version=4)) if prefix_match else ""
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("storage_billing_selector_identity_invalid") from exc
    if user_id != value["user_id"] or not prefix_match or prefix_id != prefix_match[1]:
        raise ValueError("storage_billing_selector_identity_invalid")
    return value


def private_path(path: Path) -> None:
    if path.parent != PRIVATE_DIR or path.is_symlink():
        raise ValueError("storage_billing_private_bind_required")


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    private_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    os.fchmod(descriptor, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")


async def _write(directus: Any, collection: str, row: dict[str, Any], created: list[tuple[str, str]]) -> dict:
    success, result = await directus.create_item(collection, row, admin_required=True)
    if not success or not isinstance(result, dict):
        raise RuntimeError("storage_billing_fixture_write_failed")
    created.append((collection, str(result["id"])))
    return result


async def _patch(directus: Any, collection: str, row_id: str, fields: dict[str, Any]) -> None:
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("storage_billing_fixture_admin_unavailable")
    response = await directus._make_api_request(
        "PATCH", f"{directus.base_url.rstrip('/')}/items/{collection}/{row_id}",
        headers={"Authorization": f"Bearer {token}"}, json=fields,
    )
    if response.status_code != 200:
        raise RuntimeError("storage_billing_fixture_patch_failed")


async def _quote(directus: Any, *, user_id: str | None = None, team_hash: str | None = None,
                 legacy_only: bool = False, expected_status: int = 200) -> dict[str, Any] | None:
    response = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/storage-usage-metering",
        headers={"X-Internal-Service-Token": os.environ["INTERNAL_API_SHARED_TOKEN"]},
        json={"operation": "quote", "user_ids": [user_id] if user_id else [],
              "team_hashes": [team_hash] if team_hash else [], "legacy_only": legacy_only},
    )
    if response.status_code != expected_status:
        raise RuntimeError("storage_billing_metering_status_mismatch")
    if expected_status != 200:
        if response.json().get("error", {}).get("code") != "storage_usage_incomplete":
            raise RuntimeError("storage_billing_metering_error_mismatch")
        return None
    rows = response.json().get("data")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("complete") is not True:
        raise RuntimeError("storage_billing_metering_incomplete")
    return rows[0]


async def _assert_owner_metadata_hold(
    directus: Any, *, collection: str, row_id: str, field: str,
    original: Any, invalid: Any, user_id: str | None = None,
    team_hash: str | None = None,
) -> None:
    """Mutate one disposable reference; the real SQL must reject its quote."""
    if original == invalid or bool(user_id) == bool(team_hash):
        raise ValueError("storage_billing_invalid_owner_probe")
    await _patch(directus, collection, row_id, {field: invalid})
    try:
        await _quote(directus, user_id=user_id, team_hash=team_hash, expected_status=409)
    finally:
        await _patch(directus, collection, row_id, {field: original})


async def _archive_page(directus: Any, archive: Any, *, owner_hash: str | None,
                        team_hash: str | None, created: list[tuple[str, str]]) -> dict[str, Any]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    now = int(time.time())
    chat_id = str(uuid.uuid4())
    message_key = AESGCM.generate_key(bit_length=256)
    ciphertexts = []
    for _ in range(3):
        nonce = secrets.token_bytes(12)
        ciphertexts.append(base64.b64encode(
            nonce + AESGCM(message_key).encrypt(nonce, secrets.token_bytes(64), None)
        ).decode())
    message_ids = [str(uuid.uuid4()) for _ in ciphertexts]
    await _write(directus, "chats", {
        "id": chat_id, "hashed_user_id": owner_hash, "hashed_team_id": team_hash,
        "storage_state": "hot", "encrypted_title": ciphertexts[0],
        "encrypted_chat_key": ciphertexts[1], "messages_v": 3, "title_v": 1,
        "created_at": now - 30, "updated_at": now,
        "last_message_timestamp": now - 18,
    }, created)
    for index, (message_id, ciphertext) in enumerate(zip(message_ids, ciphertexts)):
        await _write(directus, "messages", {
            "id": str(uuid.uuid4()), "client_message_id": message_id,
            "chat_id": chat_id, "hashed_user_id": owner_hash,
            "encrypted_content": ciphertext, "role": "user",
            "created_at": now - 20 + index, "updated_at": now - 20 + index,
        }, created)
    checkpoint_id = str(uuid.uuid4())
    await _write(directus, "chat_compression_checkpoints", {
        "id": checkpoint_id, "chat_id": chat_id, "hashed_user_id": owner_hash,
        "encrypted_summary": base64.b64encode(secrets.token_bytes(64)).decode(),
        "compressed_up_to_timestamp": now - 18,
        "compressed_up_to_message_id": message_ids[-1],
        "covered_message_ids": message_ids, "compressed_message_count": 3,
        "summary_token_estimate": 20, "created_at": now, "updated_at": now,
    }, created)
    segment = await archive.copy_segment(
        chat_id=chat_id, checkpoint_id=checkpoint_id,
        end=(now - 18, message_ids[-1]), now_timestamp=now,
    )
    if segment.get("state") != "verified" or segment.get("page_count") != 1:
        raise RuntimeError("storage_billing_page_not_verified")
    created.append(("chat_message_archive_segments", str(segment["id"])))
    await archive.activate_isolated_capacity_segment(segment)
    pages = await directus.get_items("chat_message_archive_pages", params={
        "filter": {"segment_id": {"_eq": segment["id"]}}, "limit": 2,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if len(pages) != 1 or not pages[0].get("read_enabled") or pages[0].get("size_bytes", 0) <= 0:
        raise RuntimeError("storage_billing_page_not_active")
    page = pages[0]
    created.append(("chat_message_archive_pages", str(page["id"])))
    return {"chat_id": chat_id, "segment_id": segment["id"], "page": page}


async def _expiry_probe(directus: Any, s3: Any, selector: dict[str, str],
                        receipt: dict[str, Any]) -> dict[str, Any]:
    """Real SQL and S3 expiry, with explicitly simulated legacy logical sizes.

    A separate synthetic owner keeps the overview fixture's measured bytes intact.
    Nothing in this probe submits email or commits a credit charge.
    """
    require_expiry_profile(dict(os.environ), selector)
    from backend.core.api.app.services.s3.job_processor import RegionalStorageJobProcessor
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    user_id = str(uuid.uuid4())
    owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
    prefix = selector["fixture_prefix"] + "/expiry/" + user_id
    balance = "ci-synthetic-opaque-balance-" + secrets.token_hex(32)
    now = int(time.time())
    first_at = now - 4 * WEEK - 120
    regions = tuple(s3.region_clients)
    if regions != ("nbg1",):
        raise ValueError("storage_billing_expiry_disposable_region_required")
    token = await directus.ensure_auth_token(admin_required=True)
    response = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/users",
        headers={"Authorization": f"Bearer {token}"},
        json={"id": user_id, "email": f"ci-storage-expiry-{user_id}@example.com",
              "status": "active", "encrypted_credit_balance": balance},
    )
    if response.status_code not in (200, 201) or response.json().get("data", {}).get("id") != user_id:
        raise RuntimeError("storage_billing_expiry_disposable_owner_failed")
    receipt["created"].append(("directus_users", user_id))
    units = []
    for name, logical_bytes, created_at in (
        ("old", FREE_BYTES + 96, first_at - WEEK),
        ("survivor", 96, first_at - 1),
    ):
        raw, nonce, key = secrets.token_bytes(96), secrets.token_bytes(12), AESGCM.generate_key(256)
        ciphertext = AESGCM(key).encrypt(nonce, raw, None)
        object_key = prefix + "/" + name + ".enc"
        uploaded = await s3.upload_file("chatfiles", object_key, ciphertext, "application/octet-stream")
        receipt["objects"].append(["chatfiles", object_key])
        checksum = hashlib.sha256(ciphertext).hexdigest()
        if not await s3.verify_regional_object(bucket_key="chatfiles", object_key=object_key,
                                              region=uploaded["region"], checksum=checksum):
            raise RuntimeError("storage_billing_expiry_object_not_verified")
        row = await _write(directus, "upload_files", {
            "id": str(uuid.uuid4()), "embed_id": str(uuid.uuid4()), "user_id": user_id,
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "original_filename": "SIMULATED-storage-expiry-" + name + ".bin",
            "content_type": "application/octet-stream", "file_size_bytes": logical_bytes,
            "s3_base_url": uploaded["url"].rsplit("/", 1)[0],
            "files_metadata": {"original": {"s3_key": object_key, "size_bytes": len(ciphertext),
                                             "active_region": uploaded["region"]}},
            "aes_key": base64.b64encode(key).decode(), "aes_nonce": base64.b64encode(nonce).decode(),
            "malware_scan": "clean", "created_at": created_at,
        }, receipt["created"])
        units.append({"id": row["id"], "key": object_key, "checksum": checksum,
                      "physical_bytes": len(ciphertext), "logical_bytes": logical_bytes})
    before = await _quote(directus, user_id=user_id)
    if before["total_bytes"] != FREE_BYTES + 192:
        raise RuntimeError("storage_billing_expiry_simulated_quote_mismatch")
    periods = []

    async def invoice(at: int) -> dict[str, Any]:
        frozen = await _billing_operation(directus, "freeze_storage_period", user_id,
            period_start_at=at, measured_bytes=before["total_bytes"], credits_due=3,
            charge_id=f"storage:{owner_hash}:{at}", free_bytes=FREE_BYTES, credits_per_gib=3,
            policy_version=before["policy_version"], source_version=before["source_version"],
            category_bytes=before["categories"])
        period = frozen["period"]
        receipt["created"].append(("storage_billing_periods", period["id"]))
        periods.append(period)
        return period

    first_period = await invoice(first_at)
    receipt["created"].append(("storage_billing_owner_state", owner_hash))
    claim = await _billing_operation(directus, "claim_storage_warning", user_id, now_at=first_at)
    episode_id = claim["episode_id"]
    frozen = await _billing_operation(directus, "freeze_storage_warning_units", user_id,
                                       episode_id=episode_id, now_at=first_at)
    for unit in frozen.get("units", []):
        receipt["created"].append(("storage_billing_warning_units",
            hashlib.sha256(f"{episode_id}:{unit['unit_id']}".encode()).hexdigest()))
    if (frozen.get("frozen") is not True or frozen.get("held") is True
            or [unit.get("resource_id") for unit in frozen.get("units", [])] != [units[0]["id"]]):
        raise RuntimeError("storage_billing_expiry_fixed_oldest_selection_failed")
    # The later invoice must survive: it was absent from the first notice.
    later_period = await invoice(first_at + WEEK)
    notice = await _billing_operation(directus, "list_storage_warning_units", user_id,
                                      episode_id=episode_id, limit=50)
    replay = await _billing_operation(directus, "freeze_storage_warning_units", user_id,
                                      episode_id=episode_id, now_at=first_at + WEEK)
    if (notice.get("units") != frozen["units"] or notice.get("has_more") is not False
            or notice.get("unit_selection_hash") != frozen["unit_selection_hash"]
            or replay.get("unit_selection_hash") != frozen["unit_selection_hash"]
            or replay.get("period_ids") != [first_period["id"]]):
        raise RuntimeError("storage_billing_expiry_notice_membership_changed")
    for stage in range(1, 5):
        sent_at = first_at + (stage - 1) * WEEK
        claim = await _billing_operation(directus, "claim_storage_warning", user_id, now_at=sent_at)
        if claim.get("due") is not True or claim.get("warning_stage") != stage:
            raise RuntimeError("storage_billing_expiry_warning_stage_failed")
        delivery_id = str(uuid.uuid4())
        message_id = "ci-canned-delivery-" + delivery_id
        iso = datetime.fromtimestamp(sent_at, timezone.utc).isoformat()
        await _write(directus, "email_deliveries", {
            "id": delivery_id,
            "delivery_key": f"storage-billing-warning:{episode_id}:directus_user:{user_id}:week-{stage}",
            "email_type": f"storage-billing-failed-{stage}", "campaign_key": episode_id,
            "recipient_kind": "directus_user", "recipient_id": user_id, "stage": f"week-{stage}",
            "status": "sent", "provider": "ci-canned-no-email",
            "provider_message_id": message_id, "provider_delivery_state": "accepted", "sent_at": iso,
            "metadata": {"context": {
                "deadline_date": datetime.fromtimestamp(first_at + 4 * WEEK, timezone.utc).date().isoformat(),
                "unit_selection_hash": frozen["unit_selection_hash"],
            }, "SIMULATED": "canned provider identity; no email submitted"},
        }, receipt["created"])
        await _billing_operation(directus, "record_storage_delivery_receipt", user_id,
            episode_id=episode_id, warning_stage=stage, delivery_id=delivery_id,
            message_id=message_id, state="delivered", observed_at=sent_at, now_at=sent_at)
        await _billing_operation(directus, "acknowledge_storage_warning", user_id,
            episode_id=episode_id, warning_stage=stage, delivery_id=delivery_id, now_at=sent_at)
    early = await _billing_operation(directus, "apply_storage_expiry", user_id,
        episode_id=episode_id, expected_encrypted_balance=balance, regions=list(regions),
        now_at=first_at + 4 * WEEK - 1)
    if early.get("applied") is True:
        raise RuntimeError("storage_billing_expiry_early_delete")
    applied = await _billing_operation(directus, "apply_storage_expiry", user_id,
        episode_id=episode_id, expected_encrypted_balance=balance, regions=list(regions), now_at=now)
    if (applied.get("applied") is not True or applied.get("held") is True
            or applied.get("after_bytes") != 96
            or applied.get("waived_period_ids") != [first_period["id"]]):
        raise RuntimeError("storage_billing_expiry_result_mismatch")
    tombstones = await directus.get_items("storage_deletion_tombstones", params={
        "filter": {"object_key": {"_eq": units[0]["key"]}}, "limit": 2,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if len(tombstones) != 1:
        raise RuntimeError("storage_billing_expiry_tombstone_missing")
    tombstone = tombstones[0]
    receipt["created"].append(("storage_deletion_tombstones", tombstone["id"]))
    if (tombstone.get("logical_bucket") != "chatfiles"
            or tombstone.get("object_key") != units[0]["key"]
            or set(tombstone.get("generation_keys", {}).values()) != {units[0]["key"]}
            or any(set(states) != set(regions) for states in tombstone.get("purge_states", {}).values())
            or not tombstone.get("purge_states")):
        raise RuntimeError("storage_billing_expiry_tombstone_scope_invalid")
    purged = await RegionalStorageJobProcessor(directus_service=directus, s3_service=s3
        ).process_deletion_tombstone(tombstone["id"], int(tombstone["version"]))
    if (purged.get("state") != "completed"
            or await s3.verify_regional_object(bucket_key="chatfiles", object_key=units[0]["key"],
                region=regions[0], checksum=units[0]["checksum"])
            or not await s3.verify_regional_object(bucket_key="chatfiles", object_key=units[1]["key"],
                region=regions[0], checksum=units[1]["checksum"])):
        raise RuntimeError("storage_billing_expiry_real_purge_failed")
    after = await _quote(directus, user_id=user_id)
    remaining_uploads = await directus.get_items("upload_files", params={
        "filter": {"user_id": {"_eq": user_id}},
        "fields": "id,file_size_bytes,files_metadata", "limit": 3,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    waived = await directus.get_items("storage_billing_periods", params={
        "filter": {"id": {"_eq": first_period["id"]}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    debts = await _billing_operation(directus, "list_storage_debt", user_id)
    owner = await directus.get_items("directus_users", params={
        "filter": {"id": {"_eq": user_id}}, "fields": "id,encrypted_credit_balance", "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    charges = await directus.get_items("billing_charge_identities", params={
        "filter": {"hashed_user_id": {"_eq": owner_hash}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    usage = await directus.get_items("usage", params={
        "filter": {"user_id_hash": {"_eq": owner_hash}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if (after["total_bytes"] != 96 or len(owner) != 1
            or owner[0]["encrypted_credit_balance"] != balance
            or charges or usage or [p["id"] for p in debts["periods"]] != [later_period["id"]]):
        raise RuntimeError("storage_billing_expiry_survivor_or_ledger_changed")
    if (len(remaining_uploads) != 1 or remaining_uploads[0]["id"] != units[1]["id"]
            or int(remaining_uploads[0]["file_size_bytes"]) != 96
            or remaining_uploads[0]["files_metadata"]["original"]["s3_key"] != units[1]["key"]
            or len(waived) != 1 or waived[0]["state"] != "waived_on_expiry"
            or any(int(waived[0][field]) != int(first_period[field]) for field in (
                "measured_bytes", "credits_due", "period_start_at"))
            or any(waived[0][field] != first_period[field] for field in (
                "charge_id", "policy_version", "source_version"))
            or waived[0]["category_bytes"] != before["categories"]):
        raise RuntimeError("storage_billing_expiry_rows_or_frozen_invoice_changed")
    evidence = {"verified": True, "logical_sizes": "SIMULATED legacy file_size_bytes",
        "physical_object_bytes": sum(unit["physical_bytes"] for unit in units),
        "simulated_before_bytes": before["total_bytes"], "simulated_after_bytes": after["total_bytes"],
        "canned_delivery_receipts": 4, "real_regional_purge": True, "survivor_untouched": True,
        "ledger_unchanged": True, "warned_only_waived": True, "early_expiry_held": True,
        "episode_id": episode_id, "unit_selection_hash": frozen["unit_selection_hash"]}
    receipt["expiry"] = evidence
    return {key: evidence[key] for key in ("verified", "real_regional_purge", "ledger_unchanged",
                                         "warned_only_waived", "physical_object_bytes")}


async def _cleanup(directus: Any, s3: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    # Copy can fail after its SQL claim or S3 upload but before returning a
    # segment. Discover only rows attached to our freshly generated chat IDs.
    for chat_id in [row_id for collection, row_id in receipt.get("created", [])
                    if collection == "chats"]:
        try:
            segments = await directus.get_items("chat_message_archive_segments", params={
                "filter": {"chat_id": {"_eq": chat_id}}, "fields": "id", "limit": 10,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            pages = await directus.get_items("chat_message_archive_pages", params={
                "filter": {"chat_id": {"_eq": chat_id}},
                "fields": "id,object_key,large_objects", "limit": 10,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            if len(segments) >= 10 or len(pages) >= 10:
                raise RuntimeError("storage_billing_cleanup_scope_exceeded")
            for row in segments:
                pair = ("chat_message_archive_segments", str(row["id"]))
                if pair not in receipt["created"]:
                    receipt["created"].append(pair)
            for row in pages:
                pair = ("chat_message_archive_pages", str(row["id"]))
                if pair not in receipt["created"]:
                    receipt["created"].append(pair)
                for key in [row.get("object_key"), *[
                    ref.get("object_key") for ref in (row.get("large_objects") or [])
                    if isinstance(ref, dict)
                ]]:
                    obj = ["cold_archives", key]
                    if isinstance(key, str) and key and obj not in receipt["objects"]:
                        receipt["objects"].append(obj)
        except Exception:
            errors.append("archive:discovery_failed")
    if errors:
        return {"cleaned": False, "errors": errors}
    for collection, row_id in reversed(receipt.get("created", [])):
        try:
            existing = await directus.get_items(collection, params={
                "filter": {"id": {"_eq": row_id}}, "fields": "id", "limit": 1,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            if existing:
                if collection == "directus_users":
                    token = await directus.ensure_auth_token(admin_required=True)
                    response = await directus._make_api_request(
                        "DELETE", f"{directus.base_url.rstrip('/')}/users/{row_id}",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if response.status_code not in (200, 204):
                        errors.append(f"{collection}:delete_failed")
                elif not await directus.delete_item(collection, row_id, admin_required=True):
                    errors.append(f"{collection}:delete_failed")
        except Exception:
            errors.append(f"{collection}:delete_failed")
    if not errors:
        for bucket, key in reversed(receipt.get("objects", [])):
            try:
                await s3.delete_file(bucket, key)
            except Exception:
                errors.append("object:delete_failed")
    return {"cleaned": not errors, "errors": errors}


async def prepare(selector: dict[str, str], receipt_path: Path) -> dict[str, Any]:
    from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService
    from backend.core.api.app.tasks.base_task import BaseServiceTask

    task = BaseServiceTask()
    await task.initialize_services()
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA, "source_commit": selector["source_commit"],
        "selector_digest": hashlib.sha256(json.dumps(selector, sort_keys=True).encode()).hexdigest(),
        "user_id": selector["user_id"], "fixture_prefix": selector["fixture_prefix"],
        "created": [], "objects": [], "cleaned": False,
    }
    try:
        directus, s3 = task.directus_service, task.s3_service
        user_rows = await directus.get_items("directus_users", params={
            "filter": {"id": {"_eq": selector["user_id"]}}, "fields": "id,status", "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if len(user_rows) != 1 or user_rows[0]["id"] != selector["user_id"]:
            raise RuntimeError("storage_billing_disposable_account_missing")
        baseline = await _quote(directus, user_id=selector["user_id"], legacy_only=True)
        full_baseline = await _quote(directus, user_id=selector["user_id"], legacy_only=False)
        if baseline["total_bytes"] != 0 or full_baseline["total_bytes"] != 0:
            raise RuntimeError("storage_billing_account_not_empty")
        owner_hash = hashlib.sha256(selector["user_id"].encode()).hexdigest()
        archive = ChatMessageArchiveService(directus_service=directus, s3_service=s3)

        # An actual small encrypted upload, with legacy raw-size billing metadata.
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        raw = secrets.token_bytes(96)
        key, nonce = AESGCM.generate_key(bit_length=256), secrets.token_bytes(12)
        ciphertext = AESGCM(key).encrypt(nonce, raw, None)
        upload_key = f"{selector['fixture_prefix']}/upload.enc"
        uploaded = await s3.upload_file("chatfiles", upload_key, ciphertext,
                                        "application/octet-stream")
        receipt["objects"].append(["chatfiles", upload_key])
        if not await s3.verify_regional_object(
            bucket_key="chatfiles", object_key=upload_key,
            region=uploaded["region"], checksum=hashlib.sha256(ciphertext).hexdigest(),
        ):
            raise RuntimeError("storage_billing_upload_not_verified")
        await _write(directus, "upload_files", {
            "id": str(uuid.uuid4()), "embed_id": str(uuid.uuid4()),
            "user_id": selector["user_id"],
            "content_hash": hashlib.sha256(raw).hexdigest(),
            "original_filename": "synthetic-storage-billing.bin",
            "content_type": "application/octet-stream", "file_size_bytes": len(raw),
            "s3_base_url": uploaded["url"].rsplit("/", 1)[0],
            "files_metadata": {"original": {"s3_key": upload_key,
                                            "size_bytes": len(ciphertext),
                                            "active_region": uploaded["region"]}},
            "aes_key": base64.b64encode(key).decode(),
            "aes_nonce": base64.b64encode(nonce).decode(),
            "malware_scan": "clean", "created_at": int(time.time()),
        }, receipt["created"])
        personal = await _archive_page(directus, archive, owner_hash=owner_hash,
                                       team_hash=None, created=receipt["created"])
        personal_page = personal["page"]
        receipt["objects"].append(["cold_archives", personal_page["object_key"]])
        # A second canonical reference to the same *physical* page proves the
        # SQL (bucket,key) grouping without uploading another object.
        duplicate = {key: personal_page[key] for key in (
            "segment_id", "chat_id", "hashed_user_id", "hashed_team_id",
            "first_timestamp", "first_message_id", "last_timestamp", "last_message_id",
            "message_count", "message_ids", "message_positions", "source_fields",
            "object_key", "checksum", "source_checksum", "size_bytes", "raw_size_bytes",
            "verified_regions", "large_objects", "published", "reader_verified",
            "read_enabled", "pruned", "created_at",
        ) if key in personal_page}
        duplicate.update({"id": str(uuid.uuid4()), "page_number": 2})
        duplicate_row = await _write(directus, "chat_message_archive_pages",
                                     duplicate, receipt["created"])
        team_id = str(uuid.uuid4())
        team_hash = hashlib.sha256(team_id.encode()).hexdigest()
        team_now = int(time.time())
        await _write(directus, "teams", {
            "id": str(uuid.uuid4()), "team_id": team_id,
            "hashed_team_id": team_hash,
            "slug": "ci-billing-" + team_id[:8],
            "encrypted_name": base64.b64encode(secrets.token_bytes(96)).decode(),
            "encrypted_profile_image_metadata": base64.b64encode(secrets.token_bytes(96)).decode(),
            "created_by_user_hash": owner_hash, "status": "active",
            "created_at": team_now, "updated_at": team_now,
        }, receipt["created"])
        await _write(directus, "team_memberships", {
            "id": str(uuid.uuid4()), "hashed_team_id": team_hash,
            "hashed_user_id": owner_hash, "role": "owner", "status": "active",
            "joined_at": team_now, "created_at": team_now, "updated_at": team_now,
        }, receipt["created"])
        team = await _archive_page(directus, archive, owner_hash=None,
                                   team_hash=team_hash, created=receipt["created"])
        team_page = team["page"]
        receipt["objects"].append(["cold_archives", team_page["object_key"]])
        legacy = await _quote(directus, user_id=selector["user_id"], legacy_only=True)
        full = await _quote(directus, user_id=selector["user_id"], legacy_only=False)
        team_usage = await _quote(directus, team_hash=team_hash)
        page_bytes = int(personal_page["size_bytes"])
        if (legacy["total_bytes"] != len(raw) or
                full["total_bytes"] != len(raw) + page_bytes or
                full["categories"].get("chat_pages") != page_bytes or
                team_usage["total_bytes"] != int(team_page["size_bytes"]) or
                team_usage["policy_version"] != "unrated-team-usage-v1"):
            raise RuntimeError("storage_billing_measured_quote_mismatch")
        await _patch(directus, "chat_message_archive_pages", duplicate_row["id"],
                     {"size_bytes": page_bytes + 1})
        try:
            await _quote(directus, user_id=selector["user_id"], expected_status=409)
        finally:
            await _patch(directus, "chat_message_archive_pages", duplicate_row["id"],
                         {"size_bytes": page_bytes})
        restored = await _quote(directus, user_id=selector["user_id"])
        if restored["total_bytes"] != full["total_bytes"]:
            raise RuntimeError("storage_billing_conflict_restore_failed")
        # Every reference remains in the canonical SQL source set while its
        # owner metadata is invalid, so a 409 proves it was held rather than
        # silently omitted or attributed to the wrong payer.
        mismatched_personal = ("0" if owner_hash[0] != "0" else "1") + owner_hash[1:]
        mismatched_team = ("0" if team_hash[0] != "0" else "1") + team_hash[1:]
        for collection, row_id, field, original, invalid, quote_owner in (
            ("chat_message_archive_pages", personal_page["id"], "hashed_user_id",
             owner_hash, None, "personal"),
            ("chat_message_archive_pages", personal_page["id"], "hashed_user_id",
             owner_hash, mismatched_personal, "personal"),
            ("chat_message_archive_segments", personal["segment_id"], "hashed_user_id",
             owner_hash, None, "personal"),
            ("chat_message_archive_segments", personal["segment_id"], "hashed_user_id",
             owner_hash, mismatched_personal, "personal"),
            ("chat_message_archive_pages", team_page["id"], "hashed_team_id",
             team_hash, None, "team"),
            ("chat_message_archive_pages", team_page["id"], "hashed_team_id",
             team_hash, mismatched_team, "team"),
            ("chat_message_archive_segments", team["segment_id"], "hashed_team_id",
             team_hash, None, "team"),
            ("chat_message_archive_segments", team["segment_id"], "hashed_team_id",
             team_hash, mismatched_team, "team"),
        ):
            await _assert_owner_metadata_hold(
                directus, collection=collection, row_id=row_id, field=field,
                original=original, invalid=invalid,
                user_id=selector["user_id"] if quote_owner == "personal" else None,
                team_hash=team_hash if quote_owner == "team" else None,
            )
        if ((await _quote(directus, user_id=selector["user_id"]))["total_bytes"]
                != full["total_bytes"] or
                (await _quote(directus, team_hash=team_hash))["total_bytes"]
                != team_usage["total_bytes"]):
            raise RuntimeError("storage_billing_owner_probe_restore_failed")
        receipt.update({
            "personal_chat_id": personal["chat_id"], "team_chat_id": team["chat_id"],
            "team_hash": team_hash,
            "personal_page_key": personal_page["object_key"],
            "personal_page_size_bytes": page_bytes,
            "team_page_size_bytes": int(team_page["size_bytes"]),
            "legacy_upload_bytes": len(raw),
            "full_total_bytes": len(raw) + page_bytes,
            "legacy_quote": legacy, "full_quote": full, "team_quote": team_usage,
            "dedup_reference_count": 2, "conflict_failed_closed": True,
            "owner_metadata_failed_closed": True,
        })
        expiry = None
        if os.environ.get("STORAGE_LOGICAL_S3_BILLING_ENABLED") == "1":
            expiry = await _expiry_probe(directus, s3, selector, receipt)
        write_private_json(receipt_path, receipt)
        return {"prepared": True, "legacy_upload_bytes": len(raw),
                "page_bytes": page_bytes, "full_total_bytes": len(raw) + page_bytes,
                "team_unrated": True, "dedup": True, "conflict_failed_closed": True,
                "owner_metadata_failed_closed": True, "expiry": expiry}
    except Exception:
        await _cleanup(task.directus_service, task.s3_service, receipt)
        raise
    finally:
        await task.cleanup_services()


async def cleanup(selector: dict[str, str], receipt_path: Path) -> dict[str, Any]:
    from backend.core.api.app.tasks.base_task import BaseServiceTask

    info = receipt_path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 65536:
        raise ValueError("storage_billing_receipt_not_private_or_bounded")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(json.dumps(selector, sort_keys=True).encode()).hexdigest()
    if (receipt.get("schema") != RECEIPT_SCHEMA or
            receipt.get("source_commit") != selector["source_commit"] or
            receipt.get("selector_digest") != digest or
            receipt.get("user_id") != selector["user_id"] or
            receipt.get("fixture_prefix") != selector["fixture_prefix"]):
        raise ValueError("storage_billing_cleanup_receipt_mismatch")
    task = BaseServiceTask()
    await task.initialize_services()
    try:
        result = await _cleanup(task.directus_service, task.s3_service, receipt)
        if not result["cleaned"]:
            raise RuntimeError("storage_billing_fixture_cleanup_incomplete")
        receipt["cleaned"] = True
        write_private_json(receipt_path, receipt)
        return {"cleaned": True, "db_rows": len(receipt["created"]),
                "objects": len(receipt["objects"])}
    finally:
        await task.cleanup_services()


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated storage-billing integration fixture")
    parser.add_argument("operation", choices=("prepare", "cleanup"))
    parser.add_argument("--selector-file", required=True, type=Path)
    parser.add_argument("--receipt-file", required=True, type=Path)
    args = parser.parse_args()
    source = require_isolated_profile(dict(os.environ))
    private_path(args.selector_file)
    private_path(args.receipt_file)
    selector = load_selector(args.selector_file, source)
    result = asyncio.run(prepare(selector, args.receipt_file) if args.operation == "prepare"
                         else cleanup(selector, args.receipt_file))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
