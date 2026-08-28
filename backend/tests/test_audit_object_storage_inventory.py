"""Contract tests for the aggregate object-storage inventory verifier.

Networked inventory must execute inside the API runtime where Vault credentials
are available. Host orchestration forwards only explicit arguments and never
prints credentials, bucket names, or object keys.
"""

from io import BytesIO
from pathlib import Path

import pytest

from scripts.audit_object_storage_inventory import (
    EMPTY_SHA256,
    RUNTIME_INVENTORY_TIMEOUT_SECONDS,
    _compare_authoritative_inventory_database,
    _create_inventory_database,
    _populate_authoritative_replica_database,
    _populate_authoritative_source_database,
    _populate_verified_job_database,
    _verify_unresolved_authoritative_bytes,
    build_runtime_delegation_failure,
    probe_managed_bucket,
    runtime_inventory_command,
)


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_networked_inventory_delegates_to_api_runtime() -> None:
    command = runtime_inventory_command([
        "--env",
        "dev",
        "--probe-regions",
        "--regions",
        "nbg1,fsn1,hel1",
        "--json",
    ])

    assert command[:7] == [
        "docker",
        "exec",
        "api",
        "timeout",
        "--signal=TERM",
        "--kill-after=10s",
        f"{RUNTIME_INVENTORY_TIMEOUT_SECONDS}s",
    ]
    assert command[7:9] == ["python", "/app/scripts/audit_object_storage_inventory.py"]
    assert command[-1] == "--runtime"


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_networked_inventory_delegation_failure_is_safe_and_visible() -> None:
    report = build_runtime_delegation_failure(2, "unrecognized arguments: --flag")

    assert report == {
        "status": "blocked",
        "error_class": "RuntimeInventoryDelegationError",
        "runtime_return_code": 2,
        "runtime_stderr_present": True,
        "inventory_stage": "runtime_delegation",
        "object_keys_in_output": False,
    }


class RecordingClient:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def head_bucket(self, **_kwargs) -> None:
        self.operations.append("head_bucket")

    def put_object(self, **kwargs) -> None:
        self.operations.append("put_object")
        assert kwargs["Body"] == b""
        assert kwargs["Metadata"] == {"openmates-sha256": EMPTY_SHA256}

    def head_object(self, **_kwargs) -> dict[str, int]:
        self.operations.append("head_object")
        return {"ContentLength": 0}

    def delete_object(self, **_kwargs) -> None:
        self.operations.append("delete_object")


# contract-test: supporting surface=rest_api assertions=storage.regions.configurable-redundancy,storage.integrity.observable-reconcilable
def test_managed_bucket_probe_checks_data_plane_and_cleans_up() -> None:
    client = RecordingClient()

    probe_managed_bucket(client, "private-bucket", "private-probe-key")

    assert client.operations == ["head_bucket", "put_object", "head_object", "delete_object"]


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_authoritative_sqlite_report_separates_orphans_and_unverified_fingerprints(tmp_path: Path) -> None:
    connection = _create_inventory_database(tmp_path / "inventory.sqlite3")
    try:
        connection.executemany(
            "INSERT INTO refs(logical_bucket, object_key) VALUES (?, ?)",
            [
                ("chatfiles", "live-a"),
                ("chatfiles", "live-b"),
                ("chatfiles", "missing-source"),
            ],
        )
        connection.executemany(
            "INSERT INTO objects(region, logical_bucket, object_key, size_bytes, checksum) VALUES (?, ?, ?, ?, ?)",
            [
                ("nbg1", "chatfiles", "live-a", 10, f"sha256:{'a' * 64}"),
                ("nbg1", "chatfiles", "live-b", 20, "etag:legacy-b"),
                ("nbg1", "chatfiles", "orphan", 30, "etag:orphan"),
                ("fsn1", "chatfiles", "live-a", 10, f"sha256:{'a' * 64}"),
                ("fsn1", "chatfiles", "live-b", 20, f"sha256:{'b' * 64}"),
            ],
        )
        connection.execute(
            "INSERT INTO verified_jobs(logical_bucket, object_key, region, checksum) VALUES (?, ?, ?, ?)",
            ("chatfiles", "live-b", "fsn1", f"sha256:{'b' * 64}"),
        )
        connection.commit()

        report = _compare_authoritative_inventory_database(
            connection,
            source_region="nbg1",
            regions=("nbg1", "fsn1"),
            ambiguous_reference_count=4,
        )
    finally:
        connection.close()

    assert report["source_objects_without_references"] == 1
    assert report["references_without_source_objects"] == 1
    assert report["ambiguous_reference_count"] == 4
    assert report["regions"]["fsn1"] == {
        "authoritative_present": 2,
        "missing": 0,
        "mismatched": 0,
        "durably_verified": 1,
        "fingerprint_unverified": 0,
    }
    assert report["authoritative_replicas_match"] is False
    assert report["object_keys_in_output"] is False
    assert report["mutations_performed"] is False


