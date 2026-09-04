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
RETRYABLE_STORAGE_ERROR_CODES = frozenset(
    {
        "500",
        "502",
        "503",
        "504",
        "429",
        "BadGateway",
        "ConnectionClosedError",
        "ConnectTimeoutError",
        "EndpointConnectionError",
        "GatewayTimeout",
        "HTTPClientError",
        "InternalError",
        "ReadTimeoutError",
        "RequestTimeout",
        "RequestTimeoutException",
        "ServiceUnavailable",
        "SlowDown",
        "TooManyRequests",
        "TooManyRequestsException",
        "Throttling",
        "ThrottlingException",
    }
)
RETRYABLE_STORAGE_THROTTLED_STATUS = 429
RETRYABLE_STORAGE_SERVER_ERROR_MIN_STATUS = 500
REGIONAL_BUCKET_NAME_OVERRIDES = {
    # These default dev HEL1 names are already taken in the provider namespace.
    ("dev-openmates-chatfiles", "hel1"): "dev-openmates-chatfiles-hel1-om",
    ("dev-openmates-usage-archives", "hel1"): "dev-openmates-usage-archives-hel1-om",
    ("dev-openmates-workspace-history-archives", "hel1"): "dev-openmates-workspace-history-archives-hel1-om",
}


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


def is_retryable_storage_error(error_code: str | None, http_status: int | str | None = None) -> bool:
    """Return whether an S3 provider error can safely retry or fail over."""
    if error_code in RETRYABLE_STORAGE_ERROR_CODES:
        return True
    try:
        status = int(http_status) if http_status is not None else None
    except (TypeError, ValueError):
        return False
    return status == RETRYABLE_STORAGE_THROTTLED_STATUS or (
        status is not None and status >= RETRYABLE_STORAGE_SERVER_ERROR_MIN_STATUS
    )


def resolve_regional_bucket_name(legacy_bucket_name: str, region: str) -> str:
    """Keep existing NBG names and derive globally unique replica names."""
    if region not in SUPPORTED_STORAGE_REGIONS:
        raise ValueError(f"Unsupported storage region: {region}")
    if region == LEGACY_BUCKET_REGION:
        return legacy_bucket_name
    if override := REGIONAL_BUCKET_NAME_OVERRIDES.get((legacy_bucket_name, region)):
        return override
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
