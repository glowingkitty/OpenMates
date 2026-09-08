"""File-mapped object storage region policy tests.

The shared module is intentionally pure so API and upload services agree on
bucket naming, fallback, and retry classification. These tests avoid credentials
and cover only deterministic policy behavior.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import pytest

from backend.shared.python_utils.object_storage_regions import (
    endpoint_for_region,
    is_region_managed_bucket,
    is_retryable_storage_error,
    parse_storage_regions,
    resolve_regional_bucket_name,
    select_temporary_upload_region,
    should_replicate_bucket,
)


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.failover.health-reconciled
def test_region_policy_parses_supported_regions_and_resolves_bucket_names() -> None:
    assert parse_storage_regions("nbg1, fsn1") == ("nbg1", "fsn1")
    assert endpoint_for_region("hel1") == "https://hel1.your-objectstorage.com"
    assert resolve_regional_bucket_name("dev-openmates-chatfiles", "nbg1") == "dev-openmates-chatfiles"
    assert resolve_regional_bucket_name("dev-openmates-chatfiles", "hel1") == "dev-openmates-chatfiles-hel1-om"

    with pytest.raises(ValueError, match="Unsupported storage regions"):
        parse_storage_regions("nbg1,unknown")


# contract-test: direct surface=rest_api assertions=storage.media.explicit-exceptions,storage.failover.health-reconciled
def test_temporary_uploads_fall_forward_without_replicating_excluded_media() -> None:
    assert select_temporary_upload_region(
        configured_regions=("nbg1", "fsn1", "hel1"),
        healthy_regions={"hel1"},
        preferred_region="nbg1",
    ) == "hel1"
    assert is_retryable_storage_error("SlowDown")
    assert is_retryable_storage_error("provider-new-error", 503)
    assert not should_replicate_bucket("buffer_media")
    assert not should_replicate_bucket("product_media")
    assert is_region_managed_bucket("buffer_media")
    assert not is_region_managed_bucket("product_media")


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
def test_explicit_isolated_s3_endpoint_preserves_region_defaults() -> None:
    from backend.shared.python_utils.object_storage_regions import object_url_for_region

    assert endpoint_for_region("nbg1", endpoint_override="http://storage.ci.test:9000") == "http://storage.ci.test:9000"
    assert object_url_for_region("test-bucket", "reports/proof.json", "nbg1", endpoint_override="http://storage.ci.test:9000") == "http://storage.ci.test:9000/test-bucket/reports/proof.json"
    assert object_url_for_region("test-bucket", "proof.json", "hel1") == "https://test-bucket-hel1.hel1.your-objectstorage.com/proof.json"
    for invalid in ("file:///tmp/store", "http://user:secret@storage:9000", "https://storage/path", "https://storage?key=secret", "https://storage#fragment"):
        with pytest.raises(ValueError, match="S3 endpoint"):
            endpoint_for_region("nbg1", endpoint_override=invalid)