class AuthoritativeInventoryClient:
    def __init__(self, *, replica: bool = False) -> None:
        self.replica = replica
        self.head_keys: list[str] = []
        self.list_max_keys: list[int] = []

    def list_objects_v2(self, **kwargs) -> dict:
        self.list_max_keys.append(int(kwargs["MaxKeys"]))
        return {
            "Contents": [
                {"Key": "live", "Size": 10, "ETag": '"source-live"'},
                {"Key": "orphan", "Size": 20, "ETag": '"source-orphan"'},
            ]
        }

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        self.head_keys.append(Key)
        if self.replica and Key == "missing":
            error = RuntimeError("missing")
            error.response = {"Error": {"Code": "404"}}
            raise error
        return {
            "ContentLength": 10,
            "ETag": '"replica-live"' if self.replica else '"source-live"',
            "Metadata": {"openmates-sha256": "a" * 64} if self.replica else {},
        }


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable
def test_authoritative_scan_heads_only_referenced_objects(tmp_path: Path, monkeypatch) -> None:
    from scripts import audit_object_storage_inventory as module

    monkeypatch.setattr(module, "BUCKETS", {"chatfiles": {"managed": True}})
    connection = _create_inventory_database(tmp_path / "inventory.sqlite3")
    connection.executemany(
        "INSERT INTO refs(logical_bucket, object_key) VALUES (?, ?)",
        [("chatfiles", "live"), ("chatfiles", "missing")],
    )
    connection.commit()
    source = AuthoritativeInventoryClient()
    replica = AuthoritativeInventoryClient(replica=True)
    try:
        _populate_authoritative_source_database(
            connection,
            client=source,
            region="nbg1",
            environment="development",
        )
        _populate_authoritative_replica_database(
            connection,
            client=replica,
            source_region="nbg1",
            region="fsn1",
            environment="development",
        )
    finally:
        connection.close()

    assert source.head_keys == ["live"]
    assert replica.head_keys == ["live"]
    assert source.list_max_keys == [module.INVENTORY_LIST_MAX_KEYS]


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable
def test_inventory_listing_retries_transient_provider_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import audit_object_storage_inventory as module

    class FlakyClient:
        def __init__(self) -> None:
            self.calls = 0
            self.max_keys: list[int] = []

        def list_objects_v2(self, **kwargs) -> dict:
            self.calls += 1
            self.max_keys.append(int(kwargs["MaxKeys"]))
            if self.calls == 1:
                error = RuntimeError("temporary provider failure")
                error.response = {
                    "Error": {"Code": "504"},
                    "ResponseMetadata": {"HTTPStatusCode": 504},
                }
                raise error
            return {"Contents": [{"Key": "live", "Size": 1, "ETag": '"etag"'}]}

    client = FlakyClient()
    monkeypatch.setattr(module, "BUCKETS", {"chatfiles": {"managed": True}})
    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)

    rows = list(
        module._iter_managed_bucket_items(
            client=client,
            region="nbg1",
            environment="development",
        )
    )

    assert client.calls == 2
    assert client.max_keys == [module.INVENTORY_LIST_MAX_KEYS, module.INVENTORY_LIST_MAX_KEYS]
    assert rows[0][0] == "chatfiles"


