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
import sys
import uuid

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.core.api.app.services.s3.config import BUCKETS  # noqa: E402
from backend.shared.python_utils.object_storage_regions import (  # noqa: E402
    endpoint_for_region,
    parse_storage_regions,
    resolve_regional_bucket_name,
)


PROBE_BUCKET_PREFIX = "dev-openmates-region-probe"


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
                results.append({"region": region, "status": "failed", "error_class": type(exc).__name__})
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", choices=("dev", "prod"), required=True)
    parser.add_argument("--regions", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--probe-regions", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.dry_run == args.probe_regions:
        parser.error("Choose exactly one of --dry-run or --probe-regions")

    regions = parse_storage_regions(args.regions)
    if args.dry_run:
        report = build_dry_run_report(args.env, regions)
    else:
        report = {
            "status": "capability_probe",
            "environment": args.env,
            "results": asyncio.run(probe_region_capabilities(regions)),
            "object_keys_in_output": False,
        }

    print(json.dumps(report, indent=2, sort_keys=True) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
