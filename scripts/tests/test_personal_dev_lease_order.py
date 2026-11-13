# contract-test-file: tooling
"""Personal-dev real-test lease order.

Real-inference scripts must lease the exclusive personal-dev account before the
shared dev-stack lease, so a script waiting for the account never holds the
stack and dev restarts can always drain.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import code_run_real_test  # noqa: E402 - scripts are imported from the scripts dir like at runtime


class FakeSessions:
    DOCKER_RESOURCE_DEV_STACK = "dev-stack"

    def __init__(self, fail_on: str = "") -> None:
        self.fail_on = fail_on
        self.acquired: list[tuple[str, set[str], str]] = []
        self.released: list[str] = []

    def acquire_test_resource_lease(self, lease_id, owner, resources, *, mode, timeout):
        if self.fail_on and self.fail_on in resources:
            raise RuntimeError("busy")
        self.acquired.append((lease_id, set(resources), mode))
        return {}

    def release_test_resource_lease(self, lease_id):
        self.released.append(lease_id)
        return True


def test_account_lease_is_taken_before_shared_stack(monkeypatch):
    fake = FakeSessions()
    monkeypatch.setattr(code_run_real_test, "sessions", fake)

    leases = code_run_real_test.personal_dev_leases("embroidery-web", "ab12", timeout=5)

    assert [resources for _, resources, _ in fake.acquired] == [
        {"playwright-account:personal-dev"},
        {"dev-stack"},
    ]
    assert [mode for *_, mode in leases] == ["exclusive", "shared"]
    assert all(owner == "repository-session-ab12" for _, owner, _, _ in leases)
    assert leases[0][0].startswith("embroidery-web-account-")


def test_stack_failure_releases_account_lease(monkeypatch):
    fake = FakeSessions(fail_on="dev-stack")
    monkeypatch.setattr(code_run_real_test, "sessions", fake)

    with pytest.raises(RuntimeError):
        code_run_real_test.personal_dev_leases("code-run-personal", "ab12", timeout=5)

    assert fake.released == [fake.acquired[0][0]]