# contract-test: supporting surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.integrity.observable-reconcilable
@pytest.mark.anyio
async def test_verified_job_loader_uses_snapshot_pages_and_only_verified_regions(tmp_path: Path, monkeypatch) -> None:
    from scripts import audit_object_storage_inventory as module

    monkeypatch.setattr(module, "DIRECTUS_AUDIT_PAGE_SIZE", 2)

    class Directus:
        params: list[dict] = []

        async def get_items(self, _collection: str, *, params: dict, **_kwargs) -> list[dict]:
            self.params.append(params)
            if params["sort"] == "-created_at":
                return [{"created_at": "2026-08-28T10:00:00Z"}]
            if params["offset"] == 0:
                return [
                    {
                        "id": "job-1",
                        "created_at": "2026-08-28T09:00:00Z",
                        "logical_bucket": "chatfiles",
                        "object_key": "one",
                        "checksum": "a" * 64,
                        "state": "verified",
                        "region_states": {"nbg1": "verified", "fsn1": "pending"},
                    },
                    {
                        "id": "job-2",
                        "created_at": "2026-08-28T09:30:00Z",
                        "logical_bucket": "chatfiles",
                        "object_key": "two",
                        "checksum": f"sha256:{'b' * 64}",
                        "state": "verified",
                        "region_states": {"nbg1": "verified", "fsn1": "verified"},
                    },
                ]
            return [{
                "id": "job-3",
                "created_at": "2026-08-28T10:00:00Z",
                "logical_bucket": "chatfiles",
                "object_key": "invalid-checksum",
                "checksum": "invalid",
                "state": "verified",
                "region_states": {"nbg1": "verified"},
            }]

    directus = Directus()
    connection = _create_inventory_database(tmp_path / "inventory.sqlite3")
    try:
        await _populate_verified_job_database(connection, directus)
        rows = connection.execute(
            "SELECT logical_bucket, object_key, region, checksum FROM verified_jobs ORDER BY object_key, region"
        ).fetchall()
    finally:
        connection.close()

    assert directus.params[0] == {"fields": "created_at", "sort": "-created_at", "limit": 1}
    assert [params["offset"] for params in directus.params[1:]] == [0, 2]
    assert all(
        params["filter"] == {"created_at": {"_lte": "2026-08-28T10:00:00Z"}}
        for params in directus.params[1:]
    )
    assert rows == [
        ("chatfiles", "one", "nbg1", f"sha256:{'a' * 64}"),
        ("chatfiles", "two", "fsn1", f"sha256:{'b' * 64}"),
        ("chatfiles", "two", "nbg1", f"sha256:{'b' * 64}"),
    ]


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable,storage.privacy.ciphertext-boundary
def test_unresolved_fingerprint_pairs_use_capped_read_only_byte_verification(tmp_path: Path) -> None:
    payload = b"encrypted-ciphertext"

    class Client:
        def get_object(self, **_kwargs) -> dict:
            return {"Body": BytesIO(payload)}

    connection = _create_inventory_database(tmp_path / "inventory.sqlite3")
    try:
        connection.execute(
            "INSERT INTO refs(logical_bucket, object_key) VALUES (?, ?)",
            ("chatfiles", "live"),
        )
        connection.executemany(
            "INSERT INTO objects(region, logical_bucket, object_key, size_bytes, checksum) VALUES (?, ?, ?, ?, ?)",
            [
                ("nbg1", "chatfiles", "live", len(payload), "etag:source"),
                ("fsn1", "chatfiles", "live", len(payload), f"sha256:{'a' * 64}"),
            ],
        )
        connection.commit()

        byte_report = _verify_unresolved_authoritative_bytes(
            connection,
            clients={"nbg1": Client(), "fsn1": Client()},
            source_region="nbg1",
            regions=("nbg1", "fsn1"),
            environment="development",
        )
        report = _compare_authoritative_inventory_database(
            connection,
            source_region="nbg1",
            regions=("nbg1", "fsn1"),
            ambiguous_reference_count=0,
        )
    finally:
        connection.close()

    assert byte_report == {
        "byte_verified_pair_count": 1,
        "byte_verification_deferred_count": 0,
    }
    assert report["regions"]["fsn1"]["mismatched"] == 0
    assert report["regions"]["fsn1"]["fingerprint_unverified"] == 0
