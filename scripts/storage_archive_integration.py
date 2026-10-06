"""Disposable isolated DB/S3 archive transaction probe before capacity traffic.

Run inside the CI API container. This seeds only synthetic encrypted-shaped
fixture rows and is never counted as capacity workload evidence.
"""

from __future__ import annotations

import asyncio
import base64
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import secrets
import time
import uuid


def require_isolated_storage() -> None:
    required = {
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_STORAGE_CAPACITY_FIXTURES": "true",
        "CHAT_MESSAGE_ARCHIVE_READS_ENABLED": "1",
        "S3_ENDPOINT_URL": "http://storage.ci.test:9000",
    }
    if any(os.getenv(key) != value for key, value in required.items()):
        raise RuntimeError("Archive integration probe requires the exact isolated storage profile")
    if os.getenv("SERVER_ENVIRONMENT", "production").lower() in {"production", "prod"}:
        raise RuntimeError("Archive integration probe refuses production")
    if not os.getenv("INTERNAL_API_SHARED_TOKEN"):
        raise RuntimeError("Archive integration probe requires internal transaction authority")


@contextmanager
def _official_billing_hold():
    """Exercise the production admission condition only inside this CI probe."""
    keys = ("OPENMATES_DEPLOYMENT_MODE", "STORAGE_LOGICAL_S3_BILLING_ENABLED")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["OPENMATES_DEPLOYMENT_MODE"] = "official_cloud"
    os.environ.pop("STORAGE_LOGICAL_S3_BILLING_ENABLED", None)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def _probe_official_billing_copy_hold(archive, *, chat_id: str, checkpoint_id: str,
                                          end: tuple[int, str], source_row_ids: list[str], now: int) -> None:
    """Observe real PG originals and disposable S3 after rejected migration."""
    from backend.core.api.app.services.s3.config import get_bucket_name
    from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name
    with _official_billing_hold():
        await _expect_error(lambda: archive.copy_segment(
            chat_id=chat_id, checkpoint_id=checkpoint_id, end=end, now_timestamp=now,
        ), "ARCHIVE_BILLING_DISABLED")
        await _expect_error(lambda: archive.transaction("claim_segment", {
            "chat_id": chat_id, "checkpoint_id": checkpoint_id,
            "end_timestamp": end[0], "end_message_id": end[1], "now": now,
        }), "ARCHIVE_BILLING_DISABLED")
    segments = await archive.directus.get_items("chat_message_archive_segments", params={
        "filter": {"chat_id": {"_eq": chat_id}}, "fields": "id", "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    source = await archive.directus.get_items("messages", params={
        "filter": {"chat_id": {"_eq": chat_id}}, "fields": "id", "limit": len(source_row_ids) + 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if segments or {row["id"] for row in source} != set(source_row_ids):
        raise RuntimeError("Official billing hold altered synthetic PG originals or claims")
    prefix = "message-pages/" + hashlib.sha256(chat_id.encode()).hexdigest() + "/"
    bucket = get_bucket_name("chatfiles", archive.s3.environment)
    if not archive.s3.region_clients:
        raise RuntimeError("Official billing hold S3 proof has no configured region")
    for region, client in archive.s3.region_clients.items():
        result = await asyncio.to_thread(client.list_objects_v2,
            Bucket=resolve_regional_bucket_name(bucket, region), Prefix=prefix, MaxKeys=1)
        if not isinstance(result, dict) or result.get("Contents") or result.get("IsTruncated"):
            raise RuntimeError("Official billing hold produced a synthetic S3 copy")


async def _write(directus, collection: str, payload: dict) -> dict:
    success, row = await directus.create_item(collection, payload, admin_required=True)
    if not success or not isinstance(row, dict):
        raise RuntimeError(f"Synthetic {collection} fixture creation failed")
    return row


async def _patch(directus, collection: str, item_id: str, payload: dict) -> dict:
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("Synthetic archive fixture admin token unavailable")
    response = await directus._make_api_request(
        "PATCH", f"{directus.base_url.rstrip('/')}/items/{collection}/{item_id}",
        headers={"Authorization": f"Bearer {token}"}, json=payload,
    )
    if response.status_code != 200 or not isinstance(response.json().get("data"), dict):
        raise RuntimeError(f"Synthetic {collection} fixture update failed")
    return response.json()["data"]


async def _expect_error(action, code: str) -> None:
    try:
        await action()
    except Exception as error:
        if code not in str(error):
            raise RuntimeError(f"Expected archive fence {code}, got {type(error).__name__}") from error
    else:
        raise RuntimeError(f"Archive fence {code} did not reject synthetic operation")


async def _recovery_sql(directus, operation: str, data: dict) -> tuple[int, dict]:
    """Call the real Directus transaction, retaining only bounded status metadata."""
    response = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/chat-recovery-transaction",
        headers={"X-Internal-Service-Token": os.environ["INTERNAL_API_SHARED_TOKEN"]},
        json={"operation": operation, "data": {"protocol_version": 1, **data}},
    )
    result = response.json()
    if not isinstance(result, dict):
        raise RuntimeError("Recovery SQL transaction returned malformed response")
    detail = result.get("data" if response.status_code == 200 else "error")
    if not isinstance(detail, dict):
        raise RuntimeError("Recovery SQL transaction returned malformed metadata")
    return response.status_code, detail


def _assert_recovery_deletion_race(
    *, deletion_status: int, writer_status: int, producer_rows: list[dict],
    output_rows: list[dict], preflight_rows: list[dict],
) -> None:
    """A committed fence must leave no live producer, output, or preflight."""
    if deletion_status != 200 or writer_status not in {200, 404, 409}:
        raise RuntimeError("Recovery deletion/producer race did not serialize")
    if any(row.get("state") == "PENDING" for row in producer_rows):
        raise RuntimeError("Recovery deletion left a pending producer")
    if any(row.get("state") in {"PREPARING", "PENDING"} or not row.get("deleted_at")
           for row in output_rows):
        raise RuntimeError("Recovery deletion left a readable sealed output")
    if preflight_rows:
        raise RuntimeError("Recovery deletion left a runnable preflight")


def _assert_single_legacy_start(kind: str, attempts: list[tuple[int, dict]]) -> None:
    """Only one concurrent exact claim may authorize an inference start."""
    if len(attempts) != 2 or any(status != 200 for status, _ in attempts):
        raise RuntimeError("Concurrent legacy claims did not serialize")
    if sum(result.get("claimed") is True for _, result in attempts) != 1:
        raise RuntimeError("Legacy claim admitted zero or multiple executions")
    if kind == "ordinary" and sum(
        result.get("authorized") is True for _, result in attempts
    ) != 1:
        raise RuntimeError("Ordinary legacy claim authorization disagreed with durable claim")


def _assert_completed_claim_survives_deletion(
    deletion_status: int, deletion: dict, claim_rows: list[dict],
) -> None:
    """Deletion fences new work while retaining the completed replay marker."""
    if deletion_status != 200 or deletion.get("invalidated_legacy_batches") != 0:
        raise RuntimeError("Legacy deletion did not preserve completed claim boundary")
    if (len(claim_rows) != 1 or claim_rows[0].get("state") != "COMPLETED"
        or claim_rows[0].get("worker_completed") is not True
        or claim_rows[0].get("persistence_observed") is not True
        or claim_rows[0].get("invalidated_at")):
        raise RuntimeError("Completed legacy execution marker was lost during deletion")


def _legacy_claim_actor_payload(user_id: str) -> dict:
    """Use the same synthetic Directus login shape as normal account creation."""
    hashed_email = hashlib.sha256(f"ci-legacy:{user_id}".encode()).hexdigest()
    return {
        "id": user_id, "email": f"{hashed_email}@example.com",
        "password": secrets.token_urlsafe(32), "status": "active",
        "hashed_email": hashed_email,
    }


def _user_create_failure_metadata(response) -> str:
    """Report only bounded Directus schema diagnostics, never response messages."""
    code, field = "unknown", "unknown"
    try:
        body = response.json()
        errors = body.get("errors") if isinstance(body, dict) else None
        first = errors[0] if isinstance(errors, list) and errors else None
        extensions = first.get("extensions") if isinstance(first, dict) else None
        if isinstance(extensions, dict):
            candidate = extensions.get("code")
            if (isinstance(candidate, str) and 1 <= len(candidate) <= 48
                and all(character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
                        for character in candidate)):
                code = candidate
            candidate = extensions.get("field")
            if isinstance(candidate, list) and len(candidate) == 1:
                candidate = candidate[0]
            if candidate in {"id", "email", "password", "status", "role",
                             "hashed_email", "account_id"}:
                field = candidate
    except (TypeError, ValueError, AttributeError):
        pass
    return f"status={response.status_code} code={code} field={field}"


async def _legacy_claim_fixture_user(directus, user_id: str) -> None:
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("Synthetic legacy claim requires disposable admin authority")
    response = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/users",
        headers={"Authorization": f"Bearer {token}"},
        json=_legacy_claim_actor_payload(user_id),
    )
    if response.status_code not in {200, 201}:
        raise RuntimeError(
            "Synthetic legacy claim actor creation failed "
            + _user_create_failure_metadata(response))


def _canonical_assistant_fixture(broker_id: str, chat_id: str, owner_hash: str,
                                 now: int) -> dict:
    """Match create_message_in_directus: DB UUIDv5 is not the client ID."""
    database_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, broker_id))
    if database_id == broker_id:
        raise RuntimeError("Synthetic canonical message IDs must differ")
    return {
        "id": database_id, "client_message_id": broker_id,
        "chat_id": chat_id, "hashed_user_id": owner_hash, "role": "assistant",
        "encrypted_content": base64.b64encode(secrets.token_bytes(64)).decode(),
        "created_at": now, "updated_at": now,
    }


