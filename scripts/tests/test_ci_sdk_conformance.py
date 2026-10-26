# contract-test-file: tooling
"""Inert SDK-lane contracts; never install, compile, start a product or contact CI."""
import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import time

import pytest

from scripts import ci_sdk_conformance as sdk
from scripts.ci_coordinator import Queue, enqueue_submission
from scripts.ci_results import valid_sdk_conformance_receipt


def test_exact_queue_target_no_preparation(tmp_path):
    queue = Queue(tmp_path / "queue.sqlite")
    jobs = enqueue_submission(queue, "synthetic", "a" * 40, [sdk.TARGET], sdk.TARGET)
    assert len(jobs) == 1 and json.loads(jobs[0]["specs"]) == [sdk.TARGET]
    assert not jobs[0].get("preparation_key")


@pytest.mark.parametrize("targets", [[], ["sdk-conformance-extra"], ["nested/sdk-conformance"],
                                      ["sdk-conformance", "extra.spec.ts"], ["sdk-conformance", "sdk-conformance"], ["--release"]])
def test_queue_rejects_unknown_or_broadened_targets(tmp_path, targets):
    queue = Queue(tmp_path / "queue.sqlite")
    with pytest.raises(ValueError, match="exact unprepared target"):
        queue.enqueue("synthetic", "a" * 40, targets, sdk.TARGET)


def test_queue_rejects_prepared_or_backend_seed(tmp_path):
    queue = Queue(tmp_path / "queue.sqlite")
    for options in ({"preparation": {"key": "a" * 64}}, {"runtime_seed_job": "a" * 64}):
        with pytest.raises(ValueError):
            queue.enqueue("synthetic", "a" * 40, [sdk.TARGET], sdk.TARGET, **options)


def gate_fixture(tmp_path):
    root = tmp_path / "subject"
    matrix = {"fixture": "tests/sdk-conformance/synthetic.json", "capabilities": [{
        "id": "synthetic.local.v1", "languages": {name: {"conformance": True,
          "status": "partial" if name == "rust" else "implemented", "gaps": ["synthetic gap"] if name == "rust" else []}
          for name in ("rust", "npm", "python")}}]}
    fixture = {"capabilities": {"synthetic.local.v1": {"vectors": [{"id": "synthetic-one"}, {"id": "synthetic-two"}]}}}
    for path, value in [("config/sdk-capabilities.json", matrix), (matrix["fixture"], fixture)]:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value))
    fixture_hash = sdk.sha((root / matrix["fixture"]).read_bytes())
    report = {"matrixSha256": sdk.sha((root / "config/sdk-capabilities.json").read_bytes()),
              "openGaps": sdk.matrix_gaps(matrix), "releaseEligible": False,
              "conformance": [{"capability": "synthetic.local.v1", "language": language,
                               "fixtureSha256": fixture_hash, "status": "passed",
                               "results": [{"id": "synthetic-one", "status": "passed"},
                                           {"id": "synthetic-two", "status": "passed"}]} for language in ("rust", "npm", "python")]}
    report["expectedPlan"] = sdk.execution_plan(root, matrix)
    report["actualLaunches"] = [{"capability": row["capability"], "language": row["language"],
                                 "status": "passed", "commandSha256": "d" * 64} for row in report["expectedPlan"]]
    report["trustedProgramsSha256"] = sdk.sha(json.dumps({"synthetic.py": "e" * 64}, sort_keys=True).encode())
    return root, report


def synthetic_trust(root):
    matrix = json.loads((root / "config/sdk-capabilities.json").read_text())
    return {"contracts": {"config/sdk-capabilities.json": sdk.sha((root / "config/sdk-capabilities.json").read_bytes())},
            "programs": {"synthetic.py": "e" * 64}, "plan": sdk.execution_plan(root, matrix), "gaps": sdk.matrix_gaps(matrix)}


def test_real_result_projection_retains_gaps_and_all_vectors(tmp_path):
    root, report = gate_fixture(tmp_path)
    report["private_extra"] = "never-export"
    report["conformance"][0]["private_extra"] = "never-export"
    result = sdk.gate_receipt(root, report, trust=synthetic_trust(root))
    assert result["realRunCount"] == 3 and result["vectorOutcomeCount"] == 6
    assert result["openGapCount"] == 1 and result["releaseEligible"] is False
    assert "never-export" not in json.dumps(result)


@pytest.mark.parametrize("fault", ["echo_only", "missing_language", "duplicate_language", "wrong_fixture", "missing_vector", "gap_waiver"])
def test_gate_result_cannot_credit_echo_or_incomplete_runs(tmp_path, fault):
    root, report = gate_fixture(tmp_path)
    if fault == "echo_only":
        report["conformance"] = []
    elif fault == "missing_language":
        report["conformance"].pop()
    elif fault == "duplicate_language":
        report["conformance"][1] = report["conformance"][0]
    elif fault == "wrong_fixture":
        report["conformance"][0]["fixtureSha256"] = "f" * 64
    elif fault == "missing_vector":
        report["conformance"][0]["results"].pop()
    else:
        report["releaseEligible"] = True
    with pytest.raises(sdk.Refused):
        sdk.gate_receipt(root, report, trust=synthetic_trust(root))


def test_command_deadline_terminates_only_owned_inert_group(tmp_path):
    env = {"PATH": os.defpath, "LANG": "C.UTF-8"}
    commands = sdk.Commands(tmp_path, tmp_path, env, time.monotonic() + 0.2)
    with pytest.raises(sdk.Refused, match="deadline"):
        commands.run("inert-deadline", [sys.executable, "-c", "import time;time.sleep(30)"], seconds=20)
    assert commands.steps[0]["status"] == "failed"
    assert commands.steps[0]["elapsedSeconds"] < 5


def test_nonzero_child_has_closed_failure_and_private_log(tmp_path):
    commands = sdk.Commands(tmp_path, tmp_path, {"PATH": os.defpath}, time.monotonic() + 10)
    with pytest.raises(sdk.Refused, match="^child_failed$"):
        commands.run("inert-failure", [sys.executable, "-c", "raise SystemExit(7)"])
    assert commands.steps[0]["returncode"] == 7


def test_regular_fifo_and_symlink_refused(tmp_path):
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo, 0o600)
    with pytest.raises(sdk.Refused, match="unsafe_file"):
        sdk.regular(fifo)
    link = tmp_path / "link"
    link.symlink_to(fifo)
    with pytest.raises(sdk.Refused, match="unsafe_file"):
        sdk.regular(link)


def test_non_runner_refuses_before_commands(tmp_path, monkeypatch):
    (tmp_path / "test-results").mkdir()
    monkeypatch.setattr(sdk.subprocess, "Popen", lambda *a, **k: pytest.fail("child started"))
    results = []
    sdk.run(tmp_path, results, "/synthetic/node", verify_node=lambda: None, environ={})
    evidence = json.loads((tmp_path / "test-results/ci-sdk-conformance.json").read_text())
    assert results[0]["exit_code"] == 1
    assert evidence["code"] == "github_runner_required" and evidence["stage"] == "admission"
    assert evidence["publication"] is False and evidence["services"] == {}


def test_workflow_and_runner_do_not_enable_stack_or_publication():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/isolated-tests.yml").read_text()
    runner = (root / "scripts/ci_run_tests.py").read_text()
    import yaml
    document = yaml.safe_load(workflow)
    # PyYAML's YAML 1.1 reader can interpret GitHub's `on` key as True.
    trigger = document.get("on", document.get(True))
    sdk_modes = {"sdk-conformance", "sdk-lockfiles", "rust-wasm"}
    options = trigger["workflow_dispatch"]["inputs"]["mode"]["options"]
    assert sdk_modes <= set(options)
    steps = document["jobs"]["test"]["steps"]
    python_setup = [step for step in steps if step.get("uses") == "actions/setup-python@v5"]
    assert len(python_setup) == 1
    # Exact approved conditional: all three SDK modes use 3.12, every other
    # mode uses 3.13. Neither a missing mode nor a broader branch is admitted.
    assert python_setup[0]["with"]["python-version"] == (
        "${{ (inputs.mode == 'sdk-conformance' || inputs.mode == 'sdk-lockfiles' || "
        "inputs.mode == 'rust-wasm' || inputs.mode == 'rust-native-dev') && '3.12' || '3.13' }}")
    assert "inputs.mode != 'sdk-conformance'" in workflow
    assert "CI_SDK_DEADLINE_MONOTONIC={started + 2700}" in workflow
    clocks = [(index, step) for index, step in enumerate(steps)
              if step.get("name") == "Start bounded SDK conformance clock"]
    assert len(clocks) == 1
    clock_index, clock = clocks[0]
    assert clock["if"] == "inputs.mode == 'sdk-conformance'"
    assert clock["working-directory"] == "${{ github.workspace }}"
    assert [line.strip() for line in clock["run"].splitlines()
            if "CI_SDK_DEADLINE_MONOTONIC=" in line] == [
        "output.write(f'CI_SDK_DEADLINE_MONOTONIC={started + 2700}\\n')"]
    checkouts = [(index, step) for index, step in enumerate(steps)
                 if step.get("uses", "").startswith("actions/checkout@")]
    assert checkouts and clock_index < checkouts[0][0]
    assert checkouts[0][1]["uses"] == "actions/checkout@v4"
    assert "subject/test-results/ci-sdk-conformance.json" in workflow
    assert 'elif mode == "sdk-conformance":' in runner
    source = Path(sdk.__file__).read_text()
    assert 'ci_sdk_conformance_exec.py' in source
    executor = Path(sdk.__file__).with_name("ci_sdk_conformance_exec.py").read_text()
    assert 'namespace["conformance"](matrix, root)' in executor
    assert '"--release"' not in source


def green_sdk_evidence(tmp_path):
    root, raw = gate_fixture(tmp_path)
    report = {"runtime_profile": sdk.TARGET, "results": [{"suite": sdk.TARGET, "exit_code": 0,
                                                       "failed_stage": None, "failure_code": None}]}
    job = {"specs": json.dumps([sdk.TARGET]), "source": "a" * 40, "run_id": 123}
    evidence = {"source_commit": "a" * 40, "run_id": "123", "harness_commit": "b" * 40,
                "status": "passed", "publication": False, "services": {}, "sourceHeld": True,
                "loadIdentityVerified": True, "cleanupVerified": True,
                "gate": sdk.gate_receipt(root, raw, trust=synthetic_trust(root)),
                "artifacts": {language: {"sha256": "c" * 64, "elf": "linux-x64", "nlink": 1} for language in ("npm", "python")}}
    inputs = {name: "c" * 64 for name in sdk.LOCKS}
    evidence.update(inputs=inputs, inputSetSha256=sdk.sha(json.dumps(inputs, sort_keys=True).encode()),
                    locks=dict(inputs), dist={"frontend/packages/openmates-cli/dist/sdk-entry.js": "d" * 64},
                    steps=[{"stage": stage, "status": "passed", "returncode": 0, "terminatedReturncode": 0, "elapsedSeconds": 1}
                           for stage in ["rust-toolchain", "python-environment", "node-dependencies", "python-dependencies", "sdk-library-units", "binding-library-units", "napi-build", "python-binding-build", "sdk-facade-build", "napi-load", "python-load", "real-conformance"]])
    for step in evidence["steps"][4:6]:
        step.update(unitTests={"passed": 1, "failed": 0, "ignored": 0, "measured": 0, "filteredOut": 0},
                    started=True, command={"tool": "cargo", "admission": "strict-owner-mode",
                    "argvSha256": sdk.sha(json.dumps(sdk.library_unit_command(step["stage"]), separators=(",", ":")).encode()),
                    "executableSha256": "e" * 64})
    for value in evidence["artifacts"].values():
        value.update(device=1, inode=1, uid=os.getuid(), mode=0o600, mtimeNs=1, ctimeNs=1, bytes=96)
    expectation = {"trust": synthetic_trust(root), "expected_inputs": inputs}
    return report, evidence, job, expectation


def test_retrieved_green_sdk_evidence_requires_all_identity_and_cleanup(tmp_path):
    report, evidence, job, expectation = green_sdk_evidence(tmp_path)
    assert valid_sdk_conformance_receipt(report, evidence, job, "b" * 40, **expectation)
    for key, value in [("source_commit", "d" * 40), ("cleanupVerified", False),
                       ("sourceHeld", False), ("loadIdentityVerified", False), ("publication", True)]:
        changed = {**evidence, key: value}
        assert not valid_sdk_conformance_receipt(report, changed, job, "b" * 40, **expectation)
    changed = copy.deepcopy(evidence)
    changed["gate"]["conformance"].pop()
    assert not valid_sdk_conformance_receipt(report, changed, job, "b" * 40, **expectation)
    for field in ("inputs", "locks", "dist", "steps"):
        changed = copy.deepcopy(evidence)
        changed[field] = {} if field != "steps" else []
        assert not valid_sdk_conformance_receipt(report, changed, job, "b" * 40, **expectation)
    for field, value in [("plan", []), ("actualLaunches", []), ("openGapCount", 0), ("releaseEligible", True)]:
        changed = copy.deepcopy(evidence)
        changed["gate"][field] = value
        assert not valid_sdk_conformance_receipt(report, changed, job, "b" * 40, **expectation)
    changed = copy.deepcopy(evidence)
    changed["gate"]["conformance"] = [{"capability": "invented", "language": language,
        "status": "passed", "vectors": ["invented-one"]} for language in ("rust", "npm", "python")]
    assert not valid_sdk_conformance_receipt(report, changed, job, "b" * 40, **expectation)


@pytest.mark.parametrize("index", [4, 5])
@pytest.mark.parametrize("fault", ["missing_stage", "reordered", "faked_stage", "missing_summary", "zero_tests",
                                   "failed", "ignored", "measured", "filteredOut", "boolean_passed",
                                   "missing_command", "fake_tool", "fake_argv", "fake_image", "not_started"])
def test_retriever_requires_both_actual_whole_library_unit_receipts(tmp_path, index, fault):
    report, evidence, job, expectation = green_sdk_evidence(tmp_path)
    step = evidence["steps"][index]
    if fault == "missing_stage":
        evidence["steps"].pop(index)
    elif fault == "reordered":
        evidence["steps"][4], evidence["steps"][5] = evidence["steps"][5], evidence["steps"][4]
    elif fault == "faked_stage":
        step["stage"] = "invented-library-units"
    elif fault == "missing_summary":
        step.pop("unitTests")
    elif fault == "zero_tests":
        step["unitTests"]["passed"] = 0
    elif fault in {"failed", "ignored", "measured", "filteredOut"}:
        step["unitTests"][fault] = 1
    elif fault == "boolean_passed":
        step["unitTests"]["passed"] = True
    elif fault == "missing_command":
        step.pop("command")
    elif fault == "fake_tool":
        step["command"]["tool"] = "python"
    elif fault == "fake_argv":
        step["command"]["argvSha256"] = sdk.sha(json.dumps([
            *sdk.library_unit_command(step["stage"]), "one_test_only"], separators=(",", ":")).encode())
    elif fault == "fake_image":
        step["command"]["executableSha256"] = "not-an-executable-digest"
    elif fault == "not_started":
        step["started"] = False
    assert not valid_sdk_conformance_receipt(report, evidence, job, "b" * 40, **expectation)


@pytest.mark.parametrize("stage,manifest", [
    ("sdk-library-units", "packages/openmates-rust/Cargo.toml"),
    ("binding-library-units", "packages/openmates-session-bindings/Cargo.toml"),
])
def test_library_unit_commands_keep_locked_default_features_and_unfiltered_lib(stage, manifest):
    assert sdk.library_unit_command(stage) == ["cargo", "+1.98.1", "test", "--locked", "--manifest-path", manifest, "--lib"]
    assert sdk.command_tool(stage) == "cargo"
    assert sdk.BUDGET == 2700


@pytest.mark.parametrize("fault", [None, "source_change", "artifact_change", "child_exception", "stale_artifact",
                                   "sdk_source_change", "sdk_unit_failure", "sdk_deadline"])
