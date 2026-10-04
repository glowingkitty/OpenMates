# contract-test-file: infrastructure
"""The capacity CI opt-in retains the network and credential boundary."""

import pytest
import json
import importlib.util
import ast
import subprocess
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


def test_capacity_runner_uses_reserved_cli_slot_for_distinct_synthetic_accounts(monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    with pytest.raises(RuntimeError, match="reserved auth-account slot"):
        runner.provision_account(100, identity_index=2, cli_slot=100)
    tree = ast.parse(Path(runner.__file__).read_text())
    workload = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "run_storage_capacity")
    calls = [node for node in ast.walk(workload) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "provision_account"]
    assert len(calls) == 1
    assert ast.literal_eval(next(keyword.value for keyword in calls[0].keywords
                                 if keyword.arg == "cli_slot")) == 14


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


def test_legacy_claim_sql_probe_runs_only_on_exact_fresh_profile_before_epoch(tmp_path, monkeypatch):
    runner = _load_bound_runner(monkeypatch)
    profile = compose_profile(
        "candidate-sha", storage_capacity=True, account_emails=["ci-one@example.com"],
    )
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    calls = []
    counts = {"ordinary": 4, "batch": 4, "canonical_present": 12,
              "lifecycle_retired": 8,
              "chat_deleted": 4, "account_deleted": 4}
    receipt = {"passed": True, "legacy_claim_sql_races": counts}
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: (
        calls.append(args) or SimpleNamespace(stdout=json.dumps(receipt))
    ))
    assert runner.run_isolated_legacy_claim_probe() == receipt
    assert calls == [("exec", "-T", "-e", "OPENMATES_CI_LEGACY_CLAIM_PROBE=1",
                      "api", "python", "/app/scripts/storage_archive_integration.py")]
    private = tmp_path / "ci-capacity-private" / "legacy-claim-probe.json"
    assert json.loads(private.read_text()) == receipt
    assert private.stat().st_mode & 0o777 == 0o600

    profile["services"]["api"]["environment"]["OPENMATES_CI_ISOLATED"] = "0"
    compose_path.write_text(json.dumps(profile))
    with pytest.raises(RuntimeError, match="exact isolated capacity profile"):
        runner.run_isolated_legacy_claim_probe()
    assert len(calls) == 1


def test_legacy_claim_sql_probe_rejects_partial_receipt_and_precedes_epoch(tmp_path, monkeypatch):
    runner = _load_bound_runner(monkeypatch)
    profile = compose_profile(
        "candidate-sha", storage_capacity=True, account_emails=["ci-one@example.com"],
    )
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: SimpleNamespace(
        stdout=json.dumps({"passed": True, "legacy_claim_sql_races": {
            "ordinary": 4, "batch": 4, "canonical_present": 12,
            "lifecycle_retired": 7,
            "chat_deleted": 4, "account_deleted": 4,
        }})
    ))
    with pytest.raises(RuntimeError, match="incomplete"):
        runner.run_isolated_legacy_claim_probe()
    source = Path(runner.__file__).read_text()
    activation_block = source.split("if name in CAPACITY_EPOCH_SPECS:")[-1]
    assert activation_block.index("run_isolated_legacy_claim_probe()") < activation_block.index(
        "activate_isolated_recovery_epoch()")


