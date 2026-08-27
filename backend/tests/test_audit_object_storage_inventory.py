"""Contract tests for the aggregate object-storage inventory verifier.

Networked inventory must execute inside the API runtime where Vault credentials
are available. Host orchestration forwards only explicit arguments and never
prints credentials, bucket names, or object keys.
"""

from scripts.audit_object_storage_inventory import runtime_inventory_command


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
