"""Operator gate for the agentic-storage message and version archives.

Run inside an initialized API container. This command never prints ciphertext,
object locators, user identities, or receipt contents. No mutation is implicit.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


ROLLOUT_ID = "agentic-storage-v2"
COLLECTIONS = ("chat_message_archive_rollout", "embed_version_archive_rollout")
SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")
REVIEW_RE = re.compile(r"^reviewed:[0-9a-f]{40}:[A-Za-z0-9._/-]{8,128}$")
READ_CHECKS = (
    "regional_copy", "web_reader", "cli_reader", "npm_reader", "pip_reader",
    "apple_reader", "client_decryption", "personal_authorization",
    "team_authorization", "shared_revocation", "version_reconstruction",
    "rollback_drill",
)
PRUNE_CHECKS = READ_CHECKS + (
    "canonical_acknowledgement", "authorized_delete", "authorized_export",
    "lifecycle", "p7_zero_provider_calls", "p7_capacity_target",
)
PAUSE_REASONS = {
    "manual_pause", "checksum_failure", "reader_failure", "recovery_failure",
    "capacity_failure", "other",
}


def isolated_profile(environ: dict[str, str]) -> bool:
    return (
        environ.get("OPENMATES_CI_ISOLATED") == "1"
        and environ.get("OPENMATES_STORAGE_CAPACITY_FIXTURES") == "true"
        and environ.get("S3_ENDPOINT_URL") == "http://storage.ci.test:9000"
        and environ.get("SERVER_ENVIRONMENT") == "development"
    )


def source_commit(environ: dict[str, str]) -> str:
    source = environ.get("BUILD_COMMIT_SHA") or environ.get("OPENMATES_BUILD_SHA") or ""
    if not SOURCE_RE.fullmatch(source):
        raise ValueError("An exact 40-character deployed source commit is required")
    return source


def load_private_json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 65536:
        raise ValueError("Rollout input exceeds the bounded document size")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Rollout input must be one JSON object")
    return value


def selector_digest(selector: dict[str, Any]) -> str:
    required = {"user_id", "chat_id", "client_message_id"}
    if set(selector) != required or any(
        not isinstance(selector[key], str) or not selector[key] or len(selector[key]) > 512
        for key in required
    ):
        raise ValueError("Rollback selector requires one user, chat and message ID")
    canonical = json.dumps(selector, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def validate_receipt(
    receipt: dict[str, Any], *, operation: str, environ: dict[str, str],
    selector: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = source_commit(environ)
    if receipt.get("schema") != "agentic-storage-rollout-v1" or receipt.get("operation") != operation:
        raise ValueError("Receipt schema or explicit operation does not match")
    if receipt.get("source_commit") != source:
        raise ValueError("Receipt does not match the deployed source commit")
    profile = receipt.get("profile")
    if profile not in {"real", "isolated-ci"}:
        raise ValueError("Receipt profile is invalid")
    if profile == "isolated-ci" and not isolated_profile(environ):
        raise ValueError("Synthetic CI receipt is restricted to the exact isolated profile")
    if profile == "real" and isolated_profile(environ):
        raise ValueError("Real rollout receipt cannot authorize the disposable CI profile")
    review = receipt.get("operator_review_receipt")
    if not isinstance(review, str) or not REVIEW_RE.fullmatch(review) or review.split(":")[1] != source:
        raise ValueError("Human reviewed exact-source operator receipt is required")
    reader = receipt.get("reader_receipt")
    validation = receipt.get("validation_receipt")
    for name, value in (("reader", reader), ("validation", validation)):
        if operation == "prepare-read" and name == "validation":
            continue
        if operation in {"pause", "restore-page"}:
            continue
        if not isinstance(value, str) or not REVIEW_RE.fullmatch(value) or value.split(":")[1] != source:
            raise ValueError(f"Reviewed exact-source {name} receipt is required")
        if profile == "real" and value.startswith("ci-"):
            raise ValueError("CI fixture receipt cannot authorize real rollout")
    if operation == "pause":
        if receipt.get("pause_reason") not in PAUSE_REASONS:
            raise ValueError("Pause requires a bounded reason code")
    if operation == "restore-page":
        if selector is None or receipt.get("selector_sha256") != selector_digest(selector):
            raise ValueError("Rollback receipt does not bind the selected page")
    if operation in {"prepare-read", "configure-prune"}:
        checks = receipt.get("checks")
        if not isinstance(checks, dict):
            raise ValueError("Evidence checks are required")
        required = READ_CHECKS if operation == "prepare-read" else PRUNE_CHECKS
        for name in required:
            check = checks.get(name)
            if (not isinstance(check, dict) or check.get("passed") is not True
                    or check.get("source_commit") != source
                    or not isinstance(check.get("evidence_id"), str)
                    or len(check["evidence_id"]) < 8):
                raise ValueError(f"Missing exact-source passed evidence: {name}")
        if operation == "configure-prune":
            zero = checks["p7_zero_provider_calls"]
            if (type(zero.get("real_provider_requests")) is not int
                    or zero["real_provider_requests"] != 0
                    or zero.get("provider_credentials") != "absent"
                    or zero.get("provider_network") != "internal"):
                raise ValueError("P-7 zero-provider proof is incomplete")
            target = checks["p7_capacity_target"]
            thresholds = {"user_days": 1000, "simultaneous_executions": 500,
                          "rounds": 500000, "new_embeds": 200000,
                          "file_versions": 1000000}
            if any(type(target.get(key)) is not int or target[key] < minimum
                   for key, minimum in thresholds.items()):
                raise ValueError("P-7 target capacity receipt is incomplete")
    return receipt


async def read_rollout(directus: Any, collection: str) -> dict[str, Any] | None:
    rows = await directus.get_items(collection, params={
        "filter[id][_eq]": ROLLOUT_ID,
        "fields": "id,read_enabled,pruning_enabled,initial_cohort,compatibility_verified,"
                  "reader_receipt,validation_receipt,failure_code",
        "limit": 1,
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list):
        raise RuntimeError("Rollout state is unavailable")
    return rows[0] if rows else None


async def write_rollout(directus: Any, collection: str, fields: dict[str, Any]) -> None:
    existing = await read_rollout(directus, collection)
    if existing is None:
        success, row = await directus.create_item(
            collection, {"id": ROLLOUT_ID, **fields}, admin_required=True,
        )
        if not success or not isinstance(row, dict):
            raise RuntimeError("Rollout state could not be created")
        return
    token = await directus.ensure_auth_token(admin_required=True)
    if not token:
        raise RuntimeError("Rollout admin authority is unavailable")
    response = await directus._make_api_request(
        "PATCH", f"{directus.base_url.rstrip('/')}/items/{collection}/{ROLLOUT_ID}",
        headers={"Authorization": f"Bearer {token}"}, json=fields,
    )
    if response.status_code != 200 or not isinstance(response.json().get("data"), dict):
        raise RuntimeError("Rollout update failed")


async def aggregate_count(directus: Any, collection: str, state: Any, field: str) -> int:
    filter_value = "true" if state is True else "false" if state is False else state
    rows = await directus.get_items(collection, params={
        f"filter[{field}][_eq]": filter_value, "aggregate[count]": "*",
    }, admin_required=True, no_cache=True, raise_on_error=True)
    if not isinstance(rows, list) or len(rows) != 1:
        raise RuntimeError("Archive status count is unavailable")
    return int(rows[0].get("count", 0))


async def status(directus: Any) -> dict[str, Any]:
    states = {}
    for collection in COLLECTIONS:
        row = await read_rollout(directus, collection)
        states[collection] = {
            "present": row is not None,
            "read_enabled": bool(row and row.get("read_enabled")),
            "pruning_enabled": bool(row and row.get("pruning_enabled")),
            "initial_cohort": bool(row and row.get("initial_cohort")),
            "failed": bool(row and row.get("failure_code")),
        }
    message_counts = {state: await aggregate_count(
        directus, "chat_message_archive_segments", state, "state",
    ) for state in ("copying", "verified", "reader_active")}
    page_counts = {state: await aggregate_count(
        directus, "chat_message_archive_pages", True, state,
    ) for state in ("read_enabled", "pruned")}
    version_counts = {state: await aggregate_count(
        directus, "embed_diffs", state, "archive_state",
    ) for state in ("copied", "reader_active", "pruned", "stale")}
    return {"rollout": states, "message_segments": message_counts,
            "message_pages": page_counts, "version_rows": version_counts}


async def operate(
    directus: Any, *, operation: str, receipt: dict[str, Any],
    selector: dict[str, Any] | None = None, s3_service: Any | None = None,
) -> dict[str, Any]:
    current = {collection: await read_rollout(directus, collection) for collection in COLLECTIONS}
    if operation == "prepare-read":
        if any(row and row.get("pruning_enabled") for row in current.values()):
            raise RuntimeError("Pause existing pruning before preparing a new reader receipt")
        fields = {
            "read_enabled": True, "pruning_enabled": False,
            "initial_cohort": receipt["profile"] == "real",
            "compatibility_verified": True, "reader_receipt": receipt["reader_receipt"],
            "validation_receipt": None, "failure_code": None,
        }
        for collection in COLLECTIONS:
            await write_rollout(directus, collection, fields)
        return {"operation": operation, "updated": len(COLLECTIONS)}
    if operation == "configure-prune":
        if any(not row or not row.get("read_enabled") or row.get("failure_code")
               or row.get("reader_receipt") != receipt["reader_receipt"]
               or not row.get("compatibility_verified")
               or row.get("initial_cohort") != (receipt["profile"] == "real")
               for row in current.values()):
            raise RuntimeError("Both verified readers must match this exact-source receipt")
        try:
            for collection in COLLECTIONS:
                await write_rollout(directus, collection, {
                    "pruning_enabled": True,
                    "validation_receipt": receipt["validation_receipt"],
                })
        except Exception:
            for collection in COLLECTIONS:
                try:
                    await write_rollout(directus, collection, {"pruning_enabled": False})
                except Exception:
                    pass
            raise RuntimeError("Prune setup failed; inspect both rollout gates and pause") from None
        return {"operation": operation, "updated": len(COLLECTIONS)}
    if operation == "pause":
        for collection, row in current.items():
            if row:
                await write_rollout(directus, collection, {
                    "pruning_enabled": False, "failure_code": receipt["pause_reason"],
                })
        return {"operation": operation, "updated": sum(bool(row) for row in current.values())}
    if operation == "restore-page":
        if selector is None or s3_service is None:
            raise ValueError("Rollback requires a selected page and initialized storage")
        from backend.core.api.app.services.chat_archive_mutation_service import ChatArchiveMutationService

        result = await ChatArchiveMutationService(
            directus_service=directus, s3_service=s3_service,
        ).promote_for_message(**selector)
        return {"operation": operation, "promoted": bool(result.get("promoted"))}
    raise ValueError("Unsupported rollout operation")


async def run(args: argparse.Namespace) -> dict[str, Any]:
    from backend.core.api.app.tasks.base_task import BaseServiceTask

    selector = load_private_json(args.selector_file) if args.selector_file else None
    receipt = None
    if args.operation != "status":
        receipt = validate_receipt(
            load_private_json(args.receipt_file), operation=args.operation,
            environ=dict(os.environ), selector=selector,
        )
    task = BaseServiceTask()
    await task.initialize_services()
    try:
        if args.operation == "status":
            return await status(task.directus_service)
        if receipt is None:
            raise ValueError("Mutation receipt is required")
        return await operate(
            task.directus_service, operation=args.operation, receipt=receipt,
            selector=selector, s3_service=task.s3_service,
        )
    finally:
        await task.cleanup_services()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reviewed agentic-storage archive rollout")
    parser.add_argument("operation", choices=("status", "pause", "prepare-read", "configure-prune", "restore-page"))
    parser.add_argument("--receipt-file", type=Path)
    parser.add_argument("--selector-file", type=Path)
    args = parser.parse_args()
    if args.operation != "status" and args.receipt_file is None:
        parser.error("Mutation operations require --receipt-file")
    if args.operation == "restore-page" and args.selector_file is None:
        parser.error("restore-page requires --selector-file")
    if args.operation != "restore-page" and args.selector_file is not None:
        parser.error("--selector-file is only valid for restore-page")
    print(json.dumps(asyncio.run(run(args)), sort_keys=True))


if __name__ == "__main__":
    main()