@pytest.mark.parametrize("bad_counts", [
    {"ordinary": 4, "batch": 4, "lifecycle_retired": 8,
     "chat_deleted": 4, "account_deleted": 4},
    {"ordinary": 4, "batch": 4, "canonical_present": 11,
     "lifecycle_retired": 8, "chat_deleted": 4, "account_deleted": 4},
    {"ordinary": 4, "batch": 4, "canonical_present": True,
     "lifecycle_retired": 8, "chat_deleted": 4, "account_deleted": 4},
    {"ordinary": 4, "batch": 4, "canonical_present": 12,
     "lifecycle_retired": 8, "chat_deleted": 4, "account_deleted": 4,
     "unexpected": 1},
])
def test_legacy_claim_sql_probe_rejects_missing_or_wrong_canonical_count(
    tmp_path, monkeypatch, bad_counts,
):
    runner = _load_bound_runner(monkeypatch)
    profile = compose_profile(
        "candidate-sha", storage_capacity=True, account_emails=["ci-one@example.com"],
    )
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    monkeypatch.setattr(runner, "compose", lambda *args, **kwargs: SimpleNamespace(
        stdout=json.dumps({"passed": True, "legacy_claim_sql_races": bad_counts})
    ))
    with pytest.raises(RuntimeError, match="incomplete"):
        runner.run_isolated_legacy_claim_probe()


def test_recovery_epoch_child_program_compiles_and_uses_only_cutover_dependencies(monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    tree = ast.parse(Path(runner.__file__).read_text())
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "activate_isolated_recovery_epoch")
    literal = next(node.value for node in function.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "program" for target in node.targets))
    program = ast.literal_eval(literal)
    compile(program, "<recovery-epoch-fixture>", "exec")
    child = ast.parse(program)
    project_root = Path(runner.__file__).resolve().parents[1]
    modules = {node.module for node in child.body if isinstance(node, ast.ImportFrom)}
    for module in modules:
        assert (project_root / (module.replace(".", "/") + ".py")).is_file() or (
            project_root / module.replace(".", "/") / "__init__.py"
        ).is_file(), module
    assert "backend.core.api.app.tasks.base_task" not in modules
    assert "backend.core.api.app.services.cache" in modules
    assert "backend.core.api.app.services.directus" in modules
    assert all(name in program for name in (
        "get_cutover_state", "set_sends_paused", "activate_protocol_epoch",
        "ChatRecoveryCutoverController(cache, directus)",
    ))


