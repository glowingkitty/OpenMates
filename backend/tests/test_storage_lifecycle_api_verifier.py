"""Regional storage real-API verifier helper tests.

Only payload validation is unit tested here. The required evidence executes the
script against the real Docker-backed dev API with internal authentication.
Contract: architecture.storage-lifecycle.
"""

from pathlib import Path

import httpx

from scripts.verify_storage_lifecycle_api import (
    validate_health_payload,
    verify_public_ingress_isolation,
)


ROOT = Path(__file__).resolve().parents[2]


# contract-test: supporting surface=rest_api assertions=storage.failover.health-reconciled,storage.integrity.observable-reconcilable
def test_health_verifier_accepts_only_required_aggregate_shape() -> None:
    assert validate_health_payload(
        {
            "configured_regions": ["nbg1", "fsn1", "hel1"],
            "regions": [{
                "region": "nbg1",
                "reconciled": False,
                "probe_succeeded": True,
                "last_error_code": "",
            }],
            "pending_replication": 4,
            "source_missing_replication": 1,
            "replication_error_code_counts": {"404": 1},
            "max_replication_attempts": 3,
            "pending_deletion": 2,
            "result_truncated": False,
        }
    ) == {
        "configured_region_count": 3,
        "health_row_count": 1,
        "reconciled_region_count": 0,
        "region_states": [{
            "region": "nbg1",
            "reconciled": False,
            "probe_succeeded": True,
            "last_error_code": "",
        }],
        "pending_replication": 4,
        "source_missing_replication": 1,
        "replication_error_code_counts": {"404": 1},
        "max_replication_attempts": 3,
        "pending_deletion": 2,
        "result_truncated": False,
    }


# contract-test: supporting surface=rest_api assertions=storage.failover.health-reconciled
def test_public_ingress_connection_rejection_is_valid_when_health_is_reachable() -> None:
    def getter(url: str, **_kwargs) -> httpx.Response:
        request = httpx.Request("GET", url)
        if url.endswith("/internal/storage/health"):
            raise httpx.ConnectError("connection rejected", request=request)
        return httpx.Response(301, request=request)

    assert verify_public_ingress_isolation("https://api.example.test", getter) == "connection_rejected"


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
