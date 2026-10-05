"""Operator gate for the agentic-storage message and version archives.

Run inside an initialized API container. This command never prints ciphertext,
object locators, user identities, or receipt contents. The auto operation advances
only signed release gates; per-unit copy, ACK and retention fences still apply.
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
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


ROLLOUT_ID = "agentic-storage-v2"
AUTOMATIC_STATUS_KEY = "storage:automatic_migration:status:v1"
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
CERTIFICATE_SCHEMA = "agentic-storage-release-eligibility-v1"
CERTIFICATE_MAX_BYTES = 65536
RELEASE_TRUST_PATH = Path(__file__).resolve().parents[1] / "backend/shared/config/storage_rollout_release_public_key.json"
CERTIFICATE_RELEASE_URL = (
    "https://github.com/glowingkitty/OpenMates/releases/download/"
    "storage-rollout-v1/{source}.json"
)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def fetch_release_certificate(environ: dict[str, str]) -> dict[str, Any] | None:
    """Read a source-named public release asset; signature verification follows."""
    url = CERTIFICATE_RELEASE_URL.format(source=source_commit(environ))
    try:
        with urlopen(Request(url, headers={"User-Agent": "openmates-storage-rollout/1"}), timeout=8) as response:
            raw = response.read(CERTIFICATE_MAX_BYTES + 1)
    except (HTTPError, URLError, TimeoutError):
        return None
    if len(raw) > CERTIFICATE_MAX_BYTES:
        raise ValueError("Storage release certificate exceeds size limit")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Storage release certificate must be an object")
    return value


def validate_release_certificate(
    certificate: dict[str, Any], *, environ: dict[str, str],
    now: datetime | None = None,
    trusted_public_key: str | None = None,
) -> dict[str, Any]:
    """Verify the release issuer and exact installed source before any gate write.

    The signer is a release authority, not an installation operator. An absent
    trust key or certificate simply leaves the existing PostgreSQL source in
    place. No certificate can override a failed per-unit transition fence.
    """
    if set(certificate) != {"schema", "payload", "signature"} or certificate["schema"] != CERTIFICATE_SCHEMA:
        raise ValueError("Storage release certificate schema is invalid")
    payload = certificate["payload"]
    if not isinstance(payload, dict) or payload.get("source_commit") != source_commit(environ):
        raise ValueError("Storage release certificate does not match installed source")
    public_key_text = trusted_public_key
    if public_key_text is None:
        try:
            trust = load_private_json(RELEASE_TRUST_PATH)
            if trust.get("schema") != "agentic-storage-release-trust-v1" or trust.get("algorithm") != "Ed25519":
                raise ValueError("Storage release trust schema is invalid")
            public_key_text = trust["public_key"]
        except (OSError, KeyError, ValueError) as exc:
            raise ValueError("Storage release trust key is unavailable") from exc
    try:
        public_key_bytes = base64.b64decode(public_key_text, validate=True)
        signature = base64.b64decode(certificate["signature"], validate=True)
        if len(public_key_bytes) != 32 or len(signature) != 64:
            raise ValueError("Storage release signature is malformed")
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature, _canonical_json(payload))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ValueError("Storage release signature is invalid") from exc
    try:
        issued = datetime.fromisoformat(payload["issued_at"].replace("Z", "+00:00"))
        current = now or datetime.now(timezone.utc)
        if issued.tzinfo is None or issued > current:
            raise ValueError("Storage release certificate is outside its validity window")
        if payload.get("validity") == "exact-source" and payload.get("expires_at") is None:
            # Immutable-source release evidence remains valid for that source.
            # Live compatibility, source, failure and per-unit fences still
            # run at every advancement; time cannot authorize a transition.
            pass
        else:
            if payload.get("validity") not in {None, "time-window"}:
                raise ValueError("Storage release certificate validity is invalid")
            expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None or expires <= current or expires <= issued:
                raise ValueError("Storage release certificate is outside its validity window")
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Storage release certificate"):
            raise
        raise ValueError("Storage release certificate validity is invalid") from exc
    if payload.get("profile") != "real" or payload.get("client_compatibility_verified") is not True:
        raise ValueError("Storage release client compatibility is unverified")
    if payload.get("reader_ready") is not True:
        raise ValueError("Storage release reader evidence is incomplete")
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("Storage release evidence is missing")
    # Expiry renewal and publishing later P-7 evidence cannot change reader
    # identity: installed readers remain resumable across those releases.
    source = payload["source_commit"]
    digest = hashlib.sha256(_canonical_json({
        "source_commit": source, "checks": {name: checks.get(name) for name in READ_CHECKS},
    })).hexdigest()[:32]
    validation_digest = hashlib.sha256(_canonical_json({
        "source_commit": source, "checks": {name: checks.get(name) for name in PRUNE_CHECKS},
    })).hexdigest()[:32]
    receipt = {
        "schema": "agentic-storage-rollout-v1", "operation": "prepare-read",
        "source_commit": source, "profile": "real",
        "operator_review_receipt": f"reviewed:{source}:auto-release-{digest}",
        "reader_receipt": f"reviewed:{source}:auto-reader-{digest}",
        "validation_receipt": f"reviewed:{source}:auto-validation-{validation_digest}",
        "checks": checks,
    }
    validate_receipt(receipt, operation="prepare-read", environ=environ)
    if payload.get("prune_ready") is True:
        validate_receipt({**receipt, "operation": "configure-prune"}, operation="configure-prune", environ=environ)
    return {"payload": payload, "receipt": receipt, "digest": digest}


async def suspend_pruning(directus: Any, current: dict[str, Any]) -> None:
    """Keep authorized archive reads available; retry eligibility next sweep."""
    for name, row in current.items():
        if row and row.get("pruning_enabled"):
            await write_rollout(directus, name, {"pruning_enabled": False})
            row["pruning_enabled"] = False


async def auto_advance(
    directus: Any, *, certificate: dict[str, Any] | None,
    environ: dict[str, str], now: datetime | None = None,
    compatibility_status: dict[str, Any] | None = None,
    trusted_public_key: str | None = None,
) -> dict[str, Any]:
    """Advance both archives together; retries are safe and never restore data."""
    current = {name: await read_rollout(directus, name) for name in COLLECTIONS}

    async def pause(reason: str, *, status: str = "paused") -> dict[str, Any]:
        await suspend_pruning(directus, current)
        return {"status": status, "reason": reason, "retry_seconds": 60}

    if any(row and row.get("failure_code") for row in current.values()):
        return await pause("existing_failure_code")
    from backend.shared.python_utils.storage_archive_rollout_config import archive_feature_enabled
    if any(not archive_feature_enabled(flag, environ) for flag in (
        "CHAT_MESSAGE_ARCHIVE_COPY_ENABLED", "CHAT_MESSAGE_ARCHIVE_READS_ENABLED",
        "EMBED_VERSION_ARCHIVE_COPY_ENABLED", "EMBED_VERSION_ARCHIVE_READ_ENABLED",
    )):
        return await pause("migration_emergency_opt_out")
    if certificate is None:
        return await pause("release_certificate_unavailable", status="pending")
    try:
        eligibility = validate_release_certificate(
            certificate, environ=environ, now=now, trusted_public_key=trusted_public_key,
        )
    except ValueError:
        return await pause("release_certificate_invalid")
    receipt = eligibility["receipt"]
    compatibility = compatibility_status or {}
    if not (compatibility.get("enforced") is True
            and compatibility.get("minimum_capability") == "agentic-storage-v2"
            and type(compatibility.get("incompatible_sessions")) is int
            and compatibility["incompatible_sessions"] >= 0
            and compatibility.get("source_commit") == receipt["source_commit"]):
        return await pause("client_compatibility_enforcement_pending", status="pending")
    readers_match = all(
        row and row.get("read_enabled") and row.get("reader_receipt") == receipt["reader_receipt"]
        and row.get("compatibility_verified") for row in current.values()
    )
    if not readers_match:
        await suspend_pruning(directus, current)
        await operate(directus, operation="prepare-read", receipt=receipt)
    # Stage the signed admission requirement after proving every installed
    # API guard. Heartbeats can then retire old idle sessions. Actual unit
    # activation/pruning still requires zero incompatible sessions in its
    # immediate shared guard, so staging cannot expose or remove hot payloads.
    if compatibility["incompatible_sessions"] != 0:
        return await pause("client_compatibility_enforcement_pending", status="pending")
    if any(not archive_feature_enabled(flag, environ) for flag in (
        "CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED", "EMBED_VERSION_ARCHIVE_PRUNE_ENABLED",
    )):
        await suspend_pruning(directus, current)
        return {"status": "reader_enabled", "reason": "pruning_emergency_opt_out", "retry_seconds": 60}
    if eligibility["payload"].get("prune_ready") is not True:
        await suspend_pruning(directus, current)
        return {"status": "reader_enabled", "reason": "prune_evidence_pending",
                "source_commit": receipt["source_commit"], "retry_seconds": 60}
    if readers_match and all(
        row and row.get("pruning_enabled") and row.get("validation_receipt") == receipt["validation_receipt"]
        for row in current.values()
    ):
        return {"status": "prune_enabled", "source_commit": receipt["source_commit"]}
    await operate(directus, operation="configure-prune", receipt={**receipt, "operation": "configure-prune"})
    return {"status": "prune_enabled", "source_commit": receipt["source_commit"]}


async def automatic_tick(directus: Any, *, environ: dict[str, str] | None = None,
                         cache_service: Any | None = None) -> dict[str, Any]:
    """Bounded unattended entry point shared by updater and periodic sweeps."""
    env = dict(os.environ) if environ is None else environ
    from backend.shared.python_utils.storage_archive_rollout_config import (
        archive_feature_enabled, trusted_isolated_storage_profile,
        isolated_archive_advancement_allowed,
    )
    if trusted_isolated_storage_profile(env):
        rows = {name: await read_rollout(directus, name) for name in COLLECTIONS}
        enabled = all(archive_feature_enabled(flag, env) for flag in (
            "CHAT_MESSAGE_ARCHIVE_COPY_ENABLED", "CHAT_MESSAGE_ARCHIVE_READS_ENABLED", "CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED",
            "EMBED_VERSION_ARCHIVE_COPY_ENABLED", "EMBED_VERSION_ARCHIVE_READ_ENABLED", "EMBED_VERSION_ARCHIVE_PRUNE_ENABLED",
        ))
        try:
            eligible = enabled and await isolated_archive_advancement_allowed(
                directus, phase="prune", environ=env, require_pruning_enabled=False,
            )
        except Exception:
            eligible = False
        if eligible:
            for name, row in rows.items():
                if not row.get("pruning_enabled"):
                    await write_rollout(directus, name, {"pruning_enabled": True})
            result = {"status": "prune_enabled", "source_commit": source_commit(env)}
        else:
            await suspend_pruning(directus, rows)
            result = {"status": "pending", "reason": "isolated_runtime_or_receipt_gate_pending", "retry_seconds": 60}
        if cache_service is not None:
            await cache_service.set(AUTOMATIC_STATUS_KEY, result, ttl=172800)
        return result
    certificate = None
    try:
        from backend.shared.python_utils.storage_archive_rollout_config import cached_release_certificate
        certificate = await cached_release_certificate(env)
    except (ValueError, TypeError, OSError):
        # Invalid installed provenance and malformed release assets both close
        # destructive advancement without disrupting the storage job sweep.
        result = await auto_advance(directus, certificate=None, environ=env)
        if cache_service is not None:
            await cache_service.set(AUTOMATIC_STATUS_KEY, result, ttl=172800)
        return result
    compatibility = None
    if certificate is not None:
        try:
            from backend.core.api.app.services.storage_archive_client_compatibility import runtime_compatibility_status
            compatibility = await runtime_compatibility_status(directus, source_commit=source_commit(env))
        except Exception:
            compatibility = None
    result = await auto_advance(directus, certificate=certificate, environ=env,
                                compatibility_status=compatibility)
    if cache_service is not None:
        await cache_service.set(AUTOMATIC_STATUS_KEY, result, ttl=172800)
    return result


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


async def status(directus: Any, *, cache_service: Any | None = None) -> dict[str, Any]:
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
    automatic = {"status": "pending", "reason": "eligibility_check_pending", "retry_seconds": 60}
    if any(state["failed"] for state in states.values()):
        automatic = {"status": "paused", "reason": "existing_failure_code", "retry_seconds": 60}
    elif all(state["pruning_enabled"] for state in states.values()):
        automatic = {"status": "prune_enabled"}
    elif all(state["read_enabled"] for state in states.values()):
        automatic = {"status": "reader_enabled", "reason": "prune_evidence_pending", "retry_seconds": 60}
    if cache_service is not None:
        cached = await cache_service.get(AUTOMATIC_STATUS_KEY)
        if (not any(state["failed"] for state in states.values())
                and isinstance(cached, dict)
                and cached.get("status") in {"pending", "paused", "reader_enabled", "prune_enabled"}
                and (cached["status"] != "prune_enabled" or all(state["pruning_enabled"] for state in states.values()))):
            # Project explicitly so neither receipts nor private row metadata
            # can become operator-visible through a cached value.
            automatic = {"status": cached["status"]}
            if isinstance(cached.get("reason"), str) and re.fullmatch(r"[a-z_]{1,80}", cached["reason"]):
                automatic["reason"] = cached["reason"]
            if type(cached.get("retry_seconds")) is int and 0 < cached["retry_seconds"] <= 86400:
                automatic["retry_seconds"] = cached["retry_seconds"]
    return {"automatic": automatic,
            "legacy_full_graph": {"status": "paused", "reason": "metadata_retention_policy_pending"},
            "rollout": states, "message_segments": message_counts,
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
    if args.operation not in {"status", "auto"}:
        receipt = validate_receipt(
            load_private_json(args.receipt_file), operation=args.operation,
            environ=dict(os.environ), selector=selector,
        )
    certificate = None
    if args.operation == "auto" and args.certificate_file:
        certificate = load_private_json(args.certificate_file)
    task = BaseServiceTask()
    await task.initialize_services()
    try:
        if args.operation == "status":
            return await status(task.directus_service, cache_service=task.cache_service)
        if args.operation == "auto":
            if not args.certificate_file:
                return await automatic_tick(task.directus_service, cache_service=task.cache_service)
            # This optional module supplies runtime evidence for incompatible
            # client exclusion. Absence leaves pruning closed.
            compatibility_status = None
            try:
                from backend.core.api.app.services.storage_archive_client_compatibility import runtime_compatibility_status
            except ImportError:
                pass
            else:
                result = runtime_compatibility_status(
                    task.directus_service, source_commit=source_commit(dict(os.environ)),
                )
                compatibility_status = await result if asyncio.iscoroutine(result) else result
            return await auto_advance(
                task.directus_service, certificate=certificate,
                environ=dict(os.environ), compatibility_status=compatibility_status,
            )
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
    parser.add_argument("operation", choices=("status", "auto", "pause", "prepare-read", "configure-prune", "restore-page"))
    parser.add_argument("--receipt-file", type=Path)
    parser.add_argument("--selector-file", type=Path)
    parser.add_argument("--certificate-file", type=Path)
    args = parser.parse_args()
    if args.operation not in {"status", "auto"} and args.receipt_file is None:
        parser.error("Mutation operations require --receipt-file")
    if args.operation in {"status", "auto"} and args.receipt_file is not None:
        parser.error("--receipt-file is only valid for reviewed operations")
    if args.operation != "auto" and args.certificate_file is not None:
        parser.error("--certificate-file is only valid for auto")
    if args.operation == "restore-page" and args.selector_file is None:
        parser.error("restore-page requires --selector-file")
    if args.operation != "restore-page" and args.selector_file is not None:
        parser.error("--selector-file is only valid for restore-page")
    print(json.dumps(asyncio.run(run(args)), sort_keys=True))


if __name__ == "__main__":
    main()