def test_pipeline_uses_fixed_real_commands_private_env_and_source_artifact_fences(tmp_path, monkeypatch, fault):
    root, gate = gate_fixture(tmp_path)
    monkeypatch.setattr(sdk, "load_trust", lambda: synthetic_trust(root))
    monkeypatch.setattr(sdk, "verify_programs", lambda *args: None)
    (root / "test-results").mkdir()
    pyproject = root / "packages/openmates-python/pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text('[project]\ndependencies = ["synthetic-sdk-dependency"]\n')
    monkeypatch.setattr(sdk.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(sdk, "git", lambda root, *args: "a" * 40 if args[-1] == "HEAD" else "b" * 40)
    monkeypatch.setattr(sdk.subprocess, "run", lambda *a, **k: type("Result", (), {"returncode": 1})())
    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/synthetic/tools/" + name)
    inputs = {name: "c" * 64 for name in sdk.LOCKS}
    monkeypatch.setattr(sdk, "snapshot", lambda root: dict(inputs))
    monkeypatch.setattr(sdk, "source_inputs_from_git", lambda root, source: dict(inputs))
    environment = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted",
                   "OPENMATES_CI_ISOLATED": "1", "BUILD_COMMIT_SHA": "a" * 40,
                   "CI_CANDIDATE_TREE": "b" * 40, "CI_SPECS_JSON": json.dumps([sdk.TARGET]),
                   "CI_SDK_STARTED_MONOTONIC": str(time.monotonic()), "GITHUB_RUN_ID": "123",
                   "CI_HARNESS_COMMIT": "d" * 40, "OPENMATES_API_KEY": "never-export",
                   "NODE_OPTIONS": "never-inherit", "DBUS_SESSION_BUS_ADDRESS": "never-inherit"}
    environment["CI_SDK_DEADLINE_MONOTONIC"] = str(float(environment["CI_SDK_STARTED_MONOTONIC"]) + sdk.BUDGET)
    calls = []
    node_artifact = root / "frontend/packages/openmates-cli/native/linux-x64.node"
    python_artifact = root / "packages/openmates-python/openmates/_native.abi3.so"
    if fault == "stale_artifact":
        node_artifact.parent.mkdir(parents=True)
        node_artifact.write_bytes(b"synthetic stale library")
    blob = bytearray(96)
    blob[:6] = b"\x7fELF\x02\x01"
    blob[18:20] = (62).to_bytes(2, "little")

    def command(self, stage, command, **kwargs):
        self.check()
        calls.append((stage, command))
        self.steps.append({"stage": stage, "status": "passed"})
        assert not {"NODE_OPTIONS", "NODE_PATH", "DBUS_SESSION_BUS_ADDRESS", "OPENMATES_API_KEY", "GH_TOKEN"}.intersection(self.env)
        assert Path(self.env["HOME"]).is_relative_to(self.private)
        assert Path(self.env["TMPDIR"]).is_relative_to(self.private)
        assert self.env["RUSTUP_TOOLCHAIN"] == "1.98.1" and self.env["CARGO_BUILD_JOBS"] == "2"
        assert self.env["OPENMATES_STATE_DIR"].startswith(self.env["HOME"])
        if stage == "rust-toolchain":
            assert command == ["/synthetic/tools/rustup", "toolchain", "install", "1.98.1", "--profile", "minimal", "--component", "rustfmt"]
        if stage in sdk.LIBRARY_UNIT_MANIFESTS:
            assert command == sdk.library_unit_command(stage)
            assert "--locked" in command and "--lib" in command
            assert not {"--offline", "--no-default-features", "--features", "--ignored"}.intersection(command)
        if stage == "sdk-library-units":
            if fault != "stale_artifact":
                assert not node_artifact.exists() and not python_artifact.exists()
            if fault == "sdk_source_change":
                inputs[sdk.LOCKS[0]] = "f" * 64
            elif fault == "sdk_unit_failure":
                raise sdk.Refused("child_failed")
            elif fault == "sdk_deadline":
                self.deadline = time.monotonic() - 1
                self.check()
        if fault == "child_exception" and stage == "napi-build":
            raise RuntimeError("never-export")
        if stage == "napi-build":
            node_artifact.parent.mkdir(parents=True)
            node_artifact.write_bytes(blob)
        elif stage == "python-binding-build":
            assert (self.private / "napi-preserved.node").read_bytes() == blob
            assert (self.private / "napi-preserved.node").stat().st_mode & 0o777 == 0o600
            python_artifact.parent.mkdir(parents=True)
            python_artifact.write_bytes(blob + b"synthetic-python-feature")
        elif stage == "sdk-facade-build":
            dist = root / "frontend/packages/openmates-cli/dist"
            dist.mkdir()
            (dist / "sdk-entry.js").write_bytes(b"synthetic facade")
        elif stage == "real-conformance":
            assert Path(command[1]).name == "ci_sdk_conformance_exec.py" and command[2] == str(root)
            assert "--release" not in command
            Path(command[3]).write_text(json.dumps(gate))
            if fault == "source_change":
                inputs["synthetic-changed-input"] = "e" * 64
            elif fault == "artifact_change":
                node_artifact.write_bytes(blob + b"tamper")
    monkeypatch.setattr(sdk.Commands, "run", command)
    attestations = []
    results = []
    sdk.run(root, results, "/synthetic/attested/node", environ=environment,
            verify_node=lambda: attestations.append(True))
    evidence = json.loads((root / "test-results/ci-sdk-conformance.json").read_text())
    assert "never-export" not in json.dumps(evidence)
    assert evidence["cleanupVerified"] is True
    assert not list((root / "test-results/ci-private").iterdir())
    if fault is None:
        assert results[0]["exit_code"] == 0 and evidence["status"] == "passed"
        assert evidence["gate"]["realRunCount"] == 3
        assert evidence["artifacts"]["npm"]["sha256"] != evidence["artifacts"]["python"]["sha256"]
        assert evidence["gate"]["openGapCount"] == 1 and evidence["publication"] is False
        assert len(attestations) == 3
        assert [stage for stage, _ in calls] == ["rust-toolchain", "python-environment", "node-dependencies",
            "python-dependencies", "sdk-library-units", "binding-library-units", "napi-build", "python-binding-build", "sdk-facade-build", "napi-load", "python-load", "real-conformance"]
    else:
        assert results[0]["exit_code"] == 1 and evidence["status"] == "failed"
        assert evidence["code"] == {"source_change": "source_changed", "artifact_change": "artifact_changed",
                                    "child_exception": "unclassified", "stale_artifact": "preexisting_native_artifact",
                                    "sdk_source_change": "source_changed", "sdk_unit_failure": "child_failed",
                                    "sdk_deadline": "deadline"}[fault]
        if fault in {"sdk_source_change", "sdk_unit_failure", "sdk_deadline"}:
            assert not {"binding-library-units", "napi-build", "python-binding-build", "real-conformance"}.intersection(stage for stage, _ in calls)
            assert evidence["diagnostics"]["category"] == "rust_compile_or_unit"



def test_deadline_stops_owned_descendant_but_preserves_unrelated_inert_group(tmp_path):
    sentinel = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"],
                                start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    marker = tmp_path / "inert-child.pid"
    producer = ("import subprocess,sys,time,pathlib;"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                "pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(30)")
    commands = sdk.Commands(tmp_path, tmp_path, {"PATH": os.defpath}, time.monotonic() + 1)
    try:
        with pytest.raises(sdk.Refused, match="deadline"):
            commands.run("inert-descendant", [sys.executable, "-c", producer, str(marker)])
        assert marker.is_file()
        process = Path("/proc") / marker.read_text() / "stat"
        assert not process.exists() or process.read_text().split(")", 1)[1].split()[0] == "Z"
        assert sentinel.poll() is None
    finally:
        sdk.terminate(sentinel)


def test_completed_child_cannot_bypass_log_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk, "MAX_LOG", 8)
    commands = sdk.Commands(tmp_path, tmp_path, {"PATH": os.defpath}, time.monotonic() + 10)
    with pytest.raises(sdk.Refused, match="diagnostic_bound"):
        commands.run("inert-output-bound", [sys.executable, "-c", "print('synthetic too long')"])


def test_reviewed_program_pin_rejects_forged_candidate_aggregate_before_execution(tmp_path):
    program = tmp_path / "scripts/check_sdk_conformance.py"
    program.parent.mkdir()
    program.write_bytes(b"synthetic reviewed controller")
    trust = {"programs": {"scripts/check_sdk_conformance.py": sdk.sha(program.read_bytes())}, "contracts": {}}
    sdk.verify_programs(tmp_path, trust)
    program.write_bytes(b"print('forged allpass and zero gaps')")
    with pytest.raises(sdk.Refused, match="reviewed_program_changed"):
        sdk.verify_programs(tmp_path, trust)


def test_reviewed_contract_pin_rejects_changed_candidate_matrix_before_execution(tmp_path):
    contract = tmp_path / "config/sdk-capabilities.json"
    contract.parent.mkdir()
    contract.write_bytes(b'{"capabilities": ["reviewed fixture"]}')
    trust = {"programs": {}, "contracts": {"config/sdk-capabilities.json": sdk.sha(contract.read_bytes())}}
    sdk.verify_programs(tmp_path, trust)
    contract.write_bytes(b'{"capabilities": [], "releaseEligible": true}')
    with pytest.raises(sdk.Refused, match="reviewed_contract_changed"):
        sdk.verify_programs(tmp_path, trust)


def test_forged_complete_vector_json_cannot_erase_reviewed_gaps(tmp_path):
    root, report = gate_fixture(tmp_path)
    report["openGaps"] = []
    report["releaseEligible"] = True
    with pytest.raises(sdk.Refused, match="gate_incomplete"):
        sdk.gate_receipt(root, report, trust=synthetic_trust(root))


def test_claimed_passes_without_actual_driver_launches_refused(tmp_path):
    root, report = gate_fixture(tmp_path)
    report["actualLaunches"] = []
    with pytest.raises(sdk.Refused, match="gate_launches"):
        sdk.gate_receipt(root, report, trust=synthetic_trust(root))


def test_real_reviewed_contract_preserves_54_by_615_and_adds_exact_three_window_adapters():
    trust = immutable_trust_test_fixture("sdk-conformance-trust-window-7edfe1b.json", "22e16b9aeaf520466b0b7281c7dab47e99b088dc6fc1b30df2b705b967dbe383")
    assert len(trust["gaps"]) == 159
    assert len(trust["plan"]) == 57
    assert sum(len(row["vectors"]) for row in trust["plan"]) == 687
    # Immutable original prefix: every old fixture/vector/language/hash survives.
    assert (
        sdk.sha(json.dumps(trust["plan"][:54], sort_keys=True).encode())
        == "68483b1c2184d521ef87e7658e689d0703c51e279b12fde891a70630aa2fe293"
    )
    assert sum(len(row["vectors"]) for row in trust["plan"][:54]) == 615
    assert (
        sdk.sha(json.dumps(trust["gaps"][:156], sort_keys=True).encode())
        == "4b3e7cbb6f2a985ce9b74e563c517a03c94d5303dbec62e29e578c7bb2008306"
    )
    added = trust["plan"][54:]
    assert [row["language"] for row in added] == ["rust", "npm", "python"]
    assert all(
        row["capability"] == "session.message-window.v1"
        and row["fixture"]
        == "tests/sdk-conformance/fixtures/session-message-window.json"
        and row["fixtureSha256"]
        == "6ac93df9f8618b27256b0dd6b4542d6e4289d435dd595eed2c402f764b325556"
        and len(row["vectors"]) == len(set(row["vectors"])) == 24
        for row in added
    )
    assert all(row["vectors"] == added[0]["vectors"] for row in added)
    assert sum(len(row["vectors"]) for row in added) == 72
    assert all(
        gap.startswith("session.message-window.v1 [") for gap in trust["gaps"][156:]
    )


def test_reviewed_window_pins_preserve_every_unrelated_program_and_contract():
    trust = immutable_trust_test_fixture("sdk-conformance-trust-window-7edfe1b.json", "22e16b9aeaf520466b0b7281c7dab47e99b088dc6fc1b30df2b705b967dbe383")
    programs = copy.deepcopy(trust["programs"])
    added = [
        "packages/openmates-session-bindings/examples/session-message-window-conformance.rs",
        "tests/sdk-conformance/message_window_server.py",
        "tests/sdk-conformance/runners/session-message-window.mjs",
        "tests/sdk-conformance/runners/session-message-window.py",
        "tests/sdk-conformance/test_message_window_peer.py",
        "tests/sdk-conformance/test_message_window_runner.cjs",
        "tests/sdk-conformance/test_message_window_runner.py",
    ]
    assert len(programs) == 81
    for name in added:
        assert len(programs.pop(name)) == 64
    assert (
        programs["scripts/check_sdk_conformance.py"]
        == "58f0e1b2721f89ed19c13efd27ee908e6fa0aaa7786a737cf0467bab6ec03dac"
    )
    programs["scripts/check_sdk_conformance.py"] = (
        "a96148a8fbdf6a6406913cbe357137adf5eb77a5897361ea50851ca4ef1f2498"
    )
    assert (
        sdk.sha(json.dumps(programs, sort_keys=True).encode())
        == "950a80e183dd7ddb305aeb0cd403cca40a601c7eef7ce4b54319a9a35d2cf21b"
    )
    contracts = copy.deepcopy(trust["contracts"])
    assert len(contracts) == 17
    assert (
        contracts.pop("tests/sdk-conformance/fixtures/session-message-window.json")
        == "6ac93df9f8618b27256b0dd6b4542d6e4289d435dd595eed2c402f764b325556"
    )
    assert (
        contracts["config/sdk-capabilities.json"]
        == "d5d2ef678ead7614228b01559f9aea9a050bf0e16a783a1be732a134fdb3d01e"
    )
    contracts["config/sdk-capabilities.json"] = (
        "8d8236ac9eeddcfb6f62dd85e9015c02e9fd9035ba171ff80238db9dc22bbe0e"
    )
    assert (
        sdk.sha(json.dumps(contracts, sort_keys=True).encode())
        == "3c081508f25d7dc489b20889dd77127c3d8055aa458eedf6cea9a98907033cf9"
    )


def test_raw_failure_log_retained_privately_but_only_closed_compiler_fields_export(tmp_path):
    private_root = tmp_path / "ci-private"
    private = private_root / "sdk-synthetic"
    private.mkdir(parents=True, mode=0o700)
    root = tmp_path / "subject"
    tracked = "packages/openmates-session-bindings/src/session.rs"
    data = ("error[E0425]: never-export-synthetic-private-value\n"
            " --> " + tracked + ":12:7\n"
            " --> /private/never-export-path:99:4\n").encode()
    (private / "napi-build.log").write_bytes(data)
    result = sdk.failure_diagnostics(private, root, "napi-build", {tracked: "a" * 64}, [])
    assert result["compiler"] == [{"kind": "rustc", "code": "E0425",
                                   "locations": [{"path": tracked, "line": 12, "column": 7}]}]
    assert "never-export" not in json.dumps(result)
    retained = list(private_root.glob("failure-sdk-*/napi-build.log"))
    assert len(retained) == 1 and retained[0].read_bytes() == data
    assert retained[0].stat().st_mode & 0o777 == 0o600
    assert result["privateRetained"]["sha256"] == sdk.sha(data)
    assert result["rawUpload"] is False


def test_immutable_git_input_hashes_are_reconstructed_not_candidate_claims(tmp_path, monkeypatch):
    source = "a" * 40
    name = "packages/openmates-rust/Cargo.lock"
    oid = "b" * 40
    blob = b"synthetic immutable compiler input"
    def check_output(command, **kwargs):
        assert command == ["git", "ls-tree", "-r", "-z", source, "--", *sdk.INPUTS]
        return f"100644 blob {oid}\t{name}\0".encode()
    def run(command, **kwargs):
        assert kwargs["input"] == (oid + "\n").encode()
        if command[-1] == "--batch-check":
            output = f"{oid} blob {len(blob)}\n".encode()
        else:
            assert command[-1] == "--batch"
            output = f"{oid} blob {len(blob)}\n".encode() + blob + b"\n"
        return type("Result", (), {"stdout": output})()
    monkeypatch.setattr(sdk.subprocess, "check_output", check_output)
    monkeypatch.setattr(sdk.subprocess, "run", run)
    assert sdk.source_inputs_from_git(tmp_path, source) == {name: sdk.sha(blob)}


def test_trusted_executor_launches_actual_inert_drivers_not_candidate_main(tmp_path, monkeypatch):
    from scripts import ci_sdk_conformance_exec as executor
    root, report = gate_fixture(tmp_path)
    trust = synthetic_trust(root)
    program = root / "scripts/check_sdk_conformance.py"
    program.parent.mkdir()
    program.write_text('''
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1]
RUNNERS={language:[sys.executable,str(ROOT/'synthetic-driver.py'),'--language',language] for language in ('rust','npm','python')}
ADAPTER_OVERRIDES={}
def check_generated(root): pass
def discover_inventory(root): return {}
def validate_matrix(matrix,inventory,root): return ['synthetic.local.v1 [rust] partial: synthetic gap']
def conformance(matrix,root):
    output=[]
    for language in ('rust','npm','python'):
        result=subprocess.run(RUNNERS[language]+['--fixture',str(root/matrix['fixture']),'--capability','synthetic.local.v1'],cwd=root,capture_output=True,text=True,timeout=2)
        output.append(json.loads(result.stdout))
    return output
if __name__=='__main__': raise RuntimeError('candidate main must never execute')
''')
    driver = root / "synthetic-driver.py"
    driver.write_text('''
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--language');p.add_argument('--fixture');p.add_argument('--capability');a=p.parse_args()
raw=Path(a.fixture).read_bytes();vectors=json.loads(raw)['capabilities'][a.capability]['vectors']
print(json.dumps({'capability':a.capability,'language':a.language,'status':'passed','fixtureSha256':hashlib.sha256(raw).hexdigest(),'results':[{'id':row['id'],'status':'passed'} for row in vectors]}))
''')
    trust["programs"] = {"scripts/check_sdk_conformance.py": sdk.sha(program.read_bytes()),
                         "synthetic-driver.py": sdk.sha(driver.read_bytes())}
    monkeypatch.setattr(executor, "load_trust", lambda: trust)
    monkeypatch.setattr(executor, "snapshot", lambda root: {})
    destination = tmp_path / "protected.json"
    executor.execute(root, destination, time.monotonic() + 5)
    actual = json.loads(destination.read_text())
    assert len(actual["actualLaunches"]) == 3
    assert all(row["status"] == "passed" for row in actual["actualLaunches"])
    assert actual["openGaps"] == trust["gaps"] and actual["releaseEligible"] is False
    assert sdk.gate_receipt(root, actual, trust=trust)["vectorOutcomeCount"] == 6


def test_bounded_driver_output_refused_and_recorded_without_raw_stream(tmp_path, monkeypatch):
    from scripts import ci_sdk_conformance_exec as executor
    monkeypatch.setattr(executor, "LIMIT", 8)
    driver = executor.Driver(tmp_path, {"programs": {}, "contracts": {}}, [], time.monotonic() + 3)
    with pytest.raises(sdk.Refused, match="driver_output_bound"):
        driver.run([sys.executable, "-c", "print('never-export-private-stream')"], cwd=tmp_path,
                   capture_output=True, text=True, timeout=2)
    assert driver.failure["code"] == "driver_output_bound"
    assert "never-export" not in json.dumps(driver.failure)


@pytest.mark.parametrize("summary,accepted", [
    ("test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out", True),
    ("test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out", False),
    ("test result: ok. 10 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out", False),
    ("test result: ok. 10 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out", False),
    ("test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 1 filtered out", False),
    ("test result: ok. 10 passed; 0 failed; 0 ignored; 1 measured; 0 filtered out", False),
    ("test result: ok. 10 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.01s", True),
    ("test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out\n" * 2, False),
    ("synthetic echo without unit evidence", False),
])
@pytest.mark.parametrize("stage", ["sdk-library-units", "binding-library-units"])
def test_unit_stage_requires_positive_actual_cargo_summary_shape(tmp_path, summary, accepted, stage):
    commands = sdk.Commands(tmp_path, tmp_path, {"PATH": os.defpath}, time.monotonic() + 5)
    command = [sys.executable, "-c", "print(" + repr(summary) + ")"]
    if accepted:
        commands.run(stage, command)
        assert commands.steps[0]["unitTests"] == {"passed": 10, "failed": 0, "ignored": 0, "measured": 0, "filteredOut": 0}
    else:
        with pytest.raises(sdk.Refused, match="unit_test_evidence"):
            commands.run(stage, command)


