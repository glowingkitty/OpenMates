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
