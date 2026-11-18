# contract-test-file: tooling
"""Disk admission policy approved by the owner on 2026-11-17 (TASK-7646).

One hard floor of 10 GiB as an emergency line, no percent ceiling, no extra
margin under pressure, and reservations sized from measured use.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_results  # noqa: E402 - repo-local modules, path set just above
import ci_source  # noqa: E402
import disk_coordinator_state  # noqa: E402
import resource_budget as budget  # noqa: E402
import sessions  # noqa: E402

GIB = 1024**3
MIB = 1024**2


def test_one_hard_floor_of_10_gib_and_no_percent_ceiling():
    assert budget.MIN_FREE == 10 * GIB
    assert budget.MAX_USED_PERCENT == 100
    assert disk_coordinator_state.RECOVERY_MARGIN == 0
    assert sessions.WORKTREE_MIN_FREE_BYTES == 10 * GIB
    assert sessions.WORKTREE_MAX_DISK_PERCENT == 100
    assert ci_results.RESERVE == 10 * GIB
    assert ci_source.DISK_RESERVE == 10 * GIB


def test_reservations_follow_measured_use():
    assert ci_results.RESULT_RESERVE == 256 * MIB
    assert sessions.WORKTREE_RESERVE_BYTES == 512 * MIB


class _Usage:
    def __init__(self, free_gib: float, total_gib: float = 300):
        self.total = int(total_gib * GIB)
        self.free = int(free_gib * GIB)
        self.used = self.total - self.free


def test_admission_allows_work_until_the_floor_regardless_of_percent():
    # 95% used but 15 GiB free: the old 30 GiB floor and 85% ceiling refused this.
    assert budget.admission(Path("/"), 512 * MIB, usage=_Usage(15))["allowed"] is True
    assert budget.admission(Path("/"), 512 * MIB, usage=_Usage(10.2))["allowed"] is False