def test_failure_vector_attribution_only_accepts_reviewed_fixture_ids(tmp_path):
    root, report = gate_fixture(tmp_path)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    (private / "driver-failure.json").write_text(json.dumps({
        "code": "driver_failed", "adapter": {"capability": "synthetic.local.v1", "language": "rust"},
        "failedVectorIds": ["synthetic-one", "never-export-secret-id"], "returncode": 7,
        "private_extra": "never-export-secret-payload"}))
    actual = sdk.failure_diagnostics(private, root, "real-conformance", {}, report["expectedPlan"])
    assert actual["failedVectorIds"] == ["synthetic-one"]
    assert actual["vectorAttribution"] == "exact-known-ids"
    assert actual["adapter"]["fixtureSha256"] == report["expectedPlan"][0]["fixtureSha256"]
    assert actual["driverReturncode"] == 7
    assert "never-export" not in json.dumps(actual)


@pytest.mark.parametrize("invalid", [False, True])
def test_driver_stream_metadata_survives_only_as_bounded_counts_and_digests(tmp_path, invalid):
    root, raw = gate_fixture(tmp_path)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    output = {"code": "driver_failed", "returncode": 7,
              "stdoutBytes": 12, "stdoutSha256": "a" * 64,
              "stderrBytes": 34, "stderrSha256": "b" * 64,
              "stdout": "never-export-synthetic-secret", "stderr": "never-export-synthetic-secret"}
    if invalid:
        output.update(stdoutBytes=True, stdoutSha256="never-export-secretlike-digest",
                      stderrBytes=4 * 1024**2 + 65537)
    (private / "driver-failure.json").write_text(json.dumps(output))
    actual = sdk.failure_diagnostics(private, root, "real-conformance", {}, raw["expectedPlan"])
    assert actual["driverReturncode"] == 7
    for key in ("stdoutBytes", "stdoutSha256", "stderrBytes", "stderrSha256"):
        if invalid:
            assert key not in actual
        else:
            assert actual[key] == output[key]
    assert "never-export" not in json.dumps(actual)
    assert "stdout" not in actual and "stderr" not in actual


@pytest.mark.parametrize("raw,expected", [
    (b"ERR_PNPM_OUTDATED_LOCKFILE frozen file contains never-export-token", {"pnpm": ["ERR_PNPM_OUTDATED_LOCKFILE"]}),
    (b"npm error code ENOENT\nnpm error path /private/never-export-token", {"npm": ["ENOENT"]}),
    (b"frontend/packages/ui prepare: npm error code ENOENT\nnever-export-token", {"npm": ["ENOENT"]}),
    (b"frontend/packages/ui prepare: sh: 1: npm: not found\nnever-export-token", {"npmCommandMissing": True}),
    (b"Internal Error: Cannot find matching keyid: never-export-signature", {"corepack": ["corepack_signature_key_missing"]}),
    (b"sh: 1: npm: not found\nELIFECYCLE command failed", {"npmCommandMissing": True}),
    (b"ERR_PNPM_NEVER_EXPORT_SECRET\nnpm error code NEVER_EXPORT_SECRET\nnever-export-token", {"classification": "unclassified"}),
])
def test_package_setup_diagnostics_use_finite_identifiers_only(raw, expected):
    actual = sdk.package_diagnostics(raw)
    for key, value in expected.items():
        assert actual[key] == value
    assert "never-export" not in json.dumps(actual).lower()
    assert "NEVER_EXPORT" not in json.dumps(actual)
    assert "/private" not in json.dumps(actual)


def test_command_fingerprint_exposes_no_private_argv_or_home(tmp_path):
    executable = tmp_path / "pnpm"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    command = [str(executable), "install", "--frozen-lockfile", "never-export-synthetic-token"]
    actual = sdk.command_identity("node-dependencies", command, {"PATH": os.defpath})
    assert actual["tool"] == "pnpm" and actual["executableKind"] == "script"
    assert actual["argvSha256"] == sdk.sha(json.dumps(command, separators=(",", ":")).encode())
    assert actual["executableSha256"] == sdk.sha(executable.read_bytes())
    assert str(tmp_path) not in json.dumps(actual) and "never-export" not in json.dumps(actual)


def test_workspace_lifecycle_can_find_managed_npm_without_inheriting_user_state(tmp_path, monkeypatch):
    managed = tmp_path / "managed-node-bin"
    pinned = tmp_path / "attested-node-bin"
    package_manager = tmp_path / "pnpm-action-bin"
    empty = tmp_path / "empty-system-bin"
    home = tmp_path / "private-home"
    python_bin = tmp_path / "empty-python-bin"
    for directory in (managed, pinned, package_manager, empty, home, python_bin):
        directory.mkdir(mode=0o700)
    scripts = {
        managed / "npm": "#!/bin/sh\n[ \"$HOME\" = \"$INERT_PRIVATE_HOME\" ] || exit 99\nnode\nprintf 'managed-npm-used\\n'\n",
        managed / "node": "#!/bin/sh\nprintf 'unattested-node-wrong\\n'\n",
        pinned / "node": "#!/bin/sh\nprintf 'attested-node-used\\n'\n",
        package_manager / "pnpm": "#!/bin/sh\nexec /bin/sh -c 'npm run synthetic-workspace-prepare'\n",
    }
    for path, content in scripts.items():
        path.write_text(content)
        path.chmod(0o700)
    monkeypatch.setattr(sdk.os, "defpath", str(empty))
    # This reproduces the former builder's directory choices without calling a
    # real package manager, Node, network or any product program.
    old_path = os.pathsep.join((str(pinned), str(package_manager), str(python_bin), str(empty)))
    env = {"PATH": old_path, "HOME": str(home), "INERT_PRIVATE_HOME": str(home)}
    before = subprocess.run([str(package_manager / "pnpm"), "install", "--frozen-lockfile"],
                            env=env, capture_output=True, timeout=2)
    assert before.returncode == 127
    assert sdk.package_diagnostics(before.stderr)["npmCommandMissing"] is True
    env["PATH"] = sdk.tool_search_path(pinned / "node", package_manager / "rustup",
                                        package_manager / "pnpm", managed / "npm", python_bin / "python")
    after = subprocess.run([str(package_manager / "pnpm"), "install", "--frozen-lockfile"],
                           env=env, capture_output=True, timeout=2)
    assert after.returncode == 0
    assert after.stdout == b"attested-node-used\nmanaged-npm-used\n"
    assert not after.stderr
    assert env["HOME"] == str(home)


def test_setup_failure_projection_keeps_only_closed_manager_codes(tmp_path):
    private = tmp_path / "ci-private/sdk-synthetic"
    private.mkdir(parents=True, mode=0o700)
    (private / "node-dependencies.log").write_bytes(
        b"ERR_PNPM_UNSUPPORTED_ENGINE https://private.invalid/?token=never-export-token\n"
        b"npm error code EBADENGINE\n")
    result = sdk.failure_diagnostics(private, tmp_path, "node-dependencies", {}, [])
    assert result["packageManager"]["pnpm"] == ["ERR_PNPM_UNSUPPORTED_ENGINE"]
    assert result["packageManager"]["npm"] == ["EBADENGINE"]
    assert "https://" not in json.dumps(result) and "never-export" not in json.dumps(result)


@pytest.mark.parametrize("version,expected", [("10.23.0", {"name": "pnpm", "version": "10.23.0"}),
                                               ("10.23.0-never-export-secret", None)])
def test_command_entry_package_metadata_is_closed_and_not_a_runtime_version_claim(tmp_path, version, expected):
    directory = tmp_path / "managed-pnpm"
    (directory / "bin").mkdir(parents=True)
    executable = directory / "bin/pnpm"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    (directory / "package.json").write_text(json.dumps({"name": "pnpm", "version": version,
                                                       "private": "never-export-secret"}))
    result = sdk.command_identity("node-dependencies", [str(executable), "install", "--frozen-lockfile"], {"PATH": os.defpath})
    assert result["entryPackage"] == expected
    assert "never-export" not in json.dumps(result)


def test_readonly_running_python_and_venv_alias_identities_match_kernel():
    # Metadata/hash reads only; no SDK/product/package-manager call.
    aliases = [Path(sys.executable)]
    if Path("/tmp/rust-tui-sdk-python-venv/bin/python").exists():
        aliases.append(Path("/tmp/rust-tui-sdk-python-venv/bin/python"))
    receipts = [sdk.command_identity("python-environment", [str(alias), "-m", "venv", "synthetic"], {"PATH": os.defpath})
                for alias in aliases]
    assert all(value["admission"] == "current-python-kernel-fd" and value["tool"] == "python" for value in receipts)
    assert len({value["executableSha256"] for value in receipts}) == 1


def test_managed_alias_fd_launch_preserves_private_venv_identity(tmp_path):
    alias = tmp_path / "managed-python"
    alias.symlink_to(sys.executable)
    commands = sdk.Commands(tmp_path, tmp_path, {"PATH": os.defpath, "HOME": str(tmp_path), "PYTHONNOUSERSITE": "1"}, time.monotonic() + 5)
    script = "import sys,json;print(json.dumps({'same_alias':sys.executable==sys.argv[1],'version':list(sys.version_info[:2])}))"
    log = commands.run("python-environment", [str(alias), "-c", script, str(alias)], seconds=3)
    assert json.loads(log.read_text()) == {"same_alias": True, "version": list(sys.version_info[:2])}
    assert commands.steps[0]["started"] is True
    assert commands.steps[0]["command"]["admission"] == "current-python-kernel-fd"


def test_fd_launch_does_not_execute_replaced_alias_and_records_held_failure(tmp_path):
    alias = tmp_path / "managed-python"
    alias.symlink_to(sys.executable)
    marker = tmp_path / "wrong-executable-ran"
    wrong = tmp_path / "wrong-shell"
    wrong.write_text("#!/bin/sh\n: > " + str(marker) + "\n")
    wrong.chmod(0o700)
    command = [str(alias), "-c", "print('verified-python-image')"]
    with sdk.admitted_command("python-load", command, {"PATH": os.defpath}) as entry:
        alias.unlink()
        alias.symlink_to(wrong)
        result = subprocess.run(command, **entry.execution(), capture_output=True, text=True, timeout=2,
                                env={"PATH": os.defpath, "HOME": str(tmp_path), "PYTHONNOUSERSITE": "1"})
        assert result.returncode == 0 and result.stdout == "verified-python-image\n"
        assert not marker.exists()
        with pytest.raises(sdk.Refused, match="^command_executable_alias_changed$"):
            entry.held()


def test_arbitrary_shell_is_not_admitted_as_managed_python(tmp_path):
    executable = tmp_path / "python"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    commands = sdk.Commands(tmp_path, tmp_path, {"PATH": os.defpath}, time.monotonic() + 3)
    with pytest.raises(sdk.Refused, match="^command_python_kernel_mismatch$"):
        commands.run("python-environment", [str(executable), "-m", "venv", "synthetic"])
    record = commands.steps[0]
    assert record["started"] is False and record["returncode"] is None
    assert record["identityFacet"] == "command_python_kernel_mismatch"
    assert not (tmp_path / "python-environment.log").exists()


def test_vendor_metadata_only_allowed_for_proven_current_python():
    from types import SimpleNamespace
    import stat
    info = SimpleNamespace(st_mode=stat.S_IFREG | 0o777, st_uid=os.getuid() + 10000, st_size=1234)
    sdk.command_policy(info, python=True, kernel_match=True)
    with pytest.raises(sdk.Refused, match="^command_python_kernel_mismatch$"):
        sdk.command_policy(info, python=True, kernel_match=False)
    with pytest.raises(sdk.Refused, match="^command_executable_owner$"):
        sdk.command_policy(info, python=False, kernel_match=True)
    info.st_uid = os.getuid()
    with pytest.raises(sdk.Refused, match="^command_executable_world_writable$"):
        sdk.command_policy(info, python=False, kernel_match=True)


def test_world_writable_node_still_refused_without_any_python_exception(tmp_path):
    executable = tmp_path / "node"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o777)
    with pytest.raises(sdk.Refused, match="^command_executable_world_writable$"):
        sdk.command_identity("napi-load", [str(executable)], {"PATH": os.defpath})



def test_fd_launch_preserves_minimal_private_venv_prefix(tmp_path):
    environment = tmp_path / "private-venv"
    (environment / "bin").mkdir(parents=True, mode=0o700)
    alias = environment / "bin/python"
    alias.symlink_to(sys.executable)
    base = Path(getattr(sys, "_base_executable", sys.executable)).resolve().parent
    (environment / "pyvenv.cfg").write_text("home = " + str(base) + "\ninclude-system-site-packages = false\nversion = " + str(sys.version_info.major) + "." + str(sys.version_info.minor) + "\n")
    command = [str(alias), "-c", "import sys,json;print(json.dumps({'alias':sys.executable==sys.argv[1],'prefix':sys.prefix==sys.argv[2],'isolated':sys.prefix!=sys.base_prefix}))", str(alias), str(environment)]
    with sdk.admitted_command("python-load", command, {"PATH": os.defpath}) as entry:
        child = subprocess.run(command, **entry.execution(), capture_output=True, text=True, timeout=3,
                               env={"PATH": os.defpath, "HOME": str(tmp_path), "PYTHONNOUSERSITE": "1"})
        assert child.returncode == 0
        assert json.loads(child.stdout) == {"alias": True, "prefix": True, "isolated": True}
        entry.held()


def test_readonly_local_node_identity_keeps_strict_policy():
    import shutil
    executable = shutil.which("node")
    if executable is None:
        pytest.skip("No local Node for read-only identity check")
    receipt = sdk.command_identity("napi-load", [executable, "--version"], {"PATH": os.defpath})
    assert receipt["tool"] == "node" and receipt["admission"] == "strict-owner-mode"
    assert receipt["executableKind"] == "elf"


def monitor_failure_report():
    expected = next(row for row in sdk.load_trust()["plan"]
                    if row["capability"] == "session.chat-change-monitor.v1" and row["language"] == "rust")
    diagnostic = {"vectorId": expected["vectors"][0], "phase": "stage", "errorCode": "unclassified"}
    return expected, {"capability": expected["capability"], "language": "rust", "status": "failed",
                      "fixtureSha256": expected["fixtureSha256"], "diagnostic": diagnostic,
                      "results": [{"id": diagnostic["vectorId"], "status": "failed"}]}


def fault_monitor_report(report, fault, expected):
    if fault == "extra":
        report["diagnostic"]["message"] = "never-export-private-payload"
    elif fault == "arbitrary_text":
        report["diagnostic"]["errorCode"] = "never-export-token"
    elif fault == "phase":
        report["diagnostic"]["phase"] = "never-export-path"
    elif fault == "foreign_vector":
        report["diagnostic"]["vectorId"] = "never-export-private-id"
    elif fault == "nonfailed_vector":
        report["diagnostic"]["vectorId"] = expected["vectors"][1]
        report["results"].append({"id": expected["vectors"][1], "status": "passed"})
    elif fault == "oversize":
        report["diagnostic"]["phase"] = "never-export-" * 1000
    elif fault == "malformed":
        report["diagnostic"] = [report["diagnostic"]]
    elif fault == "field_type":
        report["diagnostic"]["errorCode"] = {"secret": "never-export-token"}
    elif fault == "missing":
        del report["diagnostic"]["phase"]
    elif fault == "language":
        report["language"] = "python"
    elif fault == "capability":
        report["capability"] = "session.foreground-completion-recovery.v1"
    elif fault == "fixture":
        report["fixtureSha256"] = "f" * 64
    elif fault == "status":
        report["status"] = "passed"


@pytest.mark.parametrize("fault", [None, "extra", "arbitrary_text", "phase", "foreign_vector",
                                   "nonfailed_vector", "oversize", "malformed", "field_type", "missing",
                                   "language", "capability", "fixture", "status"])
def test_failed_monitor_driver_projects_only_exact_closed_fixture_diagnostic(tmp_path, fault):
    from scripts import ci_sdk_conformance_exec as executor
    expected, report = monitor_failure_report()
    fault_monitor_report(report, fault, expected)
    report["private_extra"] = "never-export-raw-output"
    command = [sys.executable, "-c", "import sys;sys.stdout.write(sys.argv[1]);sys.exit(7)",
               json.dumps(report), "--capability", expected["capability"]]
    driver = executor.Driver(tmp_path, {"programs": {}, "contracts": {}}, [expected], time.monotonic() + 5)
    driver.commands = [command]
    with pytest.raises(sdk.Refused, match="^driver_failed$"):
        driver.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=2)
    assert driver.failure["code"] == "driver_failed" and driver.failure["terminatedReturncode"] == 7
    assert driver.launches[0]["status"] == "started"  # Diagnostics never manufacture a passing launch.
    if fault is None:
        assert driver.failure["diagnostic"] == report["diagnostic"]
    else:
        assert "diagnostic" not in driver.failure
    assert "never-export" not in json.dumps(driver.failure)


@pytest.mark.parametrize("fault", [None, "extra", "arbitrary_text", "phase", "foreign_vector",
                                   "nonfailed_vector", "oversize", "malformed", "field_type", "missing"])
def test_public_failure_receipt_revalidates_monitor_diagnostic(tmp_path, fault):
    expected, report = monitor_failure_report()
    failed_id = report["results"][0]["id"]
    fault_monitor_report(report, fault, expected)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    driver = {"code": "driver_failed", "adapter": {"capability": expected["capability"], "language": "rust"},
              "failedVectorIds": [failed_id], "diagnostic": report["diagnostic"],
              "private_extra": "never-export-private-output"}
    (private / "driver-failure.json").write_text(json.dumps(driver))
    actual = sdk.failure_diagnostics(private, tmp_path, "real-conformance", {}, [expected])
    assert actual["failedVectorIds"] == [failed_id] and actual["rawUpload"] is False
    if fault is None:
        assert actual["diagnostic"] == report["diagnostic"]
    else:
        assert "diagnostic" not in actual
    assert "never-export" not in json.dumps(actual)