def test_recovery_epoch_failure_reports_only_child_location_and_class(tmp_path, monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    profile = compose_profile(
        "candidate-sha", storage_capacity=True, account_emails=["ci-one@example.com"],
    )
    compose_path = tmp_path / "compose.json"
    compose_path.write_text(json.dumps(profile))
    private = tmp_path / "ci-private"
    private.mkdir()
    monkeypatch.setattr(runner, "COMPOSE_PATH", compose_path)
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    monkeypatch.setattr(runner, "require_runner", lambda: None)
    stderr = 'Traceback (most recent call last):\n  File "<string>", line 17, in main\nRuntimeError: private-token-value'

    def failed_compose(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "docker compose exec", stderr=stderr)

    monkeypatch.setattr(runner, "compose", failed_compose)
    with pytest.raises(RuntimeError, match=r"failed at main:17 \(RuntimeError\)") as raised:
        runner.activate_isolated_recovery_epoch()
    assert "private-token-value" not in str(raised.value)
    assert (private / "recovery-epoch.stderr.log").read_text() == stderr


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("storage-capacity-replay.spec.ts", True),
        ("storage-message-embed-bundle.spec.ts", True),
        ("storage-capacity-target.spec.ts", True),
        ("storage-recovery-replay.spec.ts", True),
        ("storage-recovery-canonical-receipts.spec.ts", True),
        ("startup-sync-contract.spec.ts", False),
        ("shared-chat-bounded-history.spec.ts", False),
    ],
)
def test_epoch_activation_selector_is_exact(spec, expected, monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    assert (spec in runner.CAPACITY_EPOCH_SPECS) is expected


def test_saved_bundle_selector_is_signed_but_cannot_gate_the_capacity_workload(monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    bundle = "storage-message-embed-bundle.spec.ts"
    replay = "storage-capacity-replay.spec.ts"
    manifest = json.loads((Path(__file__).resolve().parents[1] / "ci_coverage_manifest.json").read_text())
    assert bundle in manifest["groups"]["storage_capacity_replay"]["specs"]
    assert bundle in ci_environment.STORAGE_CAPACITY_SPECS
    assert bundle in runner.CAPACITY_EPOCH_SPECS
    assert bundle not in ci_environment.CAPACITY_WORKLOAD_SPECS
    assert bundle not in runner.CAPACITY_WORKLOAD_SPECS
    assert replay in ci_environment.CAPACITY_WORKLOAD_SPECS
    assert replay in runner.CAPACITY_WORKLOAD_SPECS


def test_archive_probe_reports_inner_application_frame_without_private_values(monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    stderr = (
        '  File "/app/scripts/storage_archive_integration.py", line 591, in probe\n'
        '  File "/app/backend/core/api/app/tasks/base_task.py", line 261, in initialize_core_services\n'
        'AttributeError: private-account-token-value\n'
    )
    public = runner.sanitize_archive_probe_failure(stderr)
    assert public == (
        'Disposable archive DB/S3 transaction probe failed at '
        'initialize_core_services:261 (AttributeError)'
    )
    assert 'private-account-token-value' not in public


def test_legacy_actor_schema_failure_preserves_only_fixed_diagnostics(monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    stderr = (
        '  File "/app/scripts/storage_archive_integration.py", line 152, '
        'in _legacy_claim_fixture_user\n'
        'RuntimeError: Synthetic legacy claim actor creation failed '
        'status=400 code=INVALID_PAYLOAD field=email\n'
    )
    assert runner.sanitize_archive_probe_failure(stderr) == (
        'Disposable archive DB/S3 transaction probe failed at '
        '_legacy_claim_fixture_user:152 (RuntimeError) '
        'status=400 code=INVALID_PAYLOAD field=email'
    )


@pytest.mark.parametrize("terminal", [
    'RuntimeError: Synthetic legacy claim actor creation failed status=400 '
    'code=INVALID_PAYLOAD field=email secret=private',
    'RuntimeError: Synthetic legacy claim actor creation failed status=400 '
    'code=private-token field=email',
    'RuntimeError: Synthetic legacy claim actor creation failed status=400 '
    'code=INVALID_PAYLOAD field=private-account',
    'RuntimeError: Synthetic legacy claim actor creation failed status=400 '
    'code=INVALID_PAYLOAD field=email@example.com',
    'RuntimeError: private exception with status=400 code=INVALID_PAYLOAD field=email',
])
def test_legacy_actor_schema_failure_rejects_unbounded_suffix(monkeypatch, terminal) -> None:
    runner = _load_bound_runner(monkeypatch)
    stderr = ('  File "/app/scripts/storage_archive_integration.py", line 152, '
              'in _legacy_claim_fixture_user\n' + terminal)
    public = runner.sanitize_archive_probe_failure(stderr)
    assert public == ('Disposable archive DB/S3 transaction probe failed at '
                      '_legacy_claim_fixture_user:152 (RuntimeError)')


def test_legacy_actor_schema_failure_requires_exact_producer_frame(monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    stderr = (
        '  File "/app/scripts/storage_archive_integration.py", line 152, in other\n'
        'RuntimeError: Synthetic legacy claim actor creation failed '
        'status=400 code=INVALID_PAYLOAD field=email\n'
    )
    assert runner.sanitize_archive_probe_failure(stderr) == (
        'Disposable archive DB/S3 transaction probe failed at other:152 (RuntimeError)'
    )


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
    assert calls[1][0].count("--reporter=default") == 1
    assert calls[1][0].count("--reporter=json") == 1
    assert "--outputFile.json=" + str(tmp_path / "test-results/ci-unit-ui.json") in calls[1][0]
    assert calls[1][1] == tmp_path / "frontend/packages/ui"
    assert calls[2][0][:5] == ["pnpm", "exec", "vitest", "run", "src/lib/selected.test.ts"]
    assert calls[2][0].count("--reporter=default") == 1
    assert calls[2][0].count("--reporter=json") == 1
    assert "--outputFile.json=" + str(tmp_path / "test-results/ci-unit-web_app.json") in calls[2][0]
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
