"""Exact-source isolated Directus accountability proof for five existing collections.

Runs only against the disposable CI CMS. Synthetic rows are created and updated
through Directus, audit endpoints are queried by exact fixture item ID, and
the five collection policies are restored after a small synthetic comparison.
The private receipt contains IDs and aggregate counts, byte sizes, and timings;
ciphertext and account data are never written to it or stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
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

COLLECTIONS = ("chats", "messages", "embeds", "embed_diffs", "test_results")
SELECTOR_SCHEMA = "storage-accountability-selector-v1"
RECEIPT_SCHEMA = "storage-accountability-receipt-v1"
PRIVATE_DIR = Path("/app/ci-accountability")
SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
PREFIX_RE = re.compile(r"^ci-accountability/([0-9a-f-]{36})$")
PRIVATE_ID_RE = re.compile(r"^[1-9][0-9]{0,9}$")


def _private_host_identity(environ: dict[str, str]) -> tuple[int, int]:
    values = []
    for key in ("OPENMATES_CI_PRIVATE_HOST_UID", "OPENMATES_CI_PRIVATE_HOST_GID"):
        raw = environ.get(key, "")
        if not PRIVATE_ID_RE.fullmatch(raw):
            raise ValueError("accountability_private_owner_invalid")
        value = int(raw)
        if value > 2**31 - 1:
            raise ValueError("accountability_private_owner_invalid")
        values.append(value)
    return values[0], values[1]


def require_isolated_profile(environ: dict[str, str]) -> str:
    required = {
        "OPENMATES_CI_ISOLATED": "1",
        "OPENMATES_CI_STORAGE_ACCOUNTABILITY": "1",
        "CI": "true",
        "SERVER_ENVIRONMENT": "development",
        "OPENMATES_DEPLOYMENT_MODE": "self_host",
        "MOCK_EXTERNAL_APIS": "true",
        "CMS_URL": "http://cms:8055",
        "DATABASE_ADMIN_EMAIL": "runtime@example.com",
        "DB_HOST": "cms-database",
        "DB_DATABASE": "openmates",
        "DB_USER": "openmates",
    }
    if any(environ.get(key) != value for key, value in required.items()):
        raise ValueError("accountability_isolated_profile_required")
    source = environ.get("BUILD_COMMIT_SHA", "")
    if (not SOURCE_RE.fullmatch(source) or not environ.get("DIRECTUS_TOKEN")
            or not environ.get("DATABASE_ADMIN_PASSWORD")):
        raise ValueError("accountability_source_or_admin_missing")
    _private_host_identity(environ)
    return source


def _private_file(path: Path) -> None:
    if (path.parent != PRIVATE_DIR or path.is_symlink() or PRIVATE_DIR.is_symlink()
            or not PRIVATE_DIR.is_dir()
            or stat.S_IMODE(PRIVATE_DIR.stat().st_mode) != 0o700):
        raise ValueError("accountability_private_bind_required")


def load_selector(path: Path, source: str, *, host_uid: int, host_gid: int) -> dict[str, str]:
    _private_file(path)
    info = path.lstat()
    parent = PRIVATE_DIR.stat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 4096 or info.st_uid != host_uid or info.st_gid != host_gid
            or parent.st_uid != host_uid or parent.st_gid != host_gid):
        raise ValueError("accountability_selector_not_private_or_bounded")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) != {"schema", "source_commit", "fixture_prefix"}
            or value.get("schema") != SELECTOR_SCHEMA or value.get("source_commit") != source):
        raise ValueError("accountability_selector_mismatch")
    prefix = value.get("fixture_prefix")
    match = PREFIX_RE.fullmatch(prefix) if isinstance(prefix, str) else None
    if not match or str(uuid.UUID(match[1], version=4)) != match[1]:
        raise ValueError("accountability_fixture_prefix_invalid")
    return value


def write_private_receipt(path: Path, value: dict[str, Any], *,
                          host_uid: int, host_gid: int) -> None:
    _private_file(path)
    parent = PRIVATE_DIR.stat()
    if parent.st_uid != host_uid or parent.st_gid != host_gid:
        raise ValueError("accountability_private_owner_mismatch")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    opened = os.fstat(descriptor)
    try:
        os.fchown(descriptor, host_uid, host_gid)
        os.fchmod(descriptor, 0o600)
        owned = os.fstat(descriptor)
        if owned.st_uid != host_uid or owned.st_gid != host_gid or stat.S_IMODE(owned.st_mode) != 0o600:
            raise RuntimeError("accountability_receipt_owner_not_applied")
    except Exception:
        os.close(descriptor)
        try:
            current = path.lstat()
        except FileNotFoundError:
            current = None
        if current is not None and current.st_dev == opened.st_dev and current.st_ino == opened.st_ino:
            path.unlink()
        raise
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True, separators=(",", ":"))
        output.write("\n")


def _ciphertext() -> str:
    # Structural client AES-GCM envelope: nonce + encrypted bytes + tag.
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = secrets.token_bytes(12)
    key = AESGCM.generate_key(bit_length=256)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, secrets.token_bytes(48), None)).decode()


def _fixture_id(prefix: str, kind: str) -> str:
    # Stable private-selector IDs allow recovery cleanup after process termination.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}/{kind}"))


def fixture_rows(prefix: str) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    now = int(time.time())
    owner_hash = hashlib.sha256(prefix.encode()).hexdigest()
    chat_id = _fixture_id(prefix, "chat")
    message_id = _fixture_id(prefix, "message")
    embed_id = _fixture_id(prefix, "embed-id")
    return [
        ("chats", {
            "id": chat_id, "hashed_user_id": owner_hash, "encrypted_title": _ciphertext(),
            "encrypted_chat_key": _ciphertext(), "messages_v": 1, "title_v": 1,
            "created_at": now, "updated_at": now,
        }, {"encrypted_title": _ciphertext(), "updated_at": now + 1}),
        ("messages", {
            "id": message_id, "client_message_id": str(uuid.uuid4()), "chat_id": chat_id,
            "hashed_user_id": owner_hash, "role": "user",
            "encrypted_content": _ciphertext(), "created_at": now, "updated_at": now,
        }, {"encrypted_content": _ciphertext(), "updated_at": now + 1}),
        ("embeds", {
            "id": _fixture_id(prefix, "embed-row"), "embed_id": embed_id,
            "hashed_embed_id": hashlib.sha256(embed_id.encode()).hexdigest(),
            "hashed_chat_id": hashlib.sha256(chat_id.encode()).hexdigest(),
            "hashed_user_id": owner_hash, "encrypted_type": _ciphertext(),
            "encrypted_content": _ciphertext(), "status": "finished",
            "encryption_mode": "client", "version_number": 1,
            "created_at": now, "updated_at": now,
        }, {"encrypted_content": _ciphertext(), "updated_at": now + 1}),
        ("embed_diffs", {
            "id": _fixture_id(prefix, "diff-row"), "embed_id": embed_id, "version_number": 1,
            "encrypted_snapshot": _ciphertext(), "hashed_user_id": owner_hash,
            "created_at": now,
        }, {"encrypted_snapshot": _ciphertext()}),
        ("test_results", {
            "id": _fixture_id(prefix, "test-result"), "result_key": prefix + "/result",
            "run_key": "ci-accountability", "test_key": "storage-accountability",
            "suite": "storage", "test_name": "synthetic-accountability",
            "status": "running", "created_at": "2026-01-01T00:00:00Z",
            "created_at_unix": now,
        }, {"status": "passed"}),
    ]


async def _read_row(directus: Any, collection: str, row_id: str) -> dict[str, Any] | None:
    rows = await directus.get_items(collection, params={
        "filter": {"id": {"_eq": row_id}}, "fields": "*", "limit": 2,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if len(rows) > 1:
        raise RuntimeError("accountability_fixture_id_ambiguous")
    return rows[0] if rows else None


async def _audit_counts(directus: Any, collection: str, row_id: str) -> tuple[int, int]:
    counts = []
    for audit_collection in ("directus_activity", "directus_revisions"):
        rows = await directus.get_items(audit_collection, params={
            "filter": {"_and": [
                {"collection": {"_eq": collection}}, {"item": {"_eq": row_id}},
            ]}, "fields": "id", "limit": 2,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        counts.append(len(rows))
    return counts[0], counts[1]


async def _audit_measure(directus: Any, collection: str, row_id: str) -> dict[str, Any]:
    counts: dict[str, int] = {}
    bytes_by_kind: dict[str, int] = {}
    for kind, audit_collection in (("activity", "directus_activity"),
                                   ("revisions", "directus_revisions")):
        rows = await directus.get_items(audit_collection, params={
            "filter": {"_and": [
                {"collection": {"_eq": collection}}, {"item": {"_eq": row_id}},
            ]}, "fields": "*", "limit": 17,
        }, admin_required=True, no_cache=True, raise_on_error=True)
        if len(rows) >= 17:
            raise RuntimeError("accountability_fixture_audit_limit_exceeded")
        counts[kind] = len(rows)
        sizes = [len(json.dumps(row, sort_keys=True, separators=(",", ":"),
                                default=str).encode("utf-8")) for row in rows]
        if any(size > 256 * 1024 for size in sizes):
            raise RuntimeError("accountability_fixture_audit_row_oversized")
        bytes_by_kind[kind] = sum(sizes)
    return {"counts": counts, "serialized_json_bytes": bytes_by_kind}


async def _accountability(directus: Any, collection: str) -> str | None:
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("accountability_admin_unavailable")
    response = await directus._make_api_request(
        "GET", f"{directus.base_url.rstrip('/')}/collections/{collection}",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code != 200:
        raise RuntimeError("accountability_collection_metadata_unavailable")
    meta = (response.json().get("data") or {}).get("meta") or {}
    if "accountability" not in meta:
        raise RuntimeError("accountability_collection_policy_missing")
    return meta["accountability"]


async def _set_accountability(directus: Any, collection: str, value: str | None) -> None:
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("accountability_admin_unavailable")
    response = await directus._make_api_request(
        "PATCH", f"{directus.base_url.rstrip('/')}/collections/{collection}",
        headers={"Authorization": f"Bearer {token}"}, json={"meta": {"accountability": value}},
    )
    if not 200 <= response.status_code < 300 or await _accountability(directus, collection) != value:
        raise RuntimeError("accountability_collection_policy_update_failed")


async def _verify_metadata(directus: Any) -> None:
    for collection in COLLECTIONS:
        if await _accountability(directus, collection) is not None:
            raise RuntimeError("accountability_collection_policy_not_applied")


async def _create(directus: Any, collection: str, row: dict[str, Any]) -> None:
    success, created = await directus.create_item(collection, row, admin_required=True)
    if not success or not isinstance(created, dict) or str(created.get("id")) != row["id"]:
        raise RuntimeError("accountability_fixture_create_failed")


async def _update(directus: Any, collection: str, row_id: str,
                  fields: dict[str, Any]) -> None:
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("accountability_admin_unavailable")
    response = await directus._make_api_request(
        "PATCH", f"{directus.base_url.rstrip('/')}/items/{collection}/{row_id}",
        headers={"Authorization": f"Bearer {token}"}, json=fields,
    )
    if response.status_code != 200:
        raise RuntimeError("accountability_fixture_update_failed")


async def _cleanup_rows(directus: Any, selector: dict[str, str],
                        rows: list[tuple[str, dict[str, Any], dict[str, Any]]],
                        candidates: list[tuple[str, str]], *,
                        expect_no_audit: bool = True) -> tuple[dict[str, tuple[int, int]], int]:
    expected_rows = {row["id"]: row for _, row, _ in rows}
    audit_after_cleanup: dict[str, tuple[int, int]] = {}
    cleanup_failures = []
    deleted = 0
    for collection, row_id in reversed(candidates):
        try:
            existing = await _read_row(directus, collection, row_id)
            if existing is not None:
                expected = expected_rows[row_id]
                if collection == "test_results":
                    owned = (existing.get("result_key") == expected["result_key"]
                             and str(existing.get("result_key", "")).startswith(selector["fixture_prefix"] + "/"))
                else:
                    owned = existing.get("hashed_user_id") == expected["hashed_user_id"]
                if not owned:
                    cleanup_failures.append(collection)
                    continue
                if not await directus.delete_item(collection, row_id, admin_required=True):
                    cleanup_failures.append(collection)
                else:
                    deleted += 1
            if await _read_row(directus, collection, row_id) is not None:
                cleanup_failures.append(collection)
            audit_after_cleanup[collection] = await _audit_counts(directus, collection, row_id)
            if expect_no_audit and audit_after_cleanup[collection] != (0, 0):
                cleanup_failures.append(collection)
        except Exception:
            cleanup_failures.append(collection)
    if cleanup_failures:
        raise RuntimeError("accountability_fixture_cleanup_failed")
    return audit_after_cleanup, deleted


async def _restore_null_accountability(directus: Any) -> None:
    failures = []
    for collection in reversed(COLLECTIONS):
        try:
            current = await _accountability(directus, collection)
            if current not in (None, "all"):
                raise RuntimeError("accountability_unexpected_policy")
            if current == "all":
                await _set_accountability(directus, collection, None)
        except Exception:
            failures.append(collection)
    if failures:
        raise RuntimeError("accountability_collection_restore_failed")


async def _compare_all(directus: Any, selector: dict[str, str]) -> dict[str, Any]:
    all_selector = {**selector, "fixture_prefix": selector["fixture_prefix"] + "/all"}
    rows = fixture_rows(all_selector["fixture_prefix"])
    created: list[tuple[str, str]] = []
    elapsed_ms: dict[str, dict[str, float]] = {}
    audit: dict[str, dict[str, Any]] = {}
    error: Exception | None = None
    try:
        for collection in COLLECTIONS:
            if await _accountability(directus, collection) is not None:
                raise RuntimeError("accountability_collection_policy_changed")
            await _set_accountability(directus, collection, "all")
        for collection, row, update in rows:
            row_id = row["id"]
            if await _read_row(directus, collection, row_id) is not None:
                raise RuntimeError("accountability_comparison_fixture_collision")
            if await _audit_counts(directus, collection, row_id) != (0, 0):
                raise RuntimeError("accountability_comparison_audit_collision")
            created.append((collection, row_id))
            started = time.perf_counter_ns()
            await _create(directus, collection, row)
            created_ms = (time.perf_counter_ns() - started) / 1_000_000
            started = time.perf_counter_ns()
            await _update(directus, collection, row_id, update)
            updated_ms = (time.perf_counter_ns() - started) / 1_000_000
            elapsed_ms[collection] = {"create": round(created_ms, 3),
                                      "update": round(updated_ms, 3)}
            persisted = await _read_row(directus, collection, row_id)
            if persisted is None or any(persisted.get(key) != value for key, value in update.items()):
                raise RuntimeError("accountability_comparison_write_not_persisted")
            if collection == "embed_diffs" and (
                persisted.get("version_number") != 1 or persisted.get("embed_id") != row["embed_id"]
            ):
                raise RuntimeError("accountability_comparison_product_version_missing")
            audit[collection] = await _audit_measure(directus, collection, row_id)
            if any(audit[collection]["counts"][kind] < 1 or
                   audit[collection]["serialized_json_bytes"][kind] < 1
                   for kind in ("activity", "revisions")):
                raise RuntimeError("accountability_comparison_audit_missing")
    except Exception as exc:
        error = exc
    try:
        await _restore_null_accountability(directus)
    except Exception as restore_error:
        raise restore_error from error
    try:
        await _cleanup_rows(directus, all_selector, rows, created, expect_no_audit=False)
    except Exception as cleanup_error:
        raise cleanup_error from error
    if error:
        raise error
    return {"all_write_elapsed_ms": elapsed_ms, "all_audit": audit,
            "all_fixture_cleanup_complete": True,
            "metadata_restored_to_null": True,
            "audit_bytes_kind": "serialized_json_utf8_not_postgres_relation_bytes"}


async def prove(directus: Any, selector: dict[str, str]) -> dict[str, Any]:
    await _verify_metadata(directus)
    rows = fixture_rows(selector["fixture_prefix"])
    created: list[tuple[str, str]] = []
    audit_before: dict[str, tuple[int, int]] = {}
    audit_after: dict[str, tuple[int, int]] = {}
    null_audit: dict[str, dict[str, Any]] = {}
    write_elapsed_ms: dict[str, dict[str, float]] = {}
    error: Exception | None = None
    try:
        for collection, row, update in rows:
            row_id = row["id"]
            if await _read_row(directus, collection, row_id) is not None:
                raise RuntimeError("accountability_fixture_collision")
            audit_before[collection] = await _audit_counts(directus, collection, row_id)
            if audit_before[collection] != (0, 0):
                raise RuntimeError("accountability_fixture_audit_collision")
            created.append((collection, row_id))
            # Track the ID before POST: a lost response can occur after commit.
            started = time.perf_counter_ns()
            await _create(directus, collection, row)
            created_ms = (time.perf_counter_ns() - started) / 1_000_000
            started = time.perf_counter_ns()
            await _update(directus, collection, row_id, update)
            updated_ms = (time.perf_counter_ns() - started) / 1_000_000
            write_elapsed_ms[collection] = {"create": round(created_ms, 3),
                                            "update": round(updated_ms, 3)}
            persisted = await _read_row(directus, collection, row_id)
            if persisted is None or any(persisted.get(key) != value for key, value in update.items()):
                raise RuntimeError("accountability_fixture_write_not_persisted")
            if collection == "embed_diffs" and (
                persisted.get("version_number") != 1 or persisted.get("embed_id") != row["embed_id"]
            ):
                raise RuntimeError("accountability_product_version_missing")
            # Directus normally writes audit rows synchronously; a second bounded
            # read catches a delayed hook without polling an unbounded queue.
            audit_after[collection] = await _audit_counts(directus, collection, row_id)
            await asyncio.sleep(0.1)
            if audit_after[collection] != (0, 0) or await _audit_counts(directus, collection, row_id) != (0, 0):
                raise RuntimeError("accountability_generic_audit_created")
            null_audit[collection] = await _audit_measure(directus, collection, row_id)
            if any(null_audit[collection][key][kind] != 0
                   for key in ("counts", "serialized_json_bytes")
                   for kind in ("activity", "revisions")):
                raise RuntimeError("accountability_generic_audit_created")
    except Exception as exc:
        error = exc
    try:
        audit_after_cleanup, _ = await _cleanup_rows(directus, selector, rows, created)
    except RuntimeError as cleanup_error:
        raise cleanup_error from error
    if error:
        raise error
    comparison = await _compare_all(directus, selector)
    return {"collections": list(COLLECTIONS), "fixture_ids": [row["id"] for _, row, _ in rows],
            "audit_before": audit_before, "audit_after": audit_after,
            "audit_after_cleanup": audit_after_cleanup,
            "product_embed_diffs_persisted": True, "cleanup_complete": True,
            "comparison": {"sample": "five synthetic create/update pairs per policy",
                           "null_write_elapsed_ms": write_elapsed_ms,
                           "null_audit": null_audit, **comparison}}


async def cleanup(directus: Any, selector: dict[str, str]) -> dict[str, Any]:
    await _restore_null_accountability(directus)
    all_selector = {**selector, "fixture_prefix": selector["fixture_prefix"] + "/all"}
    all_rows = fixture_rows(all_selector["fixture_prefix"])
    all_candidates = [(collection, row["id"]) for collection, row, _ in all_rows]
    _, all_deleted = await _cleanup_rows(directus, all_selector, all_rows, all_candidates,
                                         expect_no_audit=False)
    rows = fixture_rows(selector["fixture_prefix"])
    candidates = [(collection, row["id"]) for collection, row, _ in rows]
    audit_after_cleanup, deleted = await _cleanup_rows(directus, selector, rows, candidates)
    return {"cleanup_complete": True, "deleted_count": deleted + all_deleted,
            "residual_product_rows": 0, "metadata_restored_to_null": True,
            "audit_after_cleanup": audit_after_cleanup}


async def run(selector: dict[str, str], command: str) -> dict[str, Any]:
    from backend.core.api.app.services.directus.directus import DirectusService

    directus = DirectusService()
    try:
        return await (prove(directus, selector) if command == "prove" else cleanup(directus, selector))
    finally:
        await directus.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolated Directus accountability write proof")
    parser.add_argument("command", choices=("prove", "cleanup"))
    parser.add_argument("--selector-file", type=Path, required=True)
    parser.add_argument("--receipt-file", type=Path)
    args = parser.parse_args()
    source = require_isolated_profile(dict(os.environ))
    host_uid, host_gid = _private_host_identity(dict(os.environ))
    selector = load_selector(args.selector_file, source,
                             host_uid=host_uid, host_gid=host_gid)
    if args.command == "prove":
        if args.receipt_file is None:
            raise ValueError("accountability_receipt_required")
        _private_file(args.receipt_file)
        if args.receipt_file == args.selector_file or args.receipt_file.exists():
            raise ValueError("accountability_receipt_must_be_new")
    elif args.receipt_file is not None:
        raise ValueError("accountability_cleanup_has_no_receipt")
    result = asyncio.run(run(selector, args.command))
    if args.command == "prove":
        receipt = {"schema": RECEIPT_SCHEMA, "source_commit": source,
                   "selector_digest": hashlib.sha256(json.dumps(selector, sort_keys=True).encode()).hexdigest(),
                   **result}
        write_private_receipt(args.receipt_file, receipt,
                              host_uid=host_uid, host_gid=host_gid)
        print(json.dumps({"passed": True, "collections": len(COLLECTIONS),
                          "audit_rows": 0, "product_embed_diffs_persisted": True,
                          "cleanup_complete": True,
                          "comparison_complete": True}, sort_keys=True))
    else:
        print(json.dumps({"cleanup_complete": True, "deleted_count": result["deleted_count"],
                          "residual_product_rows": 0,
                          "metadata_restored_to_null": True}, sort_keys=True))


if __name__ == "__main__":
    main()
