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


# contract-test: tooling
def test_memory_alert_only_near_the_sandbox_limit_or_on_oom():
    calm = {"mode": "e2e", "specs": ["a.spec.ts"], "peak_memory_mb": 5201, "oom_kills": 0}
    assert runner.memory_alert(calm) is None
    near = {**calm, "peak_memory_mb": runner.MEMORY_ALERT_MB}
    assert "a.spec.ts" in runner.memory_alert(near) and "8192 MB" in runner.memory_alert(near)
    assert runner.memory_alert({**calm, "oom_kills": 1}) is not None


# contract-test: tooling
def test_launch_records_oom_and_reports_heavy_spec(tmp_path, monkeypatch, env):
    class OomSandbox(FakeSandbox):
        def _run(self, cmd, **kw):
            if cmd == runner.OOM_PROBE:
                return SimpleNamespace(stdout="2\n")
            return super()._run(cmd, **kw)

    posted = []
    monkeypatch.setattr(runner.agent_question, "configured_value",
                        lambda root, key: "https://hooks.example.org/x" if key == "DISCORD_WEBHOOK_DEV_NIGHTLY" else "")
    monkeypatch.setattr(runner.discord_webhook, "post_message",
                        lambda **kw: posted.append(kw) or {"message_id": "1"})
    runner.write_state("openmates-e2b-t", mode="e2e", specs=["heavy.spec.ts"])
    sandbox = OomSandbox(["run worker 7600", "exit noworker 3000"])
    clock = Clock()
    runner.run_launch(launch_args(tmp_path), create_sandbox=lambda *_a: sandbox, now=clock.now, sleep=clock.sleep)
    state = runner.read_state("openmates-e2b-t")
    assert state["oom_kills"] == 2 and state["peak_memory_mb"] == 7600
    assert sandbox.killed and env["slot"].released
    assert len(posted) == 1 and "heavy.spec.ts" in posted[0]["payload"]["content"]
    alert = (tmp_path / "memory-alerts.jsonl").read_text().strip().splitlines()
    assert len(alert) == 1 and '"notified": true' in alert[0]


# ---- dependency-hash templates ------------------------------------------------

import ci_e2b_template as tpl  # noqa: E402

INPUTS = {"files": {"pnpm-lock.yaml": "a"}, "node": "24.22.1", "pnpm": "10.23.0", "playwright": "1.60.0",
          "rust": "1.98.1", "wasm_bindgen": "0.2.129", "recorder": ["ffmpeg"]}


def test_hash_stable_and_sensitive():
    base = runner.base_steps()
    one = tpl.definition_digest(base, INPUTS, "2.338.2")
    assert one == tpl.definition_digest(base, dict(reversed(list(INPUTS.items()))), "2.338.2")
    assert len(one) == 12 and tpl.is_deps_alias(tpl.alias_for(one))
    assert one != tpl.definition_digest(base, {**INPUTS, "playwright": "1.61.0"}, "2.338.2")
    assert one != tpl.definition_digest(base, INPUTS, "2.339.0")
    assert one != tpl.definition_digest(base[:-1], INPUTS, "2.338.2")


def test_playwright_node_pnpm_parsing():
    assert tpl.playwright_version("x\n  '@playwright/test@1.60.0':\n    y") == "1.60.0"
    assert tpl.node_version('A = 1\nNODE_VERSION = "v24.22.1"\n') == "24.22.1"
    assert tpl.package_manager('{"packageManager": "pnpm@10.23.0"}') == "10.23.0"


def test_choose_template_on_off_and_fallback():
    alias = lambda *_a: "openmates-ci-runner-abcdef012345"  # noqa: E731
    on = lambda owner: frozenset({"e2b-template"})  # noqa: E731
    assert runner.choose_template("o", "sha", enabled=on, exists=lambda n: True, alias=alias) == (alias(), "deps template")
    assert runner.choose_template("o", "sha", enabled=lambda o: frozenset(), exists=lambda n: True, alias=alias)[0] == runner.TEMPLATE_ALIAS
    name, why = runner.choose_template("o", "sha", enabled=on, exists=lambda n: False, alias=alias)
    assert name == runner.TEMPLATE_ALIAS and "not built" in why
    def boom(*_a):
        raise ValueError("no lockfile")
    assert runner.choose_template("o", "sha", enabled=on, exists=lambda n: True, alias=boom)[0] == runner.TEMPLATE_ALIAS
    assert runner.choose_template("", "sha", enabled=on)[0] == runner.TEMPLATE_ALIAS


def test_launch_records_template(tmp_path, env, monkeypatch):
    monkeypatch.setattr(runner, "choose_template", lambda owner, source: ("openmates-ci-runner-aaaaaaaaaaaa", "deps template"))
    seen = []
    box = FakeSandbox(["exit worker 1"])
    runner.run_launch(launch_args(tmp_path, owner="o", source="s"), create_sandbox=lambda *a: seen.append(a[2]) or box,
                      now=Clock().now, sleep=lambda *_: None)
    assert seen == ["openmates-ci-runner-aaaaaaaaaaaa"]
    assert runner.read_state("openmates-e2b-t")["template"] == "openmates-ci-runner-aaaaaaaaaaaa"


def test_prune_keeps_newest_three_and_only_deps_templates():
    rows = [{"id": f"t{i}", "alias": f"openmates-ci-runner-{i:012x}", "created": f"2026-11-0{i}"} for i in range(1, 6)]
    rows.append({"id": "plain", "alias": "openmates-ci-runner", "created": "2020"})
    gone = []
    removed = tpl.prune(rows, 3, gone.append)
    assert gone == ["t2", "t1"] and len(removed) == 2
