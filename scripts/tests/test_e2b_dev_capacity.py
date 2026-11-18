#!/usr/bin/env python3
# contract-test-file: tooling
"""Contracts for the dev E2B cap: 70% of the team limit, queue, daily budget, overrides.

Scope: local slot files and ledger only; no E2B key or network.
Run: python3 -m pytest scripts/tests/test_e2b_dev_capacity.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import e2b_dev_capacity as cap  # noqa: E402 - scripts/ is added to sys.path above


@pytest.fixture(autouse=True)
def state(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setattr(cap.host_load_guard, "state_dir", lambda: tmp_path)
    for name, _ in cap.ENV_OVERRIDES.values():
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_dev_share_is_seventy_percent_of_the_pro_limit() -> None:
    config = cap.settings()
    assert config.team_concurrency_limit == 100
    assert config.dev_slots == 70


def test_limit_is_configurable_by_file_and_env(state: Path, monkeypatch) -> None:
    (state / "e2b-dev-capacity.json").write_text(json.dumps({"team_concurrency_limit": 600}))
    assert cap.settings().dev_slots == 420
    monkeypatch.setenv("OPENMATES_E2B_DEV_SHARE", "0.5")
    assert cap.settings().dev_slots == 300


def test_cap_is_enforced_and_the_queue_times_out(monkeypatch) -> None:
    monkeypatch.setenv("OPENMATES_E2B_TEAM_LIMIT", "3")  # 70% of 3 -> 2 dev slots
    monkeypatch.setattr(cap, "POLL_SECONDS", 0.01)
    first, second = cap.try_acquire("a"), cap.try_acquire("b")
    assert first and second
    assert cap.try_acquire("c") is None
    messages = []
    assert cap.acquire("c", timeout=0.05, announce=messages.append) is None
    assert "waiting in the E2B queue" in messages[0]
    assert len(cap.status()["running"]) == 2
    first.release()
    third = cap.acquire("c", timeout=1)
    assert third is not None
    second.release()
    third.release()


def test_daily_budget_stops_new_runs(monkeypatch) -> None:
    monkeypatch.setenv("OPENMATES_E2B_DAILY_BUDGET_USD", "0.03")
    assert cap.budget_exhausted() is None
    cost = cap.record_spend(240, 8, 8192)  # a 4-minute cargo test at 8 vCPU / 8 GiB
    assert cost == pytest.approx(240 * (8 * 0.000014 + 8 * 0.0000045))
    assert cap.spent_today()["runs"] == 1
    assert cap.budget_exhausted() is not None
