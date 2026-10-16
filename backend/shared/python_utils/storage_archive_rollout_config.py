"""Automatic archive flags and current-release advancement fences.

Copying keeps PostgreSQL originals. Read activation and pruning additionally
require the signed release and the running API compatibility protocol. Existing
archive reads stay available when advancement pauses.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any

CI_ISOLATION_PROOF = Path("/app/ci-storage-isolation/proof.json")
CI_MOUNTINFO = Path("/proc/self/mountinfo")

_CERTIFICATE_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}


def archive_feature_enabled(name: str, environ: dict[str, str] | None = None) -> bool:
    """Enable unattended workers by default; an explicit zero is an opt-out."""
    env = os.environ if environ is None else environ
    return env.get(name, "1") == "1"


def archive_billing_hold_reason(environ: dict[str, str] | None = None) -> str | None:
    """Hold new official-cloud migration until approved logical billing is active.

    This never changes financial flags or the availability of existing archives.
    Self-host billing configuration remains independent of migration.
    """
    env = os.environ if environ is None else environ
    if (env.get("OPENMATES_DEPLOYMENT_MODE") == "official_cloud"
            and env.get("STORAGE_LOGICAL_S3_BILLING_ENABLED") != "1"):
        return "storage_billing_disabled"
    return None


async def cached_release_certificate(environ: dict[str, str]) -> dict[str, Any] | None:
    from scripts.storage_rollout import fetch_release_certificate, source_commit
    source = source_commit(environ)
    cached = _CERTIFICATE_CACHE.get(source)
    current = time.monotonic()
    if cached is not None and current - cached[0] < 60:
        return cached[1]
    certificate = await asyncio.to_thread(fetch_release_certificate, environ)
    # Keep the cache bounded even across repeated software updates.
    _CERTIFICATE_CACHE.clear()
    _CERTIFICATE_CACHE[source] = (current, certificate)
    return certificate


def trusted_isolated_storage_profile(environ: dict[str, str]) -> bool:
    """Accept only runner-verified, source-bound, read-only isolation evidence."""
    from scripts.storage_rollout import isolated_profile, source_commit
    if not isolated_profile(environ):
        return False
    try:
        source = source_commit(environ)
        info = CI_ISOLATION_PROOF.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o222
                or info.st_size > 65536):
            return False
        # A chmod'ed file in a writable container is not coordinator evidence.
        mounts = CI_MOUNTINFO.read_text().splitlines()
        if not any(len(parts := line.split()) >= 6
                   and parts[4] == str(CI_ISOLATION_PROOF.parent)
                   and "ro" in parts[5].split(",") for line in mounts):
            return False
        proof = json.loads(CI_ISOLATION_PROOF.read_text())
        now = int(time.time())
        return (
            isinstance(proof, dict) and proof.get("schema") == "agentic-storage-ci-isolation-v1"
            and proof.get("source_commit") == source
            and isinstance(proof.get("harness_commit"), str)
            and re.fullmatch(r"[0-9a-f]{40}", proof["harness_commit"]) is not None
            and isinstance(proof.get("run_id"), str) and proof["run_id"].isdecimal()
            and int(proof["run_id"]) > 0
            and proof.get("environment") == "github-isolated"
            and type(proof.get("observed_at")) is int
            and type(proof.get("expires_at")) is int
            and proof["observed_at"] <= now < proof["expires_at"]
            and proof["expires_at"] - proof["observed_at"] <= 90000
            and proof.get("provider_network") == "internal"
            and proof.get("provider_credentials") == "absent"
            and proof.get("vault_provider_keys") == ["core_server", "hetzner", "vapid"]
            and proof.get("vapid_credentials") == "generated_disposable_fixture"
            and proof.get("source_mount") == "read_only_exact_candidate"
            and proof.get("shared_dev_dns") == "rejected"
            and proof.get("shared_dev_https") == "rejected"
            and proof.get("object_storage") == "authenticated_disposable_roundtrip"
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def isolated_archive_advancement_allowed(directus_service: Any, *, phase: str,
                                              environ: dict[str, str],
                                              require_pruning_enabled: bool = True) -> bool:
    from scripts.storage_rollout import COLLECTIONS, REVIEW_RE, read_rollout, source_commit
    from backend.core.api.app.services.storage_archive_client_compatibility import runtime_compatibility_status
    if archive_billing_hold_reason(environ):
        return False
    source = source_commit(environ)
    compatibility = await runtime_compatibility_status(directus_service, source_commit=source)
    if not (compatibility.get("enforced") is True
            and compatibility.get("minimum_capability") == "agentic-storage-v2"
            and type(compatibility.get("incompatible_sessions")) is int
            and compatibility["incompatible_sessions"] == 0
            and compatibility.get("source_commit") == source):
        return False
    rows = [await read_rollout(directus_service, name) for name in COLLECTIONS]
    # Existing isolated fixture receipts remain synthetic and cannot authorize
    # real deployments. Both archive gates are established by the CI setup.
    receipt = "ci-storage-capacity:" + source
    reviewed = "reviewed:" + source + ":"
    return all(row and row.get("read_enabled") and row.get("compatibility_verified")
               and not row.get("failure_code")
               and isinstance(row.get("reader_receipt"), str)
               and (row["reader_receipt"] == receipt or (row["reader_receipt"].startswith(reviewed) and REVIEW_RE.fullmatch(row["reader_receipt"])))
               and (phase == "read" or ((not require_pruning_enabled or row.get("pruning_enabled"))
                    and isinstance(row.get("validation_receipt"), str)
                    and (row["validation_receipt"] == receipt or (row["validation_receipt"].startswith(reviewed) and REVIEW_RE.fullmatch(row["validation_receipt"])))))
               for row in rows)


async def archive_advancement_allowed(
    directus_service: Any, *, phase: str, environ: dict[str, str] | None = None,
) -> bool:
    """Recheck release and actual client fences before each transition batch."""
    if phase not in {"read", "prune"}:
        raise ValueError("Archive advancement phase must be read or prune")
    from scripts.storage_rollout import (
        COLLECTIONS, read_rollout, suspend_pruning, validate_release_certificate,
    )
    env = dict(os.environ) if environ is None else environ
    eligible = False
    feature_names = ["CHAT_MESSAGE_ARCHIVE_COPY_ENABLED", "EMBED_VERSION_ARCHIVE_COPY_ENABLED",
                     "CHAT_MESSAGE_ARCHIVE_READS_ENABLED", "EMBED_VERSION_ARCHIVE_READ_ENABLED"]
    if phase == "prune":
        feature_names += ["CHAT_MESSAGE_ARCHIVE_PRUNE_ENABLED", "EMBED_VERSION_ARCHIVE_PRUNE_ENABLED"]
    if archive_billing_hold_reason(env) or any(not archive_feature_enabled(name, env) for name in feature_names):
        rows = {name: await read_rollout(directus_service, name) for name in COLLECTIONS}
        await suspend_pruning(directus_service, rows)
        return False
    try:
        if trusted_isolated_storage_profile(env):
            eligible = await isolated_archive_advancement_allowed(directus_service, phase=phase, environ=env)
            if not eligible:
                rows = {name: await read_rollout(directus_service, name) for name in COLLECTIONS}
                await suspend_pruning(directus_service, rows)
            return eligible
        certificate = await cached_release_certificate(env)
        if certificate is not None:
            release = validate_release_certificate(certificate, environ=env)
            from backend.core.api.app.services.storage_archive_client_compatibility import runtime_compatibility_status
            compatibility = await runtime_compatibility_status(
                directus_service, source_commit=release["payload"]["source_commit"],
            )
            eligible = (
                (phase == "read" or release["payload"].get("prune_ready") is True)
                and compatibility.get("enforced") is True
                and compatibility.get("minimum_capability") == "agentic-storage-v2"
                and type(compatibility.get("incompatible_sessions")) is int
                and compatibility["incompatible_sessions"] == 0
                and compatibility.get("source_commit") == release["payload"]["source_commit"]
            )
            # A valid release must match BOTH current durable archive readers;
            # the periodic coordinator installs or refreshes those receipts.
            if eligible:
                rows = {name: await read_rollout(directus_service, name) for name in COLLECTIONS}
                receipt = release["receipt"]
                eligible = all(
                    row and row.get("read_enabled") and not row.get("failure_code")
                    and row.get("compatibility_verified")
                    and row.get("reader_receipt") == receipt["reader_receipt"]
                    and (phase == "read" or (row.get("pruning_enabled")
                         and row.get("validation_receipt") == receipt["validation_receipt"]))
                    for row in rows.values()
                )
    except Exception:
        eligible = False
    if not eligible:
        rows = {name: await read_rollout(directus_service, name) for name in COLLECTIONS}
        await suspend_pruning(directus_service, rows)
    return eligible
