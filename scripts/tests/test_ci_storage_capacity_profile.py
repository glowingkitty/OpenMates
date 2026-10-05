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

# contract-test: infrastructure

def test_full_target_has_exact_500_slots_without_provider_authority() -> None:
    profile = compose_profile("a" * 40, storage_capacity=True, capacity_concurrency=500,
                              capacity_target=True, account_emails=[])
    services = profile["services"]
    workers = [name for name in services if name == "ai-worker" or name.startswith("ai-worker-")]
    assert len(workers) == 125
    assert all("--concurrency=4" in services[name]["command"] for name in workers)
    assert all(services[name]["mem_limit"] == 1536 * 1024**2 for name in workers)
    assert all("OPENAI_API_KEY" not in services[name]["environment"] for name in workers)
    assert profile["networks"]["default"]["internal"] is True


# contract-test: infrastructure

def test_target_admission_checks_real_slot_memory_disk_and_timeout() -> None:
    from scripts.ci_environment import admit_target_capacity

    calibration = {"schema": 2, "source_commit": "a" * 40, "pilot_passed": True,
                   "observed_worker_slots": 4, "observed_worker_task_receipts": 32,
                   "worker_container_peak_metric": "cgroup_v2_memory_peak",
                   "worker_container_peak_bytes": 256 * 1024**2,
                   "driver_peak_metric": "process_rss_peak",
                   "driver_idle_peak_bytes": 64 * 1024**2,
                   "driver_sample_peak_bytes": 96 * 1024**2,
                   "driver_sample_threads": 4,
                   "fixed_stack_peak_metric": "sum_cgroup_memory_peak",
                   "fixed_stack_peak_bytes": 2 * 1024**3,
                   "disk_bytes_per_operation": 1024,
                   "measured_operations_per_second": 1000}
    options = dict(source_commit="a" * 40, runner_environment="self-hosted",
                   profile="accelerated", available_memory_bytes=256 * 1024**3,
                   available_disk_bytes=40 * 1024**3, job_timeout_seconds=10000)
    result = admit_target_capacity(calibration, **options)
    assert result["worker_slots"] == 500
    assert result["worker_replicas"] == 125
    assert result["memory_required_bytes"] < 125 * 1536 * 1024**2
    assert result["worker_container_peak_bytes"] == 256 * 1024**2
    with pytest.raises(RuntimeError, match="container ceiling"):
        admit_target_capacity(calibration | {"worker_container_peak_bytes": 1200 * 1024**2}, **options)
    with pytest.raises(RuntimeError, match="sampling provenance"):
        admit_target_capacity(calibration | {"observed_worker_slots": 2}, **options)
    with pytest.raises(RuntimeError, match="driver sample"):
        admit_target_capacity(calibration | {"driver_sample_peak_bytes": 64 * 1024**2}, **options)
    for changed, message in (({"runner_environment": "github-hosted"}, "dedicated"),
                             ({"available_memory_bytes": 1}, "memory"),
                             ({"available_disk_bytes": 1}, "disk"),
                             ({"job_timeout_seconds": 3600}, "timeout")):
        with pytest.raises(RuntimeError, match=message):
            admit_target_capacity(calibration, **(options | changed))
    with pytest.raises(RuntimeError, match="same-source"):
        admit_target_capacity(calibration | {"source_commit": "b" * 40}, **options)
    # A representative paced run uses its declared window; it has no invented
    # requirement to occupy a runner for a full calendar day.
    paced = admit_target_capacity(calibration, **(options | {"profile": "sustained"}))
    assert paced["job_timeout_required_seconds"] == result["job_timeout_required_seconds"]


# contract-test: infrastructure

def test_target_profile_does_not_accept_four_slot_substitution() -> None:
    with pytest.raises(ValueError, match="exactly 500"):
        compose_profile("a" * 40, storage_capacity=True, capacity_concurrency=4,
                        capacity_target=True)


# contract-test: infrastructure

def test_full_target_runner_requires_measured_500_slots(monkeypatch) -> None:
    import sys
    from scripts import ci_environment
    monkeypatch.setitem(sys.modules, "ci_environment", ci_environment)
    from scripts.ci_run_tests import verify_capacity_admission

    valid = {"target_capacity_admission": {"worker_slots": 500},
             "storage_capacity": {"worker_slots": 500, "worker_replicas": 125,
                                  "observed_worker_processes": 500}}
    verify_capacity_admission(True, valid)
    verify_capacity_admission(False, {})
    for changed in ({"worker_slots": 4}, {"worker_replicas": 1},
                    {"observed_worker_processes": 4}):
        with pytest.raises(RuntimeError, match="500-slot"):
            verify_capacity_admission(True, valid | {"storage_capacity": valid["storage_capacity"] | changed})


