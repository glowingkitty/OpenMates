# contract-test-file: tooling
"""Private producer/launcher guards, with no product traffic or account creation."""

import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    from scripts import ci_environment

    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    filename = Path(__file__).parents[1] / "ci_run_tests.py"
    spec = importlib.util.spec_from_file_location(
        "ci_pinned_node_unit_runner", filename
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def receipt():
    return {
        "schema_version": 1,
        "producer": "trusted-node-runtime-v1",
        "node_version": "v24.22.1",
        "sha256": "a" * 64,
        "producer_sha256": "b" * 64,
        "architecture": "arm64",
        "source": {
            key: True
            for key in (
                "proc_identity",
                "toolcache_supplier",
                "stable",
                "regular_elf",
                "single_link",
                "owner_admitted",
            )
        },
        "destination": {
            key: True
            for key in (
                "fresh_inode",
                "private_directory",
                "owner_current",
                "mode_0700",
                "single_link",
                "fsynced",
                "hash_matches",
            )
        },
    }


def test_attestation_uses_pinned_process_without_preload_and_retains_redacted_receipt(
    runner, tmp_path, monkeypatch
):
    node = "/tmp/openmates-ci-node-Synthetic/node"
    monkeypatch.setenv("OPENMATES_CI_NODE", node)
    monkeypatch.setenv("NODE_OPTIONS", "--require=untrusted.js")
    monkeypatch.setenv("NODE_PATH", "/candidate/node_modules")
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(receipt()))

    monkeypatch.setattr(runner.subprocess, "run", run)
    runner.verify_pinned_node_runtime()
    command, options = calls[0]
    assert command[0] == node and command[-1] == "verify"
    assert "NODE_OPTIONS" not in options["env"] and "NODE_PATH" not in options["env"]
    assert options["timeout"] == 15
    assert os.environ["PATH"].split(os.pathsep)[0] == str(Path(node).parent)
    assert os.environ["npm_node_execpath"] == node and os.environ["NODE"] == node
    assert json.loads((tmp_path / "ci-node-runtime.json").read_text()) == receipt()


@pytest.mark.parametrize(
    "failure", ["missing", "bad_path", "verify_failed", "source_false", "node22"]
)
def test_runtime_refusal_stops_main_before_any_account_or_browser(
    runner, tmp_path, monkeypatch, failure
):
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setenv("CI_TEST_MODE", "e2e")
    monkeypatch.setenv("CI_SPECS_JSON", '["synthetic.spec.ts"]')
    monkeypatch.setenv("GITHUB_RUN_ID", "unit")
    monkeypatch.setenv("OPENMATES_CI_NODE", "/tmp/openmates-ci-node-Synthetic/node")
    if failure == "missing":
        monkeypatch.delenv("OPENMATES_CI_NODE")
    if failure == "bad_path":
        monkeypatch.setenv("OPENMATES_CI_NODE", "/candidate/node")
    proof = receipt()
    if failure == "source_false":
        proof["source"]["proc_identity"] = False
    if failure == "node22":
        proof["node_version"] = "v22.1.0"
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=int(failure == "verify_failed"), stdout=json.dumps(proof)
        ),
    )
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *a, **k: "a" * 40)
    monkeypatch.setattr(
        runner,
        "run_e2e",
        lambda *a, **k: pytest.fail("Runtime refusal must precede accounts/browser"),
    )
    monkeypatch.setattr(
        runner,
        "provision_account",
        lambda *a, **k: pytest.fail("No account on runtime refusal"),
    )
    assert runner.main() == 1
    result = json.loads((tmp_path / "ci-results.json").read_text())
    assert result["results"] == [] and result["success"] is False


def test_direct_playwright_launcher_ignores_path_shadowing(
    runner, tmp_path, monkeypatch
):
    web = tmp_path / "web"
    cli = web / "node_modules/@playwright/test/cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("// synthetic CLI")
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "node").write_text("wrong")
    monkeypatch.setenv("PATH", str(shadow))
    monkeypatch.setenv("OPENMATES_CI_NODE", "/tmp/openmates-ci-node-Synthetic/node")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "WEB", web)
    assert runner.playwright_command() == [
        "/tmp/openmates-ci-node-Synthetic/node",
        str(cli),
    ]
    cli.unlink()
    cli.symlink_to(Path(__file__))
    with pytest.raises(RuntimeError, match="unavailable"):
        runner.playwright_command()


def test_workflow_trust_order_cache_repin_and_always_cleanup():
    text = (
        Path(__file__).parents[2] / ".github/workflows/isolated-tests.yml"
    ).read_text()
    stage = text.index("Stage attested runner Node")
    assert (
        text.index("actions/setup-node@v4")
        < stage
        < text.index("Reconstruct and verify exact detached source")
    )
    assert stage < text.index("pnpm/action-setup@v4") < text.index("cache: pnpm")
    assert (
        text.index("cache: pnpm")
        < text.index("Restore pinned Node")
        < text.index("Install workspace dependencies")
    )
    assert 'env -u NODE_OPTIONS -u NODE_PATH "$OPENMATES_CI_NODE"' in text
    assert "if: always() && env.OPENMATES_CI_NODE_STATE != ''" in text
    assert "subject/test-results/ci-node-runtime.json" in text
