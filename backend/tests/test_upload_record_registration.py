"""Contract tests for isolated upload record registration.

Upload completion depends on the core API persisting metadata and regional
replication intent. Registration failures must therefore reach the caller
instead of allowing an upload without durable redundancy to be acknowledged.
"""

import sys
import types

import pytest

if "python_multipart" not in sys.modules:
    python_multipart_module = types.ModuleType("python_multipart")
    python_multipart_module.__version__ = "0.0.99"
    sys.modules["python_multipart"] = python_multipart_module
if "multipart.multipart" not in sys.modules:
    multipart_module = types.ModuleType("multipart")
    multipart_submodule = types.ModuleType("multipart.multipart")
    multipart_submodule.parse_options_header = lambda value: (value, {})
    multipart_module.multipart = multipart_submodule
    sys.modules["multipart"] = multipart_module
    sys.modules["multipart.multipart"] = multipart_submodule

from backend.upload.routes import upload_route


class FailedRegistrationClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, url, *, json, headers):
        return type("Response", (), {"status_code": 503, "text": "unavailable"})()


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.asyncio
async def test_upload_record_registration_failure_reaches_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        upload_route.httpx,
        "AsyncClient",
        lambda *, timeout: FailedRegistrationClient(),
    )

    with pytest.raises(RuntimeError, match="HTTP 503"):
        await upload_route._store_record_via_api(
            "https://api.example.test",
            "internal-token",
            {"id": "upload-record"},
        )


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled
def test_upload_route_requires_one_active_region_for_variant_metadata() -> None:
    first = types.SimpleNamespace(key="one.bin", region="fsn1")
    second = types.SimpleNamespace(key="two.bin", region="fsn1")
    mismatched = types.SimpleNamespace(key="three.bin", region="hel1")

    class S3Service:
        def get_base_url(self, target_env="prod", *, region=None):
            return f"{target_env}:{region or 'primary'}"

    assert upload_route._single_upload_region(first, second) == "fsn1"
    assert upload_route._active_region_map(first, second) == {
        "one.bin": "fsn1",
        "two.bin": "fsn1",
    }
    with pytest.raises(RuntimeError, match="different active regions"):
        upload_route._single_upload_region(first, mismatched)
    assert upload_route._s3_base_url_for_stored_files(
        S3Service(),
        "dev",
        {"original": {"s3_key": "one.bin", "active_region": "fsn1"}},
    ) == "dev:fsn1"
    assert upload_route._active_region_map_from_stored_files(
        {"original": {"s3_key": "one.bin", "active_region": "fsn1"}}
    ) == {"one.bin": "fsn1"}
    assert upload_route._sample_stored_file_reference(
        {"original": {"s3_key": "one.bin", "active_region": "fsn1"}}
    ) == ("one.bin", "fsn1")
    assert upload_route._stored_file_references(
        {
            "original": {"s3_key": "one.bin", "active_region": "fsn1"},
            "preview": {"s3_key": "two.bin", "active_region": "fsn1"},
        }
    ) == [("one.bin", "fsn1"), ("two.bin", "fsn1")]
    assert upload_route._s3_base_url_for_stored_files(
        S3Service(),
        "dev",
        {"original": {"s3_key": "legacy.bin"}},
    ) == "dev:primary"


# contract-test: direct surface=rest_api assertions=storage.files.reference-safe-single-copy,storage.failover.health-reconciled
@pytest.mark.asyncio
async def test_stored_file_reference_probe_requires_every_variant() -> None:
    class S3Service:
        def __init__(self) -> None:
            self.calls = []

        async def check_file_exists(self, s3_key, *, target_env, region=None):
            self.calls.append((s3_key, target_env, region))
            return s3_key != "preview.bin"

    service = S3Service()

    assert not await upload_route._stored_file_references_available(
        service,
        target_env="dev",
        files_metadata={
            "original": {"s3_key": "original.bin", "active_region": "fsn1"},
            "preview": {"s3_key": "preview.bin", "active_region": "fsn1"},
        },
    )
    assert service.calls == [
        ("original.bin", "dev", "fsn1"),
        ("preview.bin", "dev", "fsn1"),
    ]