async def _probe_canonical_legacy_claim_guard(
    directus, *, kind: str, stage: str, user_id: str, chat_id: str,
    owner_hash: str, now: int,
) -> None:
    """A preexisting canonical assistant row must block the broker ID claim."""
    first_message_id, broker_id = str(uuid.uuid4()), str(uuid.uuid4())
    task_identity = hashlib.sha256(
        f"{user_id}:{chat_id}:{first_message_id}".encode()
    ).hexdigest()
    admission = {"task_identity": task_identity, "actor_user_id": user_id,
                 "hashed_user_id": owner_hash, "chat_id": chat_id,
                 "first_message_id": first_message_id, "hashed_team_id": None}
    ordinary = {**admission, "broker_task_id": broker_id,
                "dispatch_binding": secrets.token_hex(32)}
    batch = {**admission, "celery_task_id": broker_id,
             "members": [{"message_id": first_message_id, "chat_id": chat_id,
                          "hashed_user_id": owner_hash,
                          "payload_commitment": secrets.token_hex(32)}],
             "batch_commitment": secrets.token_hex(32)}
    fixture = _canonical_assistant_fixture(broker_id, chat_id, owner_hash, now)
    message_created = False
    try:
        operation = "admit_legacy_inference" if kind == "ordinary" else "prepare_legacy_batch"
        status, _ = await _recovery_sql(
            directus, operation, admission if kind == "ordinary" else batch)
        if status != 200:
            raise RuntimeError("Canonical legacy guard preparation failed")
        if kind == "ordinary" and stage == "claim":
            status, bound = await _recovery_sql(
                directus, "bind_ordinary_legacy_dispatch", ordinary)
            if status != 200 or bound.get("enqueue_allowed") is not True:
                raise RuntimeError("Canonical legacy guard dispatch binding failed")
        await _write(directus, "messages", fixture)
        message_created = True
        if kind == "ordinary" and stage == "bind":
            status, result = await _recovery_sql(
                directus, "bind_ordinary_legacy_dispatch", ordinary)
            blocked = result.get("enqueue_allowed") is False
        else:
            operation = ("claim_legacy_inference_start" if kind == "ordinary"
                         else "claim_legacy_batch")
            status, result = await _recovery_sql(
                directus, operation, ordinary if kind == "ordinary" else batch)
            blocked = result.get("claimed") is False
        if status != 200 or not blocked or result.get("status") != "CANONICAL_PRESENT":
            raise RuntimeError("Canonical assistant row did not fence legacy execution")
    finally:
        release_status, _ = await _recovery_sql(
            directus, "release_legacy_inference", {"task_identity": task_identity})
        if release_status != 200:
            raise RuntimeError("Synthetic canonical legacy lifecycle cleanup failed")
        rows = await directus.get_items("chat_recovery_legacy_batch_claims", params={
            "filter": {"task_identity": {"_eq": task_identity}}, "limit": 2,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        for row in rows:
            if not await directus.delete_item(
                "chat_recovery_legacy_batch_claims", row["id"], admin_required=True
            ):
                raise RuntimeError("Synthetic canonical legacy claim cleanup failed")
        if message_created and not await directus.delete_item(
            "messages", fixture["id"], admin_required=True
        ):
            raise RuntimeError("Synthetic canonical assistant cleanup failed")


async def _legacy_protocol_lifecycle(directus, task_identity: str) -> tuple[dict, list, list]:
    rows = await directus.get_items("chat_recovery_protocol_state", params={
        "filter": {"id": {"_eq": "chat-recovery"}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if len(rows) != 1:
        raise RuntimeError("Legacy protocol lifecycle readback missing")
    lifecycle = rows[0].get("legacy_task_lifecycle") or []
    active = rows[0].get("active_legacy_tasks") or []
    if isinstance(lifecycle, str):
        lifecycle = json.loads(lifecycle)
    if isinstance(active, str):
        active = json.loads(active)
    if not isinstance(lifecycle, list) or not isinstance(active, list):
        raise RuntimeError("Legacy protocol lifecycle was malformed")
    records = [record for record in lifecycle if isinstance(record, dict)
               and record.get("task_identity") == task_identity]
    if len(records) > 1:
        raise RuntimeError("Legacy protocol retained duplicate task identity")
    return (records[0] if records else {}), lifecycle, active


def _assert_legacy_lifecycle_stage(
    record: dict, active: list, task_identity: str, *, state: str | None,
    persistence_observed: bool | None = None,
) -> None:
    if state is None:
        if record or task_identity in active:
            raise RuntimeError("Legacy lifecycle retained retired task identity")
        return
    if (record.get("state") != state
        or (task_identity in active) != (state == "RUNNING")
        or (persistence_observed is not None
            and record.get("persistence_observed", False) is not persistence_observed)):
        raise RuntimeError("Legacy lifecycle completion proof was missing or reordered")


async def _complete_and_retire_legacy_claim(
    directus, *, task_identity: str, broker_id: str, chat_id: str,
    owner_hash: str, now: int,
) -> None:
    """Prove the held claim, exact ciphertext receipt, and completed tombstone."""
    release_status, premature = await _recovery_sql(
        directus, "release_legacy_inference", {"task_identity": task_identity})
    cleanup_status, _ = await _recovery_sql(directus, "cleanup_expired", {})
    if (release_status != 200 or cleanup_status != 200
        or premature.get("held") is not True or premature.get("released") is True):
        raise RuntimeError("Premature legacy release bypassed active claim hold")
    record, _, active = await _legacy_protocol_lifecycle(directus, task_identity)
    _assert_legacy_lifecycle_stage(
        record, active, task_identity, state="RUNNING", persistence_observed=False)

    fixture = _canonical_assistant_fixture(broker_id, chat_id, owner_hash, now)
    message_created = False
    try:
        persisted = await _write(directus, "messages", fixture)
        message_created = True
        if any(persisted.get(field) != fixture[field] for field in (
            "id", "client_message_id", "chat_id", "hashed_user_id", "role",
            "encrypted_content",
        )):
            raise RuntimeError("Synthetic canonical assistant readback differed")
        ack_status, acknowledged = await _recovery_sql(
            directus, "acknowledge_legacy_persistence", {
                "task_identity": broker_id, "chat_id": chat_id,
                "hashed_user_id": owner_hash, "assistant_message_id": broker_id,
                "ciphertext_digest": hashlib.sha256(
                    persisted["encrypted_content"].encode("utf-8")
                ).hexdigest(),
            })
        if (ack_status != 200 or acknowledged.get("acknowledged") is not True
            or acknowledged.get("output_receipt_verified") is not True
            or acknowledged.get("state") != "RUNNING"):
            raise RuntimeError("Canonical legacy persistence receipt was not verified")
        record, _, active = await _legacy_protocol_lifecycle(directus, task_identity)
        _assert_legacy_lifecycle_stage(
            record, active, task_identity, state="RUNNING", persistence_observed=True)

        completed_status, completed = await _recovery_sql(
            directus, "mark_legacy_inference_completed", {"task_identity": task_identity})
        if (completed_status != 200 or completed.get("completed") is not True
            or completed.get("state") != "PERSISTED"):
            raise RuntimeError("Legacy worker completion lacked persistence proof")
        record, lifecycle, active = await _legacy_protocol_lifecycle(directus, task_identity)
        _assert_legacy_lifecycle_stage(
            record, active, task_identity, state="PERSISTED", persistence_observed=True)
        claim_rows = await directus.get_items("chat_recovery_legacy_batch_claims", params={
            "filter": {"task_identity": {"_eq": task_identity}}, "limit": 2,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if (len(claim_rows) != 1 or claim_rows[0].get("state") != "COMPLETED"
            or claim_rows[0].get("worker_completed") is not True
            or claim_rows[0].get("persistence_observed") is not True):
            raise RuntimeError("Permanent legacy claim lacked both completion proofs")

        # Simulate only this disposable tombstone reaching its 24-hour TTL.
        # The permanent claim row remains untouched for the replay check below.
        expired = dict(record, expires_at=datetime.fromtimestamp(
            now - 1, timezone.utc).isoformat())
        lifecycle = [expired if item is record else item for item in lifecycle]
        await _patch(directus, "chat_recovery_protocol_state", "chat-recovery", {
            "legacy_task_lifecycle": lifecycle,
        })
        cleanup_status, _ = await _recovery_sql(directus, "cleanup_expired", {})
        if cleanup_status != 200:
            raise RuntimeError("Completed legacy lifecycle expiry cleanup failed")
        record, _, active = await _legacy_protocol_lifecycle(directus, task_identity)
        _assert_legacy_lifecycle_stage(record, active, task_identity, state=None)
    finally:
        if message_created and not await directus.delete_item(
            "messages", fixture["id"], admin_required=True
        ):
            raise RuntimeError("Synthetic completed assistant cleanup failed")


async def _probe_legacy_claim_sql_races(directus, now: int) -> dict:
    """Exercise permanent epoch-zero claims on actual isolated PostgreSQL."""
    status, cutover = await _recovery_sql(directus, "get_cutover_state", {})
    if (status != 200 or cutover.get("protocol_epoch") != 0
        or cutover.get("sends_paused") or cutover.get("legacy_in_flight") != 0):
        raise RuntimeError("Legacy claim probe requires a fresh isolated epoch-zero stack")
    try:
        repetitions = int(os.getenv("OPENMATES_CI_LEGACY_CLAIM_REPETITIONS", "4"))
    except ValueError as exc:
        raise RuntimeError("Legacy claim repetition count must be an integer") from exc
    if not 1 <= repetitions <= 8:
        raise RuntimeError("Legacy claim repetition count must be between 1 and 8")
    observed = {"ordinary": 0, "batch": 0, "canonical_present": 0,
                "lifecycle_retired": 0,
                "chat_deleted": 0, "account_deleted": 0}
    for kind in ("ordinary", "batch"):
        for _ in range(repetitions):
            user_id, chat_id = str(uuid.uuid4()), str(uuid.uuid4())
            owner_hash = hashlib.sha256(user_id.encode()).hexdigest()
            first_message_id = str(uuid.uuid4())
            task_identity = hashlib.sha256(
                f"{user_id}:{chat_id}:{first_message_id}".encode()
            ).hexdigest()
            broker_id = str(uuid.uuid4())
            admission = {"task_identity": task_identity, "actor_user_id": user_id,
                         "hashed_user_id": owner_hash, "chat_id": chat_id,
                         "first_message_id": first_message_id, "hashed_team_id": None}
            ordinary = {**admission, "broker_task_id": broker_id,
                        "dispatch_binding": secrets.token_hex(32)}
            batch = {**admission, "celery_task_id": broker_id,
                     "members": [
                         {"message_id": message_id, "chat_id": chat_id,
                          "hashed_user_id": owner_hash,
                          "payload_commitment": secrets.token_hex(32)}
                         for message_id in (first_message_id, str(uuid.uuid4()))
                     ], "batch_commitment": secrets.token_hex(32)}
            user_created = False
            try:
                await _legacy_claim_fixture_user(directus, user_id)
                user_created = True
                cipher = base64.b64encode(secrets.token_bytes(64)).decode()
                await _write(directus, "chats", {
                    "id": chat_id, "hashed_user_id": owner_hash, "storage_state": "hot",
                    "encrypted_title": cipher, "encrypted_chat_key": cipher,
                    "messages_v": 0, "title_v": 1,
                    "created_at": now, "updated_at": now,
                })
                if kind == "ordinary":
                    prepared_status, prepared = await _recovery_sql(
                        directus, "admit_legacy_inference", admission)
                    bound_status, bound = await _recovery_sql(
                        directus, "bind_ordinary_legacy_dispatch", ordinary)
                    if (prepared_status != 200 or prepared.get("admitted") is not True
                        or bound_status != 200 or bound.get("enqueue_allowed") is not True):
                        raise RuntimeError("Synthetic ordinary legacy claim preparation failed")
                    claim_operation, claim_payload = "claim_legacy_inference_start", ordinary
                else:
                    prepared_status, prepared = await _recovery_sql(
                        directus, "prepare_legacy_batch", batch)
                    if (prepared_status != 200 or prepared.get("execution_claimed") is not False):
                        raise RuntimeError("Synthetic batch legacy claim preparation failed")
                    claim_operation, claim_payload = "claim_legacy_batch", batch
                attempts = await asyncio.gather(
                    _recovery_sql(directus, claim_operation, claim_payload),
                    _recovery_sql(directus, claim_operation, claim_payload),
                )
                _assert_single_legacy_start(kind, attempts)
                rows = await directus.get_items("chat_recovery_legacy_batch_claims", params={
                    "filter": {"task_identity": {"_eq": task_identity}}, "limit": 2,
                }, admin_required=True, no_cache=True, raise_on_error=True)
                if len(rows) != 1 or rows[0].get("state") != "CLAIMED":
                    raise RuntimeError("Legacy execution claim lacked one permanent row")
                observed[kind] += 1
                for stage in (("bind", "claim") if kind == "ordinary" else ("claim",)):
                    await _probe_canonical_legacy_claim_guard(
                        directus, kind=kind, stage=stage, user_id=user_id,
                        chat_id=chat_id, owner_hash=owner_hash, now=now)
                    observed["canonical_present"] += 1
                await _complete_and_retire_legacy_claim(
                    directus, task_identity=task_identity, broker_id=broker_id,
                    chat_id=chat_id, owner_hash=owner_hash, now=now)
                repeat_status, repeat = await _recovery_sql(
                    directus, claim_operation, claim_payload)
                if repeat_status != 200 or repeat.get("claimed") is not False:
                    raise RuntimeError("Retired legacy lifecycle permitted duplicate execution")
                reprepare_operation = "admit_legacy_inference" if kind == "ordinary" else "prepare_legacy_batch"
                reprepare_status, reprepare = await _recovery_sql(
                    directus, reprepare_operation, admission if kind == "ordinary" else batch)
                still_claimed = (reprepare.get("admitted") is False if kind == "ordinary"
                                 else reprepare.get("execution_claimed") is True)
                if reprepare_status != 200 or not still_claimed:
                    raise RuntimeError("Retired legacy lifecycle recreated execution authority")
                observed["lifecycle_retired"] += 1
                delete_scope = "chat" if kind == "ordinary" else "account"
                deletion = {"hashed_user_id": owner_hash, "scope": delete_scope}
                if delete_scope == "chat":
                    deletion["chat_id"] = chat_id
                deleted_status, deleted = await _recovery_sql(
                    directus, "invalidate_deletion", deletion)
                late_status, _ = await _recovery_sql(directus, claim_operation, claim_payload)
                late_prepare_status, _ = await _recovery_sql(
                    directus, reprepare_operation,
                    admission if kind == "ordinary" else batch)
                if late_status not in {404, 409} or late_prepare_status not in {404, 409}:
                    raise RuntimeError("Deletion fence allowed late legacy execution")
                final_rows = await directus.get_items("chat_recovery_legacy_batch_claims", params={
                    "filter": {"task_identity": {"_eq": task_identity}}, "limit": 2,
                }, admin_required=True, no_cache=True, raise_on_error=True)
                _assert_completed_claim_survives_deletion(
                    deleted_status, deleted, final_rows)
                observed["chat_deleted" if delete_scope == "chat" else "account_deleted"] += 1
            finally:
                release_status, _ = await _recovery_sql(
                    directus, "release_legacy_inference", {"task_identity": task_identity})
                if release_status != 200:
                    raise RuntimeError("Synthetic legacy lifecycle cleanup failed")
                for collection, field, value in (
                    ("chat_recovery_legacy_batch_claims", "task_identity", task_identity),
                    ("chat_recovery_chat_deletion_fences", "id", chat_id),
                    ("chat_recovery_account_fences", "id", owner_hash),
                    ("chats", "id", chat_id),
                ):
                    rows = await directus.get_items(collection, params={
                        "filter": {field: {"_eq": value}}, "limit": 2,
                    }, admin_required=True, no_cache=True, raise_on_error=True)
                    for row in rows:
                        if not await directus.delete_item(collection, row["id"], admin_required=True):
                            raise RuntimeError("Synthetic legacy claim cleanup failed")
                if user_created:
                    token = await directus.ensure_auth_token(admin_required=True)
                    response = await directus._make_api_request(
                        "DELETE", f"{directus.base_url.rstrip('/')}/users/{user_id}",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if response.status_code not in {200, 204}:
                        raise RuntimeError("Synthetic legacy claim actor cleanup failed")
    return observed


async def probe_legacy_claims() -> dict:
    """Separate epoch-zero CI entry point; never downgrades protocol state."""
    require_isolated_storage()
    from backend.core.api.app.services.directus import DirectusService

    directus = DirectusService()
    try:
        observed = await _probe_legacy_claim_sql_races(directus, int(time.time()))
        return {"passed": True, "legacy_claim_sql_races": observed}
    finally:
        await directus.close()


async def _probe_recovery_sql_races(directus, now: int) -> dict:
    """Race real PG transactions using disposable Team and personal identities."""
    try:
        repetitions = int(os.getenv("OPENMATES_STORAGE_SQL_RACE_REPETITIONS", "8"))
    except ValueError as exc:
        raise RuntimeError("Recovery SQL race repetition count must be an integer") from exc
    if not 1 <= repetitions <= 16:
        raise RuntimeError("Recovery SQL race repetition count must be between 1 and 16")
    utc_now = datetime.now(timezone.utc)
    cipher = base64.b64encode(secrets.token_bytes(64)).decode()
    scenarios = (("team", "register"), ("team", "seal"),
                 ("team", "ack"), ("account", "register"))
    observed = {f"{scope}_{phase}": {"accepted": 0, "rejected": 0, "deleted": 0}
                for scope, phase in scenarios}
    for scope, phase in (scenario for scenario in scenarios
                         for _ in range(repetitions if scenario[0] == "team" else 1)):
        chat_id = str(uuid.uuid4())
        team_id = str(uuid.uuid4())
        team_hash = hashlib.sha256(team_id.encode()).hexdigest()
        actor_hash = hashlib.sha256(f"writer:{chat_id}".encode()).hexdigest()
        deleter_hash = hashlib.sha256(f"deleter:{chat_id}".encode()).hexdigest()
        owner_hash = actor_hash if scope == "account" else deleter_hash
        preflight_id, turn_id, task_id = (str(uuid.uuid4()) for _ in range(3))
        producer_id, embed_id, output_id = (str(uuid.uuid4()) for _ in range(3))
        message_id = str(uuid.uuid4())
        binding = hashlib.sha256(f"binding:{chat_id}".encode()).hexdigest()
        envelope = json.dumps({
            "v": 2,
            "epk": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
            "nonce": base64.urlsafe_b64encode(secrets.token_bytes(12)).decode().rstrip("="),
            "ciphertext": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
        }, separators=(",", ":"))
        producer = {
            "task_uuid": producer_id, "task_name": "ci.recovery.race",
            "kwargs_binding": binding, "hashed_user_id": actor_hash,
            "root_chat_id": chat_id, "target_chat_id": chat_id,
            "turn_id": turn_id, "preflight_id": preflight_id,
            "inference_task_id": task_id, "chat_key_version": 1,
            "primary_embed_id": embed_id, "primary_message_id": message_id,
            "primary_output_kind": "embed", "primary_output_version": 1,
            "max_children": 0,
        }
        output = {
            "record_id": output_id, "hashed_user_id": actor_hash,
            "root_chat_id": chat_id, "target_chat_id": chat_id,
            "turn_id": turn_id, "preflight_id": preflight_id,
            "inference_task_id": task_id, "subject_id": embed_id,
            "output_kind": "embed", "output_version": 1,
            "chat_key_version": 1, "sealed_payload": envelope,
            "producer_intent_id": producer_id, "producer_ordinal": 0,
            "producer_task_name": producer["task_name"],
            "producer_kwargs_binding": binding,
            "content_commitment": hashlib.sha256(envelope.encode()).hexdigest(),
        }
        team_rows: list[tuple[str, str]] = []
        canonical_rows: list[tuple[str, str]] = []
        try:
            if scope == "team":
                team_row_id = str(uuid.uuid4())
                await _write(directus, "teams", {
                    "id": team_row_id, "team_id": team_id,
                    "hashed_team_id": team_hash, "slug": f"ci-race-{chat_id}",
                    "encrypted_name": cipher,
                    "encrypted_profile_image_metadata": cipher,
                    "created_by_user_hash": deleter_hash, "status": "active",
                    "created_at": now, "updated_at": now,
                })
                team_rows.append(("teams", team_row_id))
                for member_hash, role in ((actor_hash, "member"), (deleter_hash, "owner")):
                    membership_id = str(uuid.uuid4())
                    await _write(directus, "team_memberships", {
                        "id": membership_id, "hashed_team_id": team_hash,
                        "hashed_user_id": member_hash, "role": role, "status": "active",
                        "created_at": now, "updated_at": now,
                    })
                    team_rows.append(("team_memberships", membership_id))
            await _write(directus, "chats", {
                "id": chat_id, "hashed_user_id": owner_hash,
                "hashed_team_id": team_hash if scope == "team" else None,
                "storage_state": "hot", "encrypted_title": cipher,
                "encrypted_chat_key": cipher, "messages_v": 0, "title_v": 1,
                "created_at": now, "updated_at": now,
            })
            await _write(directus, "chat_turn_preflights", {
                "id": preflight_id, "hashed_user_id": actor_hash,
                "chat_id": chat_id, "turn_id": turn_id,
                "user_message_id": message_id,
                "device_hash": hashlib.sha256(f"device:{chat_id}".encode()).hexdigest(),
                "chat_key_version": 1, "wrapped_chat_key": cipher,
                "recovery_public_key": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="),
                "encrypted_user_digest": hashlib.sha256(cipher.encode()).hexdigest(),
                "inference_commitment": binding, "commitment_version": 1,
                "expected_messages_v": 0, "committed_messages_v": 1,
                "state": "RUNNING", "inference_task_id": task_id,
                "prepared_at": utc_now.isoformat(),
                "expires_at": (utc_now + timedelta(days=1)).isoformat(),
            })
            if phase in {"seal", "ack"}:
                status, _ = await _recovery_sql(directus, "register_output_producer", producer)
                if status != 200:
                    raise RuntimeError("Synthetic Team producer setup failed")
            if phase == "ack":
                status, _ = await _recovery_sql(directus, "create_sealed_output", output)
                if status != 200:
                    raise RuntimeError("Synthetic Team sealed output setup failed")
                embed_row_id = str(uuid.uuid4())
                await _write(directus, "embeds", {
                    "id": embed_row_id, "embed_id": embed_id,
                    "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
                    "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
                    "hashed_user_id": actor_hash, "encrypted_type": cipher,
                    "encrypted_content": cipher, "status": "finished",
                    "encryption_mode": "client", "version_number": 1,
                })
                canonical_rows.append(("embeds", embed_row_id))
                for key_type in ("master", "chat"):
                    key_id = str(uuid.uuid4())
                    await _write(directus, "embed_keys", {
                        "id": key_id, "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
                        "key_type": key_type,
                        "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest()
                        if key_type == "chat" else None,
                        "hashed_user_id": actor_hash, "encrypted_embed_key": cipher,
                        "created_at": now,
                    })
                    canonical_rows.insert(0, ("embed_keys", key_id))
            deletion = {"hashed_user_id": deleter_hash if scope == "team" else actor_hash,
                        "scope": "chat" if scope == "team" else "account"}
            if scope == "team":
                deletion["chat_id"] = chat_id
            operation = {"register": "register_output_producer",
                         "seal": "create_sealed_output",
                         "ack": "acknowledge_output_embed"}[phase]
            payload = ({"hashed_user_id": actor_hash,
                        "device_hash": hashlib.sha256(f"device:{chat_id}".encode()).hexdigest(),
                        "record_id": output_id,
                        "canonical_digest": hashlib.sha256(cipher.encode()).hexdigest()}
                       if phase == "ack" else output if phase == "seal" else producer)
            (writer_status, _), (deletion_status, _) = await asyncio.gather(
                _recovery_sql(directus, operation, payload),
                _recovery_sql(directus, "invalidate_deletion", deletion),
            )
            producers = await directus.get_items("chat_recovery_output_producers", params={
                "filter": {"id": {"_eq": producer_id}}, "limit": 1,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            outputs = await directus.get_items("chat_recovery_outputs", params={
                "filter": {"id": {"_eq": output_id}}, "limit": 1,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            preflights = await directus.get_items("chat_turn_preflights", params={
                "filter": {"id": {"_eq": preflight_id}}, "limit": 1,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            _assert_recovery_deletion_race(
                deletion_status=deletion_status, writer_status=writer_status,
                producer_rows=producers, output_rows=outputs, preflight_rows=preflights,
            )
            observed[f"{scope}_{phase}"]["accepted" if writer_status == 200 else "rejected"] += 1
            observed[f"{scope}_{phase}"]["deleted"] += 1
            # A retry after the durable fence must never resurrect either row.
            retry_status, _ = await _recovery_sql(directus, operation, payload)
            if retry_status not in {404, 409}:
                raise RuntimeError("Recovery producer/output write survived deletion retry")
            if phase == "seal":
                ack_status, _ = await _recovery_sql(directus, "acknowledge_output_embed", {
                    "hashed_user_id": actor_hash,
                    "device_hash": hashlib.sha256(f"device:{chat_id}".encode()).hexdigest(),
                    "record_id": output_id,
                    "canonical_digest": hashlib.sha256(cipher.encode()).hexdigest(),
                })
                if ack_status not in {404, 409}:
                    raise RuntimeError("Recovery output ACK survived deletion fence")
        finally:
            for collection, item_id in (
                ("chat_recovery_outputs", output_id),
                ("chat_recovery_output_producers", producer_id),
                ("chat_turn_preflights", preflight_id),
                ("chat_recovery_chat_deletion_fences", chat_id),
                ("chat_recovery_account_fences", actor_hash),
                *canonical_rows,
                ("chats", chat_id),
                *reversed(team_rows),
            ):
                rows = await directus.get_items(collection, params={
                    "filter": {"id": {"_eq": item_id}}, "limit": 1,
                }, admin_required=True, no_cache=True, raise_on_error=True)
                if rows and not await directus.delete_item(collection, item_id, admin_required=True):
                    raise RuntimeError(f"Synthetic {collection} recovery race cleanup failed")
    return observed


async def _probe_legacy_embed_json_columns(directus, owner_hash: str) -> None:
    """Exercise the real locked embed write through PostgreSQL's JSON columns."""
    embed_id = str(uuid.uuid4())
    child_ids = [str(uuid.uuid4()) for _ in range(2)]
    shared_hashes = [hashlib.sha256(f"shared:{index}:{embed_id}".encode()).hexdigest()
                     for index in range(2)]
    ciphertext = base64.b64encode(secrets.token_bytes(96)).decode()
    endpoint = f"{directus.base_url.rstrip('/')}/embed-version-transaction/legacy-embed-write"
    created_id = None
    try:
        for revision, children, shares in (
            (1, child_ids[:1], shared_hashes[:1]),
            (2, child_ids, shared_hashes),
        ):
            payload = {
                "embed_id": embed_id, "hashed_user_id": owner_hash,
                "encrypted_type": ciphertext, "encrypted_content": ciphertext,
                "status": "finished", "encryption_mode": "client",
                "embed_ids": children, "shared_with_users": shares, "s3_file_keys": [],
            }
            response = await directus._make_api_request(
                "POST", endpoint,
                headers={"x-internal-service-token": os.environ["INTERNAL_API_SHARED_TOKEN"]},
                json={"embed_id": embed_id, "actor_user_hash": owner_hash, "payload": payload},
            )
            if response.status_code != 200 or response.json().get("data", {}).get("status") != (
                "created" if revision == 1 else "updated"
            ):
                raise RuntimeError("Synthetic legacy embed transaction insert/update failed")
            rows = await directus.get_items("embeds", params={
                "filter": {"embed_id": {"_eq": embed_id}}, "limit": 1,
            }, admin_required=True, no_cache=True, raise_on_error=True)
            if len(rows) != 1:
                raise RuntimeError("Synthetic legacy embed transaction readback missing")
            created_id = rows[0]["id"]
            if (rows[0].get("embed_ids") != children or
                    rows[0].get("shared_with_users") != shares or
                    rows[0].get("s3_file_keys") != []):
                raise RuntimeError("Legacy embed PostgreSQL JSON arrays changed shape")
    finally:
        if created_id and not await directus.delete_item("embeds", created_id, admin_required=True):
            raise RuntimeError("Synthetic legacy embed fixture cleanup failed")


async def _probe_team_archive(directus, archive, now: int) -> dict:
    """Prove Team archival and portability on real PG/S3."""
    chat_id = str(uuid.uuid4())
    team_hash = hashlib.sha256(f"team:{chat_id}".encode()).hexdigest()
    checkpoint_id = str(uuid.uuid4())
    message_ids = [str(uuid.uuid4()) for _ in range(3)]
    ciphertexts = [base64.b64encode(secrets.token_bytes(96)).decode() for _ in message_ids]
    await _write(directus, "chats", {
        "id": chat_id, "hashed_user_id": None, "hashed_team_id": team_hash,
        "storage_state": "hot", "encrypted_title": ciphertexts[0],
        "encrypted_chat_key": ciphertexts[1], "messages_v": 3, "title_v": 1,
        "created_at": now - 30, "updated_at": now,
        "last_message_timestamp": now - 18,
    })
    for index, message_id in enumerate(message_ids):
        await _write(directus, "messages", {
            "id": str(uuid.uuid4()), "client_message_id": message_id, "chat_id": chat_id,
            "hashed_user_id": None, "encrypted_content": ciphertexts[index],
            "role": "user", "created_at": now - 20 + index,
            "updated_at": now - 20 + index,
        })
    await _write(directus, "chat_compression_checkpoints", {
        "id": checkpoint_id, "chat_id": chat_id, "hashed_user_id": None,
        "encrypted_summary": base64.b64encode(secrets.token_bytes(64)).decode(),
        "compressed_up_to_timestamp": now - 18,
        "compressed_up_to_message_id": message_ids[-1],
        "covered_message_ids": message_ids, "compressed_message_count": 3,
        "summary_token_estimate": 20, "created_at": now, "updated_at": now,
    })
    segment = await archive.copy_segment(
        chat_id=chat_id, checkpoint_id=checkpoint_id,
        end=(now - 18, message_ids[-1]), now_timestamp=now,
    )
    if (segment.get("state") != "verified" or segment.get("hashed_user_id") is not None or
            segment.get("hashed_team_id") != team_hash):
        raise RuntimeError("Synthetic Team archive claim lost its Team-only authority")
    if not await archive.verify_reader_pages(segment):
        raise RuntimeError("Synthetic Team archive reader verification failed")
    active = await archive.transaction("activate_segment", {
        "segment_id": segment["id"], "expected_version": segment["version"], "now": now + 1,
    })
    before = await archive.read_before(chat_id=chat_id, before=None, limit=3)
    if ([row["client_message_id"] for row in before["messages"]] != message_ids or
            [row["encrypted_content"] for row in before["messages"]] != ciphertexts):
        raise RuntimeError("Synthetic Team archive S3 read differed from its ciphertext ledger")
    pages = await directus.get_items("chat_message_archive_pages", params={
        "filter": {"segment_id": {"_eq": segment["id"]}}, "limit": 2,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if len(pages) != 1 or pages[0].get("hashed_user_id") is not None or pages[0].get("hashed_team_id") != team_hash:
        raise RuntimeError("Synthetic Team archive page changed ownership scope")
    await archive.verify_pruning_replicas(pages[0])
    pruned = await archive.transaction("prune_page", {
        "segment_id": active["id"], "expected_version": active["version"],
        "page_id": pages[0]["id"], "now": now + 2,
    })
    if pruned.get("message_count") != 3:
        raise RuntimeError("Synthetic Team archive prune removed the wrong source count")
    remaining = await directus.get_items("messages", params={
        "filter": {"chat_id": {"_eq": chat_id}}, "limit": 4,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    after = await archive.read_before(chat_id=chat_id, before=None, limit=3)
    if remaining or [row["encrypted_content"] for row in after["messages"]] != ciphertexts:
        raise RuntimeError("Synthetic Team archive was not readable after source prune")
    return await _probe_team_portability(directus, archive.s3, now)


# Fixed codes only; never serialize exception messages, fixture IDs or routing.
_TEAM_PORTABILITY_STAGE = ContextVar("team_portability_stage", default="probe_bootstrap")
_TEAM_PORTABILITY_ERROR_CLASSES = frozenset({
    "RuntimeError", "AssertionError", "KeyError", "ValueError", "TypeError", "AttributeError",
    "ImportError", "ModuleNotFoundError", "TimeoutError", "ConnectionError", "OSError",
    "ClientError", "TeamPermissionError", "TeamDataPortabilityError", "ExceptionGroup",
})


async def _team_portability_cli_result() -> dict:
    """Return a public-safe failure instead of an unbounded Python traceback."""
    try:
        return await probe_team_portability()
    except Exception as error:
        error_class = type(error).__name__
        return {"passed": False, "stage": _TEAM_PORTABILITY_STAGE.get(),
                "reason": "probe_exception",
                "error_class": error_class if error_class in _TEAM_PORTABILITY_ERROR_CLASSES else "OtherError"}


async def _probe_team_portability(directus, s3, now: int) -> dict:
    """One tiny Team export/import flow against disposable Directus/PG/S3."""
    _TEAM_PORTABILITY_STAGE.set("isolation_proof")
    require_isolated_storage()
    from backend.shared.python_utils.storage_archive_rollout_config import trusted_isolated_storage_profile
    if not trusted_isolated_storage_profile(dict(os.environ)):
        raise RuntimeError("Team portability requires verified source/network/credential isolation proof")
    _TEAM_PORTABILITY_STAGE.set("fixture_imports")
    import gzip
    import sys
    from builtins import ExceptionGroup
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from botocore.exceptions import ClientError
    from backend.core.api.app.services.bounded_archive_io import put_verified_bytes
    from backend.core.api.app.services.directus.team_methods import TeamPermissionError, hash_id
    from backend.core.api.app.services.team_data_portability_service import (
        TeamDataPortabilityError, TeamDataPortabilityService,
    )
    from backend.core.api.app.services.s3.config import get_bucket_name
    from backend.shared.python_utils.object_storage_regions import resolve_regional_bucket_name

    source, destination, other = [str(uuid.uuid4()) for _ in range(3)]
    owner, viewer = str(uuid.uuid4()), str(uuid.uuid4())
    scopes = [hash_id(value) for value in (source, destination, other)]
    owner_hash = hash_id(owner)
    archive_ids = [str(uuid.uuid4()) for _ in range(3)]
    object_key = f"ci-team-portability/{archive_ids[0]}/part-1.json.gz"
    item_key = hash_id(f"memory:{source}")
    source_cipher = base64.b64encode(secrets.token_bytes(64)).decode()
    raw = gzip.compress(json.dumps({"encrypted_content": source_cipher}).encode(), mtime=0)
    cleanup_failures = []

    async def rows(collection, filters):
        result = await directus.get_items(collection, params={"filter": filters, "limit": 32, "sort": "id"},
                                         admin_required=True, no_cache=True, raise_on_error=True)
        if not isinstance(result, list) or len(result) >= 32:
            raise RuntimeError("Team portability fixture query was not bounded")
        return result

    async def destination_state():
        return {collection: await rows(collection, {"hashed_team_id": {"_eq": scopes[1]}})
                for collection in ("user_app_settings_and_memories", "team_memberships", "team_credit_accounts",
                                   "team_connected_account_grants")}

    _TEAM_PORTABILITY_STAGE.set("fixture_metadata")
    service = TeamDataPortabilityService(directus, s3_service=s3)
    try:
        for team_id, team_hash in zip((source, destination), scopes):
            await _write(directus, "teams", {
                "team_id": team_id, "hashed_team_id": team_hash, "slug": team_id,
                "encrypted_name": source_cipher, "encrypted_profile_image_metadata": source_cipher,
                "created_by_user_hash": owner_hash, "status": "active", "created_at": now, "updated_at": now,
            })
            await _write(directus, "team_memberships", {
                "hashed_team_id": team_hash, "hashed_user_id": owner_hash, "role": "owner",
                "status": "active", "joined_at": now, "created_at": now, "updated_at": now,
            })
        await _write(directus, "team_memberships", {
            "hashed_team_id": scopes[0], "hashed_user_id": hash_id(viewer), "role": "viewer",
            "status": "active", "joined_at": now, "created_at": now, "updated_at": now,
        })
        for team_hash in (scopes[0], scopes[2], None):
            await _write(directus, "user_app_settings_and_memories", {
                "hashed_team_id": team_hash, "hashed_user_id": owner_hash if team_hash is None else None,
                "app_id": "code", "item_type": "ci_portability", "item_key": item_key,
                "encrypted_item_json": source_cipher, "created_at": now, "updated_at": now,
            })
        for team_hash in (scopes[0], scopes[2]):
            await _write(directus, "team_connected_account_grants", {
                "hashed_team_id": team_hash, "hashed_user_id": owner_hash,
                "connected_account_id_hash": hash_id("disposable-account"), "role_snapshot": "owner",
                "encrypted_account_secret_key": source_cipher, "allowed_actions_hash": hash_id("read"),
                "status": "active", "created_at": now,
            })
        _TEAM_PORTABILITY_STAGE.set("fixture_object")
        verified = await put_verified_bytes(s3, object_key, raw, content_type="application/gzip")
        _TEAM_PORTABILITY_STAGE.set("fixture_archive")
        for archive_id, team_hash in zip(archive_ids, (scopes[0], scopes[2], None)):
            await _write(directus, "cold_archive_manifests", {
                "archive_id": archive_id, "resource_type": "chat", "resource_id": str(uuid.uuid4()),
                "hashed_resource_id": hash_id(archive_id), "hashed_user_id": owner_hash,
                "hashed_team_id": team_hash, "encrypted_listing_metadata": {"encrypted_title": source_cipher},
                "active_generation": 1, "graph_checksum": verified["checksum"], "part_count": 1,
                "file_references": [], "state": "cold", "version": 1, "archived_at": now, "updated_at": now,
            })
        await _write(directus, "cold_archive_parts", {
            "archive_id": archive_ids[0], "part_id": "part-1", "part_number": 1, "generation": 1,
            "logical_bucket": "cold_archives", "object_key": object_key, "checksum": verified["checksum"],
            "size_bytes": len(raw), "regional_states": {region: "verified" for region in verified["verified_regions"]},
            "created_at": now,
        })
        _TEAM_PORTABILITY_STAGE.set("export")
        artifact = (await service.export_team_data(source, owner))["artifact"]
        if ([item["archive_id"] for item in artifact["collections"]["cold_archives"]] != [archive_ids[0]]
                or base64.b64decode(artifact["collections"]["cold_archives"][0]["parts"][0]["ciphertext"]) != raw
                or any(row.get("hashed_team_id") != scopes[0]
                       for row in artifact["collections"]["user_app_settings_and_memories"])):
            raise RuntimeError("Team export changed ciphertext or mixed Personal/other-Team scope")
        grants = artifact["collections"]["team_connected_account_grants"]
        if (len(grants) != 1 or grants[0].get("hashed_team_id") != scopes[0]
                or grants[0].get("encrypted_account_secret_key") != "<redacted>"):
            raise RuntimeError("Team export omitted/mixed grant metadata or exposed its account key")
        serialized = json.dumps(artifact)
        if object_key in serialized or any(value in serialized for value in archive_ids[1:]):
            raise RuntimeError("Team export exposed storage routing or unrelated archives")
        if len(artifact["collections"]["user_app_settings_and_memories"]) != 1:
            raise RuntimeError("Team export omitted its synthetic memory")
        _TEAM_PORTABILITY_STAGE.set("viewer_authorization")
        try:
            await service.export_team_data(source, viewer)
        except TeamPermissionError:
            pass
        else:
            raise RuntimeError("Viewer exported Team ciphertext")

        # Construct destination ciphertext locally; only ciphertext reaches Directus.
        destination_key = AESGCM.generate_key(bit_length=256)
        nonce = secrets.token_bytes(12)
        plaintext = b'{"note":"disposable Team import"}'
        destination_cipher = base64.b64encode(nonce + AESGCM(destination_key).encrypt(nonce, plaintext, None)).decode()
        memory = {"owner_context": "team", "hashed_team_id": scopes[0], "hashed_user_id": None,
                  "app_id": "code", "item_type": "ci_portability", "item_key": item_key,
                  "encrypted_item_json": destination_cipher, "created_at": now}
        selected = {"schema": "openmates.team_export.v1", "rewrapped_with_destination_team_key": True,
                    "collections": {"user_app_settings_and_memories": [memory]}}
        _TEAM_PORTABILITY_STAGE.set("import_preflight")
        before = await destination_state()
        for collection, detail in (("cold_archives", "restore is unsupported"),
                                   ("team_memberships", "Server-controlled Team records"),
                                   ("team_credit_accounts", "Server-controlled Team records"),
                                   ("team_connected_account_grants", "Server-controlled Team records")):
            rejected = {**selected, "collections": {**selected["collections"], collection: [{"id": str(uuid.uuid4())}]}}
            try:
                await service.import_team_data(destination, owner, rejected)
            except TeamDataPortabilityError as error:
                if detail not in str(error):
                    raise RuntimeError("Team import returned the wrong preflight rejection") from error
            else:
                raise RuntimeError("Team import accepted unsupported or authoritative rows")
            if await destination_state() != before:
                raise RuntimeError("Rejected Team import changed persisted destination state")
        _TEAM_PORTABILITY_STAGE.set("metadata_import")
        imported = await service.import_team_data(destination, owner, selected)
        persisted = await rows("user_app_settings_and_memories", {"hashed_team_id": {"_eq": scopes[1]}})
        if (imported.get("imported_rows") != 1 or len(persisted) != 1
                or persisted[0].get("hashed_user_id") or persisted[0].get("encrypted_item_json") != destination_cipher):
            raise RuntimeError("Selected Team import reported success without correct persisted ciphertext")
        decoded = base64.b64decode(persisted[0]["encrypted_item_json"])
        if AESGCM(destination_key).decrypt(decoded[:12], decoded[12:], None) != plaintext:
            raise RuntimeError("Imported Team memory lost destination-key readability")
        _TEAM_PORTABILITY_STAGE.set("revoked_authorization")
        memberships = await rows("team_memberships", {"hashed_team_id": {"_eq": scopes[0]}, "hashed_user_id": {"_eq": owner_hash}})
        await _patch(directus, "team_memberships", memberships[0]["id"], {"status": "removed", "removed_at": now})
        try:
            await service.export_team_data(source, owner)
        except TeamPermissionError:
            pass
        else:
            raise RuntimeError("Revoked membership exported Team ciphertext")
    finally:
        original_error = sys.exception()
        original_stage = _TEAM_PORTABILITY_STAGE.get()
        _TEAM_PORTABILITY_STAGE.set("fixture_cleanup")
        # Remove only fixture scopes/keys created here; continue cleanup after a failure.
        queries = [(collection, {"hashed_team_id": {"_in": scopes}}) for collection in (
            "team_data_exports", "user_app_settings_and_memories", "team_memberships", "team_credit_accounts",
            "team_connected_account_grants", "teams")]
        queries += [("user_app_settings_and_memories", {"item_key": {"_eq": item_key}}),
                    ("cold_archive_parts", {"archive_id": {"_in": archive_ids}}),
                    ("cold_archive_manifests", {"archive_id": {"_in": archive_ids}}),
                    ("storage_replication_jobs", {"object_key": {"_eq": object_key}})]
        for collection, filters in queries:
            try:
                for row in await rows(collection, filters):
                    if not await directus.delete_item(collection, row["id"], admin_required=True):
                        raise RuntimeError("Fixture deletion failed")
                if await rows(collection, filters):
                    raise RuntimeError("Fixture rows survived cleanup")
            except Exception:
                cleanup_failures.append(collection)
        for region, client in s3.region_clients.items():
            try:
                bucket = resolve_regional_bucket_name(get_bucket_name("cold_archives", s3.environment), region)
                await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=object_key)
                try:
                    await asyncio.to_thread(client.head_object, Bucket=bucket, Key=object_key)
                except ClientError as error:
                    if str(error.response.get("Error", {}).get("Code")) not in {"404", "NoSuchKey", "NotFound"}:
                        raise
                else:
                    raise RuntimeError("Fixture object survived cleanup")
            except Exception:
                cleanup_failures.append("regional-object")
        if cleanup_failures:
            cleanup_error = RuntimeError("Team portability fixture cleanup failed: " + ",".join(cleanup_failures))
            if original_error is not None:
                raise ExceptionGroup("Team portability and cleanup failed", [original_error, cleanup_error])
            raise cleanup_error
        _TEAM_PORTABILITY_STAGE.set(original_stage)
    return {"passed": True, "team_export_original_ciphertext": True, "team_scope_and_revocation": True,
            "team_import_preflight_no_writes": True, "team_selected_import_persisted": True,
            "team_portability_cleanup_verified": True}


async def probe_team_portability() -> dict:
    """Select only this tiny existing Team probe, without capacity traffic."""
    _TEAM_PORTABILITY_STAGE.set("profile_guard")
    require_isolated_storage()
    _TEAM_PORTABILITY_STAGE.set("service_initialization")
    secrets_manager, directus, s3 = await _load_archive_services()
    try:
        _TEAM_PORTABILITY_STAGE.set("probe_bootstrap")
        result = await _probe_team_portability(directus, s3, int(time.time()))
        return {**result, "source_commit": os.environ["BUILD_COMMIT_SHA"]}
    finally:
        original_stage = _TEAM_PORTABILITY_STAGE.get()
        _TEAM_PORTABILITY_STAGE.set("directus_close")
        try:
            await directus.close()
            _TEAM_PORTABILITY_STAGE.set(original_stage)
        finally:
            close_stage = _TEAM_PORTABILITY_STAGE.get()
            _TEAM_PORTABILITY_STAGE.set("secrets_close")
            await secrets_manager.aclose()
            _TEAM_PORTABILITY_STAGE.set(close_stage)


async def _probe_project_attach_deletion_fence(directus, archive, *,
                                               deleting_chat_id: str, owner_hash: str,
                                               now: int) -> None:
    """Exercise PostgreSQL's serialized Project link and chat deletion guards."""
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("Synthetic Project attachment probe lacks disposable admin token")
    project_hash = hashlib.sha256(f"project:{deleting_chat_id}".encode()).hexdigest()
    team_hash = hashlib.sha256(f"team:{deleting_chat_id}".encode()).hexdigest()

    async def attach(chat_id: str, *, item_id: str) -> object:
        return await directus._make_api_request(
            "POST", f"{directus.base_url.rstrip('/')}/items/project_items",
            headers={"Authorization": f"Bearer {token}"}, json={
                "id": item_id, "project_item_id": str(uuid.uuid4()),
                "hashed_project_id": project_hash, "hashed_user_id": None,
                "hashed_team_id": team_hash, "attached_by_user_hash": owner_hash,
                "item_type": "chat", "deleted_target_state": None,
                "target_id_hash": hashlib.sha256(chat_id.encode()).hexdigest(),
                "target_id_encrypted": base64.b64encode(secrets.token_bytes(96)).decode(),
                "created_at": now, "updated_at": now,
            },
        )

    blocked_item_id = str(uuid.uuid4())
    blocked = await attach(deleting_chat_id, item_id=blocked_item_id)
    if blocked.status_code < 400:
        raise RuntimeError("PostgreSQL allowed Project attachment after chat deletion fence")
    blocked_rows = await directus.get_items("project_items", params={
        "filter": {"id": {"_eq": blocked_item_id}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if blocked_rows:
        raise RuntimeError("Rejected Project attachment left a linked row")

    chat_id = str(uuid.uuid4())
    ciphertext = base64.b64encode(secrets.token_bytes(96)).decode()
    await _write(directus, "chats", {
        "id": chat_id, "hashed_user_id": owner_hash, "storage_state": "hot",
        "encrypted_title": ciphertext, "encrypted_chat_key": ciphertext,
        "messages_v": 0, "title_v": 1, "created_at": now, "updated_at": now,
    })
    item_id = str(uuid.uuid4())
    attached = await attach(chat_id, item_id=item_id)
    if not 200 <= attached.status_code < 300:
        raise RuntimeError("Synthetic live-chat Project attachment failed")
    try:
        deletion = await directus._make_api_request(
            "PATCH", f"{directus.base_url.rstrip('/')}/items/chats/{chat_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"storage_state": "deleting"},
        )
        if deletion.status_code < 400:
            raise RuntimeError("PostgreSQL allowed deletion with surviving Team Project link")
        chats = await directus.get_items("chats", params={
            "filter": {"id": {"_eq": chat_id}}, "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if len(chats) != 1 or chats[0].get("storage_state") == "deleting":
            raise RuntimeError("Rejected chat deletion changed canonical storage state")
        hashes = await archive.transaction("resolve_chat_hashes", {
            "hashes": [hashlib.sha256(chat_id.encode()).hexdigest()],
        })
        if len(hashes.get("chats", [])) != 1 or hashes["chats"][0].get("hashed_user_id") != owner_hash:
            raise RuntimeError("Authoritative chat-hash resolution lost Project target owner")
    finally:
        if not await directus.delete_item("project_items", item_id, admin_required=True):
            raise RuntimeError("Synthetic Project attachment cleanup failed")
        await _patch(directus, "chats", chat_id, {"storage_state": "deleting"})

    race_chat_id = str(uuid.uuid4())
    await _write(directus, "chats", {
        "id": race_chat_id, "hashed_user_id": owner_hash, "storage_state": "hot",
        "encrypted_title": ciphertext, "encrypted_chat_key": ciphertext,
        "messages_v": 0, "title_v": 1, "created_at": now, "updated_at": now,
    })
    race_item_id = str(uuid.uuid4())

    async def delete_race_chat():
        return await directus._make_api_request(
            "PATCH", f"{directus.base_url.rstrip('/')}/items/chats/{race_chat_id}",
            headers={"Authorization": f"Bearer {token}"},
            json={"storage_state": "deleting"},
        )

    attachment, deletion = await asyncio.gather(
        attach(race_chat_id, item_id=race_item_id), delete_race_chat(),
    )
    attached_ok = 200 <= attachment.status_code < 300
    deleted_ok = 200 <= deletion.status_code < 300
    if attached_ok == deleted_ok:
        raise RuntimeError("Concurrent Project attachment and chat deletion had no single winner")
    race_items = await directus.get_items("project_items", params={
        "filter": {"id": {"_eq": race_item_id}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    race_chats = await directus.get_items("chats", params={
        "filter": {"id": {"_eq": race_chat_id}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if len(race_chats) != 1 or bool(race_items) != attached_ok or (
        race_chats[0].get("storage_state") == "deleting"
    ) != deleted_ok:
        raise RuntimeError("Concurrent Project link/deletion result disagreed with canonical rows")
    retry = await (delete_race_chat() if attached_ok else attach(
        race_chat_id, item_id=race_item_id,
    ))
    if retry.status_code < 400:
        raise RuntimeError("Losing Project link/deletion operation succeeded on retry")
    if attached_ok:
        if not await directus.delete_item("project_items", race_item_id, admin_required=True):
            raise RuntimeError("Synthetic raced Project link cleanup failed")
        await _patch(directus, "chats", race_chat_id, {"storage_state": "deleting"})


async def _probe_project_upload_deletion_fence(directus, *, owner_id: str,
                                               owner_hash: str, now: int) -> None:
    """Prove upload id/embed identity and delete serialization on real PG."""
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("Synthetic upload attachment probe lacks disposable admin token")
    project_hash = hashlib.sha256(f"upload-project:{owner_id}".encode()).hexdigest()
    team_hash = hashlib.sha256(f"upload-team:{owner_id}".encode()).hexdigest()

    async def upload_row(*, upload_id: str | None = None, embed_id: str | None = None) -> dict:
        return await _write(directus, "upload_files", {
            "id": upload_id or str(uuid.uuid4()), "embed_id": embed_id or str(uuid.uuid4()),
            "user_id": owner_id, "content_hash": secrets.token_hex(32),
            "created_at": now,
        })

    async def attach(target_id: str, item_id: str):
        return await directus._make_api_request(
            "POST", f"{directus.base_url.rstrip('/')}/items/project_items",
            headers={"Authorization": f"Bearer {token}"}, json={
                "id": item_id, "project_item_id": str(uuid.uuid4()),
                "hashed_project_id": project_hash, "hashed_user_id": None,
                "hashed_team_id": team_hash, "attached_by_user_hash": owner_hash,
                "item_type": "upload", "deleted_target_state": None,
                "target_id_hash": hashlib.sha256(target_id.encode()).hexdigest(),
                "target_id_encrypted": base64.b64encode(secrets.token_bytes(96)).decode(),
                "created_at": now, "updated_at": now,
            },
        )

    async def delete_upload(upload_id: str):
        return await directus._make_api_request(
            "DELETE", f"{directus.base_url.rstrip('/')}/items/upload_files/{upload_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    for use_embed_id in (False, True):
        upload = await upload_row()
        item_id = str(uuid.uuid4())
        target_id = upload["embed_id"] if use_embed_id else upload["id"]
        linked = await attach(target_id, item_id)
        if not 200 <= linked.status_code < 300:
            raise RuntimeError("Synthetic Project upload identity attachment failed")
        blocked = await delete_upload(upload["id"])
        if blocked.status_code < 400:
            raise RuntimeError("PostgreSQL deleted upload with surviving Team Project link")
        if not await directus.delete_item("project_items", item_id, admin_required=True):
            raise RuntimeError("Synthetic upload Project link cleanup failed")
        removed = await delete_upload(upload["id"])
        if not 200 <= removed.status_code < 300:
            raise RuntimeError("Synthetic upload deletion failed after Project unlink")

    raced_upload = await upload_row()
    race_item_id = str(uuid.uuid4())
    linked, deleted = await asyncio.gather(
        attach(raced_upload["embed_id"], race_item_id), delete_upload(raced_upload["id"]),
    )
    linked_ok = 200 <= linked.status_code < 300
    deleted_ok = 200 <= deleted.status_code < 300
    if linked_ok == deleted_ok:
        raise RuntimeError("Concurrent upload Project link/deletion had no single winner")
    upload_rows = await directus.get_items("upload_files", params={
        "filter": {"id": {"_eq": raced_upload["id"]}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    item_rows = await directus.get_items("project_items", params={
        "filter": {"id": {"_eq": race_item_id}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if bool(upload_rows) != linked_ok or bool(item_rows) != linked_ok:
        raise RuntimeError("Concurrent upload Project result disagreed with canonical rows")
    retry = await (delete_upload(raced_upload["id"]) if linked_ok else attach(
        raced_upload["embed_id"], race_item_id,
    ))
    if retry.status_code < 400:
        raise RuntimeError("Losing upload Project link/deletion operation succeeded on retry")
    if linked_ok:
        if not await directus.delete_item("project_items", race_item_id, admin_required=True):
            raise RuntimeError("Synthetic raced upload Project link cleanup failed")
        removed = await delete_upload(raced_upload["id"])
        if not 200 <= removed.status_code < 300:
            raise RuntimeError("Synthetic raced upload cleanup failed")

    ambiguous_id = str(uuid.uuid4())
    first = await upload_row(upload_id=ambiguous_id)
    second = await upload_row(embed_id=ambiguous_id)
    ambiguous_item_id = str(uuid.uuid4())
    ambiguous = await attach(ambiguous_id, ambiguous_item_id)
    if ambiguous.status_code < 400:
        raise RuntimeError("PostgreSQL accepted ambiguous upload id/embed identity")
    ambiguous_rows = await directus.get_items("project_items", params={
        "filter": {"id": {"_eq": ambiguous_item_id}}, "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if ambiguous_rows:
        raise RuntimeError("Rejected ambiguous upload link left a Project row")
    for upload in (first, second):
        removed = await delete_upload(upload["id"])
        if not 200 <= removed.status_code < 300:
            raise RuntimeError("Synthetic ambiguous upload fixture cleanup failed")


async def _probe_project_embed_deletion_fence(directus, *, owner_hash: str,
                                              now: int) -> None:
    """Prove Project links and Team key wrappers serialize with embed deletion."""
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("Synthetic embed attachment probe lacks disposable admin token")
    project_hash = hashlib.sha256(f"embed-project:{owner_hash}".encode()).hexdigest()
    team_hash = hashlib.sha256(f"embed-team:{owner_hash}".encode()).hexdigest()

    async def embed_row(*, hashed_chat_id: str | None = None) -> dict:
        embed_id = str(uuid.uuid4())
        ciphertext = base64.b64encode(secrets.token_bytes(96)).decode()
        return await _write(directus, "embeds", {
            "id": str(uuid.uuid4()), "embed_id": embed_id,
            "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
            "hashed_chat_id": hashed_chat_id,
            "hashed_user_id": owner_hash, "encrypted_type": ciphertext,
            "encrypted_content": ciphertext, "status": "finished",
            "encryption_mode": "client",
        })

    async def attach_project(embed_id: str, item_id: str, *, personal: bool = False):
        return await directus._make_api_request(
            "POST", f"{directus.base_url.rstrip('/')}/items/project_items",
            headers={"Authorization": f"Bearer {token}"}, json={
                "id": item_id, "project_item_id": str(uuid.uuid4()),
                "hashed_project_id": project_hash,
                "hashed_user_id": owner_hash if personal else None,
                "hashed_team_id": None if personal else team_hash,
                "attached_by_user_hash": owner_hash,
                "item_type": "embed", "deleted_target_state": None,
                "target_id_hash": hashlib.sha256(embed_id.encode()).hexdigest(),
                "target_id_encrypted": base64.b64encode(secrets.token_bytes(96)).decode(),
                "created_at": now, "updated_at": now,
            },
        )

    async def attach_wrapper(embed_id: str, wrapper_id: str):
        return await directus._make_api_request(
            "POST", f"{directus.base_url.rstrip('/')}/items/embed_keys",
            headers={"Authorization": f"Bearer {token}"}, json={
                "id": wrapper_id, "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
                "key_type": "team", "hashed_team_id": team_hash,
                "hashed_user_id": owner_hash, "team_key_epoch": 1,
                "encrypted_embed_key": base64.b64encode(secrets.token_bytes(96)).decode(),
                "created_at": now,
            },
        )

    async def delete_embed(row_id: str):
        return await directus._make_api_request(
            "DELETE", f"{directus.base_url.rstrip('/')}/items/embeds/{row_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    missing_embed_id = str(uuid.uuid4())
    missing_link_id = str(uuid.uuid4())
    missing_wrapper_id = str(uuid.uuid4())
    if (await attach_project(missing_embed_id, missing_link_id)).status_code < 400 or (
        await attach_wrapper(missing_embed_id, missing_wrapper_id)
    ).status_code < 400:
        raise RuntimeError("PostgreSQL accepted an embed Project link or wrapper without a parent")

    for kind, attach in (("project", attach_project), ("wrapper", attach_wrapper)):
        embed = await embed_row()
        attached_id = str(uuid.uuid4())
        linked = await attach(embed["embed_id"], attached_id)
        if not 200 <= linked.status_code < 300:
            raise RuntimeError(f"Synthetic Team {kind} embed attachment failed")
        blocked = await delete_embed(embed["id"])
        if blocked.status_code < 400:
            raise RuntimeError(f"PostgreSQL deleted embed with surviving Team {kind} reference")
        collection = "project_items" if kind == "project" else "embed_keys"
        if not await directus.delete_item(collection, attached_id, admin_required=True):
            raise RuntimeError(f"Synthetic Team {kind} embed reference cleanup failed")
        removed = await delete_embed(embed["id"])
        if not 200 <= removed.status_code < 300:
            raise RuntimeError(f"Synthetic embed deletion after Team {kind} unlink failed")

        raced = await embed_row()
        race_id = str(uuid.uuid4())
        link_result, delete_result = await asyncio.gather(
            attach(raced["embed_id"], race_id), delete_embed(raced["id"]),
        )
        linked_ok = 200 <= link_result.status_code < 300
        deleted_ok = 200 <= delete_result.status_code < 300
        if linked_ok == deleted_ok:
            raise RuntimeError(f"Concurrent Team {kind} embed link/deletion had no single winner")
        embed_rows = await directus.get_items("embeds", params={
            "filter": {"id": {"_eq": raced["id"]}}, "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        link_rows = await directus.get_items(collection, params={
            "filter": {"id": {"_eq": race_id}}, "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if bool(embed_rows) != linked_ok or bool(link_rows) != linked_ok:
            raise RuntimeError(f"Concurrent Team {kind} embed result disagreed with canonical rows")
        retry = await (delete_embed(raced["id"]) if linked_ok else attach(
            raced["embed_id"], race_id,
        ))
        if retry.status_code < 400:
            raise RuntimeError(f"Losing Team {kind} embed operation succeeded on retry")
        if linked_ok:
            if not await directus.delete_item(collection, race_id, admin_required=True):
                raise RuntimeError(f"Synthetic raced Team {kind} embed reference cleanup failed")
            removed = await delete_embed(raced["id"])
            if not 200 <= removed.status_code < 300:
                raise RuntimeError(f"Synthetic raced Team {kind} embed cleanup failed")

    personal = await embed_row()
    personal_wrapper_id = str(uuid.uuid4())
    personal_wrapper = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/items/embed_keys",
        headers={"Authorization": f"Bearer {token}"}, json={
            "id": personal_wrapper_id,
            "hashed_embed_id": hashlib.sha256(personal["embed_id"].encode()).hexdigest(),
            "key_type": "master", "hashed_user_id": owner_hash,
            "encrypted_embed_key": base64.b64encode(secrets.token_bytes(96)).decode(),
            "created_at": now,
        },
    )
    if not 200 <= personal_wrapper.status_code < 300:
        raise RuntimeError("Synthetic personal master embed wrapper fixture failed")
    personal_delete = await delete_embed(personal["id"])
    if not 200 <= personal_delete.status_code < 300:
        raise RuntimeError("PostgreSQL blocked eligible personal master wrapper deletion")
    if not await directus.delete_item("embed_keys", personal_wrapper_id, admin_required=True):
        raise RuntimeError("Synthetic personal master embed wrapper cleanup failed")

    retiring_chat_id = str(uuid.uuid4())
    chat_ciphertext = base64.b64encode(secrets.token_bytes(96)).decode()
    await _write(directus, "chats", {
        "id": retiring_chat_id, "hashed_user_id": None, "hashed_team_id": team_hash,
        "storage_state": "hot", "encrypted_title": chat_ciphertext,
        "encrypted_chat_key": chat_ciphertext, "messages_v": 0, "title_v": 1,
        "created_at": now, "updated_at": now,
    })
    chat_hash = hashlib.sha256(retiring_chat_id.encode()).hexdigest()
    chat_embed = await embed_row(hashed_chat_id=chat_hash)
    chat_wrapper_id = str(uuid.uuid4())
    chat_wrapper = await directus._make_api_request(
        "POST", f"{directus.base_url.rstrip('/')}/items/embed_keys",
        headers={"Authorization": f"Bearer {token}"}, json={
            "id": chat_wrapper_id,
            "hashed_embed_id": hashlib.sha256(chat_embed["embed_id"].encode()).hexdigest(),
            "key_type": "chat", "hashed_chat_id": chat_hash,
            "hashed_team_id": team_hash, "hashed_user_id": owner_hash,
            "encrypted_embed_key": base64.b64encode(secrets.token_bytes(96)).decode(),
            "created_at": now,
        },
    )
    if not 200 <= chat_wrapper.status_code < 300:
        raise RuntimeError("Synthetic Team chat wrapper fixture failed")
    active_delete = await delete_embed(chat_embed["id"])
    if active_delete.status_code < 400:
        raise RuntimeError("PostgreSQL allowed embed deletion with active Team chat wrapper")
    await _patch(directus, "chats", retiring_chat_id, {"storage_state": "deleting"})
    retired_delete = await delete_embed(chat_embed["id"])
    if not 200 <= retired_delete.status_code < 300:
        raise RuntimeError("PostgreSQL blocked embed deletion for retiring Team chat wrapper")
    if not await directus.delete_item("embed_keys", chat_wrapper_id, admin_required=True):
        raise RuntimeError("Synthetic retiring Team chat wrapper cleanup failed")

    personal_project_embed = await embed_row()
    personal_project_item_id = str(uuid.uuid4())
    personal_link = await attach_project(
        personal_project_embed["embed_id"], personal_project_item_id, personal=True,
    )
    if not 200 <= personal_link.status_code < 300:
        raise RuntimeError("Synthetic personal Project embed link failed")
    without_fence = await delete_embed(personal_project_embed["id"])
    if without_fence.status_code < 400:
        raise RuntimeError("PostgreSQL allowed personal Project embed deletion without account fence")
    await _write(directus, "chat_recovery_account_fences", {
        "id": owner_hash, "fenced_at": datetime.now(timezone.utc).isoformat(),
    })
    with_fence = await delete_embed(personal_project_embed["id"])
    if not 200 <= with_fence.status_code < 300:
        raise RuntimeError("PostgreSQL blocked fenced personal Project embed deletion")
    if not await directus.delete_item("project_items", personal_project_item_id,
                                     admin_required=True):
        raise RuntimeError("Synthetic personal Project embed link cleanup failed")

    fenced_team_embed = await embed_row()
    fenced_team_item_id = str(uuid.uuid4())
    team_link = await attach_project(fenced_team_embed["embed_id"], fenced_team_item_id)
    if not 200 <= team_link.status_code < 300:
        raise RuntimeError("Synthetic fenced Team Project embed link failed")
    fenced_team_delete = await delete_embed(fenced_team_embed["id"])
    if fenced_team_delete.status_code < 400:
        raise RuntimeError("PostgreSQL allowed Team Project embed deletion under personal fence")
    if not await directus.delete_item("project_items", fenced_team_item_id,
                                     admin_required=True):
        raise RuntimeError("Synthetic fenced Team Project embed link cleanup failed")
    removed = await delete_embed(fenced_team_embed["id"])
    if not 200 <= removed.status_code < 300:
        raise RuntimeError("Synthetic fenced Team Project embed cleanup failed")
    if not await directus.delete_item("chat_recovery_account_fences", owner_hash,
                                     admin_required=True):
        raise RuntimeError("Synthetic account fence fixture cleanup failed")


async def _load_archive_services():
    """Initialize only the services used by this non-Celery CI probe."""
    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.s3.service import S3UploadService
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets_manager = SecretsManager()
    await secrets_manager.initialize()
    directus = DirectusService()
    try:
        s3 = S3UploadService(secrets_manager=secrets_manager, directus_service=directus)
        await s3.initialize(configure_buckets=False)
        return secrets_manager, directus, s3
    except Exception:
        await directus.close()
        await secrets_manager.aclose()
        raise


async def _probe_degraded_storage_regressions(directus, archive, now: int) -> None:
    """Exercise UUID paging, legacy completion, and schema-valid deletion scope."""
    from backend.core.api.app.routes.handlers.websocket_handlers.store_embed_handler import _complete_direct_intent
    from backend.core.api.app.services.storage_reference_service import (
        fence_account_chats_for_deletion, load_account_deletable_embed_rows,
    )

    actor_id, chat_id, team_chat_id = (str(uuid.uuid4()) for _ in range(3))
    owner_hash = hashlib.sha256(actor_id.encode()).hexdigest()
    team_hash = hashlib.sha256(team_chat_id.encode()).hexdigest()
    ciphertext = base64.b64encode(secrets.token_bytes(96)).decode()
    created: list[tuple[str, str]] = []
    actor_created = False

    async def write(collection: str, payload: dict) -> dict:
        row = await _write(directus, collection, payload)
        created.append((collection, str(row["id"])))
        return row

    try:
        await _legacy_claim_fixture_user(directus, actor_id)
        actor_created = True
        for identity, team in ((chat_id, None), (team_chat_id, team_hash)):
            await write("chats", {
                "id": identity, "hashed_user_id": owner_hash, "hashed_team_id": team,
                "storage_state": "hot", "encrypted_title": ciphertext,
                "encrypted_chat_key": ciphertext, "messages_v": 0, "title_v": 1,
                "created_at": now, "updated_at": now,
            })
        segment_ids = [f"00000000-0000-4000-8000-{number:012d}" for number in range(1, 27)]
        for segment_id in segment_ids:
            await write("chat_message_archive_segments", {
                "id": segment_id, "chat_id": chat_id,
                "chat_hash": hashlib.sha256(chat_id.encode()).hexdigest(),
                "hashed_user_id": owner_hash, "checkpoint_id": str(uuid.uuid4()),
                "start_timestamp": now - 2, "end_timestamp": now - 1,
                "end_message_id": str(uuid.uuid4()), "state": "copying",
                "lease_until": now - 100, "created_at": now,
            })
        data = {"now": now, "reads_enabled": False, "prune_enabled": False, "limit": 25}
        first = await archive.transaction("progress_candidates", data)
        second = await archive.transaction("progress_candidates", {
            **data, "after_id": first["segments"][-1]["id"], "limit": 1,
        })
        if ([row["id"] for row in first["segments"]] != segment_ids[:25]
                or [row["id"] for row in second["segments"]] != segment_ids[25:]):
            raise RuntimeError("Archive progress skipped or repeated a UUID cursor page")

        embed_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        version_ids = []
        for identity, parent in zip(embed_ids, (chat_id, team_chat_id)):
            await write("embeds", {
                "id": str(uuid.uuid4()), "embed_id": identity,
                "hashed_embed_id": hashlib.sha256(identity.encode()).hexdigest(),
                "hashed_chat_id": hashlib.sha256(parent.encode()).hexdigest(),
                "hashed_user_id": owner_hash, "encrypted_type": ciphertext,
                "encrypted_content": ciphertext, "status": "finished", "encryption_mode": "client",
            })
            version = await write("embed_diffs", {
                "id": str(uuid.uuid4()), "embed_id": identity, "version_number": 1,
                "hashed_user_id": owner_hash, "encrypted_snapshot": ciphertext,
                "created_at": now,
            })
            version_ids.append(version["id"])
        snapshot = await load_account_deletable_embed_rows(directus_service=directus, user_id_hash=owner_hash)
        if {row["id"] for row in snapshot.versions} != {version_ids[0]}:
            raise RuntimeError("Account version inventory crossed Team ownership")
        if await fence_account_chats_for_deletion(directus_service=directus, user_id_hash=owner_hash) != 1:
            raise RuntimeError("Account deletion did not fence exactly its personal chat")
        await load_account_deletable_embed_rows(directus_service=directus, user_id_hash=owner_hash)

        intent_id, embed_id = str(uuid.uuid4()), str(uuid.uuid4())
        binding = hashlib.sha256(intent_id.encode()).hexdigest()
        task_name = "apps.social_media.tasks.skill_get-posts"
        status, registered = await _recovery_sql(directus, "register_authorized_direct_skill", {
            "protocol_version": 1, "task_uuid": intent_id, "task_name": task_name,
            "kwargs_binding": binding, "actor_user_id": actor_id, "hashed_user_id": owner_hash,
            "hashed_team_id": None, "target_chat_id": None, "primary_message_id": None,
            "primary_embed_id": embed_id,
        })
        if status != 200 or registered.get("status") != "DIRECT_AUTHORIZED":
            raise RuntimeError("Synthetic direct completion registration failed")
        created.append(("chat_recovery_authorized_direct_skills", intent_id))
        status, claimed = await _recovery_sql(directus, "claim_authorized_direct_producer", {
            "protocol_version": 1, "task_uuid": intent_id, "task_name": task_name, "kwargs_binding": binding,
        })
        if status != 200 or claimed.get("claimed") is not True:
            raise RuntimeError("Synthetic direct completion claim failed")
        head = await write("embeds", {
            "id": str(uuid.uuid4()), "embed_id": embed_id,
            "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
            "hashed_user_id": owner_hash, "encrypted_type": ciphertext,
            "encrypted_content": ciphertext, "status": "finished", "encryption_mode": "client",
            "version_number": None,
        })
        pending = await _complete_direct_intent(directus, actor_hash=owner_hash, canonical_embed=head)
        if pending.get("reason_code") != "pending_wrappers":
            raise RuntimeError("Legacy direct head completed before canonical wrappers")
        await write("embed_keys", {
            "id": str(uuid.uuid4()), "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
            "hashed_user_id": owner_hash, "key_type": "master", "encrypted_embed_key": ciphertext,
            "created_at": now,
        })
        completed = await _complete_direct_intent(directus, actor_hash=owner_hash, canonical_embed=head)
        if completed.get("completed") is not True:
            raise RuntimeError("Legacy nullable canonical head left a direct intent pending")
    finally:
        for collection, identity in reversed(created):
            if not await directus.delete_item(collection, identity, admin_required=True):
                raise RuntimeError("Degraded storage regression fixture cleanup failed")
        if actor_created:
            token = await directus.ensure_auth_token(admin_required=True)
            response = await directus._make_api_request(
                "DELETE", f"{directus.base_url.rstrip('/')}/users/{actor_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code not in {200, 204}:
                raise RuntimeError("Degraded storage regression actor cleanup failed")


async def probe() -> dict:
    require_isolated_storage()
    from backend.core.api.app.services.chat_message_archive_service import ChatMessageArchiveService

    secrets_manager, directus, s3 = await _load_archive_services()
    try:
        archive = ChatMessageArchiveService(directus_service=directus, s3_service=s3)
        now = int(time.time())
        await _probe_degraded_storage_regressions(directus, archive, now)
        chat_id = str(uuid.uuid4())
        owner_hash = hashlib.sha256(chat_id.encode()).hexdigest()
        await _probe_legacy_embed_json_columns(directus, owner_hash)
        checkpoint_id = str(uuid.uuid4())
        synthetic_ciphertexts = [base64.b64encode(secrets.token_bytes(96)).decode() for _ in range(20)]
        message_ids = [str(uuid.uuid4()) for _ in range(20)]
        source_row_ids = [str(uuid.uuid4()) for _ in range(20)]
        await _write(directus, "chats", {
            "id": chat_id, "hashed_user_id": owner_hash, "encrypted_title": synthetic_ciphertexts[0],
            "encrypted_chat_key": synthetic_ciphertexts[1], "messages_v": 20, "title_v": 1,
            "created_at": now - 100, "updated_at": now, "last_message_timestamp": now - 81,
        })
        for index, (message_id, ciphertext) in enumerate(zip(message_ids, synthetic_ciphertexts)):
            await _write(directus, "messages", {
                "id": source_row_ids[index], "client_message_id": message_id, "chat_id": chat_id,
                "hashed_user_id": owner_hash, "encrypted_content": ciphertext, "role": "user",
                "created_at": now - 100 + index, "updated_at": now - 100 + index,
            })
        await _write(directus, "chat_compression_checkpoints", {
            "id": checkpoint_id, "chat_id": chat_id, "hashed_user_id": owner_hash,
            "encrypted_summary": base64.b64encode(secrets.token_bytes(64)).decode(),
            "compressed_up_to_timestamp": now - 81, "compressed_up_to_message_id": message_ids[-1],
            "covered_message_ids": message_ids,
            "compressed_message_count": 20, "summary_token_estimate": 100,
            "created_at": now, "updated_at": now,
        })
        rollout_id = "agentic-storage-v2"
        receipt = "ci-storage-capacity:" + os.environ.get("BUILD_COMMIT_SHA", "unknown")
        rollout_rows = await directus.get_items("chat_message_archive_rollout", params={
            "filter": {"id": {"_eq": rollout_id}}, "limit": 1,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        rollout_fields = {"read_enabled": True, "pruning_enabled": True, "initial_cohort": True,
                          "compatibility_verified": True, "reader_receipt": receipt,
                          "validation_receipt": receipt, "failure_code": None}
        if rollout_rows:
            await _patch(directus, "chat_message_archive_rollout", rollout_id, rollout_fields)
        else:
            await _write(directus, "chat_message_archive_rollout", {"id": rollout_id, **rollout_fields})

        end = now - 81, message_ids[-1]
        await _probe_official_billing_copy_hold(archive, chat_id=chat_id,
            checkpoint_id=checkpoint_id, end=end, source_row_ids=source_row_ids, now=now)
        claim = await archive.transaction("claim_segment", {
            "chat_id": chat_id, "checkpoint_id": checkpoint_id,
            "end_timestamp": end[0], "end_message_id": end[1], "now": now,
        })
        if claim.get("segment", {}).get("state") != "copying":
            raise RuntimeError("Synthetic exact-manifest claim did not enter copying state")
        # This row arrives after the checkpoint, but sorts inside its timestamp
        # range. Only the manifest can keep it hot through the real SQL copy.
        late_message_id = str(uuid.uuid4())
        await _write(directus, "messages", {
            "id": str(uuid.uuid4()), "client_message_id": late_message_id, "chat_id": chat_id,
            "hashed_user_id": owner_hash,
            "encrypted_content": base64.b64encode(secrets.token_bytes(96)).decode(),
            "role": "user", "created_at": now - 90, "updated_at": now,
        })
        verified = await archive.copy_segment(
            chat_id=chat_id, checkpoint_id=checkpoint_id, end=end, now_timestamp=now + 301,
        )
        if verified.get("state") != "verified" or verified.get("page_count") != 1:
            raise RuntimeError("Synthetic archive copy was not verified as one bounded page")
        retry = await archive.copy_segment(
            chat_id=chat_id, checkpoint_id=checkpoint_id, end=end, now_timestamp=now + 302,
        )
        if retry.get("id") != verified.get("id"):
            raise RuntimeError("Synthetic archive retry changed segment identity")
        activation_now = now + 302
        await _expect_error(lambda: archive.transaction("activate_segment", {
            "segment_id": verified["id"], "expected_version": verified["version"], "now": activation_now,
        }), "archive_reader_verification_incomplete")
        if not await archive.verify_reader_pages(verified):
            raise RuntimeError("Synthetic reader verification did not complete its bounded page batch")
        active = await archive.transaction("activate_segment", {
            "segment_id": verified["id"], "expected_version": verified["version"], "now": activation_now,
        })
        if active.get("state") != "reader_active" or active.get("source_copy_until") != activation_now + 86400:
            raise RuntimeError("Initial cohort did not retain the 24-hour source copy")
        await _expect_error(lambda: archive.transaction("activate_segment", {
            "segment_id": verified["id"], "expected_version": verified["version"], "now": activation_now,
        }), "archive_generation_changed")
        page = await archive.read_before(chat_id=chat_id, before=None, limit=20)
        read_rows = page["messages"]
        if [row["client_message_id"] for row in read_rows] != message_ids or [row["encrypted_content"] for row in read_rows] != synthetic_ciphertexts:
            raise RuntimeError("Synthetic archive S3 read differs from source ciphertext ledger")
        page_id = page["archive_page_ids"][0]
        prune_data = {"segment_id": active["id"], "expected_version": active["version"],
                      "page_id": page_id, "now": activation_now}
        with _official_billing_hold():
            await _expect_error(lambda: archive.transaction("prune_page", prune_data), "ARCHIVE_BILLING_DISABLED")
            await _expect_error(lambda: archive.transaction("activate_segment", {
                "segment_id": verified["id"], "expected_version": verified["version"], "now": activation_now,
            }), "ARCHIVE_BILLING_DISABLED")
            retained = await archive.read_before(chat_id=chat_id, before=None, limit=20)
            if ([row["client_message_id"] for row in retained["messages"]] != message_ids
                    or [row["encrypted_content"] for row in retained["messages"]] != synthetic_ciphertexts):
                raise RuntimeError("Official billing hold hid existing authorized S3 history")
        await _expect_error(lambda: archive.transaction("prune_page", prune_data), "archive_rollback_buffer_active")

        recovery_id = str(uuid.uuid4())
        utc_now = datetime.now(timezone.utc)
        await _write(directus, "chat_completion_recovery_jobs", {
            "id": recovery_id, "hashed_user_id": owner_hash, "chat_id": chat_id,
            "turn_id": str(uuid.uuid4()), "preflight_id": str(uuid.uuid4()),
            "inference_task_id": str(uuid.uuid4()), "assistant_message_id": str(uuid.uuid4()),
            "chat_key_version": 1, "state": "AVAILABLE", "lease_generation": 0,
            "created_at": utc_now.isoformat(), "expires_at": (utc_now + timedelta(days=2)).isoformat(),
        })
        future = {**prune_data, "now": activation_now + 86401}
        await _expect_error(lambda: archive.transaction("prune_page", future), "canonical_recovery_acknowledgement_required")
        if not await directus.delete_item("chat_completion_recovery_jobs", recovery_id, admin_required=True):
            raise RuntimeError("Synthetic pending recovery fixture cleanup failed")
        output_id = str(uuid.uuid4())
        sealed = base64.b64encode(secrets.token_bytes(96)).decode()
        await _write(directus, "chat_recovery_outputs", {
            "id": output_id, "hashed_user_id": owner_hash,
            "root_chat_id": chat_id, "target_chat_id": chat_id,
            "turn_id": str(uuid.uuid4()), "preflight_id": str(uuid.uuid4()),
            "inference_task_id": str(uuid.uuid4()), "subject_id": message_ids[0],
            "output_kind": "message", "output_version": 1, "chat_key_version": 1,
            "sealed_payload": sealed, "sealed_payload_digest": hashlib.sha256(sealed.encode()).hexdigest(),
            "payload_storage": "inline", "payload_size_bytes": len(sealed),
            "state": "PENDING", "created_at": utc_now.isoformat(),
        })
        await _expect_error(lambda: archive.transaction("prune_page", future), "canonical_recovery_acknowledgement_required")
        if not await directus.delete_item("chat_recovery_outputs", output_id, admin_required=True):
            raise RuntimeError("Synthetic pending output fixture cleanup failed")
        await _patch(directus, "messages", source_row_ids[0], {
            "encrypted_content": base64.b64encode(secrets.token_bytes(96)).decode(),
        })
        await _expect_error(lambda: archive.transaction("prune_page", future), "archive_source_changed")
        await _patch(directus, "messages", source_row_ids[0], {
            "encrypted_content": synthetic_ciphertexts[0], "updated_at": now - 100,
        })
        first, second = await asyncio.gather(
            archive.transaction("prune_page", future), archive.transaction("prune_page", future),
        )
        if sorted(bool(result.get("duplicate")) for result in (first, second)) != [False, True]:
            raise RuntimeError("Concurrent prune did not serialize into one write and one idempotent retry")
        chat_rows = await directus.get_items("chats", params={"filter": {"id": {"_eq": chat_id}}, "limit": 1},
                                             admin_required=True, no_cache=True, raise_on_error=True)
        remaining = await directus.get_items("messages", params={"filter": {"chat_id": {"_eq": chat_id}}, "limit": 20},
                                             admin_required=True, no_cache=True, raise_on_error=True)
        if int(chat_rows[0].get("archived_message_count") or 0) != 20 or [row["client_message_id"] for row in remaining] != [late_message_id]:
            raise RuntimeError("Prune removed a late arrival or missed covered source rows")
        # The real SQL locator must expand positions from overlapping page
        # ranges. These temporary rows test metadata selection only; the
        # verified page above is the independent S3 ciphertext read proof.
        sparse_ids = [str(uuid.uuid4()) for _ in range(4)]
        sparse_pages = []
        sparse_positions = [
            [(now - 70, sparse_ids[0]), (now - 67, sparse_ids[3])],
            [(now - 69, sparse_ids[1]), (now - 68, sparse_ids[2])],
        ]
        try:
            for number, positions in enumerate(sparse_positions, start=2):
                synthetic_page = await _write(directus, "chat_message_archive_pages", {
                    "id": str(uuid.uuid4()), "segment_id": active["id"], "chat_id": chat_id,
                    "hashed_user_id": owner_hash, "page_number": number,
                    "first_timestamp": positions[0][0], "first_message_id": positions[0][1],
                    "last_timestamp": positions[-1][0], "last_message_id": positions[-1][1],
                    "message_count": len(positions), "message_ids": [item[1] for item in positions],
                    "message_positions": [[item[0], item[1]] for item in positions],
                    "source_fields": ["id", "client_message_id", "created_at", "encrypted_content"],
                    "object_key": f"synthetic-locator-only/{chat_id}/{number}",
                    "checksum": hashlib.sha256(f"locator:{number}".encode()).hexdigest(),
                    "source_checksum": hashlib.sha256(f"source:{number}".encode()).hexdigest(),
                    "size_bytes": 1, "raw_size_bytes": 1, "verified_regions": ["nbg1"],
                    "large_objects": [], "published": True, "reader_verified": True,
                    "read_enabled": True, "pruned": False, "created_at": now,
                })
                sparse_pages.append(synthetic_page["id"])
            before = await archive.transaction("window_locators", {
                "chat_id": chat_id, "direction": "before", "limit": 3,
                "cursor_timestamp": now - 66, "cursor_message_id": str(uuid.uuid4()),
            })
            after = await archive.transaction("window_locators", {
                "chat_id": chat_id, "direction": "after", "limit": 3,
                "cursor_timestamp": now - 71, "cursor_message_id": str(uuid.uuid4()),
            })
            if ([item["message_id"] for item in before.get("locators", [])] !=
                    [sparse_ids[3], sparse_ids[2], sparse_ids[1]] or not before.get("has_more")):
                raise RuntimeError("Sparse overlap before-cursor SQL locator order was incorrect")
            if ([item["message_id"] for item in after.get("locators", [])] !=
                    [sparse_ids[0], sparse_ids[1], sparse_ids[2]] or not after.get("has_more")):
                raise RuntimeError("Sparse overlap after-cursor SQL locator order was incorrect")
            if len(before.get("pages", [])) != 2 or len(after.get("pages", [])) != 2:
                raise RuntimeError("Sparse overlap locator omitted a physical page")
        finally:
            for sparse_page_id in sparse_pages:
                if not await directus.delete_item("chat_message_archive_pages", sparse_page_id,
                                                 admin_required=True):
                    raise RuntimeError("Synthetic sparse locator fixture cleanup failed")
        await _patch(directus, "chats", chat_id, {"storage_state": "deleting"})
        await _expect_error(lambda: archive.transaction("lookup_message", {
            "chat_id": chat_id, "message_id": message_ids[0], "now": now,
        }), "chat_unavailable")
        # Leave only the fixture rollout for subsequent synthetic capacity data.
        await _patch(directus, "chat_message_archive_rollout", rollout_id, {
            **rollout_fields, "initial_cohort": False,
        })
        team_portability = await _probe_team_archive(directus, archive, now)
        await _probe_project_attach_deletion_fence(
            directus, archive, deleting_chat_id=chat_id, owner_hash=owner_hash, now=now,
        )
        await _probe_project_upload_deletion_fence(
            directus, owner_id=chat_id, owner_hash=owner_hash, now=now,
        )
        await _probe_project_embed_deletion_fence(
            directus, owner_hash=owner_hash, now=now,
        )
        recovery_races = await _probe_recovery_sql_races(directus, now)
        return {"passed": True, "degraded_storage_regressions": True, "fixture_ciphertext_digest": hashlib.sha256(
            "".join(synthetic_ciphertexts).encode()).hexdigest(),
            "source_messages": 20, "verified_pages": 1, "pruned_messages": 20,
            "official_billing_copy_prune_hold_existing_reads_available": True,
            "initial_cohort_buffer_seconds": 86400, "concurrent_prune_idempotent": True,
            "pending_recovery_fence": True, "source_mutation_fence": True,
            "late_arrival_retained": True, "reader_verified_before_activation": True,
            "sparse_overlap_sql_locators": True,
            "legacy_embed_json_readback": True,
            "team_archive_claim_read_prune": True,
            "team_data_portability": team_portability,
            "project_attach_deletion_fence": True,
            "project_attach_deletion_race": True,
            "project_upload_identity_deletion_race": True,
            "project_embed_wrapper_deletion_races": True,
            "recovery_producer_team_account_sql_races": True,
            "recovery_sql_race_outcomes": recovery_races,
            "deletion_fence": True}
    finally:
        await directus.close()
        await secrets_manager.aclose()


if __name__ == "__main__":
    if os.getenv("OPENMATES_CI_TEAM_PORTABILITY_PROBE") == "1":
        result = asyncio.run(_team_portability_cli_result())
        print(json.dumps(result, sort_keys=True))
        raise SystemExit(0 if result.get("passed") is True else 1)
    selected = probe_legacy_claims if os.getenv("OPENMATES_CI_LEGACY_CLAIM_PROBE") == "1" else probe
    print(json.dumps(asyncio.run(selected()), sort_keys=True))
