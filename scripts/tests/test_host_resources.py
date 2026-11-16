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
        self.watches = 0  # claude_chat_inputs.py watch runs
        self.zellij: list[tuple[str, ...]] = []  # zellij actions (never the real server)
        self.panes = [  # list-panes --json --all of a chat session with bars
            {"id": 0, "is_plugin": True, "plugin_url": "zellij:link"},
            {"id": 1, "is_plugin": True, "plugin_url": "compact-bar"},
            {"id": 0, "is_plugin": False, "plugin_url": None},
            {"id": 2, "is_plugin": True, "plugin_url": "compact-bar"},
            {"id": 1, "is_plugin": False, "plugin_url": None},
        ]


@pytest.fixture
def calls(monkeypatch) -> Calls:
    record = Calls()

    def fake_script(*args):
        if args[0] == "claude_chat_inputs.py":
            record.watches += 1
            return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        record.scripts.append(args)
        out = "stopped Idle chat (abc, pid 1): idle 30 min\n" if "reap" in args else "released Held chat (def)\n"
        return type("Result", (), {"returncode": 0, "stdout": out, "stderr": ""})()

    def fake_alert(problem, healed, directory, after=res.ALERT_AFTER_SECONDS, recommendation=""):
        record.alerts.append(f"{problem} | {healed}")
        return True

    monkeypatch.setattr(res, "_script", fake_script)
    monkeypatch.setattr(res, "alert", fake_alert)
    monkeypatch.setattr(res, "disk_problem", lambda path: None)
    monkeypatch.setattr(res, "_service_active", lambda unit: True)
    def fake_zellij(session, *args):
        record.zellij.append((session, *args))
        if args[0] == "list-panes":
            return type("Result", (), {"returncode": 0, "stdout": json.dumps(record.panes), "stderr": ""})()
        if args[0] == "close-pane":
            record.panes = [p for p in record.panes if not (p["is_plugin"] and f"plugin_{p['id']}" == args[2])]
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(res, "zellij_servers", lambda: {})
    monkeypatch.setattr(res, "_zellij_action", fake_zellij)
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


def test_every_tick_refreshes_the_input_box_watch(tmp_path, calls):
    res.tick(sample(1), OVERLOADED, tmp_path, tmp_path, now=NOW)
    res.tick(sample(6), HEALTHY, tmp_path, tmp_path, now=NOW + 60)
    assert calls.watches == 2


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


def zellij(rss_gib: float, cpu_ticks: int, pid: int = 42) -> dict:
    return {"claude": {"pid": pid, "rss_bytes": int(rss_gib * GIB), "cpu_ticks": cpu_ticks}}


def test_zellij_server_over_two_gib_or_two_hundred_percent_cpu_is_a_problem():
    state: dict = {}
    assert res.zellij_problem(state, NOW, zellij(0.3, 0), clock_ticks=100) is None
    # 60 s later 6,000 more ticks at 100 ticks/s: 100% CPU, under the limit
    assert res.zellij_problem(state, NOW + 60, zellij(0.3, 6_000), clock_ticks=100) is None
    busy = res.zellij_problem(state, NOW + 120, zellij(0.3, 6_000 + 60_000), clock_ticks=100)
    assert busy is not None and "1000% CPU" in busy and "`claude`" in busy
    big = res.zellij_problem(state, NOW + 180, zellij(7.0, 66_000), clock_ticks=100)
    assert big is not None and "7.0 GiB RAM" in big and "CPU" not in big
    # a restarted server (new pid) has no CPU baseline yet
    assert res.zellij_problem(state, NOW + 240, zellij(0.1, 999_999, pid=43), clock_ticks=100) is None


def test_zellij_over_limit_alerts_once_after_five_minutes(tmp_path, calls, monkeypatch):
    monkeypatch.setattr(res, "zellij_servers", lambda: zellij(3.0, 0))
    for minute in range(0, 12):
        res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW + minute * 60)
    assert len(calls.alerts) == 1 and "3.0 GiB RAM" in calls.alerts[0]
    # healing ran first: the two bars closed on the first tick, nothing left later
    assert "no bar plugins left in `claude`" in calls.alerts[0]
    monkeypatch.setattr(res, "zellij_servers", lambda: zellij(0.4, 0))
    res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW + 13 * 60)
    events = (tmp_path / "events.jsonl").read_text()
    assert '"event": "zellij_over_limit"' in events and '"kind": "zellij"' in events


def test_zellij_over_limit_closes_bar_plugins_but_never_a_terminal_pane(tmp_path, calls, monkeypatch):
    """TASK-6763: the per-tab compact-bar plugins fell behind on events and drove the server to
    1,400% CPU; closing them is the safe self-healing step. Chats are terminal panes."""
    monkeypatch.setattr(res, "zellij_servers", lambda: zellij(0.3, 0))
    res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW)
    assert calls.zellij == []  # first sample: no CPU baseline, healthy, nothing touched
    monkeypatch.setattr(res, "zellij_servers", lambda: zellij(0.3, 30_000))  # 500% CPU at 100 ticks/s
    res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW + 60)
    closes = [c for c in calls.zellij if c[1] == "close-pane"]
    assert closes == [("claude", "close-pane", "--pane-id", "plugin_1"),
                      ("claude", "close-pane", "--pane-id", "plugin_2")]
    assert all(not c[-1].startswith("terminal_") for c in closes)
    assert [p["plugin_url"] for p in calls.panes if p["is_plugin"]] == ["zellij:link"]
    assert sum(not p["is_plugin"] for p in calls.panes) == 2
    events = (tmp_path / "events.jsonl").read_text()
    assert '"event": "zellij_bars_closed"' in events and "plugin_2" in events
    assert calls.alerts == []  # healing runs at once; the push waits ZELLIJ_ALERT_AFTER_SECONDS


def test_zellij_healing_leaves_healthy_sessions_alone(tmp_path, calls, monkeypatch):
    monkeypatch.setattr(res, "zellij_servers", lambda: zellij(0.3, 0))
    for minute in range(0, 5):
        res.tick(sample(8), HEALTHY, tmp_path, tmp_path, now=NOW + minute * 60)
    assert calls.zellij == []


def test_zellij_servers_reads_session_name_rss_and_cpu_from_proc(tmp_path):
    pid = tmp_path / "123"
    pid.mkdir()
    (pid / "cmdline").write_bytes(b"/usr/local/bin/zellij\0--server\0/run/user/1/zellij/contract_version_1/claude\0")
    (pid / "stat").write_text("123 (zellij) S 1 2 3 4 5 6 7 8 9 10 700 300 0 0")
    (pid / "status").write_text("Name:\tzellij\nVmRSS:\t  2048 kB\n")
    other = tmp_path / "124"
    other.mkdir()
    (other / "cmdline").write_bytes(b"/usr/local/bin/zellij\0attach\0claude\0")
    assert res.zellij_servers(tmp_path) == {"claude": {"pid": 123, "rss_bytes": 2048 * 1024, "cpu_ticks": 1000}}
