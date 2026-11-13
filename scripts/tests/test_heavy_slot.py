# contract-test-file: tooling
"""Unit tests for scripts/heavy_slot.py (host-wide heavy command slots).

Run: python3 -m pytest scripts/tests/test_heavy_slot.py
"""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path

import pytest

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
def test_wrapped_command_applies_class_limits() -> None:
    wrapped = heavy_slot.wrapped_command(["cargo", "build"])
    assert wrapped[:3] == ["systemd-run", "--user", "--scope"]
    assert "CPUQuota=400%" in wrapped and "MemoryMax=6G" in wrapped
    assert wrapped[-2:] == ["cargo", "build"]
    assert "nice" in wrapped
    light = heavy_slot.wrapped_command(["npm", "run", "build:translations"], "light")
    assert "MemoryMax=2G" in light and "CPUQuota=200%" in light


# contract-test: tooling
@pytest.mark.parametrize(("command", "cls"), [
    (["npm", "run", "build:translations"], "light"),
    (["npm", "--prefix", "frontend/packages/ui", "run", "build:translations"], "light"),
    (["node", "scripts/build-translations.js"], "light"),
    (["/w/.venv/bin/python", "-m", "pytest", "-q", "backend/tests/test_x.py"], "light"),
    (["node", "/w/node_modules/@playwright/test/cli.js", "test", "--config", "/tmp/a/c.cjs"], "browser"),
    (["npx", "playwright", "test", "smoke.spec.ts"], "browser"),
    (["cargo", "build", "--release"], "heavy"),
    (["bash", "-c", "cd x && pnpm exec svelte-check"], "heavy"),
    (["npm", "run", "build"], "heavy"),
    (["some-unknown-tool"], "heavy"),
])
def test_command_class(command: list[str], cls: str) -> None:
    assert heavy_slot.command_class(command) == cls


# contract-test: tooling
def test_memory_admission_uses_the_class_cap_and_runs_that_just_started() -> None:
    gib = heavy_slot.host_load_guard.GIB
    # 2026-11-11: 8.4 GiB available admitted two 6 GiB-capped runs in the same second.
    assert heavy_slot.memory_shortfall(int(8.4 * gib), 0, 6 * gib) is not None
    assert heavy_slot.memory_shortfall(9 * gib, 0, 6 * gib) is None
    assert heavy_slot.memory_shortfall(14 * gib, 6 * gib, 6 * gib) is not None
    assert heavy_slot.memory_shortfall(15 * gib, 6 * gib, 6 * gib) is None
    # 2026-11-13: a translation build waited 30+ minutes with 7-9 GiB free.
    assert heavy_slot.memory_shortfall(7 * gib, 0, heavy_slot.class_cap_bytes("light")) is None
    assert heavy_slot.memory_shortfall(7 * gib, 0, heavy_slot.class_cap_bytes("browser")) is None


# contract-test: tooling
def test_recent_reserved_counts_caps_of_fresh_slots_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(heavy_slot.host_load_guard, "current_decision", lambda: (
        type("S", (), {"mem_available_bytes": 64 * heavy_slot.host_load_guard.GIB})(),
        type("D", (), {"overloaded": False, "reasons": []})()))
    acquired, why = heavy_slot.admit(tmp_path, "light", "npm run build:translations")
    assert acquired is not None, why
    fd, slot = acquired
    now = (tmp_path / "light" / f"slot-{slot}.lock").stat().st_mtime
    assert heavy_slot.recent_reserved(tmp_path, now + 1) == heavy_slot.class_cap_bytes("light")
    assert heavy_slot.recent_reserved(tmp_path, now + heavy_slot.SETTLE_SECONDS + 1) == 0
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    assert heavy_slot.recent_reserved(tmp_path, now + 1) == 0


# contract-test: tooling
def test_light_runs_use_their_own_pool(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(heavy_slot.host_load_guard, "current_decision", lambda: (
        type("S", (), {"mem_available_bytes": 200 * heavy_slot.host_load_guard.GIB})(),
        type("D", (), {"overloaded": False, "reasons": []})()))
    monkeypatch.setattr(heavy_slot, "SETTLE_SECONDS", 0)
    heavy = [heavy_slot.admit(tmp_path, "heavy", "cargo build")[0] for _ in range(heavy_slot.MAX_SLOTS)]
    assert all(heavy)
    assert heavy_slot.admit(tmp_path, "heavy", "cargo build")[0] is None
    light, why = heavy_slot.admit(tmp_path, "browser", "npx playwright test")
    assert light is not None, why
    for fd, _ in [*heavy, light]:
        os.close(fd)


# contract-test: tooling
def test_old_slot_files_count_as_a_full_heavy_cap() -> None:
    record = heavy_slot._slot_record("cargo test -p openmates-sdk")
    assert record["cap"] == heavy_slot.MEMORY_MAX_BYTES
