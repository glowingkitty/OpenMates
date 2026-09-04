# Multi-region object-storage policy contract tests.
# These tests stay pure and never contact S3 or read credentials.
# They define region-list validation and logical bucket resolution.
# Runtime capability probes belong to the inventory audit script.
# See contracts/architecture/storage-lifecycle/contract.yml.

from __future__ import annotations

import importlib

import pytest
from botocore.exceptions import ClientError

from backend.tests.s3_service_test_support import load_s3_service_module


DEFAULT_REGIONS = ("nbg1", "fsn1", "hel1")


def _regions_module():
    try:
        return importlib.import_module("backend.shared.python_utils.object_storage_regions")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Multi-region storage policy is not implemented: {exc}")


# contract-test: direct surface=rest_api assertions=storage.regions.configurable-redundancy
def test_default_and_reduced_region_sets_are_deterministic() -> None:
    module = _regions_module()

    assert module.parse_storage_regions(None) == DEFAULT_REGIONS
    assert module.parse_storage_regions("hel1,nbg1") == ("hel1", "nbg1")


# contract-test: direct surface=rest_api assertions=storage.regions.configurable-redundancy
@pytest.mark.parametrize("value", ["", " ", "nbg1,nbg1", "nbg1,unknown"])
def test_invalid_region_sets_fail_visibly(value: str) -> None:
    module = _regions_module()

    with pytest.raises(ValueError):
        module.parse_storage_regions(value)


# contract-test: direct surface=rest_api assertions=storage.regions.configurable-redundancy
def test_logical_bucket_resolution_preserves_nbg_alias_and_uses_unique_replica_names() -> None:
    module = _regions_module()

    assert module.resolve_regional_bucket_name("dev-openmates-chatfiles", "nbg1") == "dev-openmates-chatfiles"
    assert module.resolve_regional_bucket_name("dev-openmates-chatfiles", "fsn1") == "dev-openmates-chatfiles-fsn1"
    assert module.resolve_regional_bucket_name("dev-openmates-chatfiles", "hel1") == "dev-openmates-chatfiles-hel1-om"
    assert (
        module.resolve_regional_bucket_name("dev-openmates-usage-archives", "hel1")
        == "dev-openmates-usage-archives-hel1-om"
    )
    assert (
        module.resolve_regional_bucket_name("dev-openmates-workspace-history-archives", "hel1")
        == "dev-openmates-workspace-history-archives-hel1-om"
    )


# contract-test: supporting surface=rest_api assertions=storage.regions.configurable-redundancy,storage.privacy.ciphertext-boundary
def test_region_endpoint_is_derived_from_selected_region() -> None:
    module = _regions_module()

    assert module.endpoint_for_region("fsn1") == "https://fsn1.your-objectstorage.com"


class FakeSecretsManager:
    async def get_secret(self, *, secret_path: str, secret_key: str):
        values = {
            "s3_access_key": "test-access",
            "s3_secret_key": "test-secret",
            "s3_region_name": "nbg1",
        }
        return values.get(secret_key)


# contract-test: direct surface=rest_api assertions=storage.regions.configurable-redundancy
@pytest.mark.asyncio
async def test_core_service_builds_one_client_per_configured_region(monkeypatch: pytest.MonkeyPatch) -> None:
    service_module = load_s3_service_module()
    monkeypatch.setenv("S3_REGIONS", "nbg1,fsn1")
    created_clients = []

    def fake_client(*args, **kwargs):
        client = {"endpoint_url": kwargs["endpoint_url"], "region_name": kwargs["region_name"]}
        created_clients.append(client)
        return client

    async def skip_bucket_initialization() -> None:
        return None

    monkeypatch.setattr(service_module.boto3, "client", fake_client)
    monkeypatch.setattr(service_module, "apply_cors_settings", lambda client: None)
    service = service_module.S3UploadService(FakeSecretsManager())
    monkeypatch.setattr(service, "_initialize_buckets", skip_bucket_initialization)
    monkeypatch.setattr(service, "_reconcile_regional_bucket_policies", skip_bucket_initialization)

    await service.initialize()

    assert tuple(service.region_clients) == ("nbg1", "fsn1")
    assert service.client is service.region_clients["nbg1"]
    assert service.region_clients["fsn1"]["endpoint_url"] == "https://fsn1.your-objectstorage.com"
    assert len(created_clients) >= 2


