# contract-test-file: tooling
"""Host-resources guard (scripts/host_resources.py): self-heal first, one alert per incident.

Run: python3 -m pytest scripts/tests/test_host_resources.py
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import host_load_guard as guard  # noqa: E402  (path set above)
import host_resources as res  # noqa: E402

GIB = guard.GIB
NOW = 1_800_000_000.0


def sample(mem_gib: float) -> guard.Sample:
    return guard.Sample(load1=1, load5=1, cpus=16, mem_available_bytes=int(mem_gib * GIB), mem_psi_some_avg10=0)


OVERLOADED = guard.Decision(True, ["memory PSI some avg10 48 > 20"], True)
HEALTHY = guard.Decision(False, [], False)


class Calls:
    def __init__(self) -> None:
        self.scripts: list[tuple[str, ...]] = []
        self.alerts: list[str] = []


@pytest.fixture
def calls(monkeypatch) -> Calls:
    record = Calls()

    def fake_script(*args):
        record.scripts.append(args)
        out = "stopped Idle chat (abc, pid 1): idle 30 min\n" if "reap" in args else "released Held chat (def)\n"
        return type("Result", (), {"returncode": 0, "stdout": out, "stderr": ""})()

    def fake_alert(problem, healed, directory):
        record.alerts.append(f"{problem} | {healed}")
        return True

    monkeypatch.setattr(res, "_script", fake_script)
    monkeypatch.setattr(res, "alert", fake_alert)
    monkeypatch.setattr(res, "disk_problem", lambda path: None)
    monkeypatch.setattr(res, "_service_active", lambda unit: True)
    return record


def test_memory_overload_stops_idle_chats_at_once_and_at_most_every_five_minutes(tmp_path, calls):
    res.tick(sample(1), OVERLOADED, tmp_path, tmp_path, now=NOW)
    res.tick(sample(1), OVERLOADED, tmp_path, tmp_path, now=NOW + 60)
    res.tick(sample(1), OVERLOADED, tmp_path, tmp_path, now=NOW + res.REAP_INTERVAL + 1)
    assert calls.scripts == [("claude_idle_chats.py", "reap", "--pressure")] * 2
    assert '"event": "resources_reap"' in (tmp_path / "events.jsonl").read_text()


def test_healthy_host_with_headroom_releases_a_few_held_prompts_per_tick(tmp_path, calls):
    res.tick(sample(3), HEALTHY, tmp_path, tmp_path, now=NOW)  # below the release headroom
    assert calls.scripts == []
    res.tick(sample(6), HEALTHY, tmp_path, tmp_path, now=NOW)
    assert calls.scripts == [("claude_idle_chats.py", "release", "--limit", str(res.RELEASE_PER_TICK))]


def test_alert_only_after_self_healing_failed_for_twenty_minutes_and_once_per_incident(tmp_path, calls):
    for minute in range(0, 45, 5):
        res.tick(sample(1), OVERLOADED, tmp_path, tmp_path, now=NOW + minute * 60)
    assert len(calls.alerts) == 1
    assert "memory PSI" in calls.alerts[0] and "stopped 1 idle chats" in calls.alerts[0]
    res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW + 50 * 60)
    events = (tmp_path / "events.jsonl").read_text()
    assert '"event": "resources_recovered"' in events
    for minute in range(60, 85, 5):  # a new incident may alert again
        res.tick(sample(1), OVERLOADED, tmp_path, tmp_path, now=NOW + minute * 60)
    assert len(calls.alerts) == 2


def test_short_overload_that_heals_never_alerts(tmp_path, calls):
    res.tick(sample(1), OVERLOADED, tmp_path, tmp_path, now=NOW)
    res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW + 10 * 60)
    res.tick(sample(1), OVERLOADED, tmp_path, tmp_path, now=NOW + 15 * 60)
    res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW + 30 * 60)
    assert calls.alerts == []


def test_sustained_disk_problem_alerts_and_names_a_stopped_disk_coordinator(tmp_path, calls, monkeypatch):
    monkeypatch.setattr(res, "disk_problem", lambda path: "disk 95% used, 12 GiB free")
    monkeypatch.setattr(res, "_service_active", lambda unit: False)
    for minute in range(0, 25, 5):
        res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW + minute * 60)
    assert len(calls.alerts) == 1
    assert "openmates-disk-coordinator.service is not running" in calls.alerts[0]
    state = json.loads((tmp_path / "resources.json").read_text())
    assert state["disk"]["alerted"] is True


def test_disk_problem_uses_free_space_and_percent_limits(tmp_path):
    assert res.disk_problem(tmp_path, min_free=0, max_percent=100.0) is None
    assert "GiB free" in res.disk_problem(tmp_path, min_free=10**18, max_percent=100.0)
    assert "% used" in res.disk_problem(tmp_path, min_free=0, max_percent=0.0)


def test_monitor_hands_over_to_the_resources_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENMATES_HOST_LOAD_STATE_DIR", str(tmp_path))
    seen = []
    monkeypatch.setattr(res, "tick", lambda sample, decision: seen.append(decision.overloaded) or 0)
    assert guard.cmd_monitor() == 0
    assert len(seen) == 1