# contract-test: infrastructure

@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"),
                                  [], {}, "1", True, 0])
def test_target_calibration_rejects_nonfinite_or_malformed_measurements(bad) -> None:
    from scripts.ci_environment import admit_target_capacity

    calibration = {"schema": 2, "source_commit": "a" * 40, "pilot_passed": True,
                   "observed_worker_slots": 4, "observed_worker_task_receipts": 32,
                   "worker_container_peak_metric": "cgroup_v2_memory_peak",
                   "worker_container_peak_bytes": bad,
                   "driver_peak_metric": "process_rss_peak",
                   "driver_idle_peak_bytes": 64 * 1024**2,
                   "driver_sample_peak_bytes": 96 * 1024**2,
                   "driver_sample_threads": 4,
                   "fixed_stack_peak_metric": "sum_cgroup_memory_peak",
                   "fixed_stack_peak_bytes": 2 * 1024**3,
                   "disk_bytes_per_operation": 1024,
                   "measured_operations_per_second": 1000}
    with pytest.raises(RuntimeError, match="finite measured"):
        admit_target_capacity(calibration, source_commit="a" * 40,
                              runner_environment="self-hosted", profile="accelerated",
                              available_memory_bytes=256 * 1024**3,
                              available_disk_bytes=40 * 1024**3,
                              job_timeout_seconds=10000)


# contract-test: infrastructure

def test_target_calibration_rejects_non_object() -> None:
    from scripts.ci_environment import admit_target_capacity

    with pytest.raises(RuntimeError, match="JSON object"):
        admit_target_capacity([], source_commit="a" * 40,
                              runner_environment="self-hosted", profile="accelerated",
                              available_memory_bytes=256 * 1024**3,
                              available_disk_bytes=40 * 1024**3,
                              job_timeout_seconds=10000)
    with pytest.raises(RuntimeError, match="same-source"):
        admit_target_capacity({"schema": True, "source_commit": "a" * 40,
                               "pilot_passed": True}, source_commit="a" * 40,
                              runner_environment="self-hosted", profile="accelerated",
                              available_memory_bytes=256 * 1024**3,
                              available_disk_bytes=40 * 1024**3,
                              job_timeout_seconds=10000)


# contract-test: infrastructure

def test_calibration_producer_accepts_only_verified_aggregate_measurements(monkeypatch, tmp_path) -> None:
    runner = _load_bound_runner(monkeypatch)
    environment = {"source_commit": "a" * 40, "harness_commit": "b" * 40,
                   "run_id": "123", "storage_capacity": {
                       "worker_slots": 4, "worker_replicas": 1,
                       "observed_worker_processes": 4,
                       "provider_credentials": "absent", "provider_network": "internal"},
                   "services": {"ai-worker": {"container": "worker"},
                                "api": {"container": "api"}}}
    report = {"passed": True, "validation_level": "pilot",
              "counts": {"round": 240, "embed": 32, "version": 32},
              "server_task_peak_concurrency": 4, "task_receipt_count": 272,
              "provider": {"real_provider_calls": 0, "blocked_provider_calls": 0,
                           "cache_misses": 0, "cache_hits": 272},
              "measured_duration_seconds": 120,
              "hardware": {"worker_threads": 4, "driver_peak_metric": "process_rss_peak",
                           "driver_idle_peak_bytes": 64 * 1024**2,
                           "driver_sample_peak_bytes": 96 * 1024**2}}
    before = {"metric": "cgroup_v2_memory_peak",
              "peaks": {"ai-worker": 100 * 1024**2, "api": 60 * 1024**2},
              "source_free": 10**10, "docker_free": 10**10}
    after = {"metric": "cgroup_v2_memory_peak",
             "peaks": {"ai-worker": 256 * 1024**2, "api": 80 * 1024**2},
             "source_free": 10**10 - 4096, "docker_free": 10**10 - 8192}
    receipt = runner._capacity_calibration_payload(
        environment, report, before, after, succeeded=True,
    )
    assert receipt["worker_container_peak_bytes"] == 256 * 1024**2
    assert receipt["fixed_stack_peak_bytes"] == 80 * 1024**2
    assert receipt["disk_bytes_per_operation"] == 8192 / 304
    assert receipt["driver_sample_threads"] == 4
    assert receipt["observed_docker_disk_delta_bytes"] == 8192
    monkeypatch.setattr(runner, "RESULTS", tmp_path)
    report_path = tmp_path / "ci-storage-capacity.json"
    report_path.write_text(json.dumps(report))
    (tmp_path / "ci-environment.json").write_text(json.dumps(environment))
    runner._write_capacity_calibration_receipt(
        environment, report, report_path, before, after, succeeded=True,
    )
    receipt_path = tmp_path / "ci-capacity-calibration-private/receipt.json"
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(receipt_path.read_text())["pilot_report_sha256"] == __import__("hashlib").sha256(
        report_path.read_bytes()
    ).hexdigest()
    with pytest.raises(FileExistsError):
        runner._write_capacity_calibration_receipt(
            environment, report, report_path, before, after, succeeded=True,
        )
    for changed in (
        {"passed": False}, {"server_task_peak_concurrency": 3},
        {"provider": report["provider"] | {"real_provider_calls": 1}},
        {"counts": report["counts"] | {"round": 239}},
    ):
        with pytest.raises(RuntimeError, match="pilot did not pass"):
            runner._capacity_calibration_payload(
                environment, report | changed, before, after, succeeded=True,
            )
    with pytest.raises(RuntimeError, match="measurements changed"):
        runner._capacity_calibration_payload(
            environment, report, before, after | {"metric": "cgroup_v1_max_usage"},
            succeeded=True,
        )
    with pytest.raises(RuntimeError, match="disk growth"):
        runner._capacity_calibration_payload(
            environment, report, before,
            after | {"source_free": 10**10, "docker_free": 10**10}, succeeded=True,
        )


