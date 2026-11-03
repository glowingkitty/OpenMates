#!/usr/bin/env python3
# contract-test-file: tooling
"""Contracts for the host load gate (thresholds, hysteresis, Claude hooks).

Run: python3 -m pytest scripts/tests/test_host_load_guard.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import host_load_guard as guard  # noqa: E402 - path set up above

GIB = guard.GIB
HOOK = PROJECT_ROOT / ".claude" / "hooks" / "host-load-gate.sh"
CPUS = os.cpu_count() or 1


def sample(mem_gib: float = 20, load_per_cpu: float = 0.5, psi: float | None = 1.0) -> guard.Sample:
    return guard.Sample(load1=load_per_cpu * 16, load5=0, cpus=16,
                        mem_available_bytes=int(mem_gib * GIB), mem_psi_some_avg10=psi)


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"mem_gib": 2.9}, "MemAvailable"),
        ({"load_per_cpu": 3.1}, "load1"),
        ({"psi": 21}, "memory PSI"),
    ],
)
def test_any_block_threshold_trips(kwargs: dict, fragment: str) -> None:
    decision = guard.evaluate(sample(**kwargs), was_overloaded=False)
    assert decision.overloaded
    assert any(fragment in reason for reason in decision.reasons)


def test_healthy_host_is_not_overloaded_and_missing_psi_is_ignored() -> None:
    assert not guard.evaluate(sample(psi=None), was_overloaded=False).overloaded
    # Between block and resume thresholds: OK when not previously overloaded.
    assert not guard.evaluate(sample(mem_gib=4, load_per_cpu=2), was_overloaded=False).overloaded


def test_hysteresis_holds_until_every_resume_threshold_is_met() -> None:
    assert guard.evaluate(sample(mem_gib=4, load_per_cpu=1), was_overloaded=True).overloaded
    assert guard.evaluate(sample(mem_gib=8, load_per_cpu=2), was_overloaded=True).overloaded
    assert guard.evaluate(sample(mem_gib=8, load_per_cpu=1, psi=15), was_overloaded=True).overloaded
    assert not guard.evaluate(sample(mem_gib=5.1, load_per_cpu=1.4, psi=9), was_overloaded=True).overloaded


def test_proc_parsers() -> None:
    assert guard.parse_loadavg("43.39 214.61 235.54 32/3420 762557\n") == (43.39, 214.61)
    assert guard.parse_mem_available("MemTotal: 1 kB\nMemAvailable:    3382884 kB\n") == 3382884 * 1024
    psi = "some avg10=2.37 avg60=4.31 avg300=46.48 total=1\nfull avg10=0.93 avg60=3 avg300=3 total=2\n"
    assert guard.parse_psi_some_avg10(psi) == 2.37


def test_canonical_root_resolves_linked_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {tmp_path / 'main' / '.git' / 'worktrees' / 'wt'}\n")
    assert guard.canonical_root(worktree) == tmp_path / "main"


def fake_proc(root: Path, *, mem_gib: float, load_per_cpu: float, psi: float) -> Path:
    proc = root / "proc"
    (proc / "pressure").mkdir(parents=True, exist_ok=True)
    (proc / "loadavg").write_text(f"{load_per_cpu * CPUS:.2f} 1.00 1.00 1/100 1\n")
    (proc / "meminfo").write_text(f"MemAvailable: {int(mem_gib * 1024 * 1024)} kB\n")
    (proc / "pressure" / "memory").write_text(f"some avg10={psi} avg60=0 avg300=0 total=0\n")
    return proc


def run_hook(event: str, payload: dict, env: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(HOOK), event], input=json.dumps(payload), text=True,
                          capture_output=True, env=env, check=False)


@pytest.fixture
def overloaded_env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k != guard.IGNORE_ENV}
    env["OPENMATES_HOST_LOAD_PROC"] = str(fake_proc(tmp_path, mem_gib=1, load_per_cpu=5, psi=40))
    env["OPENMATES_HOST_LOAD_STATE_DIR"] = str(tmp_path / "state")
    return env


def test_hook_denies_agent_spawn_and_blocks_prompt_while_overloaded(overloaded_env: dict) -> None:
    agent = run_hook("pre-agent", {"tool_name": "Agent"}, overloaded_env)
    out = json.loads(agent.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "host_load_guard.py wait" in out["permissionDecisionReason"]

    prompt = json.loads(run_hook("prompt", {"prompt": "do work"}, overloaded_env).stdout)
    assert prompt["decision"] == "block"

    start = json.loads(run_hook("session-start", {}, overloaded_env).stdout)
    assert "overloaded" in start["hookSpecificOutput"]["additionalContext"]
    events = (Path(overloaded_env["OPENMATES_HOST_LOAD_STATE_DIR"]) / "events.jsonl").read_text()
    assert "overload_start" in events


def test_prompt_override_marker_passes_and_is_logged(overloaded_env: dict) -> None:
    result = run_hook("prompt", {"prompt": f"status? {guard.PROMPT_OVERRIDE_MARKER}"}, overloaded_env)
    assert result.returncode == 0 and result.stdout == ""
    events = (Path(overloaded_env["OPENMATES_HOST_LOAD_STATE_DIR"]) / "events.jsonl").read_text()
    assert '"event": "override"' in events


def test_hook_is_silent_when_healthy_and_hysteresis_state_persists(tmp_path: Path, overloaded_env: dict) -> None:
    run_hook("pre-agent", {}, overloaded_env)  # records overloaded state
    env = dict(overloaded_env)
    # Between thresholds: still blocked because the host was overloaded.
    env["OPENMATES_HOST_LOAD_PROC"] = str(fake_proc(tmp_path / "mid", mem_gib=4, load_per_cpu=1, psi=1))
    assert "deny" in run_hook("pre-agent", {}, env).stdout
    env["OPENMATES_HOST_LOAD_PROC"] = str(fake_proc(tmp_path / "ok", mem_gib=8, load_per_cpu=0.5, psi=1))
    healthy = run_hook("pre-agent", {}, env)
    assert healthy.returncode == 0 and healthy.stdout == ""
    assert "overload_end" in (Path(env["OPENMATES_HOST_LOAD_STATE_DIR"]) / "events.jsonl").read_text()
