#!/usr/bin/env python3
"""Audit logical and regional object-storage inventory without exposing keys.

Dry-run is deterministic and non-networked. Optional capability probes fetch
credentials from Vault inside the API runtime, create one temporary empty bucket
per configured region, verify access, and remove it in a finally block.
Object keys, credentials, and private metadata are never emitted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
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
MAINTENANCE_S3_READ_TIMEOUT_SECONDS = 90


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
        mismatched = sum(
            1
            for key in source_keys & keys
            if inventory[key] != source[key]
        )
        report = {
            "object_count": len(keys),
            "bytes": sum(size for size, _checksum in inventory.values()),
            "missing": len(source_keys - keys),
            "mismatched": mismatched,
            "extra": len(keys - source_keys),
        }
        region_reports[region] = report
        if region != source_region and any(report[field] for field in ("missing", "mismatched", "extra")):
            replicas_match = False
    return {
        "source_region": source_region,
        "source_object_count": len(source),
        "source_bytes": sum(size for size, _checksum in source.values()),
        "regions": region_reports,
        "replicas_match": replicas_match,
        "object_keys_in_output": False,
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
    metadata_checksum = _normalise_sha256((head.get("Metadata") or {}).get(SHA256_METADATA_KEY))
    if metadata_checksum:
        return f"sha256:{metadata_checksum}"
    etag = str(item.get("ETag") or "").strip('"')
    if etag:
        return f"etag:{etag}"
    raise RuntimeError("Provider inventory fingerprint unavailable")


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
        retries={"max_attempts": 2},
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
    for logical_bucket, config in BUCKETS.items():
        if not config.get("managed", True) or not should_replicate_bucket(logical_bucket):
            continue
        legacy_bucket = get_bucket_name(logical_bucket, environment)
        bucket = resolve_regional_bucket_name(legacy_bucket, region)
        continuation_token: str | None = None
        while True:
            request: dict[str, object] = {"Bucket": bucket, "MaxKeys": 1000}
            if continuation_token:
                request["ContinuationToken"] = continuation_token
            page = client.list_objects_v2(**request)
            for item in page.get("Contents") or []:
                object_key = str(item["Key"])
                yield (
                    logical_bucket,
                    object_key,
                    int(item.get("Size", 0)),
                    _inventory_object_fingerprint(client=client, bucket=bucket, item=item),
                )
            continuation_token = page.get("NextContinuationToken")
            if not continuation_token:
                break


def _create_inventory_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.execute(
        "CREATE TABLE objects (region TEXT, logical_bucket TEXT, object_key TEXT, size_bytes INTEGER, checksum TEXT, PRIMARY KEY(region, logical_bucket, object_key))"
    )
    connection.execute(
        "CREATE TABLE refs (logical_bucket TEXT, object_key TEXT, PRIMARY KEY(logical_bucket, object_key))"
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
            "SELECT COUNT(*) FROM objects s JOIN objects r ON r.region = ? AND r.logical_bucket = s.logical_bucket AND r.object_key = s.object_key WHERE s.region = ? AND (r.size_bytes != s.size_bytes OR r.checksum != s.checksum)",
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
            "extra": int(extra),
        }
        if region != source_region and any((missing, mismatched, extra)):
            replicas_match = False
    return {
        "source_region": source_region,
        "source_object_count": int(source_count),
        "source_bytes": int(source_bytes),
        "regions": reports,
        "replicas_match": replicas_match,
        "object_keys_in_output": False,
    }


async def verify_replica_inventory(
    *,
    environment: str,
    regions: tuple[str, ...],
    source_region: str,
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
            try:
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
            finally:
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


async def probe_region_capabilities(regions: tuple[str, ...]) -> list[dict[str, str]]:
    """Create, access, and remove one temporary empty bucket in each region."""
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
        probe_suffix = uuid.uuid4().hex[:12]
        for region in regions:
            client = boto3.client(
                "s3",
                endpoint_url=endpoint_for_region(region),
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
            bucket_name = f"{PROBE_BUCKET_PREFIX}-{region}-{probe_suffix}"
            created = False
            try:
                await asyncio.to_thread(client.create_bucket, Bucket=bucket_name)
                created = True
                await asyncio.to_thread(client.head_bucket, Bucket=bucket_name)
                results.append({"region": region, "status": "passed"})
            except Exception as exc:
                results.append({"region": region, "status": "failed", **sanitized_provider_error(exc)})
            finally:
                if created:
                    try:
                        await asyncio.to_thread(client.delete_bucket, Bucket=bucket_name)
                    except Exception as exc:
                        results.append({
                            "region": region,
                            "status": "cleanup_failed",
                            "error_class": type(exc).__name__,
                        })
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
    parser.add_argument("--backfill-recovered-source", action="store_true")
    parser.add_argument("--provision-regions", action="store_true")
    parser.add_argument("--source-region", default="nbg1")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    selected_modes = sum((
        args.dry_run,
        args.probe_regions,
        args.verify_replicas,
        args.backfill_recovered_source,
        args.provision_regions,
    ))
    if selected_modes != 1:
        parser.error(
            "Choose exactly one of --dry-run, --probe-regions, --verify-replicas, "
            "--backfill-recovered-source, or --provision-regions"
        )

    regions = parse_storage_regions(args.regions)
    if args.dry_run:
        report = build_dry_run_report(args.env, regions)
    elif args.probe_regions:
        report = {
            "status": "capability_probe",
            "environment": args.env,
            "results": asyncio.run(probe_region_capabilities(regions)),
            "object_keys_in_output": False,
        }
    elif args.verify_replicas:
        if args.source_region not in regions:
            parser.error("--source-region must be included in configured regions")
        environment = "development" if args.env == "dev" else "production"
        try:
            report = asyncio.run(
                verify_replica_inventory(
                    environment=environment,
                    regions=regions,
                    source_region=args.source_region,
                )
            )
            report["status"] = "passed" if report["replicas_match"] else "drift_detected"
        except Exception as exc:
            report = {
                "status": "blocked",
                "failure_class": type(exc).__name__,
                "object_keys_in_output": False,
            }
    elif args.backfill_recovered_source:
        if args.source_region not in regions:
            parser.error("--source-region must be included in configured regions")
        environment = "development" if args.env == "dev" else "production"
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
                "failure_class": type(exc).__name__,
                "object_keys_in_output": False,
            }
    else:
        environment = "development" if args.env == "dev" else "production"
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