# contract-test: infrastructure

def test_calibration_snapshot_uses_cgroup_aggregate_and_real_four_slot_evidence(monkeypatch, tmp_path) -> None:
    runner = _load_bound_runner(monkeypatch)
    evidence = {"storage_capacity": {"worker_slots": 4, "worker_replicas": 1,
                                      "observed_worker_processes": 4},
                "services": {"ai-worker": {"container": "worker"},
                             "api": {"container": "api"}}}
    monkeypatch.setattr(runner, "_container_cgroup_peak",
                        lambda container: ("cgroup_v2_memory_peak",
                                           256 * 1024**2 if container == "worker" else 64 * 1024**2))
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *args, **kwargs: str(tmp_path))
    monkeypatch.setattr(runner.shutil, "disk_usage", lambda path: SimpleNamespace(free=10**10))
    result = runner._capacity_calibration_snapshot(evidence)
    assert result["peaks"] == {"ai-worker": 256 * 1024**2, "api": 64 * 1024**2}
    assert result["metric"] == "cgroup_v2_memory_peak"
    with pytest.raises(RuntimeError, match="four live"):
        runner._capacity_calibration_snapshot(
            evidence | {"storage_capacity": evidence["storage_capacity"] |
                        {"observed_worker_processes": 2}}
        )


# contract-test: infrastructure

def test_calibration_cgroup_peak_fails_closed_when_unavailable(monkeypatch) -> None:
    runner = _load_bound_runner(monkeypatch)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if command[-1] == "/sys/fs/cgroup/memory.peak":
            return SimpleNamespace(returncode=0, stdout="268435456\n")
        return SimpleNamespace(returncode=1, stdout="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    assert runner._container_cgroup_peak("worker") == (
        "cgroup_v2_memory_peak", 256 * 1024**2,
    )
    assert calls[0][:3] == ["docker", "exec", "worker"]
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""))
    with pytest.raises(RuntimeError, match="cgroup peak"):
        runner._container_cgroup_peak("worker")


# contract-test: infrastructure

