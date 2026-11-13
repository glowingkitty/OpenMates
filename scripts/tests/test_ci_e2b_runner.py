# contract-test-file: tooling
"""Unit tests for scripts/ci_e2b_runner.py with fakes (no network, no E2B, no GitHub)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_e2b_runner as runner  # noqa: E402

SECRET = "SECRET-JIT-CONFIG"


class FakeSlot:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


class FakeSandbox:
    sandbox_id = "sbx-1"

    def __init__(self, probes):
        self.probes = list(probes)
        self.killed = False
        self.files = SimpleNamespace(write=lambda *_a, **_k: None)
        self.commands = SimpleNamespace(run=self._run)

    def _run(self, cmd, **_kw):
        if cmd == runner.PROBE:
            return SimpleNamespace(stdout=self.probes.pop(0) if self.probes else "run noworker 100")
        return SimpleNamespace(stdout="")

    def kill(self):
        self.killed = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "state_root", lambda: tmp_path)
    calls = {"deleted": [], "spend": [], "slot": FakeSlot()}
    monkeypatch.setattr(runner, "delete_runner", lambda repo, rid: calls["deleted"].append(rid))
    monkeypatch.setattr(runner.e2b_dev_capacity, "try_acquire", lambda *_a, **_k: calls["slot"])
    monkeypatch.setattr(runner.e2b_dev_capacity, "budget_exhausted", lambda *_a, **_k: None)
    monkeypatch.setattr(runner.e2b_dev_capacity, "record_spend",
                        lambda s, c, m: calls["spend"].append(s) or 0.5)
    return calls


def launch_args(tmp_path, **over):
    cfg = tmp_path / "x.cfg"
    cfg.write_text(SECRET)
    base = dict(repo="o/r", label="openmates-e2b-t", runner_id=7, timeout_minutes=5,
                config_file=str(cfg), no_job_seconds=30)
    base.update(over)
    return argparse.Namespace(**base)


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds * 20


def test_job_label_sanitizes_and_limits():
    assert runner.job_label("Abc_12/X") == "openmates-e2b-abc-12-x"
    assert len(runner.job_label("a" * 200)) <= 60
    assert not runner.job_label("a" * 200).endswith("-")


def test_start_failure_deletes_registration_and_hides_config(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "state_root", lambda: tmp_path)
    monkeypatch.setattr(runner, "register_runner", lambda repo, label: (9, label, SECRET))
    deleted, seen = [], {}

    class Proc:
        def poll(self):
            return None

        def kill(self):
            seen["killed"] = True

        def wait(self):
            pass

    def spawn(argv, log):
        seen["argv"] = argv
        seen["cfg"] = Path(argv[argv.index("--config-file") + 1]).read_text()
        return Proc()

    monkeypatch.setattr(runner, "spawn_launcher", spawn)
    monkeypatch.setattr(runner, "delete_runner", lambda repo, rid: deleted.append(rid))
    assert runner.start("o/r", "tok", 5, tmp_path, ready_wait=0.2) is None
    assert deleted == [9] and seen["killed"]
    assert SECRET not in " ".join(seen["argv"])
    assert seen["cfg"] == SECRET


def test_start_success_returns_details(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "state_root", lambda: tmp_path)
    monkeypatch.setattr(runner, "register_runner", lambda repo, label: (9, label, SECRET))

    def spawn(argv, log):
        runner.write_state(runner.job_label("tok"), state="ready", sandbox_id="sbx-9")
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(runner, "spawn_launcher", spawn)
    result = runner.start("o/r", "tok", 5, tmp_path, ready_wait=2)
    assert result["sandbox_id"] == "sbx-9" and result["runner_id"] == 9


@pytest.mark.parametrize("probes,final", [
    (["run worker 900", "exit worker 1200"], "done"),
    (["run noworker 100"] * 50, "timeout"),
    (["run worker 100"] * 400, "timeout"),
])
def test_launch_cleans_up(tmp_path, env, probes, final):
    box = FakeSandbox(probes)
    clock = Clock()
    code = runner.run_launch(launch_args(tmp_path), create_sandbox=lambda *_: box, now=clock.now, sleep=clock.sleep)
    state = runner.read_state("openmates-e2b-t")
    assert state["state"] == final and (code == 0) == (final == "done")
    assert box.killed and env["deleted"] == [7] and len(env["spend"]) == 1 and env["slot"].released
    assert not (tmp_path / "x.cfg").exists()
    if final == "done":
        assert state["peak_memory_mb"] == 1200


def test_launch_no_slot_fails_and_deletes_registration(tmp_path, env, monkeypatch):
    monkeypatch.setattr(runner.e2b_dev_capacity, "try_acquire", lambda *_a, **_k: None)
    assert runner.run_launch(launch_args(tmp_path)) == 1
    assert runner.read_state("openmates-e2b-t")["state"] == "failed" and env["deleted"] == [7]


def test_launch_sandbox_error_cleans_up(tmp_path, env):
    def boom(*_):
        raise RuntimeError("no sandbox")

    assert runner.run_launch(launch_args(tmp_path), create_sandbox=boom) == 1
    assert runner.read_state("openmates-e2b-t")["state"] == "failed"
    assert env["deleted"] == [7] and env["slot"].released and env["spend"] == []


# contract-test: tooling
def test_overflow_switch_is_off_unless_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "state_root", lambda: tmp_path / "e2b")
    assert runner.overflow_enabled() is False
    (tmp_path / "e2b-overflow.json").write_text('{"enabled": "yes"}')
    assert runner.overflow_enabled() is False
    (tmp_path / "e2b-overflow.json").write_text('{"enabled": true}')
    assert runner.overflow_enabled() is True
