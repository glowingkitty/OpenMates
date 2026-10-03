# contract-test-file: infrastructure
"""The capacity CI opt-in retains the network and credential boundary."""

import pytest
import json
import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path

from scripts import ci_environment
from scripts.ci_environment import compose_profile


def _load_bound_runner(monkeypatch):
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    runner_path = Path(__file__).resolve().parents[1] / "ci_run_tests.py"
    module_spec = importlib.util.spec_from_file_location("_capacity_ci_runner", runner_path)
    assert module_spec and module_spec.loader
    runner = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(runner)
    return runner


def test_capacity_profile_uses_private_network_storage_and_replay_only() -> None:
    profile = compose_profile("candidate-sha", storage_capacity=True, capacity_concurrency=2,
                              account_emails=["ci-one@example.com"])
    services = profile["services"]
    assert services["api"]["environment"]["OPENMATES_STORAGE_CAPACITY_FIXTURES"] == "true"
    assert services["api"]["environment"]["OPENMATES_CI_ISOLATED"] == "1"
    assert services["api"]["environment"]["CHAT_MESSAGE_ARCHIVE_COPY_ENABLED"] == "1"
    assert services["api"]["environment"]["CHAT_MESSAGE_ARCHIVE_READS_ENABLED"] == "1"
    assert services["ai-worker"]["environment"]["OPENMATES_CAPACITY_RECEIPT_ROOT"] == "/app/capacity-receipts"
    assert "--concurrency=2" in services["ai-worker"]["command"]
    assert "object-storage" in services
    assert profile["networks"]["default"]["internal"] is True
    for service in ("api", "core-worker", "ai-worker"):
        assert "OPENAI_API_KEY" not in services[service]["environment"]


def test_capacity_profile_rejects_public_provider_proxy() -> None:
    with pytest.raises(ValueError, match="public-provider"):
        compose_profile("candidate-sha", storage_capacity=True, public_provider=True)


def test_recovery_epoch_fixture_requires_exact_disposable_profile(tmp_path, monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)

    profile = compose_profile(
        "candidate-sha", storage_capacity=True, account_emails=["ci-one@example.com"],
    )
    compose_path = tmp_path / "compose.json"
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    calls = []
    receipt = {"protocol_epoch": 1, "sends_paused": False, "legacy_in_flight": 0}
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: (
        calls.append(args) or SimpleNamespace(stdout=json.dumps(receipt))
    ))
    compose_path.write_text(json.dumps(profile))
    assert runner.activate_isolated_recovery_epoch() == receipt
    assert calls[0][:5] == (
        "exec", "-T", "-e", "OPENMATES_CI_RECOVERY_EPOCH_FIXTURE=1", "api",
    )
    assert "activate_protocol_epoch" in calls[0][-1]
    assert "set_sends_paused" in calls[0][-1]

    profile["services"]["api"]["environment"]["OPENMATES_CI_ISOLATED"] = "0"
    compose_path.write_text(json.dumps(profile))
    with pytest.raises(RuntimeError, match="exact isolated capacity profile"):
        runner.activate_isolated_recovery_epoch()
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("storage-capacity-replay.spec.ts", True),
        ("storage-capacity-target.spec.ts", True),
        ("storage-recovery-replay.spec.ts", True),
        ("startup-sync-contract.spec.ts", False),
        ("shared-chat-bounded-history.spec.ts", False),
    ],
)
def test_epoch_activation_selector_is_exact(spec, expected, monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    assert (spec in runner.CAPACITY_EPOCH_SPECS) is expected


def _runner_with_frontend_files(tmp_path, monkeypatch):
    runner = _load_bound_runner(monkeypatch)
    targets = [
        "frontend/packages/ui/src/services/__tests__/sendersChatMessagesProtocol.test.ts",
        "frontend/apps/web_app/src/lib/selected.test.ts",
        "frontend/packages/openmates-cli/tests/embedCreatorDurability.test.ts",
    ]
    for target in targets:
        file = tmp_path / target
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("// fixture\n")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "WEB", tmp_path / "frontend/apps/web_app")
    monkeypatch.setattr(runner, "RESULTS", tmp_path / "test-results")
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "configure_proof_dimensions", lambda: None)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *args, **kwargs: "a" * 40)
    monkeypatch.setenv("CI_TEST_MODE", "vitest")
    monkeypatch.setenv("GITHUB_RUN_ID", "1")
    return runner, targets


def test_focused_vitest_runs_only_exact_package_targets(tmp_path, monkeypatch) -> None:
    runner, targets = _runner_with_frontend_files(tmp_path, monkeypatch)
    monkeypatch.setenv("CI_SPECS_JSON", json.dumps(targets))
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda command, **kwargs: (
        calls.append((command, kwargs.get("cwd"))) or SimpleNamespace(returncode=0)
    ))
    assert runner.main() == 0
    assert calls[0][0] == ["pnpm", "exec", "svelte-kit", "sync"]
    assert calls[1][0][:5] == ["pnpm", "exec", "vitest", "run",
                               "src/services/__tests__/sendersChatMessagesProtocol.test.ts"]
    assert calls[1][1] == tmp_path / "frontend/packages/ui"
    assert calls[2][0][:5] == ["pnpm", "exec", "vitest", "run", "src/lib/selected.test.ts"]
    assert calls[2][1] == tmp_path / "frontend/apps/web_app"
    assert calls[3][0] == ["pnpm", "run", "build"]
    assert calls[3][1] == tmp_path / "frontend/packages/openmates-cli"
    assert calls[4][0][-1] == "tests/embedCreatorDurability.test.ts"
    assert calls[4][1] == tmp_path / "frontend/packages/openmates-cli"
    assert not any("account-import.test.ts" in command for command, _ in calls)
    receipt = json.loads((runner.RESULTS / "ci-results.json").read_text())
    assert receipt["success"] is True
    assert all(result["selection_mode"] == "focused" for result in receipt["results"])


@pytest.mark.parametrize("target", [
    "../frontend/packages/ui/src/escape.test.ts",
    "/tmp/escape.test.ts",
    "frontend/apps/web_app/tests/storage-capacity-replay.spec.ts",
    "frontend/packages/openmates-cli/tests/not-a-test.ts",
    "frontend/packages/ui/src/services/__tests__/missing.test.ts",
    "frontend/packages/ui/src/services/__tests__/bad.test.ts/../selected.test.ts",
])
def test_focused_vitest_rejects_unapproved_or_missing_target(tmp_path, monkeypatch, target) -> None:
    runner, _ = _runner_with_frontend_files(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Vitest selection"):
        runner.validate_vitest_targets([target], root=tmp_path)


def test_empty_vitest_selection_preserves_existing_full_suite(tmp_path, monkeypatch) -> None:
    runner, _ = _runner_with_frontend_files(tmp_path, monkeypatch)
    monkeypatch.setenv("CI_SPECS_JSON", "[]")
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda command, **kwargs: (
        calls.append(command) or SimpleNamespace(returncode=0)
    ))
    assert runner.main() == 0
    assert sum(command[:4] == ["pnpm", "exec", "vitest", "run"] for command in calls) == 2
    assert any("tests/account-import.test.ts" in command for command in calls)
    assert any("tests/plans.test.ts" in command for command in calls)
    receipt = json.loads((runner.RESULTS / "ci-results.json").read_text())
    assert receipt["success"] is True
    assert all("selection_mode" not in result for result in receipt["results"])
