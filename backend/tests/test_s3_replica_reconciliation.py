"""Regional replica reconciliation planning contract tests.

Planning is pure and aggregate: verified drift can be copied, tombstones block
repair, and ambiguity never produces destructive action.
Contract: architecture.storage-lifecycle.
"""

from __future__ import annotations

import importlib

import pytest


def _reconciliation_module():
    try:
        return importlib.import_module("backend.core.api.app.services.s3.reconciliation")
    except ModuleNotFoundError as exc:
        pytest.fail(f"Replica reconciliation is not implemented: {exc}")


# contract-test: direct surface=rest_api assertions=storage.failover.health-reconciled,storage.integrity.observable-reconcilable
def test_reconciliation_classifies_drift_and_repairs_only_verified_sources() -> None:
    module = _reconciliation_module()
    plan = module.plan_replica_reconciliation(
        desired={
            1: {"checksum": "sha256:one", "regions": ("nbg1", "fsn1")},
            2: {"checksum": "sha256:two", "regions": ("nbg1", "fsn1")},
        },
        observed={
            (1, "nbg1"): "sha256:one",
            (2, "nbg1"): "sha256:wrong",
        },
        tombstoned_generations=set(),
        ambiguous_generations=set(),
    )

    assert plan["classifications"] == {"missing": 2, "mismatched": 1}
    assert plan["copy_actions"] == [
        {"generation": 1, "source_region": "nbg1", "target_region": "fsn1"}
    ]
    assert plan["delete_actions"] == []


# contract-test: direct surface=rest_api assertions=storage.deletion.global-authoritative,storage.integrity.observable-reconcilable
def test_tombstones_and_ambiguity_block_repair_and_deletion() -> None:
    module = _reconciliation_module()
    plan = module.plan_replica_reconciliation(
        desired={
            3: {"checksum": "sha256:deleted", "regions": ("nbg1", "fsn1")},
            4: {"checksum": "sha256:ambiguous", "regions": ("nbg1", "fsn1")},
        },
        observed={(3, "nbg1"): "sha256:deleted"},
        tombstoned_generations={3},
        ambiguous_generations={4},
    )

    assert plan["copy_actions"] == []
    assert plan["delete_actions"] == []
    assert plan["classifications"] == {"pending_delete": 1, "ambiguous": 1}