@pytest.mark.parametrize("capability,language", [
    ("session.chat-change-monitor.v1", "npm"),
    ("session.chat-change-monitor.v1", "python"),
    ("session.foreground-completion-recovery.v1", "rust"),
])
def test_vector_diagnostic_never_broadens_unrelated_adapter_scope(capability, language):
    expected, report = monitor_failure_report()
    expected = {**expected, "capability": capability, "language": language}
    diagnostic = report["diagnostic"]
    assert sdk.project_vector_diagnostic(diagnostic, expected, [diagnostic["vectorId"]]) is None


@pytest.mark.parametrize("phase,code", [
    ("list", "invalid"), ("discard", "crypto"), ("durable_read", "storage_io"),
    ("peer_start", "peer_protocol"), ("storage_setup", "storage_io"), ("client_setup", "unclassified"),
])
def test_monitor_diagnostic_accepts_explicit_operation_phase_and_closed_code(phase, code):
    expected, report = monitor_failure_report()
    diagnostic = {**report["diagnostic"], "phase": phase, "errorCode": code}
    assert sdk.project_vector_diagnostic(diagnostic, expected, [diagnostic["vectorId"]]) == diagnostic


@pytest.mark.parametrize("duplicate", ["errorCode", "fixtureSha256"])
def test_duplicate_failed_stdout_fields_cannot_authorize_diagnostic(tmp_path, duplicate):
    from scripts import ci_sdk_conformance_exec as executor
    expected, report = monitor_failure_report()
    raw = json.dumps(report)
    target = json.dumps(report["diagnostic"]["errorCode"] if duplicate == "errorCode" else report[duplicate])
    raw = raw.replace(json.dumps(duplicate) + ": " + target,
                      json.dumps(duplicate) + ": \"never-export-ambiguous-value\", "
                      + json.dumps(duplicate) + ": " + target, 1)
    command = [sys.executable, "-c", "import sys;sys.stdout.write(sys.argv[1]);sys.exit(7)",
               raw, "--capability", expected["capability"]]
    driver = executor.Driver(tmp_path, {"programs": {}, "contracts": {}}, [expected], time.monotonic() + 5)
    driver.commands = [command]
    with pytest.raises(sdk.Refused, match="^driver_failed$"):
        driver.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=2)
    assert "diagnostic" not in driver.failure and "never-export" not in json.dumps(driver.failure)


def test_monitor_diagnostic_not_projected_outside_conformance_stage(tmp_path):
    expected, report = monitor_failure_report()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    (private / "driver-failure.json").write_text(json.dumps({
        "code": "driver_failed", "adapter": {"capability": expected["capability"], "language": "rust"},
        "failedVectorIds": [report["diagnostic"]["vectorId"]], "diagnostic": report["diagnostic"]}))
    actual = sdk.failure_diagnostics(private, tmp_path, "python-binding-build", {}, [expected])
    assert "diagnostic" not in actual


def unit_location_fixture(tmp_path, stage="sdk-library-units", source=None):
    root = tmp_path / "subject"
    name = str(Path(sdk.LIBRARY_UNIT_MANIFESTS[stage]).parent / "src/lib.rs")
    path = root / name
    path.parent.mkdir(parents=True)
    path.write_text(source or 'fn actual() {}\nfn unicode() { let _ = "é🦀"; }\n')
    return root, {name: sdk.sha(path.read_bytes())}, name


def failed_unit_summary(passed=2, failed=1, ignored=0, measured=0, filtered=0):
    return (f"test result: FAILED. {passed} passed; {failed} failed; {ignored} ignored; "
            f"{measured} measured; {filtered} filtered out; finished in 69.54s")


@pytest.mark.parametrize("stage", list(sdk.LIBRARY_UNIT_MANIFESTS))
def test_rust_unit_projection_is_coordinates_and_counts_only_never_test_names_or_values(tmp_path, stage):
    root, inputs, tracked = unit_location_fixture(tmp_path, stage)
    data = ("running 3 tests\n"
            "test never_export_test_token ... FAILED\n"
            "---- never_export_test_token stdout ----\n"
            f"thread 'never_export_thread_token' (123456) panicked at {tracked}:1:4:\n"
            "assertion `left == right` failed\nleft: never-export-password\nright: never-export-network-body\n"
            + failed_unit_summary() + "\n\nerror: test failed, to rerun pass `--lib`\n").encode()
    actual = sdk.rust_unit_diagnostics(data, root, inputs, stage)
    assert actual == {"panicLocations": [{"path": tracked, "line": 1, "column": 4}],
                      "reportedCounts": {"passed": 2, "failed": 1, "ignored": 0, "measured": 0, "filteredOut": 0}}
    assert "never_export" not in json.dumps(actual) and "never-export" not in json.dumps(actual)
    assert "123456" not in json.dumps(actual) and "failedTests" not in actual


@pytest.mark.parametrize("source", [
    'macro_rules! unused { () => { mod phantom { #[test] fn not_a_real_test() {} } }; }',
    'fn outer() { mod inner { #[test] fn not_registered() {} } }',
    '#[some_macro([0] mod phantom { #[test] fn not_a_real_test() {} })]\nfn wrapper() {}\n#[test]\nfn actual() {}',
])
def test_rust_unit_projection_never_inventories_any_source_test_module_or_attribute(tmp_path, source):
    root, inputs, _ = unit_location_fixture(tmp_path, source=source)
    raw = b"test phantom::not_a_real_test ... FAILED\ntest inner::not_registered ... FAILED\n"
    assert sdk.rust_unit_diagnostics(raw, root, inputs, "sdk-library-units") is None
    assert not hasattr(sdk, "unit_test_inventory")


@pytest.mark.parametrize("location", ["/private/never-export-token:1:2", "src/untracked.rs:1:2",
    "src/lib.rs:0:2", "src/lib.rs:99999999:2", "src/lib.rs:1:0", "src/lib.rs:1:999999",
    "src/lib.rs:1:16", "src/lib.rs:2:36"])
def test_rust_unit_untracked_or_out_of_range_panic_coordinates_omit_every_raw_field(tmp_path, location):
    root, inputs, _ = unit_location_fixture(tmp_path)
    raw = f"thread 'never-export-thread' panicked at {location}:\nnever-export-secret\n".encode()
    assert sdk.rust_unit_diagnostics(raw, root, inputs, "sdk-library-units") is None


@pytest.mark.parametrize("line,column", [(1, 1), (1, 15), (2, 30), (2, 34), (2, 35)])
def test_rust_unit_panic_coordinates_allow_character_byte_and_end_of_line_widths(tmp_path, line, column):
    root, inputs, tracked = unit_location_fixture(tmp_path)
    raw = f"thread '<unnamed>' (4321) panicked at src/lib.rs:{line}:{column}:\nnever-export\n".encode()
    assert sdk.rust_unit_diagnostics(raw, root, inputs, "sdk-library-units") == {
        "panicLocations": [{"path": tracked, "line": line, "column": column}]}


@pytest.mark.parametrize("fault", ["changed", "missing", "symlink", "bytes", "files"])
def test_rust_unit_coordinates_require_held_source_identity_and_resource_bounds(tmp_path, monkeypatch, fault):
    root, inputs, tracked = unit_location_fixture(tmp_path)
    path = root / tracked
    if fault == "changed":
        path.write_text('fn changed() {}\n')
    elif fault == "missing":
        path.unlink()
    elif fault == "symlink":
        path.unlink()
        foreign = tmp_path / "never-export-source"
        foreign.write_text('fn private() {}\n')
        path.symlink_to(foreign)
    elif fault == "bytes":
        monkeypatch.setattr(sdk, "MAX_UNIT_SOURCE_BYTES", 1)
    else:
        monkeypatch.setattr(sdk, "MAX_UNIT_SOURCE_FILES", 0)
    assert sdk.rust_unit_diagnostics(b"thread 'private' panicked at src/lib.rs:1:2:\n", root, inputs, "sdk-library-units") is None


@pytest.mark.parametrize("raw", [
    "error: private counter 12345\n",
    "private assertion: " + failed_unit_summary(),
    failed_unit_summary() + "\nnever-export-trailing-assertion",
    failed_unit_summary(failed=1000001),
    failed_unit_summary(failed=0),
    "running 9 tests\n" + failed_unit_summary(),
    "running 1000001 tests\n" + failed_unit_summary(),
    failed_unit_summary() + "\ntest result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.00s",
    "test result: FAILED. 2 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out;",
    failed_unit_summary() + "\nerror: never-export-secret",
])
def test_rust_unit_counts_require_trailing_complete_bounded_failed_summary_and_consistent_running(tmp_path, raw):
    root, inputs, _ = unit_location_fixture(tmp_path)
    assert sdk.rust_unit_diagnostics(raw.encode(), root, inputs, "sdk-library-units") is None


def test_rust_unit_counts_select_final_complete_summary_and_omit_raw_noise(tmp_path):
    root, inputs, _ = unit_location_fixture(tmp_path)
    raw = (failed_unit_summary(passed=999) + "\nnever-export-panic-text\n"
           "running 4 tests\n" + failed_unit_summary(ignored=1, filtered=20)
           + "\nerror: test failed, to rerun pass `-p openmates-rust --lib`\n")
    assert sdk.rust_unit_diagnostics(raw.encode(), root, inputs, "sdk-library-units") == {
        "panicLocations": [], "reportedCounts": {"passed": 2, "failed": 1, "ignored": 1, "measured": 0, "filteredOut": 20}}


def test_rust_unit_location_cap_dedup_and_log_tail_are_bounded(tmp_path, monkeypatch):
    root, inputs, tracked = unit_location_fixture(tmp_path)
    monkeypatch.setattr(sdk, "MAX_UNIT_DIAGNOSTIC_LOCATIONS", 1)
    raw = ("thread 'private' panicked at src/lib.rs:1:2:\n" * 3
           + "thread 'private' panicked at src/lib.rs:2:2:\n").encode()
    assert sdk.rust_unit_diagnostics(raw, root, inputs, "sdk-library-units") == {
        "panicLocations": [{"path": tracked, "line": 1, "column": 2}]}
    assert sdk.rust_unit_diagnostics(raw + b"x" * 65536, root, inputs, "sdk-library-units") is None


def test_failure_diagnostics_preserves_compiler_private_retention_exit_scope_and_never_exports_identifiers(tmp_path):
    root, inputs, tracked = unit_location_fixture(tmp_path)
    private = tmp_path / "private" / "sdk-synthetic"
    private.mkdir(parents=True, mode=0o700)
    data = (f"error[E0425]: never-export-compiler\n --> {tracked}:1:2\n"
            "thread 'never-export-thread' panicked at src/lib.rs:1:2:\nnever-export-assertion\n").encode()
    (private / "sdk-library-units.log").write_bytes(data)
    actual = sdk.failure_diagnostics(private, root, "sdk-library-units", inputs, [])
    assert actual["category"] == "rust_compile_or_unit" and actual["rawUpload"] is False
    assert actual["compiler"][0]["code"] == "E0425"
    assert actual["rustUnits"] == {"panicLocations": [{"path": tracked, "line": 1, "column": 2}]}
    assert actual["privateRetained"]["sha256"] == sdk.sha(data)
    retained = list(private.parent.glob("failure-sdk-*/sdk-library-units.log"))
    assert len(retained) == 1 and retained[0].read_bytes() == data and retained[0].stat().st_mode & 0o777 == 0o600
    assert "never-export" not in json.dumps(actual)
    (private / "napi-build.log").write_bytes(data)
    assert "rustUnits" not in sdk.failure_diagnostics(private, root, "napi-build", inputs, [])


def message_window_gate_fixture(tmp_path, *, historical=False, message_id_current=False):
    """Synthetic validator input only; never an actual library pass receipt."""
    root, report = gate_fixture(tmp_path)
    identity = "session.message-window.v1"
    trust = sdk.load_trust()
    assert not (historical and message_id_current)
    if not message_id_current:
        trust = restore_before_message_id_registration(trust)
    if historical:
        trust = restore_before_cache_adapter_registration(trust)
    vectors = next(
        row["vectors"]
        for row in trust["plan"]
        if row["capability"] == identity
    )
    if message_id_current:
        assert len(vectors) == 27
    elif historical:
        assert len(vectors) == 24
    else:
        assert len(vectors) == 25
    matrix_path = root / "config/sdk-capabilities.json"
    matrix = json.loads(matrix_path.read_text())
    matrix["capabilities"][0]["id"] = identity
    matrix["fixture"] = "tests/sdk-conformance/window-synthetic.json"
    raw = {
        "capabilities": {identity: {"vectors": [{"id": value} for value in vectors]}}
    }
    fixture = root / matrix["fixture"]
    fixture.write_text(json.dumps(raw))
    matrix_path.write_text(json.dumps(matrix))
    report["matrixSha256"] = sdk.sha(matrix_path.read_bytes())
    report["openGaps"] = sdk.matrix_gaps(matrix)
    report["conformance"] = [
        {
            "capability": identity,
            "language": language,
            "fixtureSha256": sdk.sha(fixture.read_bytes()),
            "status": "passed",
            "results": [{"id": value, "status": "passed"} for value in vectors],
        }
        for language in ("rust", "npm", "python")
    ]
    report["expectedPlan"] = sdk.execution_plan(root, matrix)
    report["actualLaunches"] = [
        {
            "capability": row["capability"],
            "language": row["language"],
            "status": "passed",
            "commandSha256": "d" * 64,
        }
        for row in report["expectedPlan"]
    ]
    return root, report


@pytest.mark.parametrize("historical", [False, True])
def test_three_complete_window_validator_rows_remain_blocked_by_declared_gap(tmp_path, historical):
    root, report = message_window_gate_fixture(tmp_path, historical=historical)
    result = sdk.gate_receipt(root, report, trust=synthetic_trust(root))
    if historical:
        assert result["realRunCount"] == 3 and result["vectorOutcomeCount"] == 72
    else:
        assert result["realRunCount"] == 3 and result["vectorOutcomeCount"] == 75
    assert result["openGapCount"] == 1 and result["releaseEligible"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "missing_adapter",
        "duplicate_adapter",
        "missing_vector",
        "extra_vector",
        "wrong_fixture",
        "wrong_capability",
        "wrong_language",
        "plan_reordered",
        "missing_launch",
        "launch_reordered",
        "gap_erased",
        "release_claim",
    ],
)
@pytest.mark.parametrize("historical", [False, True])
def test_window_admission_rejects_partial_forged_or_reordered_results(tmp_path, fault, historical):
    root, report = message_window_gate_fixture(tmp_path, historical=historical)
    if fault == "missing_adapter":
        report["conformance"].pop()
    elif fault == "duplicate_adapter":
        report["conformance"][1] = copy.deepcopy(report["conformance"][0])
    elif fault == "missing_vector":
        report["conformance"][0]["results"].pop()
    elif fault == "extra_vector":
        report["conformance"][0]["results"].append(
            {"id": "invented-private", "status": "passed"}
        )
    elif fault == "wrong_fixture":
        report["conformance"][0]["fixtureSha256"] = "f" * 64
    elif fault == "wrong_capability":
        report["conformance"][0]["capability"] = "unreviewed"
    elif fault == "wrong_language":
        report["conformance"][0]["language"] = "unreviewed"
    elif fault == "plan_reordered":
        report["expectedPlan"].reverse()
    elif fault == "missing_launch":
        report["actualLaunches"].pop()
    elif fault == "launch_reordered":
        report["actualLaunches"].reverse()
    elif fault == "gap_erased":
        report["openGaps"] = []
    else:
        report["releaseEligible"] = True
    with pytest.raises(sdk.Refused):
        sdk.gate_receipt(root, report, trust=synthetic_trust(root))


# Message-window failures reuse the owned driver and its existing bounded streams.
def message_window_failure_report():
    expected = {"capability": "session.message-window.v1", "language": "rust",
                "vectors": ["window-latest", "window-before"], "fixtureSha256": "a" * 64}
    report = {"capability": expected["capability"], "language": "rust", "status": "failed",
              "fixtureSha256": expected["fixtureSha256"],
              "results": [{"id": "window-latest", "status": "failed"}],
              "diagnostic": {"vectorId": "window-latest", "phase": "window_assert",
                             "errorCode": "assertion", "sourceCoordinate": "run_vector.window_assert"}}
    return expected, report


def fault_message_window_report(report, fault):
    diagnostic = report["diagnostic"]
    if fault == "extra":
        diagnostic["message"] = "never-export-raw-error"
    elif fault == "missing":
        del diagnostic["sourceCoordinate"]
    elif fault == "foreign_vector":
        diagnostic["vectorId"] = "never-export-foreign-id"
    elif fault == "nonfailed_vector":
        diagnostic["vectorId"] = "window-before"
    elif fault == "phase":
        diagnostic["phase"] = "never-export-checkpoint"
    elif fault == "error":
        diagnostic["errorCode"] = "never-export-error-prose"
    elif fault == "coordinate":
        diagnostic["sourceCoordinate"] = "never-export-path"
    elif fault == "mismatched_coordinate":
        diagnostic["sourceCoordinate"] = "run_vector.peer_start"
    elif fault == "oversize":
        diagnostic["sourceCoordinate"] = "never-export-" * 1024
    elif fault == "type":
        diagnostic["sourceCoordinate"] = {"secret": "never-export-token"}
    elif fault in {"fixture", "language", "status", "capability"}:
        report[{"fixture": "fixtureSha256"}.get(fault, fault)] = {
            "fixture": "b" * 64, "language": "npm", "status": "passed",
            "capability": "session.saved-chat-read.v1"}[fault]


@pytest.mark.parametrize("phase", sorted(sdk.MESSAGE_WINDOW_DIAGNOSTIC_PHASES))
def test_message_window_exact_checkpoint_projects_closed_source_coordinate(phase):
    expected, report = message_window_failure_report()
    diagnostic = {**report["diagnostic"], "phase": phase, "sourceCoordinate": "run_vector." + phase}
    assert sdk.project_vector_diagnostic(diagnostic, expected, ["window-latest"]) == diagnostic


@pytest.mark.parametrize("fault", [None, "extra", "missing", "foreign_vector", "nonfailed_vector",
    "phase", "error", "coordinate", "mismatched_coordinate", "oversize", "type", "fixture",
    "language", "status", "capability", "duplicate"])
