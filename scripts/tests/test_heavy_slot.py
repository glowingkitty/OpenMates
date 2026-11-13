"""Unit tests for scripts/heavy_slot.py (host-wide heavy command slots).

Run: python3 -m pytest scripts/tests/test_heavy_slot.py
"""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import heavy_slot  # noqa: E402 - scripts/ is added to sys.path above


# contract-test: tooling
def test_slots_are_exclusive_and_bounded(tmp_path: Path) -> None:
    held = [heavy_slot.try_acquire(tmp_path) for _ in range(heavy_slot.MAX_SLOTS)]
    assert all(item is not None for item in held)
    assert sorted(slot for _, slot in held) == list(range(heavy_slot.MAX_SLOTS))
    assert heavy_slot.try_acquire(tmp_path) is None
    fd, _ = held[0]
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    reacquired = heavy_slot.try_acquire(tmp_path)
    assert reacquired is not None
    for fd, _ in [reacquired, *held[1:]]:
        os.close(fd)


# contract-test: tooling
def test_wrapped_command_applies_limits() -> None:
    wrapped = heavy_slot.wrapped_command(["cargo", "build"])
    assert wrapped[:3] == ["systemd-run", "--user", "--scope"]
    assert f"CPUQuota={heavy_slot.CPU_QUOTA}" in wrapped
    assert f"MemoryMax={heavy_slot.MEMORY_MAX}" in wrapped
    assert wrapped[-2:] == ["cargo", "build"]
    assert "nice" in wrapped


# contract-test: tooling
def test_memory_admission_counts_a_run_that_just_started() -> None:
    gib = heavy_slot.host_load_guard.GIB
    # 2026-11-11: 8.4 GiB available admitted two 6 GiB-capped runs in the same second.
    assert heavy_slot.memory_shortfall(int(8.4 * gib), recent=0) is not None
    assert heavy_slot.memory_shortfall(9 * gib, recent=0) is None
    assert heavy_slot.memory_shortfall(14 * gib, recent=1) is not None
    assert heavy_slot.memory_shortfall(15 * gib, recent=1) is None


# contract-test: tooling
def test_recent_starts_ignores_settled_and_free_slots(tmp_path: Path) -> None:
    held = heavy_slot.try_acquire(tmp_path)
    assert held is not None
    fd, slot = held
    now = (tmp_path / f"slot-{slot}.lock").stat().st_mtime
    assert heavy_slot.recent_starts(tmp_path, now + 1) == 1
    assert heavy_slot.recent_starts(tmp_path, now + heavy_slot.SETTLE_SECONDS + 1) == 0
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    assert heavy_slot.recent_starts(tmp_path, now + 1) == 0
