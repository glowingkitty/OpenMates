#!/usr/bin/env python3
# contract-test-file: tooling
"""Contracts for the Bash guard's heavy local build/test/benchmark block.

Builds, tests and benchmarks run in isolated CI or through the resource-limited heavy_slot wrapper.
Run: python3 -m pytest scripts/tests/test_heavy_local_guard.py
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASH_GUARD = PROJECT_ROOT / ".claude" / "hooks" / "bash-guard.sh"
CPUS = os.cpu_count() or 1


def run_bash_guard(command: str, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    return subprocess.run(["bash", str(BASH_GUARD)], input=json.dumps(payload), text=True,
                          capture_output=True, cwd=PROJECT_ROOT, env=env, check=False)


def fake_host_env(tmp_path: Path, *, overloaded: bool) -> dict:
    proc = tmp_path / "proc"
    (proc / "pressure").mkdir(parents=True)
    load = 5 * CPUS if overloaded else 0.1
    mem_kb = (1 if overloaded else 20) * 1024 * 1024
    (proc / "loadavg").write_text(f"{load} 1 1 1/1 1\n")
    (proc / "meminfo").write_text(f"MemAvailable: {mem_kb} kB\n")
    (proc / "pressure" / "memory").write_text("some avg10=0.00 avg60=0 avg300=0 total=0\n")
    env = {k: v for k, v in os.environ.items()
           if k not in {"OPENMATES_ALLOW_LOCAL_HEAVY", "OPENMATES_IGNORE_HOST_LOAD"}}
    env["OPENMATES_HOST_LOAD_PROC"] = str(proc)
    env["OPENMATES_HOST_LOAD_STATE_DIR"] = str(tmp_path / "state")
    return env


@pytest.mark.parametrize(
    "command",
    [
        "cargo build -p openmates_sdk",
        "cargo +nightly test --workspace",
        "cargo check",
        "cargo clippy --all-targets",
        "cargo run --bin openmates",
        "cargo bench",
        "env RUSTFLAGS=-g cargo test",
        "bash -c 'cargo build --release'",
        "rustc main.rs",
        "wasm-pack build frontend/packages/x",
        "wasm-bindgen target/x.wasm",
        "vitest run",
        "pnpm vitest run",
        "npx vitest run",
        "pnpm exec vitest run",
        "playwright test",
        "npx playwright test foo.spec.ts",
        "pnpm build",
        "pnpm -C frontend/apps/web_app build",
        "cd frontend/apps/web_app && pnpm test",
        "npm run build",
        "npx vite build",
        "npx svelte-kit build",
        "node scripts/web_rust_bench/bench.cjs",
        "python3 -m scripts.rust_bench",
        "node scripts/benchmark_chat_latency_web.cjs",
        "chromium --headless=new about:blank",
    ],
)
def test_heavy_local_commands_are_blocked_with_ci_pointer(command: str, tmp_path: Path) -> None:
    result = run_bash_guard(command, fake_host_env(tmp_path, overloaded=False))
    assert result.returncode == 2, command
    reason = json.loads(result.stderr)["reason"]
    assert "ci_coordinator.py submit" in reason and "rust-check" in reason
    assert "scripts/heavy_slot.py run --" in reason


def test_heavy_command_through_slot_wrapper_is_allowed(tmp_path: Path) -> None:
    result = run_bash_guard(
        "python3 scripts/heavy_slot.py run -- cargo build --release",
        fake_host_env(tmp_path, overloaded=False),
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "cargo fmt --all -- --check",
        "cargo metadata --format-version 1",
        "cargo tree -p openmates_sdk",
        "rustfmt src/lib.rs",
        "cargo --version",
        "pnpm install",
        "python3 -m pytest scripts/tests/test_host_load_guard.py",
        "python3 scripts/ci_coordinator.py submit --mode rust-check",
        "git status",
    ],
)
def test_light_commands_stay_allowed_on_a_healthy_host(command: str, tmp_path: Path) -> None:
    assert run_bash_guard(command, fake_host_env(tmp_path, overloaded=False)).returncode == 0, command


def test_real_inference_override_is_logged_and_still_load_gated(tmp_path: Path) -> None:
    command = "OPENMATES_ALLOW_LOCAL_HEAVY=real-inference cargo run --bin openmates"
    healthy = fake_host_env(tmp_path / "ok", overloaded=False)
    assert run_bash_guard(command, healthy).returncode == 0
    events = (Path(healthy["OPENMATES_HOST_LOAD_STATE_DIR"]) / "events.jsonl").read_text()
    assert "heavy_local_override" in events

    busy = fake_host_env(tmp_path / "busy", overloaded=True)
    result = run_bash_guard(command, busy)
    assert result.returncode == 2
    assert "overloaded" in json.loads(result.stderr)["reason"]


def test_pytest_is_refused_only_while_overloaded(tmp_path: Path) -> None:
    result = run_bash_guard("python3 -m pytest scripts/tests", fake_host_env(tmp_path, overloaded=True))
    assert result.returncode == 2
    assert "host_load_guard.py wait" in json.loads(result.stderr)["reason"]
