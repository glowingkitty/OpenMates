#!/usr/bin/env python3
"""Audit logical and regional object-storage inventory without exposing keys.

Dry-run is deterministic and non-networked. Optional capability probes fetch
credentials from Vault inside the API runtime, exercise each managed regional
bucket with a temporary empty object, and remove it in a finally block.
Object keys, credentials, and private metadata are never emitted.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.core.api.app.services.s3.config import BUCKETS, get_bucket_name  # noqa: E402
from backend.shared.python_utils.object_storage_regions import (  # noqa: E402
    endpoint_for_region,
    parse_storage_regions,
    resolve_regional_bucket_name,
    should_replicate_bucket,
)


PROBE_BUCKET_PREFIX = "dev-openmates-region-probe"
MISSING_BUCKET_CODES = {"404", "NoSuchBucket", "NotFound"}
SHA256_METADATA_KEY = "openmates-sha256"
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
MAINTENANCE_S3_READ_TIMEOUT_SECONDS = 90
MAINTENANCE_S3_MAX_ATTEMPTS = 3
DIRECTUS_AUDIT_PAGE_SIZE = 500
MAX_UNRESOLVED_BYTE_CHECKS = 100
INVENTORY_LIST_MAX_KEYS = 100
INVENTORY_LIST_RETRY_ATTEMPTS = 3
INVENTORY_LIST_RETRY_DELAY_SECONDS = 2
RUNTIME_INVENTORY_TIMEOUT_SECONDS = 900
HOST_DELEGATION_TIMEOUT_SECONDS = RUNTIME_INVENTORY_TIMEOUT_SECONDS + 30


def runtime_inventory_command(arguments: list[str]) -> list[str]:
    """Run networked inventory inside the API boundary where Vault is available."""
    forwarded = [argument for argument in arguments if argument != "--runtime"]
    return [
        "docker",
        "exec",
        "api",
        "timeout",
        "--signal=TERM",
        "--kill-after=10s",
        f"{RUNTIME_INVENTORY_TIMEOUT_SECONDS}s",
        "python",
        "/app/scripts/audit_object_storage_inventory.py",
        *forwarded,
        "--runtime",
    ]


def build_runtime_delegation_failure(return_code: int, stderr: str) -> dict[str, object]:
    return {
        "status": "blocked",
        "error_class": "RuntimeInventoryDelegationError",
        "runtime_return_code": return_code,
        "runtime_stderr_present": bool(stderr.strip()),
        "inventory_stage": "runtime_delegation",
        "object_keys_in_output": False,
    }


def sanitized_provider_error(error: Exception) -> dict[str, object]:
    """Return provider classification without request IDs, names, or messages."""
    result: dict[str, object] = {"error_class": type(error).__name__}
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        result["error_code"] = str(response.get("Error", {}).get("Code") or "Unknown")
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(status, int):
            result["http_status"] = status
    return result


class InventoryStageError(RuntimeError):
    """Attach a non-sensitive audit stage to a provider failure."""

    def __init__(self, stage: str, error: Exception) -> None:
        super().__init__(type(error).__name__)
        self.stage = stage
        self.error = error


def compare_regional_inventory(
    *,
    source_region: str,
    regions: tuple[str, ...],
    inventories: dict[str, dict[tuple[str, str], tuple[int, str]]],
) -> dict:
    """Compare exact ciphertext inventories while returning aggregate evidence only."""
    source = inventories[source_region]
    source_keys = set(source)
    region_reports: dict[str, dict[str, int]] = {}
    replicas_match = True
    for region in regions:
        inventory = inventories[region]
        keys = set(inventory)
        relations = [
            _inventory_relation(source[key], inventory[key])
            for key in source_keys & keys
        ]
        mismatched = relations.count("mismatched")
        fingerprint_unverified = relations.count("fingerprint_unverified")
        report = {
            "object_count": len(keys),
            "bytes": sum(size for size, _checksum in inventory.values()),
            "missing": len(source_keys - keys),
            "mismatched": mismatched,
            "fingerprint_unverified": fingerprint_unverified,
            "extra": len(keys - source_keys),
        }
        region_reports[region] = report
        if region != source_region and any(
            report[field]
            for field in ("missing", "mismatched", "fingerprint_unverified", "extra")
        ):
            replicas_match = False
    return {
        "source_region": source_region,
        "source_object_count": len(source),
        "source_bytes": sum(size for size, _checksum in source.values()),
        "regions": region_reports,
        "replicas_match": replicas_match,
        "object_keys_in_output": False,
    }


def _inventory_relation(source: tuple[int, str], replica: tuple[int, str]) -> str:
    """Classify comparable checksums without treating ETags as SHA-256."""
    source_size, source_fingerprint = source
    replica_size, replica_fingerprint = replica
    if source_size != replica_size:
        return "mismatched"
    if source_fingerprint == replica_fingerprint:
        return "matched"
    if source_fingerprint.startswith("sha256:") and replica_fingerprint.startswith("sha256:"):
        return "mismatched"
    return "fingerprint_unverified"


def compare_authoritative_regional_inventory(
    *,
    source_region: str,
    regions: tuple[str, ...],
    references: set[tuple[str, str]],
    ambiguous_reference_count: int,
    inventories: dict[str, dict[tuple[str, str], tuple[int, str]]],
) -> dict:
    """Compare only live references and classify source-only objects separately."""
    source = inventories[source_region]
    source_keys = set(source)
    repairable_references = references & source_keys
    reports: dict[str, dict[str, int]] = {}
    replicas_match = not (references - source_keys) and ambiguous_reference_count == 0
    for region in regions:
        inventory = inventories[region]
        present = repairable_references & set(inventory)
        relations = [_inventory_relation(source[key], inventory[key]) for key in present]
        report = {
            "authoritative_present": len(present),
            "missing": len(repairable_references - set(inventory)),
            "mismatched": relations.count("mismatched"),
            "fingerprint_unverified": relations.count("fingerprint_unverified"),
        }
        reports[region] = report
        if region != source_region and any(
            report[field] for field in ("missing", "mismatched", "fingerprint_unverified")
        ):
            replicas_match = False
    return {
        "source_region": source_region,
        "source_object_count": len(source_keys),
        "source_objects_without_references": len(source_keys - references),
        "authoritative_reference_count": len(references),
        "references_without_source_objects": len(references - source_keys),
        "ambiguous_reference_count": ambiguous_reference_count,
        "regions": reports,
        "authoritative_replicas_match": replicas_match,
        "object_keys_in_output": False,
        "mutations_performed": False,
    }


def _normalise_sha256(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    checksum = value.removeprefix("sha256:").lower()
    if len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum):
        return None
    return checksum


def _inventory_object_fingerprint(*, client: object, bucket: str, item: dict[str, object]) -> str:
    head = client.head_object(Bucket=bucket, Key=str(item["Key"]))
    return _inventory_head_fingerprint(head=head, fallback_etag=item.get("ETag"))


def _inventory_head_fingerprint(*, head: dict[str, object], fallback_etag: object = None) -> str:
    """Return SHA metadata when available, otherwise a provider ETag."""
    metadata_checksum = _normalise_sha256((head.get("Metadata") or {}).get(SHA256_METADATA_KEY))
    if metadata_checksum:
        return f"sha256:{metadata_checksum}"
    etag = str(head.get("ETag") or fallback_etag or "").strip('"')
    if etag:
        return f"etag:{etag}"
    raise RuntimeError("Provider inventory fingerprint unavailable")


def _stream_object_sha256(body: object) -> str:
    digest = hashlib.sha256()
    try:
        while chunk := body.read(1024 * 1024):
            digest.update(chunk)
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            close()
    return f"sha256:{digest.hexdigest()}"


def _scan_region_inventory(
    *,
    client: object,
    region: str,
    environment: str,
) -> dict[tuple[str, str], tuple[int, str]]:
    return {
        (logical_bucket, object_key): (size, checksum)
        for logical_bucket, object_key, size, checksum in _iter_region_inventory(
            client=client,
            region=region,
            environment=environment,
        )
    }


def _build_maintenance_region_clients(
    *,
    access_key: str,
    secret_key: str,
    regions: tuple[str, ...],
) -> dict[str, object]:
    """Build S3 clients for long-running maintenance scans."""
    import boto3
    from botocore.config import Config

    config = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path"},
        connect_timeout=10,
        read_timeout=MAINTENANCE_S3_READ_TIMEOUT_SECONDS,
        retries={"max_attempts": MAINTENANCE_S3_MAX_ATTEMPTS, "mode": "standard"},
    )
    return {
        region: boto3.client(
            "s3",
            endpoint_url=endpoint_for_region(region),
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
        )
        for region in regions
    }


def _iter_region_inventory(
    *,
    client: object,
    region: str,
    environment: str,
):
    """Yield one streamed ciphertext inventory row at a time."""
    for logical_bucket, bucket, item in _iter_managed_bucket_items(
        client=client,
        region=region,
        environment=environment,
    ):
        yield (
            logical_bucket,
            str(item["Key"]),
            int(item.get("Size", 0)),
            _inventory_object_fingerprint(client=client, bucket=bucket, item=item),
        )


def _iter_managed_bucket_items(
    *,
    client: object,
    region: str,
    environment: str,
):
    """Yield provider list rows for every managed replicated logical bucket."""
    for logical_bucket, config in BUCKETS.items():
        if not config.get("managed", True) or not should_replicate_bucket(logical_bucket):
            continue
        legacy_bucket = get_bucket_name(logical_bucket, environment)
        bucket = resolve_regional_bucket_name(legacy_bucket, region)
        continuation_token: str | None = None
        while True:
            request: dict[str, object] = {"Bucket": bucket, "MaxKeys": INVENTORY_LIST_MAX_KEYS}
            if continuation_token:
                request["ContinuationToken"] = continuation_token
            page = _list_objects_v2_page(client=client, request=request)
            for item in page.get("Contents") or []:
                yield logical_bucket, bucket, item
            continuation_token = page.get("NextContinuationToken")
            if not continuation_token:
                break


def _list_objects_v2_page(*, client: object, request: dict[str, object]) -> dict[str, object]:
    transient_codes = {"500", "502", "503", "504", "RequestTimeout"}
    transient_classes = {"ReadTimeoutError", "EndpointConnectionError"}
    for attempt in range(INVENTORY_LIST_RETRY_ATTEMPTS):
        try:
            return client.list_objects_v2(**request)
        except Exception as error:
            evidence = sanitized_provider_error(error)
            if (
                str(evidence.get("error_code")) not in transient_codes
                and str(evidence.get("error_class")) not in transient_classes
            ) or attempt + 1 >= INVENTORY_LIST_RETRY_ATTEMPTS:
                raise
            time.sleep(INVENTORY_LIST_RETRY_DELAY_SECONDS * (attempt + 1))
    raise RuntimeError("Provider inventory page unavailable")


def _create_inventory_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.execute(
        "CREATE TABLE objects (region TEXT, logical_bucket TEXT, object_key TEXT, size_bytes INTEGER, checksum TEXT, PRIMARY KEY(region, logical_bucket, object_key))"
    )
    connection.execute(
        "CREATE TABLE refs (logical_bucket TEXT, object_key TEXT, PRIMARY KEY(logical_bucket, object_key))"
    )
    connection.execute(
        "CREATE TABLE verified_jobs (logical_bucket TEXT, object_key TEXT, region TEXT, checksum TEXT, PRIMARY KEY(logical_bucket, object_key, region))"
    )
    return connection


def _populate_region_database(
    connection: sqlite3.Connection,
    *,
    client: object,
    region: str,
    environment: str,
) -> None:
    for row in _iter_region_inventory(client=client, region=region, environment=environment):
        connection.execute(
            "INSERT OR REPLACE INTO objects(region, logical_bucket, object_key, size_bytes, checksum) VALUES (?, ?, ?, ?, ?)",
            (region, *row),
        )
    connection.commit()


def _populate_authoritative_source_database(
    connection: sqlite3.Connection,
    *,
    client: object,
    region: str,
    environment: str,
) -> None:
    """List all source objects but HEAD only those with live references."""
    references = {
        (str(logical_bucket), str(object_key))
        for logical_bucket, object_key in connection.execute(
            "SELECT logical_bucket, object_key FROM refs"
        )
    }
    for logical_bucket, bucket, item in _iter_managed_bucket_items(
        client=client,
        region=region,
        environment=environment,
    ):
        object_key = str(item["Key"])
        checksum = "unreferenced"
        if (logical_bucket, object_key) in references:
            checksum = _inventory_object_fingerprint(client=client, bucket=bucket, item=item)
        connection.execute(
            "INSERT OR REPLACE INTO objects(region, logical_bucket, object_key, size_bytes, checksum) VALUES (?, ?, ?, ?, ?)",
            (region, logical_bucket, object_key, int(item.get("Size", 0)), checksum),
        )
    connection.commit()


def _populate_authoritative_replica_database(
    connection: sqlite3.Connection,
    *,
    client: object,
    source_region: str,
    region: str,
    environment: str,
) -> None:
    """HEAD only live references that exist in the authoritative source."""
    source_references = connection.execute(
        "SELECT f.logical_bucket, f.object_key FROM refs f JOIN objects s ON s.region = ? AND s.logical_bucket = f.logical_bucket AND s.object_key = f.object_key",
        (source_region,),
    ).fetchall()
    for logical_bucket, object_key in source_references:
        legacy_bucket = get_bucket_name(str(logical_bucket), environment)
        bucket = resolve_regional_bucket_name(legacy_bucket, region)
        try:
            head = client.head_object(Bucket=bucket, Key=str(object_key))
        except Exception as error:
            response = getattr(error, "response", None)
            code = response.get("Error", {}).get("Code") if isinstance(response, dict) else None
            if str(code) in {"404", "NoSuchKey", "NotFound"}:
                continue
            raise
        connection.execute(
            "INSERT OR REPLACE INTO objects(region, logical_bucket, object_key, size_bytes, checksum) VALUES (?, ?, ?, ?, ?)",
            (
                region,
                str(logical_bucket),
                str(object_key),
                int(head.get("ContentLength", 0)),
                _inventory_head_fingerprint(head=head),
            ),
        )
    connection.commit()


def _compare_inventory_database(
    connection: sqlite3.Connection,
    *,
    source_region: str,
    regions: tuple[str, ...],
) -> dict:
    source_count, source_bytes = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM objects WHERE region = ?",
        (source_region,),
    ).fetchone()
    reports: dict[str, dict[str, int]] = {}
    replicas_match = True
    for region in regions:
        count, size_bytes = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM objects WHERE region = ?",
            (region,),
        ).fetchone()
        missing = connection.execute(
            "SELECT COUNT(*) FROM objects s LEFT JOIN objects r ON r.region = ? AND r.logical_bucket = s.logical_bucket AND r.object_key = s.object_key WHERE s.region = ? AND r.object_key IS NULL",
            (region, source_region),
        ).fetchone()[0]
        mismatched = connection.execute(
            "SELECT COUNT(*) FROM objects s JOIN objects r ON r.region = ? AND r.logical_bucket = s.logical_bucket AND r.object_key = s.object_key WHERE s.region = ? AND (r.size_bytes != s.size_bytes OR (s.checksum LIKE 'sha256:%' AND r.checksum LIKE 'sha256:%' AND r.checksum != s.checksum))",
            (region, source_region),
        ).fetchone()[0]
        fingerprint_unverified = connection.execute(
            "SELECT COUNT(*) FROM objects s JOIN objects r ON r.region = ? AND r.logical_bucket = s.logical_bucket AND r.object_key = s.object_key WHERE s.region = ? AND r.size_bytes = s.size_bytes AND r.checksum != s.checksum AND NOT (s.checksum LIKE 'sha256:%' AND r.checksum LIKE 'sha256:%')",
            (region, source_region),
        ).fetchone()[0]
        extra = connection.execute(
            "SELECT COUNT(*) FROM objects r LEFT JOIN objects s ON s.region = ? AND s.logical_bucket = r.logical_bucket AND s.object_key = r.object_key WHERE r.region = ? AND s.object_key IS NULL",
            (source_region, region),
        ).fetchone()[0]
        reports[region] = {
            "object_count": int(count),
            "bytes": int(size_bytes),
            "missing": int(missing),
            "mismatched": int(mismatched),
            "fingerprint_unverified": int(fingerprint_unverified),
            "extra": int(extra),
        }
        if region != source_region and any((missing, mismatched, fingerprint_unverified, extra)):
            replicas_match = False
    return {
        "source_region": source_region,
        "source_object_count": int(source_count),
        "source_bytes": int(source_bytes),
        "regions": reports,
        "replicas_match": replicas_match,
        "object_keys_in_output": False,
    }


async def _populate_reference_database(connection: sqlite3.Connection, directus_service: object) -> int:
    """Load authoritative references into SQLite and return ambiguity count."""
    from backend.core.api.app.services.storage_reference_service import (
        iter_authoritative_storage_reference_pages,
    )

    ambiguous_count = 0
    async for authority in iter_authoritative_storage_reference_pages(
        directus_service=directus_service,
        encryption_service=directus_service.encryption_service,
    ):
        ambiguous_count += len(authority.ambiguous)
        connection.executemany(
            "INSERT OR IGNORE INTO refs(logical_bucket, object_key) VALUES (?, ?)",
            authority.references,
        )
    connection.commit()
    return ambiguous_count


async def _populate_verified_job_database(connection: sqlite3.Connection, directus_service: object) -> None:
    """Load only checksum-verified regional job evidence in bounded pages."""
    latest = await directus_service.get_items(
        "storage_replication_jobs",
        params={"fields": "created_at", "sort": "-created_at", "limit": 1},
        no_cache=True,
        admin_required=True,
        raise_on_error=True,
    ) or []
    if not latest:
        return
    snapshot_created_at = latest[0].get("created_at")
    if not snapshot_created_at:
        raise RuntimeError("Verified regional storage job snapshot has no timestamp")
    offset = 0
    while True:
        rows = await directus_service.get_items(
            "storage_replication_jobs",
            params={
                "filter": {"created_at": {"_lte": snapshot_created_at}},
                "fields": "id,logical_bucket,object_key,checksum,state,region_states,created_at",
                "sort": "created_at,id",
                "limit": DIRECTUS_AUDIT_PAGE_SIZE,
                "offset": offset,
            },
            no_cache=True,
            admin_required=True,
            raise_on_error=True,
        ) or []
        for row in rows:
            if row.get("state") != "verified":
                continue
            checksum = _normalise_sha256(row.get("checksum"))
            if not checksum:
                continue
            for region, state in dict(row.get("region_states") or {}).items():
                if state != "verified":
                    continue
                connection.execute(
                    "INSERT OR REPLACE INTO verified_jobs(logical_bucket, object_key, region, checksum) VALUES (?, ?, ?, ?)",
                    (
                        str(row.get("logical_bucket")),
                        str(row.get("object_key")),
                        str(region),
                        f"sha256:{checksum}",
                    ),
                )
        if len(rows) < DIRECTUS_AUDIT_PAGE_SIZE:
            break
        offset += len(rows)
    connection.commit()


def _compare_authoritative_inventory_database(
    connection: sqlite3.Connection,
    *,
    source_region: str,
    regions: tuple[str, ...],
    ambiguous_reference_count: int,
) -> dict:
    """Compare physical inventory only where current Directus references exist."""
    source_count = connection.execute(
        "SELECT COUNT(*) FROM objects WHERE region = ?", (source_region,)
    ).fetchone()[0]
    reference_count = connection.execute("SELECT COUNT(*) FROM refs").fetchone()[0]
    source_orphans = connection.execute(
        "SELECT COUNT(*) FROM objects o LEFT JOIN refs r ON r.logical_bucket = o.logical_bucket AND r.object_key = o.object_key WHERE o.region = ? AND r.object_key IS NULL",
        (source_region,),
    ).fetchone()[0]
    references_without_source = connection.execute(
        "SELECT COUNT(*) FROM refs r LEFT JOIN objects s ON s.region = ? AND s.logical_bucket = r.logical_bucket AND s.object_key = r.object_key WHERE s.object_key IS NULL",
        (source_region,),
    ).fetchone()[0]
    source_orphans_by_bucket = dict(connection.execute(
        "SELECT o.logical_bucket, COUNT(*) FROM objects o LEFT JOIN refs r ON r.logical_bucket = o.logical_bucket AND r.object_key = o.object_key WHERE o.region = ? AND r.object_key IS NULL GROUP BY o.logical_bucket ORDER BY o.logical_bucket",
        (source_region,),
    ).fetchall())
    references_without_source_by_bucket = dict(connection.execute(
        "SELECT r.logical_bucket, COUNT(*) FROM refs r LEFT JOIN objects s ON s.region = ? AND s.logical_bucket = r.logical_bucket AND s.object_key = r.object_key WHERE s.object_key IS NULL GROUP BY r.logical_bucket ORDER BY r.logical_bucket",
        (source_region,),
    ).fetchall())
    reports: dict[str, dict[str, int]] = {}
    replicas_match = references_without_source == 0 and ambiguous_reference_count == 0
    for region in regions:
        present = connection.execute(
            "SELECT COUNT(*) FROM refs f JOIN objects s ON s.region = ? AND s.logical_bucket = f.logical_bucket AND s.object_key = f.object_key JOIN objects r ON r.region = ? AND r.logical_bucket = f.logical_bucket AND r.object_key = f.object_key",
            (source_region, region),
        ).fetchone()[0]
        missing = connection.execute(
            "SELECT COUNT(*) FROM refs f JOIN objects s ON s.region = ? AND s.logical_bucket = f.logical_bucket AND s.object_key = f.object_key LEFT JOIN objects r ON r.region = ? AND r.logical_bucket = f.logical_bucket AND r.object_key = f.object_key WHERE r.object_key IS NULL",
            (source_region, region),
        ).fetchone()[0]
        mismatched = connection.execute(
            "SELECT COUNT(*) FROM refs f JOIN objects s ON s.region = ? AND s.logical_bucket = f.logical_bucket AND s.object_key = f.object_key JOIN objects r ON r.region = ? AND r.logical_bucket = f.logical_bucket AND r.object_key = f.object_key WHERE r.size_bytes != s.size_bytes OR (s.checksum LIKE 'sha256:%' AND r.checksum LIKE 'sha256:%' AND r.checksum != s.checksum)",
            (source_region, region),
        ).fetchone()[0]
        durably_verified = connection.execute(
            "SELECT COUNT(*) FROM refs f JOIN objects s ON s.region = ? AND s.logical_bucket = f.logical_bucket AND s.object_key = f.object_key JOIN objects r ON r.region = ? AND r.logical_bucket = f.logical_bucket AND r.object_key = f.object_key JOIN verified_jobs v ON v.logical_bucket = f.logical_bucket AND v.object_key = f.object_key AND v.region = ? AND v.checksum = r.checksum WHERE r.size_bytes = s.size_bytes AND r.checksum != s.checksum AND NOT (s.checksum LIKE 'sha256:%' AND r.checksum LIKE 'sha256:%')",
            (source_region, region, region),
        ).fetchone()[0]
        fingerprint_unverified = connection.execute(
            "SELECT COUNT(*) FROM refs f JOIN objects s ON s.region = ? AND s.logical_bucket = f.logical_bucket AND s.object_key = f.object_key JOIN objects r ON r.region = ? AND r.logical_bucket = f.logical_bucket AND r.object_key = f.object_key LEFT JOIN verified_jobs v ON v.logical_bucket = f.logical_bucket AND v.object_key = f.object_key AND v.region = ? AND v.checksum = r.checksum WHERE r.size_bytes = s.size_bytes AND r.checksum != s.checksum AND NOT (s.checksum LIKE 'sha256:%' AND r.checksum LIKE 'sha256:%') AND v.object_key IS NULL",
            (source_region, region, region),
        ).fetchone()[0]
        reports[region] = {
            "authoritative_present": int(present),
            "missing": int(missing),
            "mismatched": int(mismatched),
            "durably_verified": int(durably_verified),
            "fingerprint_unverified": int(fingerprint_unverified),
        }
        if region != source_region and any((missing, mismatched, fingerprint_unverified)):
            replicas_match = False
    return {
        "source_region": source_region,
        "source_object_count": int(source_count),
        "source_objects_without_references": int(source_orphans),
        "source_objects_without_references_by_logical_bucket": source_orphans_by_bucket,
        "authoritative_reference_count": int(reference_count),
        "references_without_source_objects": int(references_without_source),
        "references_without_source_objects_by_logical_bucket": references_without_source_by_bucket,
        "ambiguous_reference_count": int(ambiguous_reference_count),
        "regions": reports,
        "authoritative_replicas_match": replicas_match,
        "object_keys_in_output": False,
        "mutations_performed": False,
    }


def _verify_unresolved_authoritative_bytes(
    connection: sqlite3.Connection,
    *,
    clients: dict[str, object],
    source_region: str,
    regions: tuple[str, ...],
    environment: str,
) -> dict[str, int]:
    """Read a capped set of unresolved authoritative pairs and compare SHA-256."""
    candidates: list[tuple[str, str, str]] = []
    for region in regions:
        if region == source_region:
            continue
        rows = connection.execute(
            "SELECT f.logical_bucket, f.object_key FROM refs f JOIN objects s ON s.region = ? AND s.logical_bucket = f.logical_bucket AND s.object_key = f.object_key JOIN objects r ON r.region = ? AND r.logical_bucket = f.logical_bucket AND r.object_key = f.object_key LEFT JOIN verified_jobs v ON v.logical_bucket = f.logical_bucket AND v.object_key = f.object_key AND v.region = ? AND v.checksum = r.checksum WHERE r.size_bytes = s.size_bytes AND r.checksum != s.checksum AND NOT (s.checksum LIKE 'sha256:%' AND r.checksum LIKE 'sha256:%') AND v.object_key IS NULL ORDER BY f.logical_bucket, f.object_key LIMIT ?",
            (source_region, region, region, MAX_UNRESOLVED_BYTE_CHECKS + 1),
        ).fetchall()
        candidates.extend((str(logical_bucket), str(object_key), region) for logical_bucket, object_key in rows)
    if len(candidates) > MAX_UNRESOLVED_BYTE_CHECKS:
        return {"byte_verified_pair_count": 0, "byte_verification_deferred_count": len(candidates)}

    source_checksums: dict[tuple[str, str], str] = {}
    for logical_bucket, object_key, region in candidates:
        identity = (logical_bucket, object_key)
        legacy_bucket = get_bucket_name(logical_bucket, environment)
        if identity not in source_checksums:
            source_bucket = resolve_regional_bucket_name(legacy_bucket, source_region)
            source = clients[source_region].get_object(Bucket=source_bucket, Key=object_key)
            source_checksums[identity] = _stream_object_sha256(source["Body"])
            connection.execute(
                "UPDATE objects SET checksum = ? WHERE region = ? AND logical_bucket = ? AND object_key = ?",
                (source_checksums[identity], source_region, logical_bucket, object_key),
            )
        replica_bucket = resolve_regional_bucket_name(legacy_bucket, region)
        replica = clients[region].get_object(Bucket=replica_bucket, Key=object_key)
        replica_checksum = _stream_object_sha256(replica["Body"])
        connection.execute(
            "UPDATE objects SET checksum = ? WHERE region = ? AND logical_bucket = ? AND object_key = ?",
            (replica_checksum, region, logical_bucket, object_key),
        )
    connection.commit()
    return {
        "byte_verified_pair_count": len(candidates),
        "byte_verification_deferred_count": 0,
    }


async def verify_replica_inventory(
    *,
    environment: str,
    regions: tuple[str, ...],
    source_region: str,
    authoritative_only: bool = False,
) -> dict:
    """Read every replicated ciphertext once and compare exact regional bytes."""
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets = SecretsManager()
    await secrets.initialize()
    try:
        access_key = await secrets.get_secret("kv/data/providers/hetzner", "s3_access_key")
        secret_key = await secrets.get_secret("kv/data/providers/hetzner", "s3_secret_key")
        if not access_key or not secret_key:
            raise RuntimeError("Object-storage credentials are unavailable")
        clients = _build_maintenance_region_clients(
            access_key=access_key,
            secret_key=secret_key,
            regions=regions,
        )
        with tempfile.TemporaryDirectory(prefix="openmates-regional-inventory-") as temporary:
            connection = _create_inventory_database(Path(temporary) / "inventory.sqlite3")
            directus = None
            try:
                if not authoritative_only:
                    for region in regions:
                        await asyncio.to_thread(
                            _populate_region_database,
                            connection,
                            client=clients[region],
                            region=region,
                            environment=environment,
                        )
                    return _compare_inventory_database(
                        connection,
                        source_region=source_region,
                        regions=regions,
                    )
                from backend.core.api.app.services.directus import DirectusService

                directus = DirectusService()
                try:
                    ambiguous_count = await _populate_reference_database(connection, directus)
                    await _populate_verified_job_database(connection, directus)
                except Exception as error:
                    raise InventoryStageError("authoritative_references", error) from error
                try:
                    await asyncio.to_thread(
                        _populate_authoritative_source_database,
                        connection,
                        client=clients[source_region],
                        region=source_region,
                        environment=environment,
                    )
                except Exception as error:
                    raise InventoryStageError("source_inventory", error) from error
                for region in regions:
                    if region == source_region:
                        continue
                    try:
                        await asyncio.to_thread(
                            _populate_authoritative_replica_database,
                            connection,
                            client=clients[region],
                            source_region=source_region,
                            region=region,
                            environment=environment,
                        )
                    except Exception as error:
                        raise InventoryStageError(f"replica_inventory:{region}", error) from error
                try:
                    byte_report = await asyncio.to_thread(
                        _verify_unresolved_authoritative_bytes,
                        connection,
                        clients=clients,
                        source_region=source_region,
                        regions=regions,
                        environment=environment,
                    )
                except Exception as error:
                    raise InventoryStageError("unresolved_byte_verification", error) from error
                report = _compare_authoritative_inventory_database(
                    connection,
                    source_region=source_region,
                    regions=regions,
                    ambiguous_reference_count=ambiguous_count,
                )
                report.update(byte_report)
                return report
            finally:
                if directus is not None:
                    await directus.close()
                connection.close()
    finally:
        await secrets.aclose()


async def schedule_recovered_source_backfill(
    *,
    environment: str,
    regions: tuple[str, ...],
    source_region: str,
) -> dict:
    """Schedule idempotent repairs only for currently authoritative references."""
    from datetime import datetime, timezone

    from backend.core.api.app.services.directus import DirectusService
    from backend.core.api.app.services.s3.recovery_backfill import (
        backfill_recovered_page,
        persist_region_reconciliation_state,
    )
    from backend.core.api.app.services.storage_reference_service import (
        iter_authoritative_storage_reference_pages,
    )
    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets = SecretsManager()
    await secrets.initialize()
    directus = DirectusService()
    try:
        access_key = await secrets.get_secret("kv/data/providers/hetzner", "s3_access_key")
        secret_key = await secrets.get_secret("kv/data/providers/hetzner", "s3_secret_key")
        if not access_key or not secret_key:
            raise RuntimeError("Object-storage credentials are unavailable")
        s3_clients = _build_maintenance_region_clients(
            access_key=access_key,
            secret_key=secret_key,
            regions=regions,
        )
        with tempfile.TemporaryDirectory(prefix="openmates-recovery-backfill-") as temporary:
            connection = _create_inventory_database(Path(temporary) / "backfill.sqlite3")
            try:
                await asyncio.to_thread(
                    _populate_region_database,
                    connection,
                    client=s3_clients[source_region],
                    region=source_region,
                    environment=environment,
                )
                totals = {
                    "processed": 0,
                    "scheduled": 0,
                    "skipped_tombstoned": 0,
                    "skipped_unavailable_source": 0,
                    "skipped_source_checksum_mismatch": 0,
                    "skipped_newer_authority": 0,
                }
                reference_count = 0
                missing_count = 0
                ambiguous_count = 0
                async for authority in iter_authoritative_storage_reference_pages(
                    directus_service=directus,
                    encryption_service=directus.encryption_service,
                ):
                    ambiguous_count += len(authority.ambiguous)
                    page: list[dict[str, object]] = []
                    for logical_bucket, object_key in authority.references:
                        connection.execute(
                            "INSERT OR IGNORE INTO refs(logical_bucket, object_key) VALUES (?, ?)",
                            (logical_bucket, object_key),
                        )
                        reference_count += 1
                        source = connection.execute(
                            "SELECT checksum FROM objects WHERE region = ? AND logical_bucket = ? AND object_key = ?",
                            (source_region, logical_bucket, object_key),
                        ).fetchone()
                        if source is None:
                            missing_count += 1
                            continue
                        page.append({
                            "logical_bucket": logical_bucket,
                            "object_key": object_key,
                            "generation": 1,
                            "checksum": source[0],
                        })
                    connection.commit()
                    for offset in range(0, len(page), 100):
                        result = await backfill_recovered_page(
                            references=page[offset:offset + 100],
                            source_region=source_region,
                            configured_regions=regions,
                            s3_clients=s3_clients,
                            directus_service=directus,
                            environment=environment,
                            now=datetime.now(timezone.utc),
                            next_cursor="more" if offset + 100 < len(page) else None,
                        )
                        for field in totals:
                            totals[field] += int(result[field])
                source_count = connection.execute(
                    "SELECT COUNT(*) FROM objects WHERE region = ?", (source_region,)
                ).fetchone()[0]
                orphan_count = connection.execute(
                    "SELECT COUNT(*) FROM objects o LEFT JOIN refs r ON r.logical_bucket = o.logical_bucket AND r.object_key = o.object_key WHERE o.region = ? AND r.object_key IS NULL",
                    (source_region,),
                ).fetchone()[0]
                backfill_complete = (
                    missing_count == 0
                    and ambiguous_count == 0
                    and totals["skipped_unavailable_source"] == 0
                    and totals["skipped_source_checksum_mismatch"] == 0
                )
                failback_ready = await persist_region_reconciliation_state(
                    directus_service=directus,
                    region=source_region,
                    historical_backfill_complete=backfill_complete,
                    now=datetime.now(timezone.utc),
                )
                return {
                    "status": "scheduled",
                    "source_region": source_region,
                    "source_object_count": int(source_count),
                    "authoritative_reference_count": reference_count,
                    "references_without_objects": missing_count,
                    "objects_without_references": int(orphan_count),
                    "ambiguous_references": ambiguous_count,
                    "historical_backfill_complete": backfill_complete,
                    "failback_ready": failback_ready,
                    **totals,
                    "object_keys_in_output": False,
                }
            finally:
                connection.close()
    finally:
        await directus.close()
        await secrets.aclose()


def build_dry_run_report(environment: str, regions: tuple[str, ...]) -> dict:
    """Return aggregate policy counts without object names or network access."""
    name_field = "dev_name" if environment == "dev" else "name"
    physical_buckets = {
        resolve_regional_bucket_name(config[name_field], region)
        for config in BUCKETS.values()
        for region in regions
    }
    return {
        "status": "dry_run",
        "environment": environment,
        "regions": list(regions),
        "logical_bucket_count": len(BUCKETS),
        "planned_physical_bucket_count": len(physical_buckets),
        "reference_sources": ["embeds.s3_file_keys", "upload_files.files_metadata"],
        "live_classification": "not_run_in_configuration_dry_run",
        "object_keys_in_output": False,
        "mutations_performed": False,
    }


def classify_inventory(
    *,
    references: set[tuple[str, str]],
    objects: list[dict[str, object]],
    ambiguous_reference_count: int,
) -> dict[str, int | bool]:
    """Classify bounded reference/object fixtures and emit aggregate data only."""
    object_keys = {
        (str(item["logical_bucket"]), str(item["object_key"]))
        for item in objects
    }
    total_bytes = sum(int(item.get("size_bytes", 0)) for item in objects)
    return {
        "reference_count": len(references),
        "object_count": len(object_keys),
        "object_bytes": total_bytes,
        "references_without_objects": len(references - object_keys),
        "objects_without_references": len(object_keys - references),
        "ambiguous_references": ambiguous_reference_count,
        "object_keys_in_output": False,
        "mutations_performed": False,
    }


def probe_managed_bucket(client: object, bucket: str, object_key: str) -> None:
    """Verify required data-plane operations and always remove the probe object."""
    written = False
    try:
        client.head_bucket(Bucket=bucket)
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=b"",
            Metadata={SHA256_METADATA_KEY: EMPTY_SHA256},
        )
        written = True
        response = client.head_object(Bucket=bucket, Key=object_key)
        if int(response.get("ContentLength", -1)) != 0:
            raise RuntimeError("Capability probe object size mismatch")
    finally:
        if written:
            client.delete_object(Bucket=bucket, Key=object_key)


async def probe_region_capabilities(
    environment: str,
    regions: tuple[str, ...],
) -> list[dict[str, object]]:
    """Probe read/write/delete against one existing managed bucket per region."""
    import boto3
    from botocore.config import Config

    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets = SecretsManager()
    await secrets.initialize()
    try:
        access_key = await secrets.get_secret("kv/data/providers/hetzner", "s3_access_key")
        secret_key = await secrets.get_secret("kv/data/providers/hetzner", "s3_secret_key")
        if not access_key or not secret_key:
            raise RuntimeError("Object-storage credentials are unavailable")

        results = []
        probe_suffix = uuid.uuid4().hex
        for region in regions:
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_for_region(region),
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
            bucket_name = resolve_regional_bucket_name(
                get_bucket_name("chatfiles", environment),
                region,
            )
            object_key = f".openmates-region-probe/{probe_suffix}"
            try:
                await asyncio.to_thread(
                    probe_managed_bucket,
                    client,
                    bucket_name,
                    object_key,
                )
                results.append({"region": region, "status": "passed"})
            except Exception as exc:
                results.append({"region": region, "status": "failed", **sanitized_provider_error(exc)})
        return results
    finally:
        await secrets.aclose()


async def provision_regional_buckets(
    *,
    environment: str,
    regions: tuple[str, ...],
) -> dict:
    """Create and verify only missing managed replicated physical buckets."""
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    from backend.core.api.app.utils.secrets_manager import SecretsManager

    secrets = SecretsManager()
    await secrets.initialize()
    try:
        access_key = await secrets.get_secret("kv/data/providers/hetzner", "s3_access_key")
        secret_key = await secrets.get_secret("kv/data/providers/hetzner", "s3_secret_key")
        if not access_key or not secret_key:
            raise RuntimeError("Object-storage credentials are unavailable")
        config = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=20,
            retries={"max_attempts": 2},
        )
        reports: dict[str, dict[str, object]] = {}
        for region in regions:
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_for_region(region),
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=config,
            )
            physical_buckets = {
                resolve_regional_bucket_name(get_bucket_name(logical_bucket, environment), region)
                for logical_bucket, bucket_config in BUCKETS.items()
                if bucket_config.get("managed", True) and should_replicate_bucket(logical_bucket)
            }
            report: dict[str, object] = {
                "planned": len(physical_buckets),
                "existing": 0,
                "created": 0,
                "failed": 0,
                "errors": {},
            }
            errors: dict[str, int] = {}
            for bucket in sorted(physical_buckets):
                try:
                    await asyncio.to_thread(client.head_bucket, Bucket=bucket)
                    report["existing"] = int(report["existing"]) + 1
                    continue
                except ClientError as error:
                    code = str(error.response.get("Error", {}).get("Code") or "Unknown")
                    status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
                    if code not in MISSING_BUCKET_CODES and status != 404:
                        report["failed"] = int(report["failed"]) + 1
                        error_key = f"{code}:{status if isinstance(status, int) else 'unknown'}"
                        errors[error_key] = errors.get(error_key, 0) + 1
                        continue
                try:
                    await asyncio.to_thread(client.create_bucket, Bucket=bucket)
                    await asyncio.to_thread(client.head_bucket, Bucket=bucket)
                    report["created"] = int(report["created"]) + 1
                except Exception as error:
                    report["failed"] = int(report["failed"]) + 1
                    evidence = sanitized_provider_error(error)
                    error_key = f"{evidence.get('error_code', evidence['error_class'])}:{evidence.get('http_status', 'unknown')}"
                    errors[error_key] = errors.get(error_key, 0) + 1
            report["errors"] = errors
            reports[region] = report
        return {
            "status": "passed" if all(int(report["failed"]) == 0 for report in reports.values()) else "blocked",
            "regions": reports,
            "bucket_names_in_output": False,
            "object_keys_in_output": False,
        }
    finally:
        await secrets.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("dev", "prod"), required=True)
    parser.add_argument("--regions", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--probe-regions", action="store_true")
    parser.add_argument("--verify-replicas", action="store_true")
    parser.add_argument("--verify-authoritative-replicas", action="store_true")
    parser.add_argument("--backfill-recovered-source", action="store_true")
    parser.add_argument("--provision-regions", action="store_true")
    parser.add_argument("--source-region", default="nbg1")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--runtime", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    selected_modes = sum((
        args.dry_run,
        args.probe_regions,
        args.verify_replicas,
        args.verify_authoritative_replicas,
        args.backfill_recovered_source,
        args.provision_regions,
    ))
    if selected_modes != 1:
        parser.error(
            "Choose exactly one of --dry-run, --probe-regions, --verify-replicas, "
            "--verify-authoritative-replicas, "
            "--backfill-recovered-source, or --provision-regions"
        )

    if not args.dry_run and not args.runtime:
        completed = subprocess.run(
            runtime_inventory_command(sys.argv[1:]),
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=HOST_DELEGATION_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            if completed.stdout:
                print(completed.stdout.strip())
            else:
                print(
                    json.dumps(
                        build_runtime_delegation_failure(completed.returncode, completed.stderr),
                        indent=2,
                        sort_keys=True,
                    )
                    if args.json
                    else build_runtime_delegation_failure(completed.returncode, completed.stderr)
                )
            return completed.returncode
        print(completed.stdout.strip())
        return 0

    regions = parse_storage_regions(args.regions)
    environment = "development" if args.env == "dev" else "production"
    if args.dry_run:
        report = build_dry_run_report(args.env, regions)
    elif args.probe_regions:
        report = {
            "status": "capability_probe",
            "environment": args.env,
            "results": asyncio.run(probe_region_capabilities(environment, regions)),
            "object_keys_in_output": False,
        }
    elif args.verify_replicas or args.verify_authoritative_replicas:
        if args.source_region not in regions:
            parser.error("--source-region must be included in configured regions")
        try:
            report = asyncio.run(
                verify_replica_inventory(
                    environment=environment,
                    regions=regions,
                    source_region=args.source_region,
                    authoritative_only=args.verify_authoritative_replicas,
                )
            )
            match_field = "authoritative_replicas_match" if args.verify_authoritative_replicas else "replicas_match"
            report["status"] = "passed" if report[match_field] else "drift_detected"
        except Exception as exc:
            root_error = exc.error if isinstance(exc, InventoryStageError) else exc
            report = {
                "status": "blocked",
                **sanitized_provider_error(root_error),
                "object_keys_in_output": False,
            }
            if isinstance(exc, InventoryStageError):
                report["inventory_stage"] = exc.stage
    elif args.backfill_recovered_source:
        if args.source_region not in regions:
            parser.error("--source-region must be included in configured regions")
        try:
            report = asyncio.run(
                schedule_recovered_source_backfill(
                    environment=environment,
                    regions=regions,
                    source_region=args.source_region,
                )
            )
        except Exception as exc:
            report = {
                "status": "blocked",
                **sanitized_provider_error(exc),
                "object_keys_in_output": False,
            }
    else:
        try:
            report = asyncio.run(
                provision_regional_buckets(
                    environment=environment,
                    regions=regions,
                )
            )
        except Exception as exc:
            report = {
                "status": "blocked",
                **sanitized_provider_error(exc),
                "bucket_names_in_output": False,
                "object_keys_in_output": False,
            }

    print(json.dumps(report, indent=2, sort_keys=True) if args.json else report)
    return 0 if report.get("status") not in {"blocked", "drift_detected"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