class RecordingPresignClient:
    def __init__(self) -> None:
        self.params = None

    def generate_presigned_url(self, operation, *, Params, ExpiresIn):
        self.params = {"operation": operation, "Params": Params, "ExpiresIn": ExpiresIn}
        return "https://signed.example.test"


# contract-test: direct surface=rest_api assertions=storage.regions.configurable-redundancy
def test_presigned_url_uses_selected_regional_client_and_bucket() -> None:
    service_module = load_s3_service_module()
    service = service_module.S3UploadService(FakeSecretsManager())
    fsn_client = RecordingPresignClient()
    service.region_name = "nbg1"
    service.region_clients = {"fsn1": fsn_client}

    url = service.generate_presigned_url(
        "dev-openmates-chatfiles",
        "owner-a/hash-a/original.bin",
        expiration=60,
        region="fsn1",
    )

    assert url == "https://signed.example.test"
    assert fsn_client.params == {
        "operation": "get_object",
        "Params": {
            "Bucket": "dev-openmates-chatfiles-fsn1",
            "Key": "owner-a/hash-a/original.bin",
        },
        "ExpiresIn": 60,
    }


class ExistingBucketClient:
    def __init__(self) -> None:
        self.head_buckets = []
        self.acls = []

    def head_bucket(self, *, Bucket):
        self.head_buckets.append(Bucket)

    def put_bucket_acl(self, *, Bucket, ACL):
        self.acls.append((Bucket, ACL))


class MissingRegionalBucketClient(ExistingBucketClient):
    def __init__(self) -> None:
        super().__init__()
        self.created_buckets = []

    def head_bucket(self, *, Bucket):
        self.head_buckets.append(Bucket)
        if Bucket not in self.created_buckets:
            raise ClientError(
                {"Error": {"Code": "NoSuchBucket", "Message": "missing"}},
                "HeadBucket",
            )

    def create_bucket(self, *, Bucket):
        self.created_buckets.append(Bucket)


class ExternalUploadClient:
    def head_object(self, *, Bucket, Key):
        return {"Metadata": {"openmates-sha256": "a" * 64}}


class MissingChecksumClient:
    def head_object(self, *, Bucket, Key):
        return {"Metadata": {}}

    def get_object(self, *, Bucket, Key):
        from io import BytesIO

        return {"Body": BytesIO(b"legacy-ciphertext")}


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_external_upload_checksum_metadata_creates_replication_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    service_module = load_s3_service_module()
    service = service_module.S3UploadService(FakeSecretsManager())
    service.environment = "development"
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": ExternalUploadClient()}
    persisted = []

    async def persist(**kwargs):
        persisted.append(kwargs)

    monkeypatch.setattr(service, "_persist_replication_outbox", persist)

    await service.persist_external_upload_replication(
        logical_bucket="chatfiles",
        object_key="owner-a/hash-a/original.bin",
    )

    assert persisted == [{
        "logical_bucket": "chatfiles",
        "object_key": "owner-a/hash-a/original.bin",
        "checksum": "a" * 64,
        "active_region": "nbg1",
    }]


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.asyncio
async def test_external_upload_without_checksum_metadata_hashes_ciphertext(monkeypatch: pytest.MonkeyPatch) -> None:
    service_module = load_s3_service_module()
    service = service_module.S3UploadService(FakeSecretsManager())
    service.environment = "development"
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": MissingChecksumClient()}
    persisted = []

    async def persist(**kwargs):
        persisted.append(kwargs)

    monkeypatch.setattr(service, "_persist_replication_outbox", persist)

    await service.persist_external_upload_replication(
        logical_bucket="chatfiles",
        object_key="owner-a/hash-a/original.bin",
    )

    assert persisted[0]["checksum"] == "beceee1f9a57fbe4da761d4275b3fd1d5bd12d3a851f3f4ba6954ac81a8b12ab"


