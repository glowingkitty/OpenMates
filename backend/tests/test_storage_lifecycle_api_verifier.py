"""Regional storage real-API verifier helper tests.

Only payload validation is unit tested here. The required evidence executes the
script against the real Docker-backed dev API with internal authentication.
Contract: architecture.storage-lifecycle.
"""

from pathlib import Path

from scripts.verify_storage_lifecycle_api import validate_health_payload


ROOT = Path(__file__).resolve().parents[2]


# contract-test: supporting surface=rest_api assertions=storage.failover.health-reconciled,storage.integrity.observable-reconcilable
def test_health_verifier_accepts_only_required_aggregate_shape() -> None:
    assert validate_health_payload(
        {
            "configured_regions": ["nbg1", "fsn1", "hel1"],
            "regions": [{"region": "nbg1", "reconciled": False}],
            "pending_replication": 4,
            "pending_deletion": 2,
            "result_truncated": False,
        }
    ) == {
        "configured_region_count": 3,
        "health_row_count": 1,
        "pending_replication": 4,
        "pending_deletion": 2,
        "result_truncated": False,
    }


# contract-test: supporting surface=rest_api assertions=storage.integrity.observable-reconcilable
def test_api_images_include_runtime_verifiers() -> None:
    for dockerfile in (
        ROOT / "backend/core/api/Dockerfile",
        ROOT / "backend/core/api/Dockerfile.selfhost",
    ):
        content = dockerfile.read_text()
        assert "COPY scripts/verify_storage_lifecycle_api.py /app/scripts/verify_storage_lifecycle_api.py" in content
        assert "COPY scripts/verify_storage_replication_cli_chat.py /app/scripts/verify_storage_replication_cli_chat.py" in content
        assert "COPY scripts/audit_object_storage_inventory.py /app/scripts/audit_object_storage_inventory.py" in content
