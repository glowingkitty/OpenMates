# contract-test-file: tooling
"""Prevent partial or cloud-incompatible CI evidence from activating cutover.

Known core specs may run after a real isolated account preflight passes.
Cloud, provider and unknown requirements remain explicit incomplete coverage.
Workflow cleanup failure must not be promoted to an overall passing pilot.
See docs/architecture/isolated-github-tests.md.
"""

import pytest
from scripts.ci_coverage import partition, verify_pilot


def receipt():
    return {
        "state": "success", "run_id": 7, "source_commit": "a" * 40,
        "harness_commit": "b" * 40, "artifact_url": "synthetic",
        "report": {"success": True, "results": [{
            "spec": "test-account-preflight.spec.ts", "exit_code": 0,
            "stats": {"expected": 1, "skipped": 0},
        }]},
        "environment": {"runner_environment": "github-hosted", "shared_dev_https": "rejected",
                        "frontend": {"source_commit": "a" * 40},
                        "services": {name: {} for name in ("api", "core-worker", "cms", "cms-database", "cache", "vault")}},
    }


def test_cloud_and_unknown_coverage_never_fall_back_to_self_host():
    allowed, held = partition(["tasks-flow.spec.ts", "anonymous-production-repair.spec.ts", "new.spec.ts"])
    assert allowed == ["tasks-flow.spec.ts"]
    assert "official-cloud" in held["anonymous-production-repair.spec.ts"]
    assert "new.spec.ts" in held


def test_cleanup_failure_and_skipped_preflight_cannot_activate():
    data = receipt()
    data["state"] = "failure"
    with pytest.raises(RuntimeError, match="successful GitHub job"):
        verify_pilot(data)
    data["state"] = "success"
    data["report"]["results"][0]["stats"]["skipped"] = 1
    with pytest.raises(RuntimeError, match="without skipped"):
        verify_pilot(data)


def test_verified_core_profile_does_not_claim_all_e2e_complete():
    verified = verify_pilot(receipt())
    assert verified["ready"] is True
    assert verified["all_e2e_migrated"] is False
    assert "anonymous-production-repair.spec.ts" in verified["held_coverage"]
