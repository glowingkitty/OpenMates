"""Contract tests for the aggregate object-storage inventory verifier.

Networked inventory must execute inside the API runtime where Vault credentials
are available. Host orchestration forwards only explicit arguments and never
prints credentials, bucket names, or object keys.
"""

from scripts.audit_object_storage_inventory import (
    EMPTY_SHA256,
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

    assert command[:5] == ["docker", "exec", "api", "python", "/app/scripts/audit_object_storage_inventory.py"]
    assert command[-1] == "--runtime"


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