def test_message_window_driver_nonzero_failure_remains_failed_and_projects_only_closed_fields(tmp_path, fault):
    from scripts import ci_sdk_conformance_exec as executor
    expected, report = message_window_failure_report()
    fault_message_window_report(report, fault)
    raw = json.dumps(report)
    if fault == "duplicate":
        raw = raw.replace('"sourceCoordinate": ', '"sourceCoordinate":"never-export-ambiguous", "sourceCoordinate": ', 1)
    command = [sys.executable, "-c", "import sys;sys.stdout.write(sys.argv[1]);sys.exit(1)",
               raw, "--capability", expected["capability"]]
    driver = executor.Driver(tmp_path, {"programs": {}, "contracts": {}}, [expected], time.monotonic() + 5)
    driver.commands = [command]
    with pytest.raises(sdk.Refused, match="^driver_failed$"):
        driver.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=2)
    assert driver.failure["terminatedReturncode"] == 1 and driver.launches[0]["status"] == "started"
    if fault is None:
        assert driver.failure["diagnostic"] == report["diagnostic"]
        assert driver.failure["failedVectorIds"] == ["window-latest"]
    else:
        assert "diagnostic" not in driver.failure
    assert "never-export" not in json.dumps(driver.failure)


@pytest.mark.parametrize("fault", [None, "extra", "missing", "foreign_vector", "nonfailed_vector",
    "phase", "error", "coordinate", "mismatched_coordinate", "oversize", "type"])
def test_message_window_public_projection_revalidates_checkpoint_without_private_data(tmp_path, fault):
    expected, report = message_window_failure_report()
    fault_message_window_report(report, fault)
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    (private / "driver-failure.json").write_text(json.dumps({"code":"driver_failed",
        "adapter":{"capability":expected["capability"],"language":"rust"},
        "failedVectorIds":["window-latest"], "diagnostic":report["diagnostic"],
        "private_extra":"never-export-private-payload"}))
    actual = sdk.failure_diagnostics(private, tmp_path, "real-conformance", {}, [expected])
    assert actual["rawUpload"] is False and actual["failedVectorIds"] == ["window-latest"]
    if fault is None:
        assert actual["diagnostic"] == report["diagnostic"]
    else:
        assert "diagnostic" not in actual
    assert "never-export" not in json.dumps(actual)


def test_message_window_diagnostic_stays_rust_conformance_only(tmp_path):
    expected, report = message_window_failure_report()
    for language in ("npm", "python"):
        assert sdk.project_vector_diagnostic(report["diagnostic"], {**expected, "language":language}, ["window-latest"]) is None
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    (private / "driver-failure.json").write_text(json.dumps({"code":"driver_failed",
        "adapter":{"capability":expected["capability"],"language":"rust"},
        "failedVectorIds":["window-latest"], "diagnostic":report["diagnostic"]}))
    assert "diagnostic" not in sdk.failure_diagnostics(private, tmp_path, "napi-build", {}, [expected])


def immutable_trust_test_fixture(name, expected_sha256):
    # Historical inputs are test data only. Runtime load_trust/verify_programs
    # continue reading the protected live manifest beside their module.
    raw = (Path(__file__).with_name("fixtures") / name).read_bytes()
    assert sdk.sha(raw) == expected_sha256
    return json.loads(raw)


def test_current_reviewed_aggregate_keeps_exact_live_authority_and_counts():
    approval = immutable_trust_test_fixture("sdk-conformance-trust-reviewed229-delta.json", "bdbd7a7d020394bc71d6ab84da1abc9a7fae75c748f04d920c1708c24fa9b969")
    live_path = Path(sdk.__file__).with_name("ci_sdk_conformance_trust.json")
    live_bytes = live_path.read_bytes()
    assert sdk.sha(live_bytes) == "f3f2041553a6063a8fbe7a41761be6b0cdfe1c7893be49159514dff40c5013b0"
    trust = sdk.load_trust()
    assert trust == json.loads(live_bytes)
    trust = restore_before_cache_settlement_registration(trust)
    assert {k: len(trust[k]) for k in approval["afterCounts"]} == {'programs': 263, 'contracts': 67, 'plan': 87, 'gaps': 174}
    assert approval["approvedCurrentSha256"] == sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode())
    assert trust["gaps"] and approval["releaseEligible"] is False
    assert {k: v for k, v in trust.items() if k not in ("programs", "contracts", "plan", "gaps")} == approval["unrelatedMetadata"]


