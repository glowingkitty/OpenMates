"""Shared Hetzner Object Storage region policy.

This module contains only deterministic configuration logic so API and upload
processes can share region and bucket naming without sharing credentials or
application service dependencies. Runtime health and failover live elsewhere.
See contracts/architecture/storage-lifecycle/contract.yml.
"""

from __future__ import annotations


SUPPORTED_STORAGE_REGIONS = ("nbg1", "fsn1", "hel1")
DEFAULT_STORAGE_REGIONS = SUPPORTED_STORAGE_REGIONS
LEGACY_BUCKET_REGION = "nbg1"
HETZNER_OBJECT_STORAGE_DOMAIN = "your-objectstorage.com"
REGION_MANAGED_MEDIA_BUCKETS = {"buffer_media"}
REGION_EXCLUDED_BUCKETS = {"product_media"}
NON_REPLICATED_BUCKETS = REGION_MANAGED_MEDIA_BUCKETS | REGION_EXCLUDED_BUCKETS


def parse_storage_regions(value: str | None) -> tuple[str, ...]:
    """Parse an ordered, non-empty, unique subset of supported regions."""
    if value is None:
        return DEFAULT_STORAGE_REGIONS

    regions = tuple(part.strip() for part in value.split(",") if part.strip())
    if not regions:
        raise ValueError("Storage region list cannot be empty")
    if len(set(regions)) != len(regions):
        raise ValueError("Storage region list cannot contain duplicates")

    unknown = tuple(region for region in regions if region not in SUPPORTED_STORAGE_REGIONS)
    if unknown:
        raise ValueError(f"Unsupported storage regions: {', '.join(unknown)}")
    return regions


def endpoint_for_region(region: str) -> str:
    """Return the Hetzner endpoint for one supported region."""
    if region not in SUPPORTED_STORAGE_REGIONS:
        raise ValueError(f"Unsupported storage region: {region}")
    return f"https://{region}.{HETZNER_OBJECT_STORAGE_DOMAIN}"


def resolve_regional_bucket_name(legacy_bucket_name: str, region: str) -> str:
    """Keep existing NBG names and derive globally unique replica names."""
    if region not in SUPPORTED_STORAGE_REGIONS:
        raise ValueError(f"Unsupported storage region: {region}")
    if region == LEGACY_BUCKET_REGION:
        return legacy_bucket_name
    return f"{legacy_bucket_name}-{region}"


def select_temporary_upload_region(
    *,
    configured_regions: tuple[str, ...],
    healthy_regions: set[str],
    preferred_region: str,
) -> str:
    """Select the preferred region or first healthy configured fallback."""
    if preferred_region in configured_regions and preferred_region in healthy_regions:
        return preferred_region
    for region in configured_regions:
        if region in healthy_regions:
            return region
    raise RuntimeError("No healthy configured storage region")


def should_replicate_bucket(logical_bucket: str) -> bool:
    """Return whether the logical surface participates in durable replication."""
    return logical_bucket not in NON_REPLICATED_BUCKETS


def is_region_managed_bucket(logical_bucket: str) -> bool:
    """Product media remains outside this rollout; buffer media uses fallback."""
    return logical_bucket not in REGION_EXCLUDED_BUCKETS
