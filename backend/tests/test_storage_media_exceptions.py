# Explicit object-storage media exception contract tests.
# Product media stays outside regional storage policy in this rollout.
# Temporary review media may fall forward to a healthy configured region.
# Review media remains private, time-bounded, and non-replicated.
# See contracts/architecture/storage-lifecycle/contract.yml.

from __future__ import annotations

import pytest

from backend.shared.python_utils import object_storage_regions
from backend.tests.s3_service_test_support import load_s3_service_module


# contract-test: direct surface=rest_api assertions=storage.media.explicit-exceptions
def test_buffer_media_falls_forward_to_first_healthy_region_without_replication() -> None:
    selected = object_storage_regions.select_temporary_upload_region(
        configured_regions=("nbg1", "fsn1", "hel1"),
        healthy_regions={"fsn1", "hel1"},
        preferred_region="nbg1",
    )

    assert selected == "fsn1"
    assert object_storage_regions.should_replicate_bucket("buffer_media") is False


# contract-test: direct surface=rest_api assertions=storage.media.explicit-exceptions
def test_product_media_is_not_claimed_by_regional_storage_policy() -> None:
    assert object_storage_regions.is_region_managed_bucket("product_media") is False


# contract-test: supporting surface=rest_api assertions=storage.media.explicit-exceptions
def test_temporary_upload_fails_visibly_when_no_region_is_healthy() -> None:
    try:
        object_storage_regions.select_temporary_upload_region(
            configured_regions=("nbg1", "fsn1"),
            healthy_regions=set(),
            preferred_region="nbg1",
        )
    except RuntimeError as exc:
        assert str(exc) == "No healthy configured storage region"
    else:
        raise AssertionError("Temporary upload must fail when every configured region is unhealthy")


class FakeSecretsManager:
    pass


# contract-test: direct surface=rest_api assertions=storage.media.explicit-exceptions
@pytest.mark.asyncio
async def test_buffer_media_upload_uses_selected_region_and_no_replication_path(monkeypatch: pytest.MonkeyPatch) -> None:
    service_module = load_s3_service_module()
    service = service_module.S3UploadService(FakeSecretsManager())
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": object(), "fsn1": object()}
    calls = []

    async def fake_upload_file(**kwargs):
        calls.append(kwargs)
        return {"region": kwargs["region"]}

    monkeypatch.setattr(service, "upload_file", fake_upload_file)

    result = await service.upload_temporary_file(
        bucket_key="buffer_media",
        file_key="review/session/video.mp4",
        content=b"encrypted-or-approved-review-media",
        content_type="video/mp4",
        healthy_regions={"fsn1"},
    )

    assert result == {"region": "fsn1"}
    assert calls[0]["region"] == "fsn1"
    assert "replicate" not in calls[0]