# contract-test: direct surface=rest_api assertions=storage.regions.configurable-redundancy,storage.retention.system-generation-only
@pytest.mark.asyncio
async def test_existing_regional_buckets_receive_acl_lifecycle_and_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    service_module = load_s3_service_module()
    bucket_config = {
        "name": "openmates-chatfiles",
        "dev_name": "dev-openmates-chatfiles",
        "access": "private",
        "lifecycle_policy": 30,
    }
    monkeypatch.setattr(service_module, "BUCKETS", {"chatfiles": bucket_config})
    monkeypatch.setattr(service_module, "CORS_ENABLED_BUCKETS", ["dev-openmates-chatfiles"])
    monkeypatch.setattr(service_module, "BUCKET_CREATION_SETTLE_SECONDS", 0)
    lifecycle_calls = []
    cors_calls = []
    monkeypatch.setattr(
        service_module,
        "apply_lifecycle_policies",
        lambda client, configs, environment: lifecycle_calls.append((client, configs, environment)),
    )
    monkeypatch.setattr(
        service_module,
        "apply_cors_settings",
        lambda client, buckets: cors_calls.append((client, buckets)),
    )
    nbg_client = ExistingBucketClient()
    fsn_client = ExistingBucketClient()
    service = service_module.S3UploadService(FakeSecretsManager())
    service.environment = "development"
    service.region_clients = {"nbg1": nbg_client, "fsn1": fsn_client}

    await service._reconcile_regional_bucket_policies()

    assert nbg_client.acls == [("dev-openmates-chatfiles", "private")]
    assert fsn_client.acls == [("dev-openmates-chatfiles-fsn1", "private")]
    assert [call[2] for call in lifecycle_calls] == ["development", "development"]
    assert [list(call[1].values())[0]["dev_name"] for call in lifecycle_calls] == [
        "dev-openmates-chatfiles",
        "dev-openmates-chatfiles-fsn1",
    ]
    assert [call[1] for call in cors_calls] == [
        ["dev-openmates-chatfiles"],
        ["dev-openmates-chatfiles-fsn1"],
    ]


# contract-test: direct surface=rest_api assertions=storage.regions.configurable-redundancy,storage.integrity.observable-reconcilable
@pytest.mark.asyncio
async def test_missing_managed_replica_is_created_once_and_exclusions_are_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = load_s3_service_module()
    bucket_config = {
        "name": "openmates-chatfiles",
        "dev_name": "dev-openmates-chatfiles",
        "access": "private",
        "lifecycle_policy": 30,
    }
    excluded_config = {
        "name": "openmates-buffer-media",
        "dev_name": "dev-openmates-buffer-media",
        "access": "private",
        "lifecycle_policy": 2,
    }
    unmanaged_config = {
        "name": "openmates-retired",
        "dev_name": "dev-openmates-retired",
        "access": "private",
        "managed": False,
    }
    monkeypatch.setattr(
        service_module,
        "BUCKETS",
        {
            "chatfiles": bucket_config,
            "buffer_media": excluded_config,
            "retired": unmanaged_config,
        },
    )
    monkeypatch.setattr(service_module, "CORS_ENABLED_BUCKETS", ["dev-openmates-chatfiles"])
    monkeypatch.setattr(service_module, "apply_lifecycle_policies", lambda *_args: None)
    monkeypatch.setattr(service_module, "apply_cors_settings", lambda *_args: None)
    client = MissingRegionalBucketClient()
    service = service_module.S3UploadService(FakeSecretsManager())
    service.environment = "development"
    service.region_clients = {"fsn1": client}

    await service._reconcile_regional_bucket_policies()
    await service._reconcile_regional_bucket_policies()

    assert client.created_buckets == ["dev-openmates-chatfiles-fsn1"]
    assert client.head_buckets == [
        "dev-openmates-chatfiles-fsn1",
        "dev-openmates-chatfiles-fsn1",
    ]
    assert client.acls == [
        ("dev-openmates-chatfiles-fsn1", "private"),
        ("dev-openmates-chatfiles-fsn1", "private"),
    ]


# contract-test: direct surface=rest_api assertions=storage.integrity.observable-reconcilable,storage-resilience.core.s3-is-noncritical
@pytest.mark.asyncio
async def test_active_region_failure_does_not_skip_replica_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_module = load_s3_service_module()
    service = service_module.S3UploadService(FakeSecretsManager())
    service.configured = True
    service.client = object()
    regional_calls = []

    async def fail_active_region() -> None:
        raise service_module.ReadTimeoutError(endpoint_url="https://storage.invalid")

    async def reconcile_replicas() -> None:
        regional_calls.append(True)

    monkeypatch.setattr(service, "_initialize_buckets", fail_active_region)
    monkeypatch.setattr(service, "_reconcile_regional_bucket_policies", reconcile_replicas)

    with pytest.raises(RuntimeError, match="object_storage_reconciliation_failed"):
        await service.reconcile_configuration()

    assert regional_calls == [True]