def test_current_reviewed_aggregate_preserves_exact_old_pins_and_expectations():
    approval = immutable_trust_test_fixture("sdk-conformance-trust-reviewed229-delta.json", "bdbd7a7d020394bc71d6ab84da1abc9a7fae75c748f04d920c1708c24fa9b969")
    trust = restore_before_cookie_registration(sdk.load_trust(), approval)
    for bucket in ("programs", "contracts"):
        restored = copy.deepcopy(trust[bucket])
        added = updated = 0
        for path, change in approval["pinDeltas"][bucket].items():
            assert restored[path] == change["after"]
            if change["before"] is None:
                del restored[path]
                added += 1
            else:
                restored[path] = change["before"]
                updated += 1
        assert (added, updated) == {"programs": (45, 29), "contracts": (13, 2)}[bucket]
        assert len(restored) == approval["beforeCounts"][bucket]
        assert sdk.sha(json.dumps(restored, sort_keys=True).encode()) == approval["baseDictionaryDigests"][bucket]
    delta = approval["expectations"]
    plans = copy.deepcopy(trust["plan"])
    for added in delta["planAdded"]:
        assert plans.count(added) == 1
        assert added["capability"] == "sdk.embeds.version-content"
        assert len(added["vectors"]) == len(set(added["vectors"])) == 102
        plans.remove(added)
    for change in delta["planChanged"]:
        assert change["after"]["capability"] == "session.password-totp-rotation.v1"
        assert len(change["before"]["vectors"]) == 6 and len(change["after"]["vectors"]) == 14
        index = plans.index(change["after"])
        plans[index] = change["before"]
    assert len(delta["planAdded"]) == len(delta["planChanged"]) == 3
    assert len(plans) == 81
    assert sdk.sha(json.dumps(plans, sort_keys=True).encode()) == approval["baseDictionaryDigests"]["plan"]
    gaps = copy.deepcopy(trust["gaps"])
    for added in delta["gapAdded"]:
        assert gaps.count(added) == 1 and added.startswith("sdk.embeds.version-content [")
        gaps.remove(added)
    for change in delta["gapChanged"]:
        assert change["after"].startswith(("session.password-totp-rotation.v1 [", "sdk.session-client ["))
        index = gaps.index(change["after"])
        gaps[index] = change["before"]
    assert len(delta["gapAdded"]) == 3 and len(delta["gapChanged"]) == 6
    assert sum(c["after"].startswith("session.password-totp-rotation.v1 [") for c in delta["gapChanged"]) == 3
    assert sum(c["after"].startswith("sdk.session-client [") for c in delta["gapChanged"]) == 3
    assert len(gaps) == 168
    assert sdk.sha(json.dumps(gaps, sort_keys=True).encode()) == approval["baseDictionaryDigests"]["gaps"]

    # Restore the immediately prior published229 snapshot independently of the
    # older201 baseline. This preserves its readable exact review witness.
    witness = approval["priorApproved229Witness"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in witness["wavePinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    assert witness["planUnchanged"] is True
    for change in witness["gapChanged"]:
        index = prior["gaps"].index(change["after"])
        prior["gaps"][index] = change["before"]
    assert {k: len(prior[k]) for k in witness["counts"]} == {"programs": 229, "contracts": 60, "plan": 84, "gaps": 171}
    assert witness["trustSha256"] == "078292cbdf749ac0d7f5b23e898dcd01931fb45947eaaaa2b1273cf76bafa43a"
    for bucket in ("programs", "contracts", "plan", "gaps"):
        assert sdk.sha(json.dumps(prior[bucket], sort_keys=True).encode()) == witness["dictionaryDigests"][bucket]


def test_current_mechanical_compile_fix_preserves_exact_prior246_authority():
    approval = immutable_trust_test_fixture("sdk-conformance-trust-reviewed229-delta.json", "bdbd7a7d020394bc71d6ab84da1abc9a7fae75c748f04d920c1708c24fa9b969")
    witness = approval["priorApproved246Witness"]
    trust = restore_before_cookie_registration(sdk.load_trust(), approval)
    prior = copy.deepcopy(trust)
    assert set(witness["programPinDeltas"]) == {
        "packages/openmates-rust/src/client/saved_chat_read.rs",
        "packages/openmates-rust/src/client/recovery/opaque_tests.rs",
        "packages/openmates-rust/src/client/transport_plaintext_tests.rs",
    }
    for path, change in witness["programPinDeltas"].items():
        assert prior["programs"][path] == change["after"]
        prior["programs"][path] = change["before"]
    assert witness["contractsPlansGapsMetadataUnchanged"] is True
    assert {k: len(prior[k]) for k in witness["counts"]} == {"programs": 246, "contracts": 63, "plan": 84, "gaps": 171}
    assert witness["trustSha256"] == "14e1b8915bb01579168943b7f68bc757c79f04c16cf6b9b9df0f4595a897559a"
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == witness["trustSha256"]
    for bucket in ("programs", "contracts", "plan", "gaps"):
        assert sdk.sha(json.dumps(prior[bucket], sort_keys=True).encode()) == witness["dictionaryDigests"][bucket]


def restore_before_cookie_registration(trust, approval):
    trust = restore_before_cache_settlement_registration(trust)
    witness = approval["priorCompileFix246Witness"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in witness["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for bucket, field in (("plan", "planAdded"), ("gaps", "gapAdded")):
        assert len(witness[field]) == 3
        for added in witness[field]:
            assert prior[bucket].count(added) == 1
            if bucket == "plan":
                assert added["capability"] == "session.embeds.version-content.v1"
                assert len(added["vectors"]) == len(set(added["vectors"])) == 21
            else:
                assert added.startswith("session.embeds.version-content.v1 [")
            prior[bucket].remove(added)
    assert {k: len(prior[k]) for k in witness["counts"]} == {"programs": 246, "contracts": 63, "plan": 84, "gaps": 171}
    assert witness["trustSha256"] == "0918a67a01e2a5f7570f227fedca8c13d657eba9094e4871944035eb7b0fbd90"
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == witness["trustSha256"]
    return prior


def restore_before_cache_settlement_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    trust = restore_before_cache_adapter_registration(trust)
    delta = immutable_trust_test_fixture("sdk-conformance-trust-cache-settlement-source-delta.json", "68c1a85b9c676b9c66c80a0d67ccd7f953f665834071e4a87c7db37305f67ad5")
    restored = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert restored[bucket][path] == change["after"]
            if change["before"] is None:
                del restored[bucket][path]
            else:
                restored[bucket][path] = change["before"]
    assert restored["gaps"][-3:] == delta["gapAdded"]
    del restored["gaps"][-3:]
    assert sdk.sha((json.dumps(restored, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return restored


def test_cache_settlement_source_registration_is_exact_and_not_release_proof():
    delta = immutable_trust_test_fixture("sdk-conformance-trust-cache-settlement-source-delta.json", "68c1a85b9c676b9c66c80a0d67ccd7f953f665834071e4a87c7db37305f67ad5")
    live = restore_before_cache_adapter_registration(sdk.load_trust())
    assert {k: len(live[k]) for k in delta["afterCounts"]} == delta["afterCounts"]
    prior = restore_before_cache_settlement_registration(live)
    assert live["plan"] == prior["plan"] and len(prior["plan"]) == 87
    assert live["gaps"][:174] == prior["gaps"] and len(live["gaps"]) == 177
    assert {k: v for k,v in live.items() if k not in ("programs","contracts","gaps")} == {k: v for k,v in prior.items() if k not in ("programs","contracts","gaps")}
    assert delta["releaseEligible"] is False
    assert all("openmates-tui-native" not in item["path"] for item in delta["reviewedSources"])


def restore_before_cache_adapter_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == opaque["afterSha256"]:
        trust = restore_before_opaque_read_id_registration(trust)
    first_page = immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == first_page["afterSha256"]:
        trust = restore_before_first_page_browser_registration(trust)
    constant = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == constant["afterSha256"]:
        trust = restore_before_message_id_constant_registration(trust)
    message_ids = immutable_trust_test_fixture("sdk-conformance-trust-message-id-delta.json", "2ac9a3303a2cf3e19d1edbeb5d7fdeadceaa5f5aedc578a90b0e6368e8e3bdf9")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == message_ids["afterSha256"]:
        trust = restore_before_message_id_registration(trust)
    envelope = immutable_trust_test_fixture("sdk-conformance-trust-version-result-delta.json", "a12756e8020b6c84f4b67d1d10b050992d032a6cfa6d2a8408bd13dc1fe22672")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == envelope["afterSha256"]:
        trust = restore_before_version_envelope_registration(trust)
    browser = immutable_trust_test_fixture("sdk-conformance-trust-browser-local-wire-cursor-delta.json", "ce725e243ed00e27f69792e51415ee6fafb0e91c08f42a4a5a466c10bf0b7c1d")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser["afterSha256"]:
        trust = restore_before_browser_local_wire_cursor_registration(trust)
    seeding = immutable_trust_test_fixture("sdk-conformance-trust-cache-peer-seeding-delta.json", "08c1e10699cd73c735352e82a02749ced7305af638d70e7b7292a0e9b3cfc8fc")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == seeding["afterSha256"]:
        trust = restore_before_cache_peer_seeding_registration(trust)
    delta = immutable_trust_test_fixture("sdk-conformance-trust-cache-settlement-adapters-delta.json", "33506804d67aab4f5d301d756583961df30c1bf81a6930b7808bc2c9ee3b3df1")
    actual = sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode())
    # Known immutable predecessor is accepted solely for transitive test-data
    # restoration; runtime load_trust/verify_programs retain one live authority.
    if actual == delta["beforeSha256"]:
        return copy.deepcopy(trust)
    assert actual == delta["afterSha256"]
    restored = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert restored[bucket][path] == change["after"]
            if change["before"] is None:
                del restored[bucket][path]
            else:
                restored[bucket][path] = change["before"]
    for change in delta["planChanged"]:
        assert restored["plan"][change["index"]] == change["after"]
        restored["plan"][change["index"]] = copy.deepcopy(change["before"])
    assert restored["plan"][-3:] == delta["planAdded"]
    del restored["plan"][-3:]
    assert sdk.sha((json.dumps(restored, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return restored


def test_cache_adapters_add_exact_three_required_plans_preserve_old87_and_all_gaps():
    delta = immutable_trust_test_fixture("sdk-conformance-trust-cache-settlement-adapters-delta.json", "33506804d67aab4f5d301d756583961df30c1bf81a6930b7808bc2c9ee3b3df1")
    live = restore_before_cache_peer_seeding_registration(sdk.load_trust())
    assert sdk.sha((json.dumps(live, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    assert {key: len(live[key]) for key in delta["afterCounts"]} == {"programs":276,"contracts":71,"plan":90,"gaps":177}
    prior = restore_before_cache_adapter_registration(live)
    assert len(prior["plan"]) == 87
    restored_prefix = copy.deepcopy(live["plan"][:87])
    assert len(delta["planChanged"]) == 6
    for change in delta["planChanged"]:
        assert restored_prefix[change["index"]] == change["after"]
        assert change["after"]["capability"] in {"session.message-window.v1","session.saved-chat-read.v1"}
        assert {k:v for k,v in change["before"].items() if k not in ("fixtureSha256","vectors")} == {k:v for k,v in change["after"].items() if k not in ("fixtureSha256","vectors")}
        assert set(change["before"]["vectors"]) < set(change["after"]["vectors"])
        assert len(change["after"]["vectors"]) == len(change["before"]["vectors"]) + 1
        restored_prefix[change["index"]] = copy.deepcopy(change["before"])
    assert restored_prefix == prior["plan"]
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert live["gaps"] == prior["gaps"] and len(live["gaps"]) == 177
    assert {k:v for k,v in live.items() if k not in ("programs","contracts","plan")} == {k:v for k,v in prior.items() if k not in ("programs","contracts","plan")}
    added = live["plan"][87:]
    assert [row["language"] for row in added] == ["rust","npm","python"]
    for row in added:
        assert row["capability"] == "session.cache-preferred-settlement.v1"
        assert row["vectors"] == sorted({"selected-exact-ack","selected-wrong-hash","selected-wrong-revision","stale-a-active-b","discarded-stage","explicit-consent","monitor-exact-ack","selected-denied"})
        assert row["fixture"] == "tests/sdk-conformance/fixtures/session-cache-preferred-settlement.json"
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == 0
    assert len(delta["reviewedSourceClosure"]) == 19
    assert all("openmates-tui-native" not in item["path"] and "browser" not in item["path"] for item in delta["reviewedSourceClosure"])


@pytest.mark.parametrize("capability", ["session.message-window.v1", "session.saved-chat-read.v1"])
def test_explicit_private_read_policy_retains_every_prior_fixture_oracle(capability):
    delta = immutable_trust_test_fixture("sdk-conformance-trust-cache-settlement-adapters-delta.json", "33506804d67aab4f5d301d756583961df30c1bf81a6930b7808bc2c9ee3b3df1")
    witness = next(row for row in delta["fixtureWitnesses"] if row["capability"] == capability)
    root = Path(__file__).resolve().parents[2]
    raw = (root / witness["path"]).read_bytes()
    raw = restore_before_message_id_fixture_raw(raw, capability)
    assert sdk.sha(raw) == witness["afterRawSha256"]
    restored = json.loads(raw)
    suite = restored["capabilities"][capability]
    assert suite.pop("allow_private_operations") is True
    assert suite["vectors"].pop() == witness["addedDeniedVector"]
    assert witness["addedDeniedVector"]["allow_private_operations"] is False
    assert witness["addedDeniedVector"]["expected_error"] == "forbidden"
    assert len(suite["vectors"]) == witness["priorVectorCount"] == {"session.message-window.v1":24,"session.saved-chat-read.v1":54}[capability]
    assert sdk.sha(json.dumps(suite["vectors"], sort_keys=True).encode()) == witness["priorVectorsSha256"]
    assert sdk.sha(json.dumps(restored, sort_keys=True).encode()) == witness["beforeSemanticSha256"]


def restore_before_cache_peer_seeding_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == opaque["afterSha256"]:
        trust = restore_before_opaque_read_id_registration(trust)
    first_page = immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == first_page["afterSha256"]:
        trust = restore_before_first_page_browser_registration(trust)
    constant = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == constant["afterSha256"]:
        trust = restore_before_message_id_constant_registration(trust)
    message_ids = immutable_trust_test_fixture("sdk-conformance-trust-message-id-delta.json", "2ac9a3303a2cf3e19d1edbeb5d7fdeadceaa5f5aedc578a90b0e6368e8e3bdf9")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == message_ids["afterSha256"]:
        trust = restore_before_message_id_registration(trust)
    envelope = immutable_trust_test_fixture("sdk-conformance-trust-version-result-delta.json", "a12756e8020b6c84f4b67d1d10b050992d032a6cfa6d2a8408bd13dc1fe22672")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == envelope["afterSha256"]:
        trust = restore_before_version_envelope_registration(trust)
    browser = immutable_trust_test_fixture("sdk-conformance-trust-browser-local-wire-cursor-delta.json", "ce725e243ed00e27f69792e51415ee6fafb0e91c08f42a4a5a466c10bf0b7c1d")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser["afterSha256"]:
        trust = restore_before_browser_local_wire_cursor_registration(trust)
    delta = immutable_trust_test_fixture("sdk-conformance-trust-cache-peer-seeding-delta.json", "08c1e10699cd73c735352e82a02749ced7305af638d70e7b7292a0e9b3cfc8fc")
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    restored = copy.deepcopy(trust)
    for path, change in delta["programPinDeltas"].items():
        assert restored["programs"][path] == change["after"]
        if change["before"] is None:
            del restored["programs"][path]
        else:
            restored["programs"][path] = change["before"]
    assert sdk.sha((json.dumps(restored, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return restored


def test_cache_peer_seeding_pins_exact_six_reviewed_paths_without_contract_plan_or_gap_change():
    delta = immutable_trust_test_fixture("sdk-conformance-trust-cache-peer-seeding-delta.json", "08c1e10699cd73c735352e82a02749ced7305af638d70e7b7292a0e9b3cfc8fc")
    live = restore_before_browser_local_wire_cursor_registration(sdk.load_trust())
    assert {k:len(live[k]) for k in delta["afterCounts"]} == {"programs":277,"contracts":71,"plan":90,"gaps":177}
    prior = restore_before_cache_peer_seeding_registration(live)
    assert set(delta["programPinDeltas"]) == {
        "packages/openmates-session-bindings/examples/session-cache-preferred-settlement-conformance.rs",
        "packages/openmates-session-bindings/src/session_cache_settlement_tests.rs",
        "tests/sdk-conformance/cache_settlement_peer.py",
        "tests/sdk-conformance/runners/session-cache-preferred-settlement.mjs",
        "tests/sdk-conformance/runners/session-cache-preferred-settlement.py",
        "tests/sdk-conformance/test_cache_settlement_peer.py",
    }
    assert sum(row["before"] is None for row in delta["programPinDeltas"].values()) == 1
    assert next(path for path,row in delta["programPinDeltas"].items() if row["before"] is None) == "tests/sdk-conformance/test_cache_settlement_peer.py"
    assert len(prior["programs"]) == 276
    assert {k:v for k,v in live.items() if k != "programs"} == {k:v for k,v in prior.items() if k != "programs"}
    for bucket in ("contracts","plan","gaps"):
        assert sdk.sha(json.dumps(live[bucket],sort_keys=True).encode()) == delta["unchangedDigests"][bucket]
    assert len(live["plan"]) == 90 and len(live["gaps"]) == 177
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    assert all(row["sourceProposalSha256"] == "0606a049b6ee3c9c33b30dac1ba6f1948709243809ccf9c7aca2db99b9e1cae3" for row in delta["reviewedSourceClosure"])


def restore_before_browser_local_wire_cursor_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == opaque["afterSha256"]:
        trust = restore_before_opaque_read_id_registration(trust)
    first_page = immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == first_page["afterSha256"]:
        trust = restore_before_first_page_browser_registration(trust)
    constant = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == constant["afterSha256"]:
        trust = restore_before_message_id_constant_registration(trust)
    message_ids = immutable_trust_test_fixture("sdk-conformance-trust-message-id-delta.json", "2ac9a3303a2cf3e19d1edbeb5d7fdeadceaa5f5aedc578a90b0e6368e8e3bdf9")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == message_ids["afterSha256"]:
        trust = restore_before_message_id_registration(trust)
    envelope = immutable_trust_test_fixture("sdk-conformance-trust-version-result-delta.json", "a12756e8020b6c84f4b67d1d10b050992d032a6cfa6d2a8408bd13dc1fe22672")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == envelope["afterSha256"]:
        trust = restore_before_version_envelope_registration(trust)
    delta = immutable_trust_test_fixture("sdk-conformance-trust-browser-local-wire-cursor-delta.json", "ce725e243ed00e27f69792e51415ee6fafb0e91c08f42a4a5a466c10bf0b7c1d")
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    restored = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert restored[bucket][path] == change["after"]
            if change["before"] is None:
                del restored[bucket][path]
            else:
                restored[bucket][path] = change["before"]
    for change in delta["gapChanged"]:
        assert restored["gaps"][change["index"]] == change["after"]
        restored["gaps"][change["index"]] = change["before"]
    assert sdk.sha((json.dumps(restored, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return restored


def test_browser_local_wire_cursor_registration_preserves_prior_authority_and_explicit_sdk_gaps():
    delta = immutable_trust_test_fixture("sdk-conformance-trust-browser-local-wire-cursor-delta.json", "ce725e243ed00e27f69792e51415ee6fafb0e91c08f42a4a5a466c10bf0b7c1d")
    live = restore_before_message_id_registration(sdk.load_trust())
    prior = restore_before_browser_local_wire_cursor_registration(live)
    assert {key:len(live[key]) for key in delta["afterCounts"]} == {"programs":283,"contracts":73,"plan":90,"gaps":177}
    assert live["plan"] == prior["plan"] and len(live["plan"]) == 90
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert len(delta["gapChanged"]) == 3 and len(live["gaps"]) == len(prior["gaps"]) == 177
    for change in delta["gapChanged"]:
        assert change["before"].startswith("sdk.session-client [")
        assert change["after"] == change["before"] + "; " + delta["matrixDelta"]["gapAddedEachLanguage"]
    assert {k:v for k,v in live.items() if k not in ("programs","contracts","gaps")} == {k:v for k,v in prior.items() if k not in ("programs","contracts","gaps")}
    assert len(delta["reviewedSourceClosure"]) == 13
    assert all("openmates-tui-native" not in item["path"] and "workerHost" not in item["path"] and "workerRuntime" not in item["path"] for item in delta["reviewedSourceClosure"])
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    root = Path(__file__).resolve().parents[2]
    raw = (root / "config/sdk-capabilities.json").read_bytes()
    raw = restore_before_message_id_matrix_raw(raw)
    assert sdk.sha(raw) == delta["matrixDelta"]["afterSha256"]
    matrix = json.loads(raw)
    row = next(row for row in matrix["capabilities"] if row["id"] == "sdk.session-client")
    assert row["languages"]["rust"]["api"].count(delta["matrixDelta"]["rustApiAdded"]) == 1
    for value in row["languages"].values():
        assert value["status"] == "partial" and value["conformance"] is False
        assert value["gaps"][-1] == delta["matrixDelta"]["gapAddedEachLanguage"]


def restore_before_version_envelope_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == opaque["afterSha256"]:
        trust = restore_before_opaque_read_id_registration(trust)
    first_page = immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == first_page["afterSha256"]:
        trust = restore_before_first_page_browser_registration(trust)
    constant = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == constant["afterSha256"]:
        trust = restore_before_message_id_constant_registration(trust)
    message_ids = immutable_trust_test_fixture("sdk-conformance-trust-message-id-delta.json", "2ac9a3303a2cf3e19d1edbeb5d7fdeadceaa5f5aedc578a90b0e6368e8e3bdf9")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == message_ids["afterSha256"]:
        trust = restore_before_message_id_registration(trust)
    delta = immutable_trust_test_fixture("sdk-conformance-trust-version-result-delta.json", "a12756e8020b6c84f4b67d1d10b050992d032a6cfa6d2a8408bd13dc1fe22672")
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for path, change in delta["programPinDeltas"].items():
        assert prior["programs"][path] == change["after"]
        prior["programs"][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def test_version_envelope_registration_changes_only_exact_two_reviewed_programs():
    delta = immutable_trust_test_fixture("sdk-conformance-trust-version-result-delta.json", "a12756e8020b6c84f4b67d1d10b050992d032a6cfa6d2a8408bd13dc1fe22672")
    live = restore_before_message_id_registration(sdk.load_trust())
    prior = restore_before_version_envelope_registration(live)
    assert {k:len(live[k]) for k in delta["afterCounts"]} == {"programs":283,"contracts":73,"plan":90,"gaps":177}
    assert delta["programPinDeltas"] == {
        "scripts/tests/test_sdk_session_embed_version_gate.py": {
            "before":"2c7d07dbd019d6ae92bc595b6add95ea42956587a993ae5f190612e89cf2cd47",
            "after":"c9edc5419eab7313ee635a880e24a85e4715c7fd30b3db2d5cc07d91f8ababb0"},
        "tests/sdk-conformance/runners/session-embed-version-content.py": {
            "before":"03cbb14e06476a6b2aa42c86ff713e6836173481188553e91a7fb6afdf743b85",
            "after":"6feba5e19b96a2ce8511fb92adf49c8fe709d7f6dfa87033a372441fe7a0f430"},
    }
    assert {k:v for k,v in live.items() if k!="programs"} == {k:v for k,v in prior.items() if k!="programs"}
    assert len(live["plan"]) == 90 and len(live["gaps"]) == 177
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == 0


def message_id_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-message-id-delta.json", "2ac9a3303a2cf3e19d1edbeb5d7fdeadceaa5f5aedc578a90b0e6368e8e3bdf9")


def restore_before_message_id_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == opaque["afterSha256"]:
        trust = restore_before_opaque_read_id_registration(trust)
    first_page = immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == first_page["afterSha256"]:
        trust = restore_before_first_page_browser_registration(trust)
    constant = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == constant["afterSha256"]:
        trust = restore_before_message_id_constant_registration(trust)
    delta = message_id_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for change in delta["planChanged"]:
        assert prior["plan"][change["index"]] == change["after"]
        prior["plan"][change["index"]] = copy.deepcopy(change["before"])
    for change in delta["gapChanged"]:
        assert prior["gaps"][change["index"]] == change["after"]
        prior["gaps"][change["index"]] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def restore_before_message_id_matrix_raw(raw):
    raw = selected_recovery_matrix_history(raw)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha(raw) == cache_embed["matrixDelta"]["afterSha256"]:
        raw = restore_before_cache_embed_matrix_raw(raw)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha(raw) == ordinary["matrixDelta"]["afterSha256"]:
        raw = restore_before_ordinary_retention_matrix_raw(raw)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha(raw) == opaque["matrixDelta"]["afterSha256"]:
        raw = restore_before_opaque_read_id_matrix_raw(raw)
    first_page = immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")
    if sdk.sha(raw) == first_page["matrixDelta"]["afterSha256"]:
        raw = restore_before_first_page_browser_matrix_raw(raw)
    constant = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")
    if sdk.sha(raw) == constant["matrixDelta"]["afterSha256"]:
        raw = restore_before_message_id_constant_matrix_raw(raw)
    delta = message_id_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    for identity in delta["families"]:
        family = next(row for row in matrix["capabilities"] if row["id"] == identity)
        for language in ("rust", "npm", "python"):
            assert family["languages"][language]["gaps"].pop() == delta["gapAddedEachLanguage"]
        if identity == "sdk.session-client":
            assert family["languages"]["rust"]["api"].count(delta["rustApiAdded"]) == 1
            family["languages"]["rust"]["api"].remove(delta["rustApiAdded"])
    restored = (json.dumps(matrix, indent=2) + "\n").encode()
    assert sdk.sha(restored) == delta["beforeSha256"]
    return restored


def restore_before_message_id_fixture_raw(raw, capability):
    witness = next(row for row in message_id_registration_delta()["fixtureWitnesses"] if row["capability"] == capability)
    assert sdk.sha(raw) == witness["afterSha256"]
    document = json.loads(raw)
    suite = document["capabilities"][capability]
    assert len(suite["vectors"]) == witness["afterCount"]
    added = suite["vectors"][witness["beforeCount"]:]
    assert [row["id"] for row in added] == witness["addedVectorIds"]
    assert sdk.sha(json.dumps(added, sort_keys=True).encode()) == witness["addedVectorsSha256"]
    del suite["vectors"][witness["beforeCount"]:]
    assert sdk.sha(json.dumps(suite["vectors"], sort_keys=True).encode()) == witness["priorVectorsSha256"]
    assert suite["protocol"]["cursor_note"] == witness["cursorNote"]["after"]
    suite["protocol"]["cursor_note"] = witness["cursorNote"]["before"]
    restored = (json.dumps(document, indent=2) + "\n").encode()
    assert sdk.sha(restored) == witness["beforeSha256"]
    return restored


def test_message_id_registration_preserves_exact_prior_authority_and_six_plan_families():
    delta = message_id_registration_delta()
    live = restore_before_message_id_constant_registration(sdk.load_trust())
    prior = restore_before_message_id_registration(live)
    assert {key:len(live[key]) for key in delta["afterCounts"]} == {"programs":283,"contracts":75,"plan":90,"gaps":177}
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert len(delta["planChanged"]) == 6
    assert {(row["after"]["capability"],row["after"]["language"]) for row in delta["planChanged"]} == {(cap,lang) for cap in ("session.message-window.v1","session.saved-chat-read.v1") for lang in ("rust","npm","python")}
    changed_indices = {row["index"] for row in delta["planChanged"]}
    for index,(before,after) in enumerate(zip(prior["plan"],live["plan"])):
        if index not in changed_indices:
            assert before == after
        else:
            assert {k:v for k,v in before.items() if k not in ("fixtureSha256","vectors")} == {k:v for k,v in after.items() if k not in ("fixtureSha256","vectors")}
            assert set(before["vectors"]) < set(after["vectors"])
            assert len(after["vectors"]) == {"session.message-window.v1":27,"session.saved-chat-read.v1":66}[after["capability"]]
    assert len(delta["sourceClosure"]) == 16
    assert len([row for row in delta["sourceClosure"] if row["bucket"] is None]) == 2
    assert all(not path.startswith("frontend/packages/openmates-tui-native/") for group in delta["pinDeltas"].values() for path in group)
    assert len(delta["gapChanged"]) == 9
    for change in delta["gapChanged"]:
        assert change["after"] == change["before"] + "; " + delta["matrixDelta"]["gapAddedEachLanguage"]
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    root = Path(__file__).resolve().parents[2]
    before_matrix = json.loads(restore_before_message_id_matrix_raw(historical_cache_embed_matrix_raw((root/"config/sdk-capabilities.json").read_bytes())))
    after_matrix = json.loads(restore_before_first_page_browser_matrix_raw(historical_cache_embed_matrix_raw((root/"config/sdk-capabilities.json").read_bytes())))
    assert len(before_matrix["capabilities"]) == len(after_matrix["capabilities"]) == 66
    for before,after in zip(before_matrix["capabilities"],after_matrix["capabilities"]):
        assert before["id"] == after["id"]
        for language in ("rust","npm","python"):
            assert before["languages"][language]["status"] == after["languages"][language]["status"]
            assert before["languages"][language]["conformance"] == after["languages"][language]["conformance"]


@pytest.mark.parametrize("capability", ["session.message-window.v1","session.saved-chat-read.v1"])
def test_message_id_fixtures_losslessly_restore_every_original_vector(capability):
    delta = message_id_registration_delta()
    witness = next(row for row in delta["fixtureWitnesses"] if row["capability"] == capability)
    root = Path(__file__).resolve().parents[2]
    raw = (root/witness["path"]).read_bytes()
    restored = json.loads(restore_before_message_id_fixture_raw(raw,capability))
    assert len(restored["capabilities"][capability]["vectors"]) == {"session.message-window.v1":25,"session.saved-chat-read.v1":55}[capability]
    assert restored["capabilities"][capability]["allow_private_operations"] is True
    assert restored["capabilities"][capability]["vectors"][-1]["allow_private_operations"] is False
    assert restored["capabilities"][capability]["vectors"][-1]["expected_error"] == "forbidden"


def test_current_message_id_window_validator_retains_all27_without_release_claim(tmp_path):
    root,report = message_window_gate_fixture(tmp_path,message_id_current=True)
    result = sdk.gate_receipt(root,report,trust=synthetic_trust(root))
    assert result["realRunCount"] == 3 and result["vectorOutcomeCount"] == 81
    assert result["openGapCount"] == 1 and result["releaseEligible"] is False


@pytest.mark.parametrize("fault", ["missing_adapter","duplicate_adapter","missing_vector","extra_vector","wrong_fixture","wrong_capability","wrong_language","plan_reordered","missing_launch","launch_reordered","gap_erased","release_claim"])
def test_current_message_id_window_rejects_each_partial_forged_or_reordered_result(tmp_path,fault):
    root,report = message_window_gate_fixture(tmp_path,message_id_current=True)
    if fault == "missing_adapter":
        report["conformance"].pop()
    elif fault == "duplicate_adapter":
        report["conformance"][1] = copy.deepcopy(report["conformance"][0])
    elif fault == "missing_vector":
        report["conformance"][0]["results"].pop()
    elif fault == "extra_vector":
        report["conformance"][0]["results"].append({"id":"invented-private","status":"passed"})
    elif fault == "wrong_fixture":
        report["conformance"][0]["fixtureSha256"] = "f"*64
    elif fault == "wrong_capability":
        report["conformance"][0]["capability"] = "unreviewed"
    elif fault == "wrong_language":
        report["conformance"][0]["language"] = "unreviewed"
    elif fault == "plan_reordered":
        report["expectedPlan"].reverse()
    elif fault == "missing_launch":
        report["actualLaunches"].pop()
    elif fault == "launch_reordered":
        report["actualLaunches"].reverse()
    elif fault == "gap_erased":
        report["openGaps"] = []
    else:
        report["releaseEligible"] = True
    with pytest.raises(sdk.Refused):
        sdk.gate_receipt(root,report,trust=synthetic_trust(root))


def restore_before_message_id_constant_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == opaque["afterSha256"]:
        trust = restore_before_opaque_read_id_registration(trust)
    first_page = immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == first_page["afterSha256"]:
        trust = restore_before_first_page_browser_registration(trust)
    delta = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            prior[bucket][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def restore_before_message_id_constant_matrix_raw(raw):
    raw = selected_recovery_matrix_history(raw)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha(raw) == cache_embed["matrixDelta"]["afterSha256"]:
        raw = restore_before_cache_embed_matrix_raw(raw)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha(raw) == ordinary["matrixDelta"]["afterSha256"]:
        raw = restore_before_ordinary_retention_matrix_raw(raw)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha(raw) == opaque["matrixDelta"]["afterSha256"]:
        raw = restore_before_opaque_read_id_matrix_raw(raw)
    first_page = immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")
    if sdk.sha(raw) == first_page["matrixDelta"]["afterSha256"]:
        raw = restore_before_first_page_browser_matrix_raw(raw)
    delta = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    family = next(row for row in matrix["capabilities"] if row["id"] == delta["family"])
    assert family["languages"]["rust"]["api"].count(delta["rustApiAdded"]) == 1
    family["languages"]["rust"]["api"].remove(delta["rustApiAdded"])
    restored = (json.dumps(matrix, indent=2) + "\n").encode()
    assert sdk.sha(restored) == delta["beforeSha256"]
    return restored


def test_message_id_constant_classification_preserves_exact_applied_v3_authority():
    delta = immutable_trust_test_fixture("sdk-conformance-trust-message-id-constant-delta.json", "a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2")
    live = restore_before_first_page_browser_registration(sdk.load_trust())
    prior = restore_before_message_id_constant_registration(live)
    assert {key:len(live[key]) for key in delta["counts"]} == {"programs":283,"contracts":75,"plan":90,"gaps":177}
    assert {key:value for key,value in live.items() if key not in ("programs","contracts")} == {key:value for key,value in prior.items() if key not in ("programs","contracts")}
    assert live["plan"] == prior["plan"] and live["gaps"] == prior["gaps"]
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert len(delta["pinDeltas"]["programs"]) == len(delta["pinDeltas"]["contracts"]) == 1
    root = Path(__file__).resolve().parents[2]
    raw = restore_before_opaque_read_id_matrix_raw(historical_cache_embed_matrix_raw((root/"config/sdk-capabilities.json").read_bytes()))
    restored = restore_before_message_id_constant_matrix_raw(raw)
    matrix = json.loads(raw)
    family = next(row for row in matrix["capabilities"] if row["id"] == "sdk.session-client")
    assert delta["matrixDelta"]["rustApiAdded"] == "client.message_window.MAX_MESSAGE_ID_BYTES"
    assert family["languages"]["rust"]["api"].count(delta["matrixDelta"]["rustApiAdded"]) == 1
    assert all(delta["matrixDelta"]["rustApiAdded"] not in family["languages"][language]["api"] for language in ("npm","python"))
    assert sdk.sha(restored) == "9b62b9ea19a5503e42c2e926fe860c79557217352ebf736a0c1029538f3286e1"
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0


def first_page_browser_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-first-page-browser-delta.json", "d6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf")


def restore_before_first_page_browser_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == opaque["afterSha256"]:
        trust = restore_before_opaque_read_id_registration(trust)
    delta = first_page_browser_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    assert prior["plan"][-3:] == delta["planAdded"]
    assert prior["gaps"][-3:] == delta["gapAdded"]
    del prior["plan"][-3:]
    del prior["gaps"][-3:]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def restore_before_first_page_browser_matrix_raw(raw):
    raw = selected_recovery_matrix_history(raw)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha(raw) == cache_embed["matrixDelta"]["afterSha256"]:
        raw = restore_before_cache_embed_matrix_raw(raw)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha(raw) == ordinary["matrixDelta"]["afterSha256"]:
        raw = restore_before_ordinary_retention_matrix_raw(raw)
    opaque = immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")
    if sdk.sha(raw) == opaque["matrixDelta"]["afterSha256"]:
        raw = restore_before_opaque_read_id_matrix_raw(raw)
    delta = first_page_browser_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    assert matrix["capabilities"][-1]["id"] == delta["familyAdded"]
    matrix["capabilities"].pop()
    for identity, added in delta["rustApisAddedToExisting"].items():
        family = next(row for row in matrix["capabilities"] if row["id"] == identity)
        for api in added:
            assert family["languages"]["rust"]["api"].count(api) == 1
            family["languages"]["rust"]["api"].remove(api)
    restored = (json.dumps(matrix, indent=2) + "\n").encode()
    assert sdk.sha(restored) == delta["beforeSha256"]
    return restored


def test_first_page_browser_registration_preserves_all90_plans_and177_gaps():
    delta = first_page_browser_registration_delta()
    live = restore_before_ordinary_retention_registration(sdk.load_trust())
    prior = restore_before_first_page_browser_registration(live)
    assert live["plan"][:90] == prior["plan"] and len(live["plan"]) == 93
    assert live["gaps"][:177] == prior["gaps"] and len(live["gaps"]) == 180
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"], sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert len(delta["planAdded"]) == len(delta["gapAdded"]) == 3
    assert [row["language"] for row in delta["planAdded"]] == ["rust","npm","python"]
    for row in delta["planAdded"]:
        assert row["capability"] == "session.chat-first-page-continuation.v1"
        assert row["fixtureSha256"] == delta["fixtureSha256"]
        assert row["vectors"] == sorted(vector["id"] for vector in delta["orderedFixtureVectors"])
        assert len(row["vectors"]) == len(set(row["vectors"])) == 16
    assert all(support["status"] == "partial" and support["conformance"] is True for support in delta["newFamily"]["languages"].values())
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    assert all(not path.startswith(("frontend/packages/openmates-tui-native/","frontend/apps/web_app/")) for bucket in delta["pinDeltas"].values() for path in bucket)
    browser_ui = {path:change for path,change in delta["pinDeltas"]["programs"].items() if path.startswith("frontend/packages/ui/")}
    assert set(browser_ui) == {"frontend/packages/ui/src/services/rustCore/"+name for name in ("__tests__/browserLocalCursorIO.test.cjs","browserLocalCursorIO.ts","protocol.ts","savedReadProtocol.ts","workerHost.ts","workerRuntime.ts")}
    assert all(change["before"] is not None for change in browser_ui.values())
    root = Path(__file__).resolve().parents[2]
    restored = restore_before_first_page_browser_matrix_raw(historical_cache_embed_matrix_raw((root/"config/sdk-capabilities.json").read_bytes()))
    assert sdk.sha(restored) == "69bc6f28a82b296fa9f3a577b74eab8d127f449b276f301fcd66c27f3a4d5f98"


def test_first_page_fixture_order_schema_and_pins_are_exact_without_runtime_credit():
    delta = first_page_browser_registration_delta()
    root = Path(__file__).resolve().parents[2]
    path = delta["planAdded"][0]["fixture"]
    raw = (root/path).read_bytes()
    assert sdk.sha(raw) == delta["fixtureSha256"]
    document = json.loads(raw)
    vectors = document["capabilities"]["session.chat-first-page-continuation.v1"]["vectors"]
    assert vectors == delta["orderedFixtureVectors"]
    assert sdk.sha((root/"tests/sdk-conformance/schemas/session-chat-first-page-continuation.schema.json").read_bytes()) == delta["schemaSha256"]
    assert all(row["capability"] != "session.chat-first-page-continuation.v1" for row in restore_before_first_page_browser_registration(sdk.load_trust())["plan"])


def opaque_read_id_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-opaque-read-id-delta.json", "a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27")


def restore_before_opaque_read_id_fixture_raw(raw):
    witness = opaque_read_id_registration_delta()["fixtureTransition"]
    assert sdk.sha(raw) == witness["afterSha256"]
    document = json.loads(raw)
    assert document["schema_version"] == 2 and len(document["cases"]) == witness["afterCount"] == 33
    assert document["previous_policy"] == witness["priorMetadata"]["policy"]
    assert [row["id"] for row in document["cases"][:24]] == witness["priorCaseIds"]
    assert [row["id"] for row in document["cases"][24:]] == witness["appendedCaseIds"]
    cases = []
    inverted = []
    for row in document["cases"][:24]:
        if row["valid"] != row["previous_valid"]:
            assert row["previous_valid"] is False and row["valid"] is True and row["policy_change"]
            inverted.append(row["id"])
        case = {key:value for key,value in row.items() if key not in ("previous_valid","policy_change")}
        case["valid"] = row["previous_valid"]
        cases.append(case)
    assert inverted == witness["invertedCaseIds"] and len(inverted) == 9
    assert sdk.sha(json.dumps(cases, sort_keys=True).encode()) == witness["priorCasesSha256"]
    metadata = json.loads(witness["priorMetadataJson"])
    assert metadata == witness["priorMetadata"]
    restored = (json.dumps({**metadata,"cases":cases}, indent=2) + "\n").encode()
    assert sdk.sha(restored) == witness["beforeSha256"]
    return restored


def restore_before_opaque_read_id_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == ordinary["afterSha256"]:
        trust = restore_before_ordinary_retention_registration(trust)
    delta = opaque_read_id_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    # Validate lossless prior24 BEFORE entering the prior first-page/constant
    # epoch. The actual current fixture is never rewritten or used as old proof.
    root = Path(__file__).resolve().parents[2]
    for path in delta["fixtureTransition"]["paths"]:
        assert sdk.sha(restore_before_opaque_read_id_fixture_raw((root/path).read_bytes())) == delta["fixtureTransition"]["beforeSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            prior[bucket][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def restore_before_opaque_read_id_matrix_raw(raw):
    raw = selected_recovery_matrix_history(raw)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha(raw) == cache_embed["matrixDelta"]["afterSha256"]:
        raw = restore_before_cache_embed_matrix_raw(raw)
    ordinary = immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")
    if sdk.sha(raw) == ordinary["matrixDelta"]["afterSha256"]:
        raw = restore_before_ordinary_retention_matrix_raw(raw)
    delta = opaque_read_id_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    family = next(row for row in matrix["capabilities"] if row["id"] == delta["family"])
    assert delta["rustApiRemoved"] not in family["languages"]["rust"]["api"]
    family["languages"]["rust"]["api"].append(delta["rustApiRemoved"])
    family["languages"]["rust"]["api"].sort()
    restored = (json.dumps(matrix, indent=2) + "\n").encode()
    assert sdk.sha(restored) == delta["beforeSha256"]
    return restored


def test_opaque_read_id_registration_preserves_all93_plans180_gaps_and_old_authority():
    delta = opaque_read_id_registration_delta()
    live = restore_before_ordinary_retention_registration(sdk.load_trust())
    prior = restore_before_opaque_read_id_registration(live)
    assert {key:len(live[key]) for key in delta["counts"]} == {"programs":309,"contracts":79,"plan":93,"gaps":180}
    assert live["plan"] == prior["plan"] and live["gaps"] == prior["gaps"]
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"], sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert {key:value for key,value in live.items() if key not in ("programs","contracts")} == {key:value for key,value in prior.items() if key not in ("programs","contracts")}
    assert len(delta["sourceClosure"]) == 21
    assert len([row for row in delta["sourceClosure"] if row["bucket"] == "programs"]) == 17
    assert len([row for row in delta["sourceClosure"] if row["bucket"] == "contracts"]) == 2
    assert all(change["before"] is not None for bucket in delta["pinDeltas"].values() for change in bucket.values())
    root = Path(__file__).resolve().parents[2]
    raw = historical_cache_embed_matrix_raw((root/"config/sdk-capabilities.json").read_bytes())
    assert sdk.sha(restore_before_opaque_read_id_matrix_raw(raw)) == delta["matrixDelta"]["beforeSha256"]
    assert delta["matrixDelta"]["rustApiRemoved"] == "client.message_window.MAX_MESSAGE_ID_BYTES"
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0


@pytest.mark.parametrize("path", ["tests/sdk-conformance/fixtures/message-id-compatibility.json","packages/openmates-rust/tests/fixtures/message-id-compatibility.json"])
def test_opaque_fixture33_preserves_prior24_and_explicitly_inverts_only_nine_syntax_cases(path):
    witness = opaque_read_id_registration_delta()["fixtureTransition"]
    root = Path(__file__).resolve().parents[2]
    raw = (root/path).read_bytes()
    prior = json.loads(restore_before_opaque_read_id_fixture_raw(raw))
    current = json.loads(raw)
    assert len(prior["cases"]) == 24 and len(current["cases"]) == 33
    for old,new in zip(prior["cases"],current["cases"]):
        assert old["id"] == new["id"] and old["value"] == new["value"]
        assert old["valid"] == new["previous_valid"]
        if old["id"] not in witness["invertedCaseIds"]:
            assert old["valid"] == new["valid"]
    assert len(witness["invertedCaseIds"]) == 9
    assert all(row["valid"] is False for row in current["cases"] if row["value"] == "" or not isinstance(row["value"],str))


def ordinary_retention_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-ordinary-retention-delta.json", "13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b")


def restore_before_ordinary_retention_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    legacy = immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == legacy["afterSha256"]:
        trust = restore_before_legacy_webcrypto_registration(trust)
    delta = ordinary_retention_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for change in delta["gapDeltas"]:
        assert prior["gaps"][change["index"]] == change["after"]
        prior["gaps"][change["index"]] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def restore_before_ordinary_retention_matrix_raw(raw):
    raw = selected_recovery_matrix_history(raw)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha(raw) == cache_embed["matrixDelta"]["afterSha256"]:
        raw = restore_before_cache_embed_matrix_raw(raw)
    delta = ordinary_retention_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    family = next(row for row in matrix["capabilities"] if row["id"] == delta["family"])
    for symbol in delta["rustApiAdded"]:
        assert family["languages"]["rust"]["api"].count(symbol) == 1
        family["languages"]["rust"]["api"].remove(symbol)
    assert family["description"].endswith(delta["obligation"])
    family["description"] = delta["priorDescription"]
    for language, obligation in delta["retentionGaps"].items():
        assert family["languages"][language]["gaps"].pop() == obligation
    restored = (json.dumps(matrix, indent=2) + "\n").encode()
    assert sdk.sha(restored) == delta["beforeSha256"]
    return restored


def test_ordinary_retention_classifies_existing_auth_without_promoting_any_plan_or_status():
    delta = ordinary_retention_registration_delta()
    live = restore_before_legacy_webcrypto_registration(sdk.load_trust())
    prior = restore_before_ordinary_retention_registration(live)
    assert live["plan"] == prior["plan"] and len(live["plan"]) == 93
    assert len(live["gaps"]) == len(prior["gaps"]) == 180
    changed = {row["index"] for row in delta["gapDeltas"]}
    assert len(changed) == 3
    assert sum(a != b for a,b in zip(live["gaps"],prior["gaps"])) == 3
    for index,(old_gap,current_gap) in enumerate(zip(prior["gaps"],live["gaps"])):
        if index in changed:
            assert current_gap.startswith(old_gap + "; Ordinary fresh-password retention remains required partial: ")
        else:
            assert old_gap == current_gap
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"], sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert len(delta["sourceClosure"]) == 22
    assert {key:len(live[key]) for key in delta["counts"]} == delta["counts"]
    assert set(delta["missingFunctionalConformance"]) == {"rust", "npm", "python"}
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    root = Path(__file__).resolve().parents[2]
    raw = historical_cache_embed_matrix_raw((root/"config/sdk-capabilities.json").read_bytes())
    assert sdk.sha(restore_before_ordinary_retention_matrix_raw(raw)) == delta["matrixDelta"]["beforeSha256"]
    old_matrix = json.loads(restore_before_ordinary_retention_matrix_raw(raw))
    matrix = json.loads(raw)
    assert len(matrix["capabilities"]) == len(old_matrix["capabilities"])
    for old_cap,new_cap in zip(old_matrix["capabilities"],matrix["capabilities"]):
        for language in ("rust", "npm", "python"):
            for key in ("status", "conformance", "evidence"):
                assert old_cap["languages"][language][key] == new_cap["languages"][language][key]
            if new_cap["id"] == "sdk.session-client":
                assert new_cap["languages"][language]["gaps"][:-1] == old_cap["languages"][language]["gaps"]
                assert new_cap["languages"][language]["gaps"][-1] == delta["matrixDelta"]["retentionGaps"][language]
                assert new_cap["languages"][language]["status"] == "partial"
            else:
                assert new_cap["languages"][language]["gaps"] == old_cap["languages"][language]["gaps"]


def test_ordinary_retention_fixture_maintained_schema_validates_both_synthetic_plans():
    import jsonschema
    root = Path(__file__).resolve().parents[2]
    delta = ordinary_retention_registration_delta()
    schema = json.loads((root/delta["schema"]).read_bytes())
    fixture = json.loads((root/delta["fixture"]).read_bytes())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(fixture)
    assert len(fixture["cases"]) == 2
    assert [row["effect"]["action"] for row in fixture["cases"]] == ["save_memory", "save_persisted"]
    assert all(row["effect"]["credentialAcknowledged"] is False and row["effect"]["crossDatabaseAssociationProven"] is False for row in fixture["cases"])


@pytest.mark.parametrize("mutation", ["extra", "wrong-action", "ack", "association", "unsafe-generation", "bad-owner", "wrong-stay", "missing-case"])
def test_ordinary_retention_plan_schema_refuses_policy_or_authority_drift(mutation):
    import jsonschema
    root = Path(__file__).resolve().parents[2]
    delta = ordinary_retention_registration_delta()
    schema = json.loads((root/delta["schema"]).read_bytes())
    fixture = json.loads((root/delta["fixture"]).read_bytes())
    effect = fixture["cases"][0]["effect"]
    if mutation == "extra":
        effect["rawKey"] = "forbidden"
    elif mutation == "wrong-action":
        effect["action"] = "save_persisted"
    elif mutation == "ack":
        effect["credentialAcknowledged"] = True
    elif mutation == "association":
        effect["crossDatabaseAssociationProven"] = True
    elif mutation == "unsafe-generation":
        effect["generation"] = 9007199254740992
    elif mutation == "bad-owner":
        effect["owner"] += "\n"
    elif mutation == "wrong-stay":
        fixture["cases"][0]["stayLoggedIn"] = True
    else:
        fixture["cases"].pop()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(fixture)


def legacy_webcrypto_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-legacy-webcrypto-delta.json", "c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4")


def restore_before_legacy_webcrypto_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    cache_embed = immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == cache_embed["afterSha256"]:
        trust = restore_before_cache_embed_registration(trust)
    delta = legacy_webcrypto_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path,change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def test_legacy_webcrypto_only_pins_reviewed_backend_source_and_keeps_all_runtime_gates():
    delta = legacy_webcrypto_registration_delta()
    live = restore_before_cache_embed_registration(sdk.load_trust())
    prior = restore_before_legacy_webcrypto_registration(live)
    assert live["plan"] == prior["plan"] and len(live["plan"]) == 93
    assert live["gaps"] == prior["gaps"] and len(live["gaps"]) == 180
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"], sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert {key:len(live[key]) for key in delta["counts"]} == {"programs":317,"contracts":83,"plan":93,"gaps":180}
    assert len(delta["sourceClosure"]) == 9 and len(delta["pinDeltas"]["programs"]) == 8 and len(delta["pinDeltas"]["contracts"]) == 1
    assert len(set(live["programs"]) - set(prior["programs"])) == 5
    assert len(set(live["contracts"]) - set(prior["contracts"])) == 1
    assert delta["publicApiDelta"] == delta["capabilityDelta"] == 0
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    assert len(delta["requiredUnverified"]) == 3
    root = Path(__file__).resolve().parents[2]
    assert sdk.sha(historical_cache_embed_matrix_raw((root/"config/sdk-capabilities.json").read_bytes())) == delta["matrixSha256"]
    assert sdk.sha(historical_cache_embed_cookie_raw((root/"scripts/tests/test_sdk_session_embed_version_gate.py").read_bytes())) == delta["cookieHistoricalTestSha256"]
    assert {key:value for key,value in live.items() if key not in ("programs","contracts")} == {key:value for key,value in prior.items() if key not in ("programs","contracts")}


def cache_embed_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-cache-embed-delta.json", "1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390")


def restore_before_cache_embed_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_ci_fixes_registration(trust)
    delta = cache_embed_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for change in delta["gapDeltas"]:
        assert prior["gaps"][change["index"]] == change["after"]
        prior["gaps"][change["index"]] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def restore_before_cache_embed_matrix_raw(raw):
    raw = selected_recovery_matrix_history(raw)
    delta = cache_embed_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    family = next(c for c in matrix["capabilities"] if c["id"] == delta["family"])
    for api in delta["rustApiAdded"]:
        assert family["languages"]["rust"]["api"].count(api) == 1
        family["languages"]["rust"]["api"].remove(api)
    assert family["description"].endswith(delta["descriptionAppend"])
    family["description"] = family["description"][:-len(delta["descriptionAppend"])]
    for language in ("rust", "npm", "python"):
        assert family["languages"][language]["gaps"].pop() == delta["functionalObligation"]
    prior = (json.dumps(matrix, indent=2) + "\n").encode()
    assert prior == delta["beforeRaw"].encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    return prior


def historical_cache_embed_cookie_raw(raw):
    raw = selected_recovery_cookie_history(raw)
    delta = cache_embed_registration_delta()["cookieDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    prior = delta["beforeRaw"].encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    return prior


def historical_cache_embed_matrix_raw(raw):
    raw = selected_recovery_matrix_history(raw)
    delta = cache_embed_registration_delta()["matrixDelta"]
    return restore_before_cache_embed_matrix_raw(raw) if sdk.sha(raw) == delta["afterSha256"] else raw


def test_cache_embed_registration_classifies_partial_public_surface_without_new_runtime_family():
    delta = cache_embed_registration_delta()
    live = restore_before_ci_fixes_registration(sdk.load_trust())
    prior = restore_before_cache_embed_registration(live)
    assert live["plan"] == prior["plan"] and len(live["plan"]) == 93
    assert len(live["gaps"]) == len(prior["gaps"]) == 180
    assert all(new.startswith(old) for old,new in zip(prior["gaps"],live["gaps"]))
    assert sum(a != b for a,b in zip(prior["gaps"],live["gaps"])) == 3
    assert sdk.sha(json.dumps(prior["plan"],sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"],sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    assert len(delta["sourceClosure"]) == 13
    root = Path(__file__).resolve().parents[2]
    raw = selected_recovery_matrix_history((root/"config/sdk-capabilities.json").read_bytes())
    matrix = json.loads(raw)
    before = json.loads(restore_before_cache_embed_matrix_raw(raw))
    assert len(matrix["capabilities"]) == len(before["capabilities"])
    for a,b in zip(before["capabilities"],matrix["capabilities"]):
        assert a["id"] == b["id"]
        for language in ("rust", "npm", "python"):
            for key in ("status", "conformance", "evidence"):
                assert a["languages"][language][key] == b["languages"][language][key]
            assert b["languages"][language]["gaps"][:len(a["languages"][language]["gaps"])] == a["languages"][language]["gaps"]
            if a["id"] != delta["matrixDelta"]["family"]:
                assert a == b
    family = next(c for c in matrix["capabilities"] if c["id"] == "sdk.session-client")
    for language in ("rust", "npm", "python"):
        assert family["languages"][language]["status"] == "partial"
        assert family["languages"][language]["gaps"][-1] == delta["matrixDelta"]["functionalObligation"]
    assert len(delta["publicApiDelta"]["rust"]) == 9
    assert delta["publicApiDelta"]["npm"] == delta["publicApiDelta"]["python"] == []


def test_cache_embed_historical_inverse_rejects_tampered_source_or_gap_or_matrix():
    live = sdk.load_trust()
    delta = cache_embed_registration_delta()
    for bucket in ("programs", "contracts"):
        altered = copy.deepcopy(live)
        path = next(iter(delta["pinDeltas"][bucket]))
        altered[bucket][path] = "0" * 64
        with pytest.raises(AssertionError):
            restore_before_cache_embed_registration(altered)
    altered = copy.deepcopy(live)
    altered["gaps"][delta["gapDeltas"][0]["index"]] += "tampered"
    with pytest.raises(AssertionError):
        restore_before_cache_embed_registration(altered)
    raw = (Path(__file__).resolve().parents[2]/"config/sdk-capabilities.json").read_bytes()
    with pytest.raises(AssertionError):
        restore_before_cache_embed_matrix_raw(raw + b" ")


def ci_fixes_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-ci-fixes-delta.json", "01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3")


def restore_before_ci_fixes_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    portable = immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == portable["afterSha256"]:
        trust = restore_before_binding_unit_registration(trust)
    delta = ci_fixes_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path,change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def test_ci_fixes_pins_only_existing_test_program_and_preserves_all_runtime_gates():
    delta = ci_fixes_registration_delta()
    live = restore_before_binding_unit_registration(sdk.load_trust())
    prior = restore_before_ci_fixes_registration(live)
    assert {k:len(live[k]) for k in delta["counts"]} == {"programs":323,"contracts":86,"plan":93,"gaps":180}
    assert live["plan"] == prior["plan"] and len(live["plan"]) == 93
    assert live["gaps"] == prior["gaps"] and len(live["gaps"]) == 180
    assert sdk.sha(json.dumps(prior["plan"],sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"],sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert {k:v for k,v in live.items() if k not in ("programs","contracts")} == {k:v for k,v in prior.items() if k not in ("programs","contracts")}
    assert {p for p in live["programs"] if live["programs"][p] != prior["programs"][p]} == set(delta["pinDeltas"]["programs"])
    assert len(delta["pinDeltas"]["programs"]) == 7 and len(delta["pinDeltas"]["contracts"]) == 1
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    root = Path(__file__).resolve().parents[2]
    for row in delta["sourceClosure"]:
        assert sdk.sha((root/row["path"]).read_bytes()) == row["afterSha256"]
    assert sdk.sha((root/delta["fixture"]).read_bytes()) == delta["fixtureSha256"]
    assert sdk.sha((root/"packages/openmates-browser-bindings/tests/fixtures/message-id-compatibility.json").read_bytes()) == delta["fixtureSha256"]


def test_ci_fixes_history_inverse_refuses_program_or_plan_or_gap_tampering():
    delta = ci_fixes_registration_delta()
    live = sdk.load_trust()
    for bucket in ("programs", "contracts", "plan", "gaps"):
        changed = copy.deepcopy(live)
        if bucket in ("programs", "contracts"):
            changed[bucket][next(iter(delta["pinDeltas"][bucket]))] = "0" * 64
        else:
            changed[bucket].pop()
        with pytest.raises(AssertionError):
            restore_before_ci_fixes_registration(changed)


def binding_unit_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-binding-unit-delta.json", "2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883")


def restore_before_binding_unit_registration(trust):
    trust = selected_recovery_history(trust)
    trust = first_page_npm_diagnostic_history(trust)
    delta = binding_unit_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    assert prior["programs"][delta["program"]] == delta["afterProgramSha256"]
    prior["programs"][delta["program"]] = delta["beforeProgramSha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def test_binding_unit_pins_only_existing_test_program_and_preserves_all_runtime_gates():
    delta = binding_unit_registration_delta()
    live = first_page_npm_diagnostic_history(sdk.load_trust())
    prior = restore_before_binding_unit_registration(live)
    assert {k:len(live[k]) for k in delta["counts"]} == {"programs":323,"contracts":86,"plan":93,"gaps":180}
    assert live["plan"] == prior["plan"] and len(live["plan"]) == 93
    assert live["gaps"] == prior["gaps"] and len(live["gaps"]) == 180
    assert sdk.sha(json.dumps(prior["plan"],sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"],sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert {k:v for k,v in live.items() if k != "programs"} == {k:v for k,v in prior.items() if k != "programs"}
    assert {p for p in live["programs"] if live["programs"][p] != prior["programs"][p]} == {delta["program"]}
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    root = Path(__file__).resolve().parents[2]
    assert sdk.sha((root/delta["program"]).read_bytes()) == delta["afterProgramSha256"]


def test_binding_unit_history_inverse_refuses_program_or_plan_or_gap_tampering():
    delta = binding_unit_registration_delta()
    live = sdk.load_trust()
    for bucket in ("programs", "plan", "gaps"):
        changed = copy.deepcopy(live)
        if bucket == "programs":
            changed[bucket][delta["program"]] = "0" * 64
        else:
            changed[bucket].pop()
        with pytest.raises(AssertionError):
            restore_before_binding_unit_registration(changed)


# Exact diagnostic-only historical inverse; runtime trust is never normalized.
def first_page_npm_diagnostic_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-first-page-npm-diagnostic-delta.json", "23b01408c4c497debc97dc680eff97d75de47661f8e80932b809a48132bd3a50")


def restore_before_first_page_npm_diagnostic_registration(trust):
    trust = selected_recovery_history(trust)
    delta = first_page_npm_diagnostic_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    assert prior["programs"][delta["program"]] == delta["afterProgramSha256"]
    prior["programs"][delta["program"]] = delta["beforeProgramSha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def first_page_npm_diagnostic_history(trust):
    trust = selected_recovery_history(trust)
    delta = first_page_npm_diagnostic_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_first_page_npm_diagnostic_registration(trust)
    return trust


def test_first_page_npm_diagnostic_changes_only_exact_existing_program_pin():
    delta = first_page_npm_diagnostic_delta()
    live = selected_recovery_history(sdk.load_trust())
    prior = restore_before_first_page_npm_diagnostic_registration(live)
    assert {k: len(live[k]) for k in delta["counts"]} == {"programs": 323, "contracts": 86, "plan": 93, "gaps": 180}
    assert {k: v for k, v in live.items() if k != "programs"} == {k: v for k, v in prior.items() if k != "programs"}
    assert set(live["programs"]) == set(prior["programs"])
    assert {k for k in live["programs"] if live["programs"][k] != prior["programs"][k]} == {delta["program"]}
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"], sort_keys=True).encode()) == delta["oldGapsSha256"]
    root = Path(__file__).resolve().parents[2]
    assert sdk.sha((root / delta["program"]).read_bytes()) == delta["afterProgramSha256"]
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_first_page_npm_diagnostic_inverse_refuses_unknown_drift(bucket):
    live = sdk.load_trust()
    changed = copy.deepcopy(live)
    if bucket in ("programs", "contracts"):
        changed[bucket][next(iter(changed[bucket]))] = "0" * 64
    else:
        changed[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_first_page_npm_diagnostic_registration(changed)


def test_first_page_npm_diagnostic_preserves_binding_and_old_history_prefix():
    live = sdk.load_trust()
    prior = first_page_npm_diagnostic_history(live)
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == "964f822aefd37312c53f42bc359650ff0521393d39f03d5a44ad2b03045f2180"
    old = restore_before_binding_unit_registration(live)
    assert sdk.sha((json.dumps(old, indent=2, sort_keys=True) + "\n").encode()) == binding_unit_registration_delta()["beforeSha256"]
    assert first_page_npm_diagnostic_history(prior) == prior


def selected_recovery_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-selected-cli-delta.json", "317cca0866fd683e464e6edc78e978dac265e0206e4dbc205c1d7946014967d9")


def restore_before_selected_recovery_registration(trust):
    delta = selected_recovery_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for change in delta["gapDeltas"]:
        assert prior["gaps"][change["index"]] == change["after"]
        prior["gaps"][change["index"]] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def selected_recovery_history(trust):
    delta = selected_recovery_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_selected_recovery_registration(trust)
    return trust


def restore_before_selected_recovery_matrix_raw(raw):
    delta = selected_recovery_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    family = next(row for row in matrix["capabilities"] if row["id"] == delta["family"])
    assert family["languages"]["rust"]["api"].count(delta["apiAdded"]) == 1
    family["languages"]["rust"]["api"].remove(delta["apiAdded"])
    for path in reversed(delta["evidenceAdded"]):
        assert family["languages"]["rust"]["evidence"].pop() == path
    for language in ("rust", "npm", "python"):
        assert family["languages"][language]["gaps"].pop() == delta["functionalObligation"]
    prior = (json.dumps(matrix, indent=2) + "\n").encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    return prior


def selected_recovery_matrix_history(raw):
    delta = selected_recovery_registration_delta()["matrixDelta"]
    if sdk.sha(raw) == delta["afterSha256"]:
        return restore_before_selected_recovery_matrix_raw(raw)
    return raw


def selected_recovery_cookie_history(raw):
    delta = selected_recovery_registration_delta()["cookieDelta"]
    if sdk.sha(raw) == delta["afterSha256"]:
        prior = delta["beforeRaw"].encode()
        assert sdk.sha(prior) == delta["beforeSha256"]
        return prior
    return raw


def test_selected_recovery_partial_registration_keeps_all_old_plans_and_gap_prefixes():
    delta = selected_recovery_registration_delta()
    live = sdk.load_trust()
    prior = restore_before_selected_recovery_registration(live)
    assert {key: len(live[key]) for key in delta["counts"]} == {"programs": 332, "contracts": 86, "plan": 93, "gaps": 180}
    assert live["plan"] == prior["plan"] and len(live["plan"]) == 93
    assert len(live["gaps"]) == len(prior["gaps"]) == 180
    assert all(after.startswith(before) for before, after in zip(prior["gaps"], live["gaps"]))
    assert len(delta["gapDeltas"]) == 3
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"], sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert delta["newExecutionPlans"] == 0
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    assert len(delta["sourceClosure"]) == 10
    root = Path(__file__).resolve().parents[2]
    for row in delta["sourceClosure"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["after_sha256"]
    assert delta["publicApiDelta"]["rust"]["added"] == ["client.Client.completion_recovery_jobs_for_chat"]
    assert delta["publicApiDelta"]["npm"]["added"] == delta["publicApiDelta"]["python"]["added"] == []
    witness = delta["diagnosticWitnessUnchanged"]
    assert sdk.sha((root / witness["path"]).read_bytes()) == witness["sha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == "031caae25a25d23c0fe2fe3819b02187fc8fd77620870b630094829fb2839958"
    historical = restore_before_first_page_npm_diagnostic_registration(prior)
    assert sdk.sha((json.dumps(historical, indent=2, sort_keys=True) + "\n").encode()) == "964f822aefd37312c53f42bc359650ff0521393d39f03d5a44ad2b03045f2180"


def test_selected_recovery_matrix_inverse_keeps_every_prior_status_and_obligation():
    delta = selected_recovery_registration_delta()
    raw = (Path(__file__).resolve().parents[2] / "config/sdk-capabilities.json").read_bytes()
    matrix = json.loads(raw)
    prior = json.loads(restore_before_selected_recovery_matrix_raw(raw))
    assert len(matrix["capabilities"]) == len(prior["capabilities"])
    for old, new in zip(prior["capabilities"], matrix["capabilities"]):
        assert old["id"] == new["id"]
        if old["id"] != delta["matrixDelta"]["family"]:
            assert old == new
        else:
            for language in ("rust", "npm", "python"):
                assert old["languages"][language]["status"] == new["languages"][language]["status"] == "partial"
                assert old["languages"][language]["conformance"] == new["languages"][language]["conformance"]
                assert new["languages"][language]["gaps"][:-1] == old["languages"][language]["gaps"]
                assert new["languages"][language]["gaps"][-1] == delta["matrixDelta"]["functionalObligation"]
            for language in ("npm", "python"):
                assert old["languages"][language]["api"] == new["languages"][language]["api"]


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_selected_recovery_inverse_refuses_unknown_source_contract_plan_or_gap_drift(bucket):
    changed = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        changed[bucket][next(iter(changed[bucket]))] = "0" * 64
    else:
        changed[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_selected_recovery_registration(changed)


def test_selected_recovery_matrix_and_cookie_history_refuse_unknown_drift():
    delta = selected_recovery_registration_delta()
    root = Path(__file__).resolve().parents[2]
    raw = (root / "config/sdk-capabilities.json").read_bytes()
    with pytest.raises(AssertionError):
        restore_before_selected_recovery_matrix_raw(raw + b" ")
    assert selected_recovery_matrix_history(raw + b" ") == raw + b" "
    cookie = (root / "scripts/tests/test_sdk_session_embed_version_gate.py").read_bytes()
    assert sdk.sha(selected_recovery_cookie_history(cookie)) == delta["cookieDelta"]["beforeSha256"]
    assert selected_recovery_cookie_history(cookie + b" ") == cookie + b" "
