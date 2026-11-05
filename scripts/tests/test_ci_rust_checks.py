# contract-test-file: tooling
"""Rust crate check runner: blocking/report-only exit codes, excerpts, summary."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ci_rust_checks", ROOT / "scripts/ci_rust_checks.py")
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


@pytest.fixture
def results(tmp_path, monkeypatch):
    monkeypatch.setenv("RUST_CI_RESULTS", str(tmp_path / "results"))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    return tmp_path


def failing(text: str, code: int = 101) -> list[str]:
    return [sys.executable, "-c", f"import sys; print({text!r}); sys.exit({code})"]


def test_blocking_failure_exits_and_summary_fails_with_excerpt(results, capsys):
    cargo_output = "\n".join(
        ["   Compiling openmates-sdk v0.1.0", "error[E0308]: mismatched types", "  --> src/lib.rs:3:5"]
        + [f"noise {i}" for i in range(200)]
        + ["test result: FAILED. 1 passed; 1 failed"]
    )
    assert checks.main(["run", "--name", "sdk test", "--", *failing(cargo_output)]) == 101
    out = capsys.readouterr().out
    assert "::group::Failure excerpt: sdk test" in out
    assert "::error title=sdk test failed::error[E0308]: mismatched types" in out
    assert "noise 150" not in out.split("::group::", 1)[1].split("::endgroup::")[0]

    assert checks.main(["summary"]) == 1
    summary = (results / "summary.md").read_text()
    assert "| `sdk test` | blocking | FAILED (101) |" in summary
    assert "error[E0308]: mismatched types" in summary and "test result: FAILED" in summary


def test_report_only_failure_does_not_fail_step_or_summary(results, capsys):
    output = "warning: unused variable: `x`\nerror: could not compile `openmates-sdk`"
    assert checks.main(["run", "--name", "sdk clippy", "--report-only", "--", *failing(output, 1)]) == 0
    assert "::warning title=sdk clippy failed (report-only)::" in capsys.readouterr().out
    assert checks.main(["run", "--name", "sdk test", "--", sys.executable, "-c", "print('ok')"]) == 0
    assert checks.main(["summary"]) == 0
    summary = (results / "summary.md").read_text()
    assert "| `sdk clippy` | report-only | failing (2 diagnostics) |" in summary
    assert "| `sdk test` | blocking | passed |" in summary


def test_unmatched_failure_falls_back_to_tail(results, capsys):
    lines = "\n".join(f"line {i}" for i in range(100))
    assert checks.main(["run", "--name", "odd", "--", *failing(lines, 2)]) == 2
    group = capsys.readouterr().out.split("::group::", 1)[1]
    assert "line 99" in group and "line 10\n" not in group


def test_missing_command_is_recorded_as_failure(results):
    assert checks.main(["run", "--name", "absent", "--", "/nonexistent/cargo"]) == 127
    assert checks.main(["summary"]) == 1


def test_summary_without_rows_fails(results):
    assert checks.main(["summary"]) == 1


def test_explain_prints_only_failing_receipt_classification(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
    results = tmp_path / "test-results"
    (results / "ci-rust-wasm-private").mkdir(parents=True)
    (results / "ci-results.json").write_text(json.dumps({
        "error": None, "success": False,
        "results": [{"suite": "rust-wasm", "exit_code": 1, "failed_stage": "wasm-build", "failure_code": "deadline"},
                    {"suite": "other", "exit_code": 0}],
    }))
    (results / "ci-rust-wasm.json").write_text(json.dumps({"status": "passed", "secretish": "x"}))
    (results / "ci-rust-wasm-private/cargo-tail.log").write_text("ok\nerror: linking with `cc` failed\n")
    assert checks.main(["explain", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "suite=rust-wasm, failed_stage=wasm-build, failure_code=deadline, exit_code=1" in out
    assert "suite=other" not in out and "secretish" not in out
    assert "error: linking with `cc` failed" in out


def test_rust_workflow_runs_blocking_workspace_checks_and_report_only_lints():
    workflow = yaml.safe_load((ROOT / ".github/workflows/rust.yml").read_text())
    steps = workflow["jobs"]["workspace"]["steps"]
    runs = {step.get("name"): step.get("run", "") for step in steps}

    def blocking(fragment):
        return any(fragment in run and "--report-only" not in run for run in runs.values())

    assert blocking("cargo test --workspace --locked --lib --bins --tests")
    assert blocking("cargo check --locked -p openmates --no-default-features --lib")
    assert blocking("cargo build --locked --release -p openmates --bin openmates")
    assert blocking("-p openmates-browser-bindings --target wasm32-unknown-unknown --lib")
    for fragment in ("cargo fmt --all --check", "cargo clippy --workspace --locked -- -D warnings"):
        assert any(fragment in run and "--report-only" in run for run in runs.values())
    caches = [step for step in steps if str(step.get("uses", "")).startswith("Swatinem/rust-cache@")]
    assert len(caches) == 1 and caches[0]["with"]["workspaces"] == ". -> target"
    assert caches[0]["with"]["cache-on-failure"] == "true"
    assert "Cargo.lock" in workflow[True]["push"]["paths"]
    assert steps[-1]["if"] == "always()" and "ci_rust_checks.py summary" in steps[-1]["run"]