def test_target_admission_binds_private_pilot_report_and_source(monkeypatch, tmp_path) -> None:
    import hashlib
    from scripts import ci_environment as env

    private = tmp_path / "test-results/ci-private"
    private.mkdir(parents=True)
    source, harness, run = "a" * 40, "b" * 40, "123"
    pilot = {"passed": True, "validation_level": "pilot",
             "counts": {"round": 240, "embed": 32, "version": 32},
             "server_task_peak_concurrency": 4, "task_receipt_count": 272,
             "provider": {"real_provider_calls": 0, "blocked_provider_calls": 0,
                          "cache_misses": 0, "cache_hits": 272},
             "hardware": {"worker_threads": 4, "driver_peak_metric": "process_rss_peak",
                          "driver_idle_peak_bytes": 64 * 1024**2,
                          "driver_sample_peak_bytes": 96 * 1024**2}}
    pilot_env = {"source_commit": source, "harness_commit": harness, "run_id": run,
                 "storage_capacity": {"provider_credentials": "absent",
                                      "provider_network": "internal",
                                      "observed_worker_processes": 4,
                                      "worker_replicas": 1}}
    pilot_raw, env_raw = json.dumps(pilot).encode(), json.dumps(pilot_env).encode()
    calibration = {"schema": 2, "source_commit": source,
                   "harness_commit": harness, "run_id": run, "pilot_passed": True,
                   "pilot_report_sha256": hashlib.sha256(pilot_raw).hexdigest(),
                   "ci_environment_sha256": hashlib.sha256(env_raw).hexdigest(),
                   "observed_worker_slots": 4, "observed_worker_task_receipts": 272,
                   "worker_container_peak_metric": "cgroup_v2_memory_peak",
                   "worker_container_peak_bytes": 256 * 1024**2,
                   "driver_peak_metric": "process_rss_peak",
                   "driver_idle_peak_bytes": 64 * 1024**2,
                   "driver_sample_peak_bytes": 96 * 1024**2,
                   "driver_sample_threads": 4,
                   "fixed_stack_peak_metric": "sum_cgroup_memory_peak",
                   "fixed_stack_peak_bytes": 2 * 1024**3,
                   "disk_bytes_per_operation": 1024,
                   "measured_operations_per_second": 1000}
    paths = [private / "capacity-target-calibration.json",
             private / "capacity-target-pilot-report.json",
             private / "capacity-target-ci-environment.json"]
    for path, content in zip(paths, (json.dumps(calibration).encode(), pilot_raw, env_raw)):
        path.write_bytes(content)
        path.chmod(0o600)
    monkeypatch.setattr(env, "SOURCE", str(tmp_path))
    monkeypatch.setattr(env, "_available_target_memory_bytes", lambda: 256 * 1024**3)
    monkeypatch.setattr(env.shutil, "disk_usage", lambda path: SimpleNamespace(free=40 * 1024**3))
    monkeypatch.setattr(env.subprocess, "check_output", lambda *args, **kwargs: str(tmp_path))
    monkeypatch.setenv("CI_STORAGE_CAPACITY_CALIBRATION_RUN_ID", run)
    monkeypatch.setenv("CI_HARNESS_COMMIT", harness)
    monkeypatch.setenv("CI_STORAGE_CAPACITY_JOB_TIMEOUT_SECONDS", "10000")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    assert env.require_target_admission(source)["worker_slots"] == 500
    paths[1].write_bytes(pilot_raw + b" ")
    with pytest.raises(RuntimeError, match="digest differs"):
        env.require_target_admission(source)


# contract-test: infrastructure

def test_target_cgroup_read_failure_cannot_fall_back_to_host_memory(monkeypatch) -> None:
    from pathlib import Path
    from scripts.ci_environment import _available_target_memory_bytes

    def fake_read(path):
        if str(path) == "/proc/meminfo":
            return "MemAvailable: 1048576 kB\n"
        raise OSError("synthetic unreadable cgroup")

    monkeypatch.setattr(Path, "read_text", fake_read)
    monkeypatch.setattr(Path, "exists", lambda path: str(path) == "/sys/fs/cgroup/memory.max")
    with pytest.raises(RuntimeError, match="cgroup"):
        _available_target_memory_bytes()


# contract-test: infrastructure

def test_target_available_memory_respects_restrictive_v2_cgroup(monkeypatch) -> None:
    from pathlib import Path
    from scripts.ci_environment import _available_target_memory_bytes

    values = {"/proc/meminfo": "MemAvailable: 2097152 kB\n",
              "/sys/fs/cgroup/memory.max": str(1024**3),
              "/sys/fs/cgroup/memory.current": str(512 * 1024**2)}
    monkeypatch.setattr(Path, "read_text", lambda path: values[str(path)])
    monkeypatch.setattr(Path, "exists", lambda path: str(path) == "/sys/fs/cgroup/memory.max")
    assert _available_target_memory_bytes() == 512 * 1024**2


def test_capacity_archive_eligibility_proof_is_readonly_and_all_runtime_sources_are_candidate_bound():
    source = "a" * 40
    profile = compose_profile(source, storage_capacity=True, capacity_concurrency=2)
    for name in ("api", "core-worker", "ai-worker"):
        service = profile["services"][name]
        assert service["environment"]["BUILD_COMMIT_SHA"] == source
        assert any(isinstance(mount, str) and mount.endswith("/storage-isolation:/app/ci-storage-isolation:ro")
                   for mount in service["volumes"])
