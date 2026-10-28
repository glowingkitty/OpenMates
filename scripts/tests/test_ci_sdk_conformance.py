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
    # INERT packaging receipt fixture only; no native/package operation runs.
    packaged_fixture = root / "tests/sdk-conformance/fixtures/api-key-foundation.json"
    packaged_fixture.parent.mkdir(parents=True, exist_ok=True)
    packaged_ids = [f"synthetic-packaged-{index}" for index in range(23)]
    packaged_fixture.write_text(json.dumps({"capabilities": {"sdk.configuration": {"vectors": [{"id": value} for value in packaged_ids]}}}))
    report["packagedSdkV1"] = {"status": "passed", "entrypoint": "openmates/sdk/v1",
        "fixtureSha256": sdk.sha(packaged_fixture.read_bytes()), "vectorIds": packaged_ids,
        "artifactSha256": "e" * 64, "nativeSha256": "c" * 64,
        "nativeAdapter": "actual-rust-api-key-library", "ambientSyntheticCliStateAccess": False,
        "explicitFixtureCredentials": True, "cliLauncherObserved": False, "rawTracePublished": False}
    return root, report


def synthetic_trust(root):
    matrix = json.loads((root / "config/sdk-capabilities.json").read_text())
    return {"contracts": {"config/sdk-capabilities.json": sdk.sha((root / "config/sdk-capabilities.json").read_bytes()),
            "tests/sdk-conformance/fixtures/api-key-foundation.json": sdk.sha((root / "tests/sdk-conformance/fixtures/api-key-foundation.json").read_bytes())},
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
    # INERT retriever fixture includes the real-shaped npm configuration plan
    # so ordered23 proof is independently bound to plan+immutable fixture bytes.
    matrix_path = root / "config/sdk-capabilities.json"
    matrix = json.loads(matrix_path.read_text())
    fixture_path = "tests/sdk-conformance/fixtures/api-key-foundation.json"
    matrix["capabilities"].append({"id": "sdk.configuration", "fixture": fixture_path,
        "languages": {name: {"conformance": name == "npm", "status": "implemented", "gaps": []} for name in ("rust", "npm", "python")}})
    matrix_path.write_text(json.dumps(matrix))
    raw["matrixSha256"] = sdk.sha(matrix_path.read_bytes())
    raw["expectedPlan"] = sdk.execution_plan(root, matrix)
    raw["actualLaunches"] = [{"capability": row["capability"], "language": row["language"], "status": "passed", "commandSha256": "d" * 64} for row in raw["expectedPlan"]]
    raw["conformance"].append({"capability": "sdk.configuration", "language": "npm", "fixtureSha256": sdk.sha((root / fixture_path).read_bytes()), "status": "passed", "results": [{"id": value, "status": "passed"} for value in raw["packagedSdkV1"]["vectorIds"]]})
    report = {"runtime_profile": sdk.TARGET, "results": [{"suite": sdk.TARGET, "exit_code": 0,
                                                       "failed_stage": None, "failure_code": None}]}
    job = {"specs": json.dumps([sdk.TARGET]), "source": "a" * 40, "run_id": 123}
    evidence = {"source_commit": "a" * 40, "run_id": "123", "harness_commit": "b" * 40,
                "status": "passed", "publication": False, "services": {}, "sourceHeld": True,
                "loadIdentityVerified": True, "cleanupVerified": True,
                "gate": sdk.gate_receipt(root, raw, trust=synthetic_trust(root)),
                "artifacts": {language: {"sha256": "c" * 64, "elf": "linux-x64", "nlink": 1} for language in ("npm", "python")}}
    inputs = {name: "c" * 64 for name in sdk.LOCKS}
    inputs[fixture_path] = sdk.sha((root / fixture_path).read_bytes())
    evidence.update(inputs=inputs, inputSetSha256=sdk.sha(json.dumps(inputs, sort_keys=True).encode()),
                    locks={name: inputs[name] for name in sdk.LOCKS}, dist={"frontend/packages/openmates-cli/dist/sdk-entry.js": "d" * 64},
                    steps=[{"stage": stage, "status": "passed", "returncode": 0, "terminatedReturncode": 0, "elapsedSeconds": 1}
                           for stage in ["rust-toolchain", "python-environment", "node-dependencies", "python-dependencies", "sdk-library-units", "binding-library-units", "napi-build", "python-binding-build", "sdk-facade-build", "napi-load", "python-load", "real-conformance"]])
    for step in evidence["steps"][4:6]:
        step.update(unitTests={"passed": 1, "failed": 0, "ignored": 0, "measured": 0, "filteredOut": 0},
                    started=True, command={"tool": "cargo", "admission": "strict-owner-mode",
                    "argvSha256": sdk.sha(json.dumps(sdk.library_unit_command(step["stage"]), separators=(",", ":")).encode()),
                    "executableSha256": "e" * 64})
    for value in evidence["artifacts"].values():
        value.update(device=1, inode=1, uid=os.getuid(), mode=0o600, mtimeNs=1, ctimeNs=1, bytes=96)
    expectation = {"trust": synthetic_trust(root), "expected_inputs": inputs,
                   "expected_packaged_fixture": (root / fixture_path).read_bytes()}
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
            gate["packagedSdkV1"]["nativeSha256"] = sdk.sha(node_artifact.read_bytes())
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
    # This test proves real INERT aggregate drivers only, not native packaging.
    monkeypatch.setattr(executor, "run_packaged_sdk_v1", lambda *args: report["packagedSdkV1"])
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


# Three explicitly reviewed tooling witnesses only. These bytes never enter the current
# SDK trust loader, protocol fixtures or publication-size guard.
_COMPRESSED_TRUST_WITNESSES = {'sdk-conformance-trust-rich45-delta.json': (5495264, '952292ac0fa3e8fcc0869971a3959fb1e495bd868d803b5bec9ed8347e63c70c', 4121214, 'e5f8576a0595c7b3db54682d8e564401de87d898a024a89307d068bfe75628e6', 21659923, 'f5c103597daca63aef57e3463972c676fb3eeeeff9b51543e9f37ddd7aa0b620'), 'sdk-conformance-trust-full29-arrival20-delta.json': (2943800, '7fbd4fa28e95065a7cdc3d8e2a367edb2a0602d56c888d7c89c997e4f6f74616', 2207615, '37dc2a7075f71d9cebb92ac056b99e997d34e76ad31bd90af50f720c70c29bf9', 10969447, 'c481cacb139f93a0a5e533425daa74ca024a2756272b230ef5ada28b76c982d7'), 'sdk-conformance-trust-essential-currentdev-delta.json': (2002411, '754781379369eb86ffb7218c8fa3758cd4a844973045d1d68a0670f1b3fccf75', 1501573, 'eb7bc33a4fa9c92c54a3e6e55234741198c55c4716020d520d5e4adac8efc8bf', 8773733, 'db4d46417c4908319e7d97ebd772f1a6f45832159be5870bba606b4c150deeca'), 'sdk-conformance-trust-fresh-compiler-delta.json': (468826, '93b770a7bde62b41980f817882d65896d397d9895679515b81e52d0149fc5b12', 351385, 'e4a2a915121936b8700b798c7aa43f4941e1a5fd6e1018ff8bce721ee6ccd1e5', 1924890, 'ae731196eba37ee0750391bae99b3337b6731c20de1bc4b22379191ffa854989'), 'sdk-conformance-trust-baseline-repair-delta.json': (1333715, '2901711bc128f3b20128c8023abeb5cade6166e2f0741c8cbfc020882fc1bb33', 1000052, '3cd12eaea8819bd7ab395bb7c68a123f049b61ed1b7b35f85f37f4346915a0b8', 4988128, '5c2792159c26fd9d23999ffab0501729b22b890d3d225e50a517776c56fa1189')}
_COMPRESSED_TRUST_WITNESSES['sdk-conformance-trust-next-native-sdk-delta.json'] = (369846, 'a2146fdb0b14e7ec33ffad99a06746a01bd0f01425e7d69a2d24650e0e077c9d', 277150, '482d6a3e1ae3fdb874f6d13f8e84c7dff5faf80b3c59d5a10a3099d19a6c86df', 1973973, '22389488f4f03140cc03a6e5987322a84c97f14fb8f583d3f5b17dfb432a43be')
_COMPRESSED_TRUST_WITNESSES['sdk-conformance-trust-browser-ts-ci105-delta.json'] = (1303082, 'da34ccea0e228cb7f358bea929bbfd4f02d1481ab921cd1acd7e17f4dc67365a', 977078, '0fa5d3b4ae3f194d77639473eef297ee88bcc007e87cb929788987317a48d56a', 4627690, '9154cb9661ad2b9916da253212d15b2daa88ac6db481b7c75cd9532f70dc57bd')
_COMPRESSED_TRUST_WITNESSES['sdk-conformance-trust-phase1-currentdev-history-delta.json'] = (575822, '725c56a4ce6fe6a566fb833406ec7b75ecef649f757d6d302154cd074b08688b', 431633, '22a3466808f655d90b3fa23481d899296f76e21f991a810797e7daafc4fe5c4d', 2361431, '5cb68db06550428cdb09850ebc7a16d81a9fca382efa8d88428f976e1aca1f07')
_COMPRESSED_TRUST_WITNESS_BYTES = {}
_MAX_CACHED_COMPRESSED_TRUST_WITNESSES = 2
_MAX_COMPRESSED_TRUST_CONTAINER = 8 * 1024**2
_MAX_DECODED_TRUST_WITNESS = 24 * 1024**2


def _read_compressed_trust_witness(path, name, expected_sha256):
    import stat
    spec = _COMPRESSED_TRUST_WITNESSES.get(name)
    assert spec is not None and expected_sha256 == spec[5]
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
        original = os.fstat(descriptor)
        assert stat.S_ISREG(original.st_mode) and original.st_size == spec[0] <= _MAX_COMPRESSED_TRUST_CONTAINER
        chunks, count = [], 0
        while count <= spec[0]:
            chunk = os.read(descriptor, min(1024**2, spec[0] + 1 - count))
            if not chunk:
                break
            chunks.append(chunk)
            count += len(chunk)
        observed = os.fstat(descriptor)
        current = os.stat(path, follow_symlinks=False)
        def identity(value):
            return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        assert identity(original) == identity(observed) == identity(current) and stat.S_ISREG(current.st_mode)
        packed = b"".join(chunks)
        assert len(packed) == spec[0]
    except OSError:
        raise AssertionError("Historical compressed witness is not an original regular file") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return _decode_compressed_trust_witness(name, expected_sha256, packed)


def _decode_compressed_trust_witness(name, expected_sha256, packed):
    import base64
    import zlib
    spec = _COMPRESSED_TRUST_WITNESSES.get(name)
    assert spec is not None and expected_sha256 == spec[5]
    assert type(packed) is bytes and len(packed) == spec[0] <= _MAX_COMPRESSED_TRUST_CONTAINER
    actual = sdk.sha(packed)
    assert actual == spec[1]
    key = (name, actual)
    cached = _COMPRESSED_TRUST_WITNESS_BYTES.pop(key, None)
    if cached is not None:
        assert type(cached) is bytes and len(cached) == spec[4]
        _COMPRESSED_TRUST_WITNESS_BYTES[key] = cached
        return cached

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            assert key not in value
            value[key] = item
        return value

    try:
        container = json.loads(packed, object_pairs_hook=unique_object)
        assert type(container) is dict and set(container) == {"format", "decodedBytes", "decodedSha256", "compressedBytes", "compressedSha256", "payload"}
        assert container["format"] == "openmates-historical-test-witness-gzip-v1"
        assert type(container["decodedBytes"]) is int and container["decodedBytes"] == spec[4] <= _MAX_DECODED_TRUST_WITNESS
        assert container["decodedSha256"] == spec[5]
        assert type(container["compressedBytes"]) is int and container["compressedBytes"] == spec[2]
        assert container["compressedSha256"] == spec[3] and type(container["payload"]) is str
        compressed = base64.b64decode(container["payload"], validate=True)
        assert len(compressed) == spec[2] and sdk.sha(compressed) == spec[3]
        decoder = zlib.decompressobj(wbits=31)
        decoded = decoder.decompress(compressed, spec[4] + 1)
        assert len(decoded) == spec[4] and decoder.eof and not decoder.unconsumed_tail and not decoder.unused_data
        assert sdk.sha(decoded) == spec[5]
    except (ValueError, TypeError, UnicodeError, zlib.error):
        raise AssertionError("Historical compressed witness container is invalid") from None
    # Only immutable bytes are retained. Actual packed bytes were freshly read
    # and rehashed above on EVERY call; the fixed two-entry cache evicts oldest.
    if len(_COMPRESSED_TRUST_WITNESS_BYTES) >= _MAX_CACHED_COMPRESSED_TRUST_WITNESSES:
        _COMPRESSED_TRUST_WITNESS_BYTES.pop(next(iter(_COMPRESSED_TRUST_WITNESS_BYTES)))
    _COMPRESSED_TRUST_WITNESS_BYTES[key] = decoded
    assert len(_COMPRESSED_TRUST_WITNESS_BYTES) <= _MAX_CACHED_COMPRESSED_TRUST_WITNESSES
    return decoded


def immutable_trust_test_fixture(name, expected_sha256):
    # Historical inputs are test data only. Runtime load_trust/verify_programs
    # continue reading the protected live manifest beside their module.
    if name in _COMPRESSED_TRUST_WITNESSES:
        raw = _read_compressed_trust_witness(Path(__file__).with_name("fixtures") / name, name, expected_sha256)
    else:
        raw = (Path(__file__).with_name("fixtures") / name).read_bytes()
    assert sdk.sha(raw) == expected_sha256
    if name in _COMPRESSED_TRUST_WITNESSES:
        return json.loads(raw)  # Fresh objects; no mutable decoded-object cache.
    return _decode_reviewed_trust_fixture(name, expected_sha256, raw)


def test_current_reviewed_aggregate_keeps_exact_live_authority_and_counts():
    approval = immutable_trust_test_fixture("sdk-conformance-trust-reviewed229-delta.json", "bdbd7a7d020394bc71d6ab84da1abc9a7fae75c748f04d920c1708c24fa9b969")
    live_path = Path(sdk.__file__).with_name("ci_sdk_conformance_trust.json")
    live_bytes = live_path.read_bytes()
    assert sdk.sha(live_bytes) == "5b4d44475fafbcb4b0a6d39b4cb186f0181e10a0a390494146c32573668e646a"
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
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
    raw = restore_before_full29_arrival20_fixture_raw(raw, capability)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
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
    raw = selected_sdk_cookie_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["cookieDelta"]["afterSha256"]:
        raw = restore_before_browser45_cookie_raw(raw)
    raw = selected_recovery_cookie_history(raw)
    delta = cache_embed_registration_delta()["cookieDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    prior = delta["beforeRaw"].encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    return prior


def historical_cache_embed_matrix_raw(raw):
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
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
    raw = selected_recovery_matrix_history(restore_before_browser45_matrix_raw((root/"config/sdk-capabilities.json").read_bytes()))
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
        assert sdk.sha(browser45_historical_source_raw(root/row["path"])) == row["afterSha256"]
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
    trust = selected_recovery_history(trust)
    delta = first_page_npm_diagnostic_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    assert prior["programs"][delta["program"]] == delta["afterProgramSha256"]
    prior["programs"][delta["program"]] = delta["beforeProgramSha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def first_page_npm_diagnostic_history(trust):
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
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
    trust = selected_sdk_history(trust)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == browser45["afterSha256"]:
        trust = restore_before_browser45_registration(trust)
    delta = selected_recovery_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_selected_recovery_registration(trust)
    return trust


def restore_before_selected_recovery_matrix_raw(raw):
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
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
    raw = selected_sdk_matrix_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["matrixDelta"]["afterSha256"]:
        raw = restore_before_browser45_matrix_raw(raw)
    delta = selected_recovery_registration_delta()["matrixDelta"]
    if sdk.sha(raw) == delta["afterSha256"]:
        return restore_before_selected_recovery_matrix_raw(raw)
    return raw


def selected_recovery_cookie_history(raw):
    raw = selected_sdk_cookie_history(raw)
    browser45 = immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")
    if sdk.sha(raw) == browser45["cookieDelta"]["afterSha256"]:
        raw = restore_before_browser45_cookie_raw(raw)
    delta = selected_recovery_registration_delta()["cookieDelta"]
    if sdk.sha(raw) == delta["afterSha256"]:
        prior = delta["beforeRaw"].encode()
        assert sdk.sha(prior) == delta["beforeSha256"]
        return prior
    return raw


def test_selected_recovery_partial_registration_keeps_all_old_plans_and_gap_prefixes():
    delta = selected_recovery_registration_delta()
    live = restore_before_browser45_registration(sdk.load_trust())
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
        assert sdk.sha(browser45_historical_source_raw(root / row["path"])) == row["after_sha256"]
    assert delta["publicApiDelta"]["rust"]["added"] == ["client.Client.completion_recovery_jobs_for_chat"]
    assert delta["publicApiDelta"]["npm"]["added"] == delta["publicApiDelta"]["python"]["added"] == []
    witness = delta["diagnosticWitnessUnchanged"]
    assert sdk.sha((root / witness["path"]).read_bytes()) == witness["sha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == "031caae25a25d23c0fe2fe3819b02187fc8fd77620870b630094829fb2839958"
    historical = restore_before_first_page_npm_diagnostic_registration(prior)
    assert sdk.sha((json.dumps(historical, indent=2, sort_keys=True) + "\n").encode()) == "964f822aefd37312c53f42bc359650ff0521393d39f03d5a44ad2b03045f2180"


def test_selected_recovery_matrix_inverse_keeps_every_prior_status_and_obligation():
    delta = selected_recovery_registration_delta()
    raw = restore_before_browser45_matrix_raw((Path(__file__).resolve().parents[2] / "config/sdk-capabilities.json").read_bytes())
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


def browser45_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-browser45-delta.json", "c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb")


def restore_before_browser45_registration(trust):
    trust = selected_sdk_history(trust)
    delta = browser45_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path,change in delta["pinDeltas"][bucket].items():
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


def restore_before_browser45_matrix_raw(raw):
    raw = selected_sdk_matrix_history(raw)
    delta = browser45_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    family = next(row for row in matrix["capabilities"] if row["id"] == delta["family"])
    for symbol in delta["rustApiAdded"]:
        assert family["languages"]["rust"]["api"].count(symbol) == 1
        family["languages"]["rust"]["api"].remove(symbol)
    assert family["description"].endswith(delta["descriptionAppend"])
    family["description"] = delta["priorDescription"]
    for language in ("rust", "npm", "python"):
        assert family["languages"][language]["gaps"].pop() == delta["functionalObligation"]
    prior = (json.dumps(matrix, indent=2) + "\n").encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    return prior


def restore_before_browser45_cookie_raw(raw):
    raw = selected_sdk_cookie_history(raw)
    delta = browser45_registration_delta()["cookieDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    prior = delta["beforeRaw"].encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    return prior


def browser45_historical_source_raw(path):
    raw = path.read_bytes()
    raw = ci_fixture3_historical_source_raw(path, raw)
    peer = browser45_registration_delta()["reviewedPeerTooling"]
    if path == Path(__file__).resolve().parents[2]/peer["path"]:
        assert sdk.sha(raw) == peer["afterSha256"]
        prior = peer["beforeRaw"].encode()
        assert sdk.sha(prior) == peer["beforeSha256"]
        marker = peer["exactComment"].encode()
        assert raw.count(marker) == 1 and raw.replace(marker, b"", 1) == prior
        return prior
    delta = browser45_registration_delta()["historicalSourceEpoch"]
    if path == Path(__file__).resolve().parents[2]/delta["path"]:
        assert sdk.sha(raw) == delta["afterSha256"]
        prior = delta["beforeRaw"].encode()
        assert sdk.sha(prior) == delta["beforeSha256"]
        return prior
    return raw


def test_browser45_partial_registration_preserves_plans_gap_prefixes_and_semantic_review_hold():
    delta = browser45_registration_delta()
    live = restore_before_selected_sdk_registration(sdk.load_trust())
    prior = restore_before_browser45_registration(live)
    assert live["plan"] == prior["plan"] and len(live["plan"]) == 93
    assert len(live["gaps"]) == len(prior["gaps"]) == 180
    assert all(new.startswith(old) for old,new in zip(prior["gaps"],live["gaps"]))
    assert sum(a != b for a,b in zip(prior["gaps"],live["gaps"])) == 3
    assert sdk.sha(json.dumps(prior["plan"],sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"],sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert delta["sourceStatus"] == "SOURCE_HELD_PENDING_INDEPENDENT_CORE_SEMANTIC_REVIEW"
    assert delta["releaseEligible"] is False and delta["nativeExecutions"] == delta["sourceGateRuns"] == 0
    assert delta["newCapabilityFamilies"] == delta["newExecutionPlans"] == 0
    assert len(delta["publicApiDelta"]["rust"]["added"]) == 10
    assert delta["publicApiDelta"]["npm"]["added"] == delta["publicApiDelta"]["python"]["added"] == []
    assert len(delta["sourceClosure"]) == 45 and len(delta["newPolicyContracts"]) == 4
    root = Path(__file__).resolve().parents[2]
    raw = restore_before_selected_sdk_matrix_raw((root/"config/sdk-capabilities.json").read_bytes())
    old = json.loads(restore_before_browser45_matrix_raw(raw))
    matrix = json.loads(raw)
    assert len(matrix["capabilities"]) == len(old["capabilities"])
    for before,after in zip(old["capabilities"],matrix["capabilities"]):
        for language in ("rust", "npm", "python"):
            for key in ("status", "conformance", "evidence"):
                assert before["languages"][language][key] == after["languages"][language][key]
            assert after["languages"][language]["gaps"][:len(before["languages"][language]["gaps"])] == before["languages"][language]["gaps"]
    for a,b in ((0,2),(1,3)):
        pairs = sorted(delta["newPolicyContracts"],key=lambda row:row["path"])
        assert pairs[a]["after_sha256"] == pairs[b]["after_sha256"]


def test_browser45_inverse_rejects_tampered_source_contract_gap_plan_matrix_or_historical_input(monkeypatch):
    delta = browser45_registration_delta()
    live = sdk.load_trust()
    for bucket in ("programs", "contracts"):
        changed = copy.deepcopy(live)
        changed[bucket][next(iter(delta["pinDeltas"][bucket]))] = "0" * 64
        with pytest.raises(AssertionError):
            restore_before_browser45_registration(changed)
    for bucket in ("plan", "gaps"):
        changed = copy.deepcopy(live)
        changed[bucket].pop()
        with pytest.raises(AssertionError):
            restore_before_browser45_registration(changed)
    raw = (Path(__file__).resolve().parents[2]/"config/sdk-capabilities.json").read_bytes()
    with pytest.raises(AssertionError):
        restore_before_browser45_matrix_raw(raw+b" ")
    epoch = delta["historicalSourceEpoch"]
    assert sdk.sha(epoch["beforeRaw"].encode()) == epoch["beforeSha256"]
    target = Path(__file__).resolve().parents[2]/epoch["path"]
    original = Path.read_bytes
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "read_bytes", lambda path: b"tampered" if path == target else original(path))
        with pytest.raises(AssertionError):
            browser45_historical_source_raw(target)
    peer = delta["reviewedPeerTooling"]
    peer_target = Path(__file__).resolve().parents[2]/peer["path"]
    assert sdk.sha(peer_target.read_bytes()) == peer["afterSha256"]
    assert peer["ASTAndAssertionsExact"] is True
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "read_bytes", lambda path: b"tampered" if path == peer_target else original(path))
        with pytest.raises(AssertionError):
            browser45_historical_source_raw(peer_target)

# Exact SDK18 successor history. These helpers are inert test views only.
def selected_sdk_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-selected-sdk-delta.json", "c11c355aa92d642201ea61d6d4991a31ca72ae112b0b26620e8f1f35f9917306")


def restore_before_selected_sdk_registration(trust):
    trust = ci_fixture3_history(trust)
    delta = selected_sdk_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for change in delta["planDeltas"]:
        assert prior["plan"][change["index"]] == change["after"]
        prior["plan"][change["index"]] = change["before"]
    for change in delta["gapDeltas"]:
        assert prior["gaps"][change["index"]] == change["after"]
        prior["gaps"][change["index"]] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def selected_sdk_history(trust):
    trust = ci_fixture3_history(trust)
    delta = selected_sdk_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_selected_sdk_registration(trust)
    return trust


def restore_before_selected_sdk_matrix_raw(raw):
    raw = full29_arrival20_matrix_history(raw)
    delta = selected_sdk_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    matrix = json.loads(raw)
    family = next(row for row in matrix["capabilities"] if row["id"] == delta["family"])
    for language, symbols in delta["apiAdded"].items():
        for symbol in symbols:
            assert family["languages"][language]["api"].count(symbol) == 1
            family["languages"][language]["api"].remove(symbol)
        assert family["languages"][language]["gaps"].pop() == delta["functionalObligation"]
    prior = (json.dumps(matrix, indent=2) + "\n").encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    return prior


def selected_sdk_matrix_history(raw):
    raw = full29_arrival20_matrix_history(raw)
    delta = selected_sdk_registration_delta()["matrixDelta"]
    if sdk.sha(raw) == delta["afterSha256"]:
        return restore_before_selected_sdk_matrix_raw(raw)
    return raw


def selected_sdk_cookie_history(raw):
    raw = direct11_source_history(Path(__file__).resolve().parents[2] / "scripts/tests/test_sdk_session_embed_version_gate.py", raw)
    change = browser41_registration_delta()["cookieDelta"]
    if sdk.sha(raw) == change["afterSha256"]:
        raw = change["beforeRaw"].encode()
        assert sdk.sha(raw) == change["beforeSha256"]
    change = rich45_registration_delta()["cookieDelta"]
    if sdk.sha(raw) == change["afterSha256"]:
        raw = change["beforeRaw"].encode()
        assert sdk.sha(raw) == change["beforeSha256"]
    change = full29_arrival20_registration_delta()["cookieDelta"]
    if sdk.sha(raw) == change["afterSha256"]:
        raw = change["beforeRaw"].encode()
        assert sdk.sha(raw) == change["beforeSha256"]
    delta = selected_sdk_registration_delta()["cookieDelta"]
    if sdk.sha(raw) == delta["afterSha256"]:
        prior = delta["beforeRaw"].encode()
        assert sdk.sha(prior) == delta["beforeSha256"]
        return prior
    return raw


def restore_before_selected_sdk_fixture_raw(raw):
    delta = selected_sdk_registration_delta()["fixtureDelta"]
    assert sdk.sha(raw) == delta["afterSha256"]
    fixture = json.loads(raw)
    family = fixture["capabilities"]["session.foreground-completion-recovery.v1"]
    assert family["vectors"][8:] == delta["appendedVectors"]
    assert family["vectors"][:8] == delta["originalVectors"]
    family["vectors"] = family["vectors"][:8]
    prior = (json.dumps(fixture, indent=2) + "\n").encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    return prior


def test_selected_sdk_registration_retains_93_plan_identities_and_all_180_gap_prefixes():
    delta = selected_sdk_registration_delta()
    live = ci_fixture3_history(sdk.load_trust())
    prior = restore_before_selected_sdk_registration(live)
    assert {key: len(live[key]) for key in delta["counts"]} == {"programs": 363, "contracts": 91, "plan": 93, "gaps": 180}
    assert len(live["plan"]) == len(prior["plan"]) == 93
    assert len(live["gaps"]) == len(prior["gaps"]) == 180
    assert all(after.startswith(before) for before, after in zip(prior["gaps"], live["gaps"]))
    assert sum(a != b for a, b in zip(prior["gaps"], live["gaps"])) == 3
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"], sort_keys=True).encode()) == delta["oldGapsSha256"]
    changed = {row["index"] for row in delta["planDeltas"]}
    assert len(changed) == 3
    for index, (before, after) in enumerate(zip(prior["plan"], live["plan"])):
        assert (before["capability"], before["language"], before["fixture"]) == (after["capability"], after["language"], after["fixture"])
        if index not in changed:
            assert before == after
        else:
            assert before["capability"] == "session.foreground-completion-recovery.v1"
            assert len(before["vectors"]) == 8 and len(after["vectors"]) == 12
            assert set(before["vectors"]) < set(after["vectors"])
    assert delta["requiredPartial"] is True and delta["releaseEligible"] is False
    assert delta["nativeExecutions"] == delta["actualConformanceExecutions"] == 0
    assert delta["newCapabilityFamilies"] == delta["newExecutionPlans"] == 0
    assert delta["fullSlug22Included"] is False
    assert delta["publicApiDelta"]["rust"] == {"added": [], "removed": []}
    assert delta["publicApiDelta"]["npm"] == {"added": ["SessionClient.completionRecovery.jobsForChat", "SessionCompletionRecovery.jobsForChat"], "removed": []}
    assert delta["publicApiDelta"]["python"] == {"added": ["SessionClient.completion_recovery.jobs_for_chat", "SessionCompletionRecovery.jobs_for_chat"], "removed": []}
    root = full29_arrival20_historical_sdk_source_root(Path(__file__).resolve().parents[2])
    assert len(delta["sourceClosure"]) == 18
    for row in delta["sourceClosure"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["after_sha256"]
    for name in ("diagnosticWitnessUnchanged", "selected10WitnessUnchanged", "browser357WitnessUnchanged"):
        witness = delta[name]
        assert sdk.sha((root / witness["path"]).read_bytes()) == witness["sha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == "0f165e2f2c04d7bffe755ef9ac5fb0fc6e60e7c4299c9766d28b7152520a9a69"
    f3f = restore_before_browser45_registration(prior)
    assert sdk.sha((json.dumps(f3f, indent=2, sort_keys=True) + "\n").encode()) == "f3f2041553a6063a8fbe7a41761be6b0cdfe1c7893be49159514dff40c5013b0"
    diagnostic = restore_before_selected_recovery_registration(f3f)
    assert sdk.sha((json.dumps(diagnostic, indent=2, sort_keys=True) + "\n").encode()) == "031caae25a25d23c0fe2fe3819b02187fc8fd77620870b630094829fb2839958"


def test_selected_sdk_matrix_fixture_history_preserves_all_original_objects_and_statuses():
    delta = selected_sdk_registration_delta()
    root = EssentialCurrentdevHistoricalPath(Path(__file__).resolve().parents[2])
    raw = (root / "config/sdk-capabilities.json").read_bytes()
    raw = full29_arrival20_matrix_history(raw)
    prior = json.loads(restore_before_selected_sdk_matrix_raw(raw))
    current = json.loads(raw)
    assert len(current["capabilities"]) == len(prior["capabilities"])
    for before, after in zip(prior["capabilities"], current["capabilities"]):
        assert before["id"] == after["id"]
        if before["id"] != delta["matrixDelta"]["family"]:
            assert before == after
        else:
            for language in ("rust", "npm", "python"):
                for key in ("status", "conformance", "evidence"):
                    assert before["languages"][language][key] == after["languages"][language][key]
                assert after["languages"][language]["gaps"][:-1] == before["languages"][language]["gaps"]
    raw = (root / delta["fixtureDelta"]["path"]).read_bytes()
    old_fixture = json.loads(restore_before_selected_sdk_fixture_raw(raw))
    fixture = json.loads(raw)
    identity = delta["matrixDelta"]["family"]
    assert old_fixture["capabilities"][identity]["account"] == fixture["capabilities"][identity]["account"]
    assert old_fixture["capabilities"][identity]["protocol"] == fixture["capabilities"][identity]["protocol"]
    assert old_fixture["capabilities"][identity]["vectors"] == fixture["capabilities"][identity]["vectors"][:8]
    contract = delta["schemaContract"]
    assert sdk.sha((root / contract["path"]).read_bytes()) == contract["sha256"]


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_selected_sdk_history_refuses_unknown_pin_plan_or_gap_drift(bucket):
    changed = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        changed[bucket][next(iter(changed[bucket]))] = "0" * 64
    else:
        changed[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_selected_sdk_registration(changed)


def test_selected_sdk_history_refuses_unknown_matrix_fixture_or_cookie_bytes():
    delta = selected_sdk_registration_delta()
    root = Path(__file__).resolve().parents[2]
    raw = (root / "config/sdk-capabilities.json").read_bytes()
    with pytest.raises(AssertionError):
        restore_before_selected_sdk_matrix_raw(raw + b" ")
    assert selected_sdk_matrix_history(raw + b" ") == raw + b" "
    fixture = (root / delta["fixtureDelta"]["path"]).read_bytes()
    with pytest.raises(AssertionError):
        restore_before_selected_sdk_fixture_raw(fixture + b" ")
    cookie = (root / delta["cookieDelta"]["path"]).read_bytes()
    assert sdk.sha(selected_sdk_cookie_history(cookie)) == delta["cookieDelta"]["beforeSha256"]
    assert selected_sdk_cookie_history(cookie + b" ") == cookie + b" "


# Exact CI fixture-only successor. Historical views never normalize runtime trust.
def ci_fixture3_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-ci-unit-fixture3-delta.json", "fcc9295f930203001cd4001991f2b18719f71a8dc1f994a4fd26828212a2baba")


def restore_before_ci_fixture3_registration(trust):
    trust = native5_fixture_history(trust)
    delta = ci_fixture3_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for path, change in delta["pinDeltas"]["programs"].items():
        assert prior["programs"][path] == change["after"]
        prior["programs"][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def ci_fixture3_history(trust):
    trust = native5_fixture_history(trust)
    delta = ci_fixture3_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_ci_fixture3_registration(trust)
    return trust


def ci_fixture3_historical_source_raw(path, raw):
    raw = native5_fixture_historical_source_raw(path, raw)
    root = Path(__file__).resolve().parents[2]
    for change in ci_fixture3_registration_delta()["sourceInverse"]:
        if path == root / change["path"]:
            assert sdk.sha(raw) == change["afterSha256"]
            prior = change["beforeRaw"].encode()
            assert sdk.sha(prior) == change["beforeSha256"]
            return prior
    return raw


def test_ci_fixture3_registration_updates_only_exact_three_existing_programs():
    delta = ci_fixture3_registration_delta()
    live = native5_fixture_history(sdk.load_trust())
    prior = restore_before_ci_fixture3_registration(live)
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == "d26d08332b492b71927db31a1ea15ee806a194f2fc348b0e3b60ba2296b10b66"
    assert {key: len(live[key]) for key in delta["counts"]} == {"programs": 363, "contracts": 91, "plan": 93, "gaps": 180}
    assert set(live["programs"]) == set(prior["programs"])
    assert {path for path in live["programs"] if live["programs"][path] != prior["programs"][path]} == set(delta["pinDeltas"]["programs"])
    assert len(delta["pinDeltas"]["programs"]) == 3
    assert {key: value for key, value in live.items() if key != "programs"} == {key: value for key, value in prior.items() if key != "programs"}
    assert sdk.sha(json.dumps(prior["plan"], sort_keys=True).encode()) == delta["oldPlansSha256"]
    assert sdk.sha(json.dumps(prior["gaps"], sort_keys=True).encode()) == delta["oldGapsSha256"]
    assert delta["publicApiDelta"] == {"rust": 0, "npm": 0, "python": 0}
    assert delta["newExecutionPlans"] == delta["newCapabilityFamilies"] == 0
    assert delta["nativeExecutions"] == delta["actualConformanceExecutions"] == 0
    assert delta["releaseEligible"] is False
    assert delta["productionSourceChanged"] is False
    assert delta["preview8Registered"] is False and delta["fullSlugOrForeignReleaseRegistered"] is False


def test_ci_fixture3_exact_source_inverse_preserves_original_d26_case_evidence():
    delta = ci_fixture3_registration_delta()
    prior = restore_before_ci_fixture3_registration(sdk.load_trust())
    root = Path(__file__).resolve().parents[2]
    assert len(delta["sourceInverse"]) == 3
    for change in delta["sourceInverse"]:
        path = root / change["path"]
        raw = browser41_historical_source_raw(path, path.read_bytes())
        assert sdk.sha(raw) == change["afterSha256"]
        original = ci_fixture3_historical_source_raw(path, raw)
        assert original == change["beforeRaw"].encode()
        assert sdk.sha(original) == prior["programs"][change["path"]] == change["beforeSha256"]
        assert browser45_historical_source_raw(path) == original
        assert change["rootReviewedFixtureOnly"] is True
        assert change["oldAssertionsRemoved"] == 0
    assert delta["sourceInverse"][0]["expectedExpressionCorrection"] == "fresh randomized metadata() replaced with exact original stored metadata snapshot"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_ci_fixture3_source_inverse_refuses_unknown_bytes_and_stale_current_source(index, monkeypatch):
    change = ci_fixture3_registration_delta()["sourceInverse"][index]
    target = Path(__file__).resolve().parents[2] / change["path"]
    original = Path.read_bytes
    actual = target.read_bytes()
    for wrong in (actual + b"\n", change["beforeRaw"].encode()):
        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "read_bytes", lambda path: wrong if path == target else original(path))
            with pytest.raises(AssertionError):
                browser45_historical_source_raw(target)


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_ci_fixture3_inverse_refuses_unknown_pin_contract_plan_or_gap_drift(bucket):
    changed = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        changed[bucket][next(iter(changed[bucket]))] = "0" * 64
    else:
        changed[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_ci_fixture3_registration(changed)


# Exact native5 fixture-only successor. These are historical test views only.
def native5_fixture_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-native5-fixture-delta.json", "228b142eb6319640c55b40965db32119cbb45b0af283db595b5aaaf68a323646")


def restore_before_native5_fixture_registration(trust):
    trust = full29_arrival20_history(trust)
    delta = native5_fixture_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    change = delta["program"]
    assert prior["programs"][change["path"]] == change["afterSha256"]
    prior["programs"][change["path"]] = change["beforeSha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def native5_fixture_history(trust):
    trust = full29_arrival20_history(trust)
    delta = native5_fixture_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_native5_fixture_registration(trust)
    return trust


def native5_fixture_historical_source_raw(path, raw):
    raw = full29_arrival20_historical_source_raw(path, raw)
    change = native5_fixture_registration_delta()["program"]
    if path == Path(__file__).resolve().parents[2] / change["path"]:
        assert sdk.sha(raw) == change["afterSha256"]
        prior = change["beforeRaw"].encode()
        assert sdk.sha(prior) == change["beforeSha256"]
        return prior
    return raw


def test_native5_fixture_registration_changes_exactly_one_existing_pin_and_no_other_authority():
    delta = native5_fixture_registration_delta()
    live = full29_arrival20_history(sdk.load_trust())
    prior = restore_before_native5_fixture_registration(live)
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == "4efbf51dde5b5e06aa5240a6de77522e347cabd43b3a0a8eb7f146a00a3ae99c"
    assert {key: len(live[key]) for key in delta["counts"]} == {"programs": 363, "contracts": 91, "plan": 93, "gaps": 180}
    assert set(live["programs"]) == set(prior["programs"])
    assert {path for path in live["programs"] if live["programs"][path] != prior["programs"][path]} == {delta["program"]["path"]}
    assert {key: value for key, value in live.items() if key != "programs"} == {key: value for key, value in prior.items() if key != "programs"}
    assert "frontend/packages/openmates-tui-native/src/runtime_store.rs" not in live["programs"]
    assert delta["publicApiDelta"] == {"rust": 0, "npm": 0, "python": 0}
    assert delta["newExecutionPlans"] == delta["newCapabilityFamilies"] == delta["nativeExecutions"] == 0
    assert delta["releaseEligible"] is False and delta["productionSourceChanged"] is False
    assert delta["futureFullSlugRegistered"] is False
    d26 = restore_before_ci_fixture3_registration(prior)
    assert sdk.sha((json.dumps(d26, indent=2, sort_keys=True) + "\n").encode()) == "d26d08332b492b71927db31a1ea15ee806a194f2fc348b0e3b60ba2296b10b66"
    browser357 = restore_before_selected_sdk_registration(d26)
    assert sdk.sha((json.dumps(browser357, indent=2, sort_keys=True) + "\n").encode()) == "0f165e2f2c04d7bffe755ef9ac5fb0fc6e60e7c4299c9766d28b7152520a9a69"


def test_native5_fixture_historical_source_keeps_exact_old_case_bytes_and_all_old_oracles():
    delta = native5_fixture_registration_delta()
    change = delta["program"]
    path = Path(__file__).resolve().parents[2] / change["path"]
    raw = full29_arrival20_historical_source_raw(path, path.read_bytes())
    assert sdk.sha(raw) == change["afterSha256"]
    original = native5_fixture_historical_source_raw(path, path.read_bytes())
    assert original == change["beforeRaw"].encode()
    assert sdk.sha(original) == change["beforeSha256"]
    assert browser45_historical_source_raw(path) == original
    assert delta["reviewedOraclePreservation"]["oldNeedAndAssertExpressionsRetained"] is True
    assert delta["reviewedOraclePreservation"]["oldCount"] == 180
    assert delta["reviewedOraclePreservation"]["newCount"] == 182


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_native5_fixture_inverse_rejects_unknown_pin_contract_plan_or_gap_drift(bucket):
    changed = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        changed[bucket][next(iter(changed[bucket]))] = "0" * 64
    else:
        changed[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_native5_fixture_registration(changed)


def test_native5_fixture_source_history_rejects_unknown_or_stale_actual_source(monkeypatch):
    change = native5_fixture_registration_delta()["program"]
    path = Path(__file__).resolve().parents[2] / change["path"]
    original = Path.read_bytes
    actual = path.read_bytes()
    for wrong in (actual + b"\n", change["beforeRaw"].encode()):
        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "read_bytes", lambda target: wrong if target == path else original(target))
            with pytest.raises(AssertionError):
                browser45_historical_source_raw(path)


# Exact reviewed full-read/arrival-order successor: historical tests only.
def full29_arrival20_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-full29-arrival20-delta.json", "c481cacb139f93a0a5e533425daa74ca024a2756272b230ef5ada28b76c982d7")


def restore_before_full29_arrival20_registration(trust):
    trust = full29_sdk_header_history(trust)
    delta = full29_arrival20_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for bucket, key in (("plan", "planDeltas"), ("gaps", "gapDeltas")):
        for change in delta[key]:
            assert prior[bucket][change["index"]] == change["after"]
            prior[bucket][change["index"]] = copy.deepcopy(change["before"])
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def full29_arrival20_history(trust):
    trust = full29_sdk_header_history(trust)
    delta = full29_arrival20_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_full29_arrival20_registration(trust)
    return trust


def full29_arrival20_historical_source_raw(path, raw):
    raw = rich45_historical_source_raw(path, raw)
    raw = binding_compile2_historical_source_raw(path, raw)
    raw = full29_sdk_header_historical_source_raw(path, raw)
    root = Path(__file__).resolve().parents[2]
    for change in full29_arrival20_registration_delta()["sourceInverse"]:
        if path == root / change["path"]:
            assert sdk.sha(raw) == change["afterSha256"]
            prior = change["beforeRaw"].encode()
            assert sdk.sha(prior) == change["beforeSha256"]
            return prior
    return raw


def restore_before_full29_arrival20_matrix_raw(raw):
    raw = rich45_matrix_history(raw)
    change = full29_arrival20_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == change["afterSha256"]
    prior = change["beforeRaw"].encode()
    assert sdk.sha(prior) == change["beforeSha256"]
    return prior


def full29_arrival20_matrix_history(raw):
    raw = rich45_matrix_history(raw)
    if sdk.sha(raw) == full29_arrival20_registration_delta()["matrixDelta"]["afterSha256"]:
        return restore_before_full29_arrival20_matrix_raw(raw)
    return raw


def restore_before_full29_arrival20_fixture_raw(raw, capability):
    raw = rich45_fixture_history(raw, capability)
    delta = full29_arrival20_registration_delta()["fixtureDelta"]
    if capability != delta["capability"]:
        return raw
    assert sdk.sha(raw) == delta["afterSha256"]
    current = json.loads(raw)
    assert current["capabilities"][capability]["vectors"] == delta["originalVectors"] + delta["appendedVectors"]
    prior = delta["beforeRaw"].encode()
    assert sdk.sha(prior) == delta["beforeSha256"]
    assert json.loads(prior)["capabilities"][capability]["vectors"] == delta["originalVectors"]
    return prior


def test_full29_arrival20_registration_retains_93_plan_identities_and_all180_open_gap_rows():
    delta = full29_arrival20_registration_delta()
    live = full29_sdk_header_history(sdk.load_trust())
    prior = restore_before_full29_arrival20_registration(live)
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == "bdd56dd6719368dc47e95a1162f95fa63ff85edecd9f36186f91389b934e489e"
    assert {key: len(live[key]) for key in delta["afterCounts"]} == delta["afterCounts"]
    assert {key: len(prior[key]) for key in delta["beforeCounts"]} == {"programs": 363, "contracts": 91, "plan": 93, "gaps": 180}
    assert len(live["plan"]) == len(prior["plan"]) == 93
    assert len(live["gaps"]) == len(prior["gaps"]) == 180
    assert len(delta["planDeltas"]) == 3
    changed = {row["index"] for row in delta["planDeltas"]}
    for index, (old, new) in enumerate(zip(prior["plan"], live["plan"])):
        if index not in changed:
            assert old == new
        else:
            assert new["capability"] == "session.saved-chat-read.v1"
            assert {k: v for k, v in old.items() if k not in ("fixtureSha256", "vectors")} == {k: v for k, v in new.items() if k not in ("fixtureSha256", "vectors")}
            assert len(old["vectors"]) == 66 and len(new["vectors"]) == 74
            assert set(old["vectors"]) < set(new["vectors"])
    assert len(delta["gapDeltas"]) == 3
    for change in delta["gapDeltas"]:
        correction = delta["matrixDelta"]["gapCorrection"]
        original = next(iter(correction["old"].values()))
        assert change["before"].endswith(original)
        assert change["after"] == change["before"][:-len(original)] + correction["new"] + "; " + delta["matrixDelta"]["functionalObligation"]
    assert {k: v for k, v in live.items() if k not in ("programs", "contracts", "plan", "gaps")} == {k: v for k, v in prior.items() if k not in ("programs", "contracts", "plan", "gaps")}
    assert delta["newCapabilityFamilies"] == delta["newExecutionPlans"] == delta["actualConformanceExecutions"] == 0
    assert delta["releaseEligible"] is False
    assert delta["nativePerformanceProposalIncluded"] is False
    assert delta["privateInstrumentationIncluded"] is False
    assert "frontend/packages/openmates-tui-native/src/runtime_store.rs" not in live["programs"]
    assert delta["publicApiDelta"]["npm"] == {"added": [], "removed": []}
    assert delta["publicApiDelta"]["python"] == {"added": ["SessionFullChatRead"], "removed": []}
    assert len(delta["publicApiDelta"]["rust"]["added"]) == 12
    assert delta["publicApiDelta"]["rust"]["removed"] == []
    old_native5 = restore_before_native5_fixture_registration(prior)
    assert sdk.sha((json.dumps(old_native5, indent=2, sort_keys=True) + "\n").encode()) == "4efbf51dde5b5e06aa5240a6de77522e347cabd43b3a0a8eb7f146a00a3ae99c"


def test_full29_arrival20_matrix_classifies_only_exact_new_partial_saved_read_symbols():
    delta = full29_arrival20_registration_delta()
    root = Path(__file__).resolve().parents[2]
    raw = (root / "config/sdk-capabilities.json").read_bytes()
    raw = rich45_matrix_history(raw)
    current = json.loads(raw)
    old = json.loads(restore_before_full29_arrival20_matrix_raw(raw))
    assert len(current["capabilities"]) == len(old["capabilities"])
    for prior, after in zip(old["capabilities"], current["capabilities"]):
        assert prior["id"] == after["id"]
        if prior["id"] != "session.saved-chat-read.v1":
            assert prior == after
            continue
        assert after["description"] == prior["description"] + delta["matrixDelta"]["descriptionSuffix"]
        for language in ("rust", "npm", "python"):
            a = after["languages"][language]
            b = prior["languages"][language]
            assert a["status"] == b["status"] == "partial"
            assert a["conformance"] == b["conformance"] is True
            assert set(a["api"]) - set(b["api"]) == set(delta["publicApiDelta"][language]["added"])
            assert set(b["api"]) - set(a["api"]) == set()
            correction = delta["matrixDelta"]["gapCorrection"]
            assert b["gaps"][-1] == correction["old"][language]
            assert a["gaps"] == b["gaps"][:-1] + [correction["new"], delta["matrixDelta"]["functionalObligation"]]
            assert a["evidence"] == b["evidence"]


def test_full29_arrival20_shared_fixture_preserves_all66_vectors_and_exact_shared5_inputs():
    delta = full29_arrival20_registration_delta()
    change = delta["fixtureDelta"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / change["path"]).read_bytes()
    raw = rich45_fixture_history(raw, change["capability"])
    old = json.loads(restore_before_full29_arrival20_fixture_raw(raw, change["capability"]))
    current = json.loads(raw)
    assert len(old["capabilities"][change["capability"]]["vectors"]) == 66
    assert len(current["capabilities"][change["capability"]]["vectors"]) == 74
    assert len(change["appendedVectors"]) == 8
    assert change["sharedFiveSha256"] == sdk.sha((root / "packages/openmates-rust/tests/fixtures/full-chat-read-metadata.json").read_bytes())
    assert delta["frozenConformance"]["patchSha256"] and delta["frozenConformance"]["manifestSha256"]
    assert delta["exactApiInventorySourceSha256"] and delta["exactApiInventorySha256"]


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_full29_arrival20_inverse_rejects_unknown_authority_or_scope_drift(bucket):
    changed = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        changed[bucket][next(iter(changed[bucket]))] = "0" * 64
    else:
        changed[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_full29_arrival20_registration(changed)


def test_full29_arrival20_source_inverse_refuses_unknown_or_stale_actual_source():
    root = Path(__file__).resolve().parents[2]
    for change in full29_arrival20_registration_delta()["sourceInverse"]:
        path = root / change["path"]
        raw = rich45_historical_source_raw(path, binding_compile2_historical_source_raw(path, full29_sdk_header_historical_source_raw(path, path.read_bytes())))
        assert full29_arrival20_historical_source_raw(path, raw) == change["beforeRaw"].encode()
        for wrong in (raw + b"\n", change["beforeRaw"].encode()):
            with pytest.raises(AssertionError):
                full29_arrival20_historical_source_raw(path, wrong)


def test_full29_arrival20_matrix_and_fixture_inverse_refuse_unknown_actual_bytes():
    delta = full29_arrival20_registration_delta()
    for change, restore in ((delta["matrixDelta"], restore_before_full29_arrival20_matrix_raw), (delta["fixtureDelta"], lambda raw: restore_before_full29_arrival20_fixture_raw(raw, "session.saved-chat-read.v1"))):
        for wrong in (change["beforeRaw"].encode(), change["beforeRaw"].encode() + b"\n"):
            with pytest.raises(AssertionError):
                restore(wrong)


def test_full29_arrival20_exact_inventory_scanners_sources_and_classifications_are_pinned():
    delta = full29_arrival20_registration_delta()
    root = Rich45HistoricalPath(Path(__file__).resolve().parents[2])
    for row in delta["exactApiInventorySources"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["sha256"]
    matrix = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    for language in ("rust", "npm", "python"):
        classified = [api for family in matrix["capabilities"] for api in family["languages"][language]["api"]]
        assert len(classified) == len(set(classified))
        assert set(classified) == set(delta["exactApiInventory"][language])
    assert {language: len(symbols) for language, symbols in delta["exactApiInventory"].items()} == {"rust": 1938, "npm": 1541, "python": 1166}


class Full29Arrival20HistoricalSourcePath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return Full29Arrival20HistoricalSourcePath(self.path / child)

    def read_bytes(self):
        return full29_arrival20_historical_source_raw(self.path, essential_currentdev_historical_bytes(self.path))


def full29_arrival20_historical_sdk_source_root(root):
    return Full29Arrival20HistoricalSourcePath(root)


def test_full29_arrival20_schema_delta_retains_every_other_root_and_definition():
    delta = full29_arrival20_registration_delta()["schemaKnownDelta"]
    root = Rich45HistoricalPath(Path(__file__).resolve().parents[2])
    raw = (root / delta["path"]).read_bytes()
    assert sdk.sha(raw) == delta["afterSha256"]
    old = json.loads(delta["beforeRaw"])
    current = json.loads(raw)
    assert sdk.sha(delta["beforeRaw"].encode()) == delta["beforeSha256"]
    assert {k: v for k, v in current.items() if k != "$defs"} == {k: v for k, v in old.items() if k != "$defs"}
    assert set(current["$defs"]) - set(old["$defs"]) == {"fullRead"}
    assert current["$defs"]["messageId"] == {"type": "string", "minLength": 1}
    for name, definition in old["$defs"].items():
        if name != "messageId":
            assert current["$defs"][name] == definition
    assert sdk.sha((root / delta["maintainedGrammarSource"]).read_bytes()) == delta["maintainedGrammarSourceSha256"]
    assert delta["frozenSourceReadsetSha256"] and delta["schemaKnownPatchSha256"]


def full29_sdk_header_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-full29-sdk-header-delta.json", "78dae416b6a1d8d107d3081b4b6a492cccb7a07d6fcebd6e228ea1297bcb96dd")


def restore_before_full29_sdk_header_registration(trust):
    trust = binding_compile2_history(trust)
    delta = full29_sdk_header_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for change in delta["sourceInverse"]:
        assert prior["programs"][change["path"]] == change["afterSha256"]
        prior["programs"][change["path"]] = change["beforeSha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def full29_sdk_header_history(trust):
    trust = binding_compile2_history(trust)
    delta = full29_sdk_header_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_full29_sdk_header_registration(trust)
    return trust


def full29_sdk_header_historical_source_raw(path, raw):
    root = Path(__file__).resolve().parents[2]
    for change in full29_sdk_header_registration_delta()["sourceInverse"]:
        if path == root / change["path"] and sdk.sha(raw) == change["afterSha256"]:
            prior = change["beforeRaw"].encode()
            assert sdk.sha(prior) == change["beforeSha256"]
            return prior
    return raw


def test_full29_sdk_header_registration_changes_only_one_existing_source_pin():
    delta = full29_sdk_header_registration_delta()
    current = binding_compile2_history(sdk.load_trust())
    old = restore_before_full29_sdk_header_registration(current)
    assert {k: len(current[k]) for k in delta["counts"]} == delta["counts"] == {"programs": 379, "contracts": 93, "plan": 93, "gaps": 180}
    assert current["contracts"] == old["contracts"] == delta["oldContracts"]
    assert current["plan"] == old["plan"] == delta["oldPlans"]
    assert current["gaps"] == old["gaps"] == delta["oldGaps"]
    assert {k for k in current["programs"] if current["programs"][k] != old["programs"][k]} == {row["path"] for row in delta["sourceInverse"]}
    assert len(delta["sourceInverse"]) == 1
    assert delta["releaseEligible"] is False and delta["actualRuntimeExecutions"] == 0


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_full29_sdk_header_exact_inverse_refuses_unknown_or_scope_drift(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_full29_sdk_header_registration(wrong)
    assert full29_sdk_header_history(wrong) == wrong


def test_full29_sdk_header_source_changes_only_validated_surface_metadata():
    root = Path(__file__).resolve().parents[2]
    for change in full29_sdk_header_registration_delta()["sourceInverse"]:
        raw = (root / change["path"]).read_bytes()
        prior = change["beforeRaw"].encode()
        assert sdk.sha(raw) == change["afterSha256"]
        assert prior.count(("surface=" + change["beforeLabel"]).encode()) == 1
        assert raw == prior.replace(("surface=" + change["beforeLabel"]).encode(), b"surface=sdks.pip", 1)
        assert full29_sdk_header_historical_source_raw(root / change["path"], raw) == prior
        assert full29_sdk_header_historical_source_raw(root / change["path"], raw + b"\n") == raw + b"\n"
        assert full29_sdk_header_historical_source_raw(root / "unknown", raw) == raw


def binding_compile2_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-binding-compile2-delta.json", "c857aa26c18b5259c71c8c864274472367cfdf42dee98c652cecf6fa8252199c")


def restore_before_binding_compile2_registration(trust):
    trust = rich45_history(trust)
    delta = binding_compile2_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for change in delta["sourceInverse"]:
        assert prior["programs"][change["path"]] == change["afterSha256"]
        prior["programs"][change["path"]] = change["beforeSha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def binding_compile2_history(trust):
    trust = rich45_history(trust)
    delta = binding_compile2_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_binding_compile2_registration(trust)
    return trust


def binding_compile2_historical_source_raw(path, raw):
    root = Path(__file__).resolve().parents[2]
    for change in binding_compile2_registration_delta()["sourceInverse"]:
        if path == root / change["path"] and sdk.sha(raw) == change["afterSha256"]:
            prior = change["beforeRaw"].encode()
            assert sdk.sha(prior) == change["beforeSha256"]
            return prior
    return raw


def test_binding_compile2_registration_updates_only_two_existing_test_pins():
    delta = binding_compile2_registration_delta()
    live = rich45_history(sdk.load_trust())
    prior = restore_before_binding_compile2_registration(live)
    assert {k: len(live[k]) for k in delta["counts"]} == delta["counts"] == {"programs": 379, "contracts": 93, "plan": 93, "gaps": 180}
    assert live["contracts"] == prior["contracts"] == delta["oldContracts"]
    assert live["plan"] == prior["plan"] == delta["oldPlans"]
    assert live["gaps"] == prior["gaps"] == delta["oldGaps"]
    assert {k: v for k, v in live.items() if k != "programs"} == {k: v for k, v in prior.items() if k != "programs"}
    assert set(live["programs"]) == set(prior["programs"])
    assert {path for path in live["programs"] if live["programs"][path] != prior["programs"][path]} == {row["path"] for row in delta["sourceInverse"]}
    assert len(delta["sourceInverse"]) == 2
    assert all(row["path"].startswith("packages/openmates-session-bindings/src/") and row["path"].endswith("tests.rs") for row in delta["sourceInverse"])
    assert delta["releaseEligible"] is False
    assert delta["actualNewCargoOrRuntimeExecutions"] == delta["newPublicApis"] == 0
    assert delta["frozenSourceManifestSha256"] == "3dd00cb1c3c01168e10f3154a55cecb22da151680489e00390ad9aaa69dc57e3"
    assert delta["frozenSourcePatchSha256"] == "bf86ca9d8756a2ab6e6cba90284f664bf5679440eaa597b1afdfa431cd0b085d"


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_binding_compile2_inverse_refuses_unknown_authority_and_scope_drift(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_binding_compile2_registration(wrong)
    assert binding_compile2_history(wrong) == wrong


def test_binding_compile2_exact_source_views_do_not_relabel_unknown_or_wrong_path():
    root = EssentialCurrentdevHistoricalPath(Path(__file__).resolve().parents[2])
    for change in binding_compile2_registration_delta()["sourceInverse"]:
        path = root / change["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == change["afterSha256"]
        assert binding_compile2_historical_source_raw(path, raw) == change["beforeRaw"].encode()
        assert binding_compile2_historical_source_raw(path, raw + b"\n") == raw + b"\n"
        assert binding_compile2_historical_source_raw(root / "unknown.rs", raw) == raw


@pytest.mark.parametrize("index", [0, 1])
def test_binding_compile2_unchanged_runtime_loader_rejects_wrong_and_stale_source(tmp_path, index):
    change = binding_compile2_registration_delta()["sourceInverse"][index]
    root = EssentialCurrentdevHistoricalPath(Path(__file__).resolve().parents[2])
    path = tmp_path / change["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (root / change["path"]).read_bytes()
    trust = {"programs": {change["path"]: change["afterSha256"]}, "contracts": {}}
    path.write_bytes(raw)
    sdk.verify_programs(tmp_path, trust)
    for wrong in (raw + b"\n", change["beforeRaw"].encode()):
        path.write_bytes(wrong)
        with pytest.raises(sdk.Refused, match="reviewed_program_changed"):
            sdk.verify_programs(tmp_path, trust)


def rich45_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-rich45-delta.json", "f5c103597daca63aef57e3463972c676fb3eeeeff9b51543e9f37ddd7aa0b620")


def restore_before_rich45_registration(trust):
    trust = browser41_history(trust)
    delta = rich45_registration_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for bucket, key in (("plan", "planDeltas"), ("gaps", "gapDeltas")):
        for change in delta[key]:
            assert prior[bucket][change["index"]] == change["after"]
            prior[bucket][change["index"]] = copy.deepcopy(change["before"])
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def rich45_history(trust):
    trust = browser41_history(trust)
    delta = rich45_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_rich45_registration(trust)
    return trust


def rich45_historical_source_raw(path, raw):
    raw = browser41_historical_source_raw(path, raw)
    root = Path(__file__).resolve().parents[2]
    for change in rich45_registration_delta()["sourceInverse"]:
        if path == root / change["path"] and sdk.sha(raw) == change["afterSha256"]:
            prior = change["beforeRaw"].encode()
            assert sdk.sha(prior) == change["beforeSha256"]
            return prior
    return raw


def restore_before_rich45_matrix_raw(raw):
    raw = browser41_matrix_history(raw)
    change = rich45_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == change["afterSha256"]
    prior = change["beforeRaw"].encode()
    assert sdk.sha(prior) == change["beforeSha256"]
    return prior


def rich45_matrix_history(raw):
    raw = browser41_matrix_history(raw)
    if sdk.sha(raw) == rich45_registration_delta()["matrixDelta"]["afterSha256"]:
        return restore_before_rich45_matrix_raw(raw)
    return raw


def restore_before_rich45_fixture_raw(raw):
    change = rich45_registration_delta()["fixtureDelta"]
    assert sdk.sha(raw) == change["afterSha256"]
    current = json.loads(raw)["capabilities"][change["capability"]]["vectors"]
    assert current == change["original74"] + change["appended29"]
    prior = change["beforeRaw"].encode()
    assert sdk.sha(prior) == change["beforeSha256"]
    return prior


def rich45_fixture_history(raw, capability):
    change = rich45_registration_delta()["fixtureDelta"]
    if capability == change["capability"] and sdk.sha(raw) == change["afterSha256"]:
        return restore_before_rich45_fixture_raw(raw)
    return raw


class Rich45HistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return Rich45HistoricalPath(self.path / child)

    def read_bytes(self):
        raw = essential_currentdev_historical_bytes(self.path)
        if self.path == Path(__file__).resolve().parents[2] / "config/sdk-capabilities.json":
            return rich45_matrix_history(raw)
        return rich45_historical_source_raw(self.path, raw)


def test_rich45_exact_registration_inverse_preserves93_plans180_gap_identities_and_compiler2():
    delta = rich45_registration_delta()
    current = browser41_history(sdk.load_trust())
    prior = restore_before_rich45_registration(current)
    assert delta["beforeSha256"] == "f85685a2b2fab7db3a6c0373e1a87b641dbfd70f687b6497668c67d6d19f37d6"
    assert {k: len(prior[k]) for k in delta["beforeCounts"]} == {"programs": 379, "contracts": 93, "plan": 93, "gaps": 180}
    assert {k: len(current[k]) for k in delta["afterCounts"]} == delta["afterCounts"]
    assert prior["plan"] == delta["originalPlans"] and prior["gaps"] == delta["originalGaps"]
    assert len(current["plan"]) == 93 and len(current["gaps"]) == 180
    assert len(delta["planDeltas"]) == len(delta["gapDeltas"]) == 3
    changed = {row["index"] for row in delta["planDeltas"]}
    for i, (old, new) in enumerate(zip(prior["plan"], current["plan"])):
        if i not in changed:
            assert old == new
        else:
            assert new["capability"] == "session.saved-chat-read.v1"
            assert {k: v for k, v in old.items() if k not in ("fixtureSha256", "vectors")} == {k: v for k, v in new.items() if k not in ("fixtureSha256", "vectors")}
            assert len(old["vectors"]) == 74 and len(new["vectors"]) == 103
            assert set(old["vectors"]) < set(new["vectors"])
    for change in delta["gapDeltas"]:
        assert change["before"].startswith("session.saved-chat-read.v1 [")
        assert change["after"] == change["before"] + "; " + delta["matrixDelta"]["obligation"]
    root = EssentialCurrentdevHistoricalPath(Path(__file__).resolve().parents[2])
    for row in delta["protectedCompiler2"]:
        assert current["programs"][row["path"]] == prior["programs"][row["path"]] == row["sha256"]
        assert sdk.sha((root / row["path"]).read_bytes()) == row["sha256"]
        assert row["path"] not in {r["path"] for r in delta["exactSourceMap"]}
    assert delta["newCapabilityFamilies"] == delta["newExecutionPlans"] == delta["actualConformanceExecutions"] == 0
    assert delta["releaseEligible"] is False and delta["browserSchedulerCancelFutureExcluded"] is True


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_rich45_strict_inverse_refuses_unknown_authority_and_scope(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_rich45_registration(wrong)
    assert rich45_history(wrong) == wrong


def test_rich45_source_map_and_unknown_bytes_never_gain_historical_authority():
    delta = rich45_registration_delta()
    root = Browser41HistoricalPath(Path(__file__).resolve().parents[2])
    assert len(delta["exactSourceMap"]) == len({r["path"] for r in delta["exactSourceMap"]}) == 45
    assert delta["sourcePacketManifestSha256"] == "ec26ba4fb61dfed59a4fcdeafa1b3bf90e54569dcba3ef44f3395b65b241532a"
    assert delta["sourceMapSha256"] == "da9e5b2e207840feb4a51957354d4220407de4dfa6162eef72a3a44797cc7be7"
    for row in delta["exactSourceMap"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["after_sha256"]
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert rich45_historical_source_raw(path, raw) == row["beforeRaw"].encode()
        assert rich45_historical_source_raw(path, raw + b"\n") == raw + b"\n"
        assert rich45_historical_source_raw(root / "unknown", raw) == raw


def test_rich45_actual_strict_loader_rejects_all_mutated_and_stale_pins(tmp_path):
    root = Browser41HistoricalPath(Path(__file__).resolve().parents[2])
    for bucket in ("programs", "contracts"):
        for name, change in rich45_registration_delta()["pinDeltas"][bucket].items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (root / name).read_bytes()
            trust = {"programs": {}, "contracts": {}}
            trust[bucket][name] = change["after"]
            path.write_bytes(raw)
            sdk.verify_programs(tmp_path, trust)
            path.write_bytes(raw + b"\n")
            with pytest.raises(sdk.Refused, match="reviewed_.*_changed"):
                sdk.verify_programs(tmp_path, trust)
            if change["before"] is not None:
                path.write_bytes(raw)
                trust[bucket][name] = change["before"]
                with pytest.raises(sdk.Refused, match="reviewed_.*_changed"):
                    sdk.verify_programs(tmp_path, trust)


def test_rich45_classifies_all3_exact_api_deltas_without_status_or_legacy_ownership_changes():
    delta = rich45_registration_delta()
    root = Browser41HistoricalPath(Path(__file__).resolve().parents[2])
    current = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    old = json.loads(delta["matrixDelta"]["beforeRaw"])
    for a, b in zip(old["capabilities"], current["capabilities"]):
        assert a["id"] == b["id"]
        if a["id"] != "session.saved-chat-read.v1":
            assert a == b
            continue
        assert b["description"] == a["description"] + delta["matrixDelta"]["descriptionSuffix"]
        for language in ("rust", "npm", "python"):
            before = a["languages"][language]
            after = b["languages"][language]
            assert after["status"] == before["status"] == "partial"
            assert after["conformance"] == before["conformance"] is True
            assert after["evidence"] == before["evidence"]
            assert after["api"] == sorted(before["api"] + delta["matrixDelta"]["apiAdded"][language])
            assert after["gaps"] == before["gaps"] + [delta["matrixDelta"]["obligation"]]
    for language in ("rust", "npm", "python"):
        classified = [api for family in current["capabilities"] for api in family["languages"][language]["api"]]
        assert len(classified) == len(set(classified))
        assert set(classified) == set(delta["exactApiInventory"][language])
    assert {language: len(names) for language, names in delta["matrixDelta"]["apiAdded"].items()} == {"rust": 66, "npm": 1, "python": 8}
    session = next(row for row in current["capabilities"] if row["id"] == "sdk.session-client")
    assert "SessionClient.openChat" in session["languages"]["npm"]["api"]
    assert "SessionClient.open_chat" in session["languages"]["python"]["api"]


def test_rich45_shared103_preserves_all74_and98_original_objects_and_exact29_inputs():
    delta = rich45_registration_delta()
    change = delta["fixtureDelta"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / change["path"]).read_bytes()
    vectors = json.loads(raw)["capabilities"][change["capability"]]["vectors"]
    assert len(vectors) == len({v["id"] for v in vectors}) == 103
    assert vectors[:74] == change["original74"]
    assert vectors[:98] == change["private98Vectors"]
    assert vectors[74:] == change["appended29"]
    core = json.loads((root / "packages/openmates-rust/tests/fixtures/chat-details-read.json").read_bytes())
    assert core["vectors"] == change["appended29"]
    assert restore_before_rich45_fixture_raw(raw).decode() == change["beforeRaw"]
    for wrong in (raw + b"\n", change["beforeRaw"].encode()):
        with pytest.raises(AssertionError):
            restore_before_rich45_fixture_raw(wrong)
    for path in ("frontend/packages/openmates-tui-native/tests/fixtures/chats-show-json.json", "packages/openmates-session-bindings/tests/fixtures/chat-details-read.json"):
        value = (root / path).read_bytes()
        assert sdk.sha(value) == delta["CLI6Sha256"]
        assert len(json.loads(value)["vectors"]) == 6
    assert sdk.sha((root / "frontend/packages/openmates-tui-native/tests/fixtures/chats-show-json.schema.json").read_bytes()) == delta["CLI6SchemaSha256"]


def test_rich45_schema_only_adds_two_named_definitions_and_matrix_strict_inverse():
    delta = rich45_registration_delta()
    root = Path(__file__).resolve().parents[2]
    change = delta["schemaDelta"]
    raw = (root / change["path"]).read_bytes()
    assert sdk.sha(raw) == change["afterSha256"]
    a = json.loads(change["beforeRaw"])
    b = json.loads(raw)
    assert {k: v for k, v in a.items() if k != "$defs"} == {k: v for k, v in b.items() if k != "$defs"}
    assert set(b["$defs"]) - set(a["$defs"]) == set(change["addedDefinitions"]) == {"chatDetailsOptions", "chatDetailsRead"}
    assert all(b["$defs"][k] == v for k, v in a["$defs"].items())
    matrix_raw = (root / "config/sdk-capabilities.json").read_bytes()
    assert restore_before_rich45_matrix_raw(matrix_raw).decode() == delta["matrixDelta"]["beforeRaw"]
    with pytest.raises(AssertionError):
        restore_before_rich45_matrix_raw(matrix_raw + b"\n")


def browser41_registration_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-browser41-rich768-delta.json", "daceb492365176ce6d6141f81ded864e3f3128cec06653a0bae4e02e795381b4")


def restore_before_browser41_registration(trust):
    trust = cli_json_header_history(trust)
    delta = browser41_registration_delta()
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


def browser41_history(trust):
    trust = cli_json_header_history(trust)
    delta = browser41_registration_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]:
        return restore_before_browser41_registration(trust)
    return trust


def browser41_historical_source_raw(path, raw):
    raw = direct11_source_history(path, raw)
    raw = cli_json_header_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    for change in browser41_registration_delta()["sourceInverse"]:
        if path == root / change["path"] and sdk.sha(raw) == change["afterSha256"]:
            prior = change["beforeRaw"].encode()
            assert sdk.sha(prior) == change["beforeSha256"]
            return prior
    return raw


def restore_before_browser41_matrix_raw(raw):
    raw = direct11_matrix_history(raw)
    change = browser41_registration_delta()["matrixDelta"]
    assert sdk.sha(raw) == change["afterSha256"]
    prior = change["beforeRaw"].encode()
    assert sdk.sha(prior) == change["beforeSha256"]
    return prior


def browser41_matrix_history(raw):
    raw = direct11_matrix_history(raw)
    if sdk.sha(raw) == browser41_registration_delta()["matrixDelta"]["afterSha256"]:
        return restore_before_browser41_matrix_raw(raw)
    return raw


class Browser41HistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return Browser41HistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def read_bytes(self):
        raw = direct11_source_history(self.path, essential_currentdev_historical_bytes(self.path))
        root = Path(__file__).resolve().parents[2]
        if self.path == root / "config/sdk-capabilities.json":
            return browser41_matrix_history(raw)
        cookie = browser41_registration_delta()["cookieDelta"]
        if self.path == root / cookie["path"] and sdk.sha(raw) == cookie["afterSha256"]:
            prior = cookie["beforeRaw"].encode()
            assert sdk.sha(prior) == cookie["beforeSha256"]
            return prior
        return browser41_historical_source_raw(self.path, raw)


def test_browser41_exact_inverse_keeps93_plans180_gap_identities_and_partial_release():
    delta = browser41_registration_delta()
    current = direct11_history(sdk.load_trust())
    prior = restore_before_browser41_registration(current)
    assert delta["beforeSha256"] == "76895b01df692f5fa82f0a40c9141f48d4da964e780b8e31c32e728100ea3915"
    assert {k: len(prior[k]) for k in delta["beforeCounts"]} == {"programs": 394, "contracts": 97, "plan": 93, "gaps": 180}
    assert {k: len(current[k]) for k in delta["afterCounts"]} == delta["afterCounts"]
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert prior["gaps"] == delta["originalGaps"]
    assert len(current["gaps"]) == len(prior["gaps"]) == 180
    assert len(delta["gapDeltas"]) == 3
    for change in delta["gapDeltas"]:
        assert change["before"].startswith("sdk.session-client [")
        assert change["after"] == change["before"] + "; " + delta["matrixDelta"]["obligation"]
    assert {k: v for k, v in current.items() if k not in ("programs", "contracts", "gaps")} == {k: v for k, v in prior.items() if k not in ("programs", "contracts", "gaps")}
    assert delta["activated"] is delta["releaseEligible"] is False
    assert delta["newExecutionPlans"] == delta["newCapabilityFamilies"] == delta["actualRuntimeExecutions"] == 0
    assert delta["futureFacadeGenuineTestsSchedulerCancelVisualExcluded"] is True


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_browser41_strict_inverse_refuses_unknown_scope_and_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_browser41_registration(wrong)
    assert browser41_history(wrong) == wrong


def test_browser41_source_map_unknown_bytes_and_paths_cannot_gain_history():
    root = Direct11HistoricalPath(Path(__file__).resolve().parents[2])
    delta = browser41_registration_delta()
    assert len(delta["sourceMap"]) == len({r["path"] for r in delta["sourceMap"]}) == 41
    for row in delta["sourceMap"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["afterSha256"]
    for change in delta["sourceInverse"]:
        path = root / change["path"]
        raw = path.read_bytes()
        assert browser41_historical_source_raw(path, raw) == change["beforeRaw"].encode()
        assert browser41_historical_source_raw(path, raw + b"\n") == raw + b"\n"
        assert browser41_historical_source_raw(root / "unknown", raw) == raw


def test_browser41_unchanged_loader_rejects_every_mutated_or_stale_pin(tmp_path):
    root = Direct11HistoricalPath(Path(__file__).resolve().parents[2])
    for bucket in ("programs", "contracts"):
        for name, change in browser41_registration_delta()["pinDeltas"][bucket].items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (root / name).read_bytes()
            trust = {"programs": {}, "contracts": {}}
            trust[bucket][name] = change["after"]
            path.write_bytes(raw)
            sdk.verify_programs(tmp_path, trust)
            path.write_bytes(raw + b"\n")
            with pytest.raises(sdk.Refused, match="reviewed_.*_changed"):
                sdk.verify_programs(tmp_path, trust)
            if change["before"] is not None:
                trust[bucket][name] = change["before"]
                path.write_bytes(raw)
                with pytest.raises(sdk.Refused, match="reviewed_.*_changed"):
                    sdk.verify_programs(tmp_path, trust)


def test_browser41_actual_api_inputs_and_classification_preserve_rich_and_foreign_apis(monkeypatch):
    cli_json_header_historical_reads(monkeypatch)
    delta = browser41_registration_delta()
    root = Direct11HistoricalPath(Path(__file__).resolve().parents[2])
    for row in delta["exactApiInventorySources"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["sha256"]
    current = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    prior = json.loads(delta["matrixDelta"]["beforeRaw"])
    for old, new in zip(prior["capabilities"], current["capabilities"]):
        assert old["id"] == new["id"]
        if old["id"] != "sdk.session-client":
            assert old == new
            continue
        assert new["description"] == old["description"] + delta["matrixDelta"]["descriptionSuffix"]
        for language in ("rust", "npm", "python"):
            a = old["languages"][language]
            b = new["languages"][language]
            assert b["status"] == a["status"] == "partial"
            assert b["conformance"] == a["conformance"] is False
            assert b["evidence"] == a["evidence"]
            assert b["api"] == sorted(a["api"] + delta["matrixDelta"]["apiAdded"][language])
            assert b["gaps"] == a["gaps"] + [delta["matrixDelta"]["obligation"]]
    for language in ("rust", "npm", "python"):
        classified = [api for family in current["capabilities"] for api in family["languages"][language]["api"]]
        assert len(classified) == len(set(classified))
        assert set(classified) == set(delta["exactApiInventory"][language])
    assert {language: len(names) for language, names in delta["matrixDelta"]["apiAdded"].items()} == {"rust": 10, "npm": 0, "python": 0}
    matrix_raw = (root / "config/sdk-capabilities.json").read_bytes()
    assert restore_before_browser41_matrix_raw(matrix_raw).decode() == delta["matrixDelta"]["beforeRaw"]
    with pytest.raises(AssertionError):
        restore_before_browser41_matrix_raw(matrix_raw + b"\n")


def test_browser41_disjoint_compact_composition_keeps_rich_context_compiler2_and103_vectors(monkeypatch):
    cli_json_header_historical_reads(monkeypatch)
    delta = browser41_registration_delta()
    proof = delta["compositionProof"]
    assert proof["browserCompactOverlap"] == []
    assert proof["unionFiles"] == 82 and proof["ownedFiles"] == 41
    assert {tuple(row["order"]) for row in proof["bothOrders"]} == {("browser", "compact"), ("compact", "browser")}
    assert all(row["all82AfterimagesExact"] and row["inverseOrderRestoresActualRich768"] for row in proof["bothOrders"])
    prior = delta["priorBrowserRichProof"]
    assert prior["overlap"] == ["packages/openmates-rust/src/client.rs"]
    assert prior["wholeFileReplacementFromStaleBrowserSupplier"] is False
    assert all(row["all81PostimagesExact"] and row["bothExactInversesRestoreCommon"] for row in prior["bothOrders"])
    root = Direct11HistoricalPath(Path(__file__).resolve().parents[2])
    assert len(delta["richPreservation"]) == 45
    assert sum(row["exactUnchanged"] for row in delta["richPreservation"]) == 41
    expected = {"packages/openmates-rust/src/client.rs", "packages/openmates-rust/src/client/chat_details.rs", "packages/openmates-rust/src/client/chat_details_json.rs", "packages/openmates-rust/src/client/chat_details_tests.rs"}
    assert {row["path"] for row in delta["richPreservation"] if not row["exactUnchanged"]} == expected
    for row in delta["richPreservation"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["newCompositeSha256"]
    assert b"pub mod chat_details;\n" in (root / "packages/openmates-rust/src/client.rs").read_bytes()
    current = direct11_history(sdk.load_trust())
    for row in delta["protectedCompiler2"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == current["programs"][row["path"]] == row["sha256"]
        assert row["path"] not in {source["path"] for source in delta["sourceMap"]}
    fixture = root / "tests/sdk-conformance/fixtures/session-saved-chat-read.json"
    assert sdk.sha(fixture.read_bytes()) == delta["rich103FixtureSha256"] == "2d1b181b90f7ceb2c00394381395c4a3881b9b6ad660877b02a2f52cdd82cea6"
    assert len(json.loads(fixture.read_bytes())["capabilities"]["session.saved-chat-read.v1"]["vectors"]) == 103
    assert all(len(row["vectors"]) == 103 for row in current["plan"] if row["capability"] == "session.saved-chat-read.v1")


def test_browser41_policy_fixture_mirrors_do_not_create_executable_plan_authority():
    root = Direct11HistoricalPath(Path(__file__).resolve().parents[2])
    a = (root / "packages/openmates-rust/tests/fixtures/browser-assistant-candidate-policy.json").read_bytes()
    b = (root / "tests/sdk-conformance/fixtures/browser-assistant-candidate-policy.json").read_bytes()
    assert a == b
    assert sdk.sha(a) == "c088f195b34ba556c49427ab105ed7b4eece95ea9c21235d740a4fc60c170783"
    current = direct11_history(sdk.load_trust())
    assert current["plan"] == browser41_registration_delta()["originalPlans"]
    assert "browser-assistant-candidate-policy.json" not in json.dumps(current["plan"])



def test_browser41_compact14_is_internal_with_no_api_number_lock_or_plan_promotion():
    delta = browser41_registration_delta()
    assert delta["compactManifestSha256"] == "67e8dda2f2e539fd75ba683567fffc761dbdc6445ac8e8374a6629a010030f5d"
    proof = delta["compactSourceProof"]
    assert proof["proposal_sha256"] == "8c0144810adf9f2fbb2277615af619bfe299f5e158373188925ecf1bc0c7e1e1"
    assert proof["public_API_number_admission_metadata_Cargo_changes"] is False
    assert proof["owned_paths"] == 4 and proof["shared_vectors_unchanged"] == 103
    root = Direct11HistoricalPath(Path(__file__).resolve().parents[2])
    raw = (root / "packages/openmates-rust/tests/fixtures/chat-details-string-escaping.json").read_bytes()
    assert sdk.sha(raw) == delta["compactInternal14Sha256"]
    assert len(json.loads(raw)["vectors"]) == 14
    assert len(delta["fourLocks"]) == 4
    for row in delta["fourLocks"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["sha256"]
        assert row["path"] not in {source["path"] for source in delta["sourceMap"]}
    current = direct11_history(sdk.load_trust())
    assert current["plan"] == delta["originalPlans"]
    assert "chat-details-string-escaping.json" not in json.dumps(current["plan"])


# Metadata-only successor: historical assertions still evaluate exact prior source.
def cli_json_header_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-cli-json-header-delta.json", "ad0ed05f84103751776fdf6b85874ede39d7d67a94e057292f6886c86bb439cb")


def restore_before_cli_json_header(trust):
    trust = direct11_history(trust)
    delta = cli_json_header_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterTrustSha256"]
    prior = copy.deepcopy(trust)
    assert prior["programs"][delta["path"]] == delta["afterSourceSha256"]
    prior["programs"][delta["path"]] = delta["beforeSourceSha256"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeTrustSha256"]
    return prior


def cli_json_header_history(trust):
    trust = direct11_history(trust)
    delta = cli_json_header_delta()
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterTrustSha256"]:
        return restore_before_cli_json_header(trust)
    return trust


def cli_json_header_source_history(path, raw):
    raw = direct11_source_history(path, raw)
    delta = cli_json_header_delta()
    if path == Path(__file__).resolve().parents[2] / delta["path"] and sdk.sha(raw) == delta["afterSourceSha256"]:
        prior = delta["beforeSourceRaw"].encode()
        assert sdk.sha(prior) == delta["beforeSourceSha256"]
        return prior
    return raw


def test_cli_json_header_exact_inverse_preserves_every_other_authority():
    delta = cli_json_header_delta()
    current = direct11_history(sdk.load_trust())
    prior = restore_before_cli_json_header(current)
    assert {k: len(current[k]) for k in delta["counts"]} == delta["counts"]
    assert {k: len(prior[k]) for k in delta["counts"]} == delta["counts"]
    assert {k: v for k, v in current.items() if k != "programs"} == {k: v for k, v in prior.items() if k != "programs"}
    assert {k: v for k, v in current["programs"].items() if k != delta["path"]} == {k: v for k, v in prior["programs"].items() if k != delta["path"]}
    assert delta["publicApiChanges"] == delta["actualRuntimeExecutions"] == 0
    assert delta["releaseEligible"] is False


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_cli_json_header_unknown_authority_cannot_be_projected(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_cli_json_header(wrong)
    assert cli_json_header_history(wrong) == wrong


def test_cli_json_header_preserves_all_source_statements_and_assertions():
    import ast
    delta = cli_json_header_delta()
    path = Path(__file__).resolve().parents[2] / delta["path"]
    raw = path.read_bytes()
    old = cli_json_header_source_history(path, raw)
    assert old.decode() == delta["beforeSourceRaw"]
    assert ast.dump(ast.parse(raw), include_attributes=False) == ast.dump(ast.parse(old), include_attributes=False)
    assert raw.count(b"# contract-test: supporting surface=cli assertions=cli.surface.semantic-parity") == delta["markers"] == 5
    assert cli_json_header_source_history(path, raw + b"\n") == raw + b"\n"
    assert cli_json_header_source_history(path.parent / "unknown.py", raw) == raw


def test_cli_json_header_actual_strict_loader_binds_new_annotation_bytes():
    root = Path(__file__).resolve().parents[2]
    delta = cli_json_header_delta()
    assert sdk.sha((root / delta["path"]).read_bytes()) == delta["afterSourceSha256"]
    sdk.verify_programs(root, sdk.load_trust())


def cli_json_header_historical_reads(monkeypatch):
    """Project only the exact approved comment successor for historical byte proofs."""
    delta = cli_json_header_delta()
    target = Path(__file__).resolve().parents[2] / delta["path"]
    original = Path.read_bytes
    prior = delta["beforeSourceRaw"].encode()
    assert sdk.sha(prior) == delta["beforeSourceSha256"]

    def historical_read(path):
        raw = original(path)
        if path == target and sdk.sha(raw) == delta["afterSourceSha256"]:
            return prior
        return raw

    monkeypatch.setattr(Path, "read_bytes", historical_read)


def test_cli_json_header_historical_reads_are_exact_and_scoped(monkeypatch, tmp_path):
    delta = cli_json_header_delta()
    root = Path(__file__).resolve().parents[2]
    target = root / delta["path"]
    current = target.read_bytes()
    unrelated = tmp_path / "unrelated.py"
    unrelated.write_bytes(current)
    cli_json_header_historical_reads(monkeypatch)
    assert target.read_bytes() == delta["beforeSourceRaw"].encode()
    assert unrelated.read_bytes() == current
    with monkeypatch.context() as inner:
        plain = Path.read_bytes
        inner.setattr(Path, "read_bytes", lambda path: current + b"\n" if path == target else plain(path))
        cli_json_header_historical_reads(inner)
        assert target.read_bytes() == current + b"\n"


def direct11_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-direct11-delta.json", "f281e38dd1a2eede63bfb22ae382094ab7daf19aac76797bd8a4db428bf47789")


def restore_before_direct11(trust):
    trust = security41_history(trust)
    delta = direct11_delta()
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


def direct11_history(trust):
    trust = security41_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == direct11_delta()["afterSha256"]:
        return restore_before_direct11(trust)
    return trust


def direct11_source_history(path, raw):
    raw = security41_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    for row in direct11_delta()["sourceInverse"]:
        if path == root / row["path"] and sdk.sha(raw) == row["afterSha256"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["beforeSha256"]
            return before
    return raw


def direct11_matrix_history(raw):
    raw = security41_matrix_history(raw)
    delta = direct11_delta()["matrixDelta"]
    if sdk.sha(raw) == delta["afterSha256"]:
        before = delta["beforeRaw"].encode()
        assert sdk.sha(before) == delta["beforeSha256"]
        return before
    return raw


class Direct11HistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return Direct11HistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def read_bytes(self):
        raw = essential_currentdev_historical_bytes(self.path)
        if self.path == Path(__file__).resolve().parents[2] / "config/sdk-capabilities.json":
            return direct11_matrix_history(raw)
        return direct11_source_history(self.path, raw)


def test_direct11_exact_inverse_retains_all93plans180gaps_and_prior_authority():
    delta = direct11_delta()
    current = security41_history(sdk.load_trust())
    prior = restore_before_direct11(current)
    assert delta["beforeSha256"] == "2b00ed8247066f76518171fd52fea54e3451ebdc3806128bfbcac49c885d32a4"
    assert {k: len(current[k]) for k in delta["afterCounts"]} == delta["afterCounts"]
    assert {k: len(prior[k]) for k in delta["beforeCounts"]} == delta["beforeCounts"]
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert prior["gaps"] == delta["originalGaps"]
    assert len(current["gaps"]) == 180 and len(delta["gapDeltas"]) == 1
    assert delta["gapDeltas"][0]["before"].startswith("sdk.apps [rust] partial:")
    assert delta["gapDeltas"][0]["after"].startswith(delta["gapDeltas"][0]["before"] + "; ")
    assert delta["newExecutionPlans"] == delta["actualRuntimeExecutions"] == 0
    assert delta["releaseEligible"] is delta["activated"] is False


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_direct11_strict_inverse_refuses_unknown_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_direct11(wrong)
    assert direct11_history(wrong) == wrong


def test_direct11_source_and_matrix_history_refuse_unknown_paths_and_bytes():
    root = Security41HistoricalPath(Path(__file__).resolve().parents[2])
    delta = direct11_delta()
    assert len(delta["sourceMap"]) == 11
    for row in delta["sourceMap"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["afterSha256"]
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert direct11_source_history(path, raw) == row["beforeRaw"].encode()
        assert direct11_source_history(path, raw + b"\n") == raw + b"\n"
        assert direct11_source_history(root / "unknown", raw) == raw
    matrix = (root / "config/sdk-capabilities.json").read_bytes()
    assert direct11_matrix_history(matrix).decode() == delta["matrixDelta"]["beforeRaw"]
    assert direct11_matrix_history(matrix + b"\n") == matrix + b"\n"


def test_direct11_actual_unchanged_loader_rejects_all_new_changed_and_stale_pins(tmp_path):
    root = Security41HistoricalPath(Path(__file__).resolve().parents[2])
    delta = direct11_delta()
    sdk.verify_programs(root, sdk.load_trust())
    for bucket in ("programs", "contracts"):
        for name, change in delta["pinDeltas"][bucket].items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (root / name).read_bytes()
            trust = {"programs": {}, "contracts": {}}
            trust[bucket][name] = change["after"]
            path.write_bytes(raw)
            sdk.verify_programs(tmp_path, trust)
            path.write_bytes(raw + b"\n")
            with pytest.raises(sdk.Refused, match="reviewed_.*_changed"):
                sdk.verify_programs(tmp_path, trust)
            if change["before"] is not None:
                path.write_bytes(raw)
                trust[bucket][name] = change["before"]
                with pytest.raises(sdk.Refused, match="reviewed_.*_changed"):
                    sdk.verify_programs(tmp_path, trust)


def test_direct11_only_sdk_apps_rust_shape_changes_and_all_languages_remain_partial():
    root = Security41HistoricalPath(Path(__file__).resolve().parents[2])
    delta = direct11_delta()
    current = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    prior = json.loads(delta["matrixDelta"]["beforeRaw"])
    for a, b in zip(prior["capabilities"], current["capabilities"]):
        assert a["id"] == b["id"]
        if a["id"] != "sdk.apps":
            assert a == b
            continue
        assert {k: v for k, v in a.items() if k != "languages"} == {k: v for k, v in b.items() if k != "languages"}
        for language in ("rust", "npm", "python"):
            old, new = a["languages"][language], b["languages"][language]
            assert old["status"] == new["status"] == "partial"
            assert old["conformance"] == new["conformance"] is False
            if language != "rust":
                assert old == new
                continue
            overlay = delta["matrixDelta"]["overlay"]
            assert new["api"] == sorted(old["api"] + overlay["append_api"])
            assert new["evidence"] == old["evidence"] + overlay["append_evidence"]
            assert new["gaps"] == old["gaps"] + overlay["append_gaps"]
    assert len(delta["matrixDelta"]["apiAdded"]["rust"]["added"]) == 6
    assert not any(v["removed"] for v in delta["matrixDelta"]["apiAdded"].values())
    assert delta["newAPICounts"] == {"rust": 2020, "npm": 1542, "python": 1174}


def test_direct11_internal_fixture_no_invented_three_sdk_runner_and_preserved_context():
    sdk = AppsCookieHistoricalSDK(globals()["sdk"])
    delta = direct11_delta()
    root = Security41HistoricalPath(Path(__file__).resolve().parents[2])
    path = "tests/sdk-conformance/fixtures/direct-skill-retention.json"
    assert sdk.sha((root / path).read_bytes()) == delta["newInternalFixtureSha256"]
    assert path not in json.dumps(sdk.load_trust()["plan"])
    assert all(row["capability"] != "sdk.apps" for row in sdk.load_trust()["plan"])
    assert len(delta["fourLocks"]) == 4
    for row in delta["fourLocks"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["sha256"]
    rich = root / "tests/sdk-conformance/fixtures/session-saved-chat-read.json"
    assert sdk.sha(rich.read_bytes()) == "2d1b181b90f7ceb2c00394381395c4a3881b9b6ad660877b02a2f52cdd82cea6"
    assert len(json.loads(rich.read_bytes())["capabilities"]["session.saved-chat-read.v1"]["vectors"]) == 103
    client = (root / "packages/openmates-rust/src/client.rs").read_bytes()
    assert b"pub use apps::DirectAppSkillAdmission;" in client
    assert b"pub mod chat_details;" in client
    assert b"pub use monitor::BrowserIncomingCachePublication;" in client


def security41_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-security41-delta.json", "3b4247f77720665088de41db3e3e426ccad0db6d1d500c0d1a06ed10747eb1bc")


def restore_before_security41(trust):
    trust = compiler_publication11_history(trust)
    delta = security41_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for bucket in ("programs", "contracts"):
        for path, change in delta["pinDeltas"][bucket].items():
            assert prior[bucket][path] == change["after"]
            if change["before"] is None:
                del prior[bucket][path]
            else:
                prior[bucket][path] = change["before"]
    for bucket, key in (("plan", "planDeltas"), ("gaps", "gapDeltas")):
        for row in delta[key]:
            assert prior[bucket][row["index"]] == row["after"]
            prior[bucket][row["index"]] = copy.deepcopy(row["before"])
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def security41_history(trust):
    trust = compiler_publication11_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == security41_delta()["afterSha256"]:
        return restore_before_security41(trust)
    return trust


def security41_source_history(path, raw):
    raw = compiler_publication11_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    for row in security41_delta()["sourceInverse"]:
        if path == root / row["path"] and sdk.sha(raw) == row["afterSha256"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["beforeSha256"]
            return before
    return raw


def security41_matrix_history(raw):
    raw = apps_cookie_matrix_history(raw)
    delta = security41_delta()["matrixDelta"]
    if sdk.sha(raw) == delta["afterSha256"]:
        before = delta["beforeRaw"].encode()
        assert sdk.sha(before) == delta["beforeSha256"]
        return before
    return raw


class Security41HistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return Security41HistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        raw = essential_currentdev_historical_bytes(self.path)
        if self.path == Path(__file__).resolve().parents[2] / "config/sdk-capabilities.json":
            return security41_matrix_history(raw)
        return security41_source_history(self.path, raw)


def test_security41_exact_inverse_preserves93_plan_and180_gap_identities():
    delta = security41_delta()
    current = compiler_publication11_history(sdk.load_trust())
    prior = restore_before_security41(current)
    assert delta["beforeSha256"] == "a2d53842be02e9c3a3a6dc16afddf11ce9db750751253cfb4b779fd5cbad4ea3"
    assert {k: len(current[k]) for k in delta["afterCounts"]} == delta["afterCounts"]
    assert {k: len(prior[k]) for k in delta["beforeCounts"]} == delta["beforeCounts"]
    assert prior["plan"] == delta["originalPlans"] and prior["gaps"] == delta["originalGaps"]
    assert len(current["plan"]) == 93 and len(current["gaps"]) == 180
    assert len(delta["planDeltas"]) == 3 and len(delta["gapDeltas"]) == 6
    for row in delta["planDeltas"]:
        a, b = row["before"], row["after"]
        assert a["capability"] == b["capability"] == "session.work-crud.v1"
        assert len(a["vectors"]) == 10 and len(b["vectors"]) == 23
        assert set(a["vectors"]) < set(b["vectors"])
        assert {k: v for k, v in a.items() if k not in ("fixtureSha256", "vectors")} == {k: v for k, v in b.items() if k not in ("fixtureSha256", "vectors")}
    for row in delta["gapDeltas"]:
        assert row["after"] == row["before"] + "; " + delta["matrixDelta"]["obligation"]
    assert delta["newExecutionPlans"] == delta["actualRuntimeExecutions"] == 0
    assert delta["releaseEligible"] is delta["activated"] is False


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_security41_inverse_refuses_unknown_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_security41(wrong)
    assert security41_history(wrong) == wrong


def test_security41_source_map_exact_scopes_and_private_dependencies_only():
    delta = security41_delta()
    root = CompilerPublication11HistoricalPath(Path(__file__).resolve().parents[2])
    assert len(delta["sourceMap"]) == 41
    for row in delta["sourceMap"]:
        assert sdk.sha((root / row["path"]).read_bytes()) == row["afterSha256"]
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert security41_source_history(path, raw) == row["beforeRaw"].encode()
        assert security41_source_history(path, raw + b"\n") == raw + b"\n"
        assert security41_source_history(root / "unknown", raw) == raw
    raw = (root / "config/sdk-capabilities.json").read_bytes()
    assert security41_matrix_history(raw).decode() == delta["matrixDelta"]["beforeRaw"]
    assert security41_matrix_history(raw + b"\n") == raw + b"\n"
    union = delta["dependencyUnion"]
    assert union["sourceUnion"] == 41 and union["sdk"] == 21 and union["scheduler"] == 16 and union["facade"] == union["decoder"] == 3
    assert len(union["facadeSchedulerOverlap"]) == 2 and union["facadeBeforeThenSchedulerFinalAfterimagesOnce"] is True
    assert delta["clientCommutation"]["bothOrdersExact"] is True
    assert delta["clientCommutation"]["wholeStaleClientReplacement"] is False


def test_security41_unchanged_strict_loader_rejects_all_new_changed_and_stale_pins(tmp_path):
    delta = security41_delta()
    root = CompilerPublication11HistoricalPath(Path(__file__).resolve().parents[2])
    sdk.verify_programs(root, sdk.load_trust())
    for bucket in ("programs", "contracts"):
        for name, change in delta["pinDeltas"][bucket].items():
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (root / name).read_bytes()
            trust = {"programs": {}, "contracts": {}}
            trust[bucket][name] = change["after"]
            path.write_bytes(raw)
            sdk.verify_programs(tmp_path, trust)
            path.write_bytes(raw + b"\n")
            with pytest.raises(sdk.Refused, match="reviewed_.*_changed"):
                sdk.verify_programs(tmp_path, trust)
            if change["before"] is not None:
                path.write_bytes(raw)
                trust[bucket][name] = change["before"]
                with pytest.raises(sdk.Refused, match="reviewed_.*_changed"):
                    sdk.verify_programs(tmp_path, trust)


def test_security41_truthful_three_language_api_classification_and_partial_states():
    delta = security41_delta()
    root = CompilerPublication11HistoricalPath(Path(__file__).resolve().parents[2])
    current = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    prior = json.loads(delta["matrixDelta"]["beforeRaw"])
    for a, b in zip(prior["capabilities"], current["capabilities"]):
        assert a["id"] == b["id"]
        if a["id"] not in ("sdk.session-client", "session.work-crud.v1"):
            assert a == b
            continue
        assert {k: v for k, v in a.items() if k != "languages"} == {k: v for k, v in b.items() if k != "languages"}
        for language in ("rust", "npm", "python"):
            old, new = a["languages"][language], b["languages"][language]
            assert old["status"] == new["status"] == "partial"
            assert old["conformance"] == new["conformance"]
            assert new["evidence"] == old["evidence"]
            assert new["gaps"] == old["gaps"] + [delta["matrixDelta"]["obligation"]]
            added = delta["matrixDelta"]["apiDelta"][language]["added"] if a["id"] == "sdk.session-client" else []
            assert new["api"] == sorted(old["api"] + added)
    api = delta["matrixDelta"]["apiDelta"]
    assert len(api["rust"]["added"]) == 39
    assert not any(v["removed"] for v in api.values())
    assert api["npm"]["added"] == api["python"]["added"] == []
    assert delta["newAPICounts"] == {"rust": 2059, "npm": 1542, "python": 1174}


def test_security41_work23_schema_enforced_with_exact_original10_and_savedread103():
    import importlib.util
    delta = security41_delta()
    root = CompilerPublication11HistoricalPath(Path(__file__).resolve().parents[2])
    name = "tests/sdk-conformance/fixtures/session-work.json"
    raw = (root / name).read_bytes()
    values = json.loads(raw)["capabilities"]["session.work-crud.v1"]["vectors"]
    assert values == delta["workFixture"]["vectors23"] and len(values) == 23
    assert values[:10] == delta["workFixture"]["original10"]
    spec = importlib.util.spec_from_file_location("security41_schema_gate", root / "scripts/check_sdk_conformance.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    assert gate.FIXTURE_SCHEMAS[name] == "tests/sdk-conformance/schemas/session-work.schema.json"
    assert gate.validate_fixture_document(name, json.loads(raw), root) is None
    bad = json.loads(raw)
    del bad["capabilities"]
    with pytest.raises(gate.jsonschema.ValidationError):
        gate.validate_fixture_document(name, bad, root)
    rich = root / "tests/sdk-conformance/fixtures/session-saved-chat-read.json"
    assert sdk.sha(rich.read_bytes()) == "2d1b181b90f7ceb2c00394381395c4a3881b9b6ad660877b02a2f52cdd82cea6"
    assert len(json.loads(rich.read_bytes())["capabilities"]["session.saved-chat-read.v1"]["vectors"]) == 103


# Exact reviewed compiler corrections: tests-only history, never runtime policy.
def compiler_publication11_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-compiler_publication11-delta.json", "8f6d4449c9c32551baf13d4a8261a1ad344a25645f43946986b24ee8692bbab5")


def restore_before_compiler_publication11(trust):
    trust = baseline_repair_history(trust)
    delta = compiler_publication11_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for path, change in delta["pinDeltas"].items():
        assert prior["programs"][path] == change["after"]
        if change["before"] is None:
            del prior["programs"][path]
        else:
            prior["programs"][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def compiler_publication11_history(trust):
    trust = baseline_repair_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == compiler_publication11_delta()["afterSha256"]:
        return restore_before_compiler_publication11(trust)
    return trust


def compiler_publication11_source_history(path, raw):
    raw = baseline_repair_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    for row in compiler_publication11_delta()["sourceInverse"]:
        if path == root / row["path"] and sdk.sha(raw) == row["afterSha256"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["beforeSha256"]
            return before
    return raw


class CompilerPublication11HistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return CompilerPublication11HistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        return compiler_publication11_source_history(self.path, essential_currentdev_historical_bytes(self.path))


def test_compiler_publication11_inverse_changes_only_eleven_reviewed_program_pins():
    delta = compiler_publication11_delta()
    current = baseline_repair_history(sdk.load_trust())
    prior = restore_before_compiler_publication11(current)
    assert delta["beforeSha256"] == "9dc0ea9fb3afc1d0a5843c6682d538508e272b5e568a9ac48c919344ddf13a92"
    assert {key: len(current[key]) for key in delta["counts"]} == {"programs": 439, "contracts": 102, "plan": 93, "gaps": 180}
    assert set(prior["programs"]) < set(current["programs"])
    assert set(current["programs"]) - set(prior["programs"]) == {row["path"] for row in delta["sourceMap"] if row["beforeSha256"] is None}
    assert {name for name in current["programs"] if current["programs"][name] != prior["programs"].get(name)} == set(delta["pinDeltas"])
    assert len(delta["pinDeltas"]) == len(delta["sourceMap"]) == 11
    assert {key: value for key, value in current.items() if key != "programs"} == {key: value for key, value in prior.items() if key != "programs"}
    assert current["plan"] == delta["originalPlans"] and current["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {"rust": 2059, "npm": 1542, "python": 1174}
    assert all(row == {"added": [], "removed": []} for row in delta["apiDelta"].values())
    assert delta["publicApiAdded"] == delta["newExecutionPlans"] == delta["newCapabilityFamilies"] == delta["actualRuntimeExecutions"] == 0
    assert delta["releaseEligible"] is delta["activated"] is False


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_compiler_publication11_inverse_refuses_unknown_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_compiler_publication11(wrong)
    assert compiler_publication11_history(wrong) == wrong


def test_compiler_publication11_source_history_is_exact_path_and_hash_only():
    delta = compiler_publication11_delta()
    root = BaselineRepairHistoricalPath(Path(__file__).resolve().parents[2])
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["afterSha256"]
        assert compiler_publication11_source_history(path, raw) == row["beforeRaw"].encode()
        assert compiler_publication11_source_history(path, raw + b"\n") == raw + b"\n"
        assert compiler_publication11_source_history(root / "unknown", raw) == raw
        assert compiler_publication11_source_history(path, row["beforeRaw"].encode()) == row["beforeRaw"].encode()


def test_compiler_publication11_strict_actual_loader_keeps_raw_source_and_stale_pin_refusals(tmp_path):
    delta = compiler_publication11_delta()
    root = BaselineRepairHistoricalPath(Path(__file__).resolve().parents[2])
    sdk.verify_programs(root, sdk.load_trust())
    # The historical read_bytes view cannot change sdk.regular()/os.open IO.
    sdk.verify_programs(CompilerPublication11HistoricalPath(root), sdk.load_trust())
    for name, change in delta["pinDeltas"].items():
        raw = (root / name).read_bytes()
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        trust = {"programs": {name: change["after"]}, "contracts": {}}
        path.write_bytes(raw)
        sdk.verify_programs(tmp_path, trust)
        path.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed"):
            sdk.verify_programs(tmp_path, trust)
        path.write_bytes(raw)
        if change["before"] is not None:
            trust["programs"][name] = change["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed"):
                sdk.verify_programs(tmp_path, trust)
    with pytest.raises(sdk.Refused, match="reviewed_program_changed"):
        sdk.verify_programs(root, restore_before_compiler_publication11(sdk.load_trust()))


def test_compiler_publication11_signature_and_namespace_changes_preserve_original_bodies():
    delta = compiler_publication11_delta()
    root = BaselineRepairHistoricalPath(Path(__file__).resolve().parents[2])
    originals = {row["path"]: row["beforeRaw"] for row in delta["sourceInverse"]}
    node = "packages/openmates-session-bindings/src/node.rs"
    source = (root / node).read_text()
    new = "pub fn release_json<'env>(&self, env: &'env napi::Env) -> napi::Result<napi::JsString<'env>>"
    old = "pub fn release_json(&self, env: napi::Env) -> napi::Result<napi::JsString>"
    assert source.count(new) == 3 and new not in originals[node]
    assert source.replace(new, old) == originals[node]
    browser = "packages/openmates-rust/src/client/browser.rs"
    source = (root / browser).read_text()
    extra = ["pub(super) use cache_metadata::BrowserMetadataOwnedTransition;\n", "pub(super) fn validate_local_json(encoded:&str)->Result<()> {local_json::validate(encoded)}\n"]
    assert all(source.count(line) == 1 for line in extra)
    for line in extra:
        source = source.replace(line, "", 1)
    assert source == originals[browser]
    monitor = "packages/openmates-rust/src/client/browser_monitor.rs"
    source = (root / monitor).read_text()
    assert source.replace("crate::client::browser::BrowserMetadataOwnedTransition", "crate::client::browser_cache_metadata::BrowserMetadataOwnedTransition") == originals[monitor]
    incoming = "packages/openmates-rust/src/client/browser_incoming_sync.rs"
    source = (root / incoming).read_text()
    assert source.replace("crate::client::browser::validate_local_json", "crate::client::local_json::validate") == originals[incoming]


def test_compiler_publication11_protected_cookie_vectors_compiler2_and_locks_are_unchanged():
    delta = compiler_publication11_delta()
    root = BaselineRepairHistoricalPath(Path(__file__).resolve().parents[2])
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    for name, digest in delta["protected"].items():
        assert sdk.sha((root / name).read_bytes()) == digest
    saved = json.loads((root / "tests/sdk-conformance/fixtures/session-saved-chat-read.json").read_bytes())
    work = json.loads((root / "tests/sdk-conformance/fixtures/session-work.json").read_bytes())
    assert len(saved["capabilities"]["session.saved-chat-read.v1"]["vectors"]) == 103
    assert len(work["capabilities"]["session.work-crud.v1"]["vectors"]) == 23
    assert delta["supplierManifests"] == {"NAPI-borrowed-Env-V2": "0330ad6700ae0c1dfdcfb25128c70fea1150787601b9278103ebb9d496cfa0b1", "browser-namespace3": "4e8cc871db9d5658af07ed35bf65f7ea8f00756b173410d8df5290937a4b178b", "publication-post-gate7": "f1e9c7afd387a48d034d1e9b2568a398a1436cc5377361a47b1267e146407a72"}


def test_compiler_publication11_guard_test_annotations_are_per_function_without_tooling_exclusion():
    delta = compiler_publication11_delta()
    root = BaselineRepairHistoricalPath(Path(__file__).resolve().parents[2])
    tests = [row for row in delta["sourceMap"] if row["beforeSha256"] is None]
    assert len(tests) == 3
    expected = "// contract-test: supporting surface=sdks.rust assertions=sdk.encryption.local-only,auth.session.isolation"
    total = 0
    for row in tests:
        source = (root / row["path"]).read_text()
        assert "contract-test-file: tooling" not in source
        count = source.count("#[test]") + source.count("#[tokio::test]")
        assert source.count(expected) == count and count > 0
        total += count
    assert total == 8


# Exact source-only reviewed concurrent Apps/security registration; no execution.
def baseline_repair_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-baseline-repair-delta.json", "5c2792159c26fd9d23999ffab0501729b22b890d3d225e50a517776c56fa1189")


def restore_before_baseline_repair(trust):
    trust = apps_cookie_history(trust)
    delta = baseline_repair_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for change in delta["pinDeltas"]:
        path, bucket = change["path"], change["bucket"]
        assert prior[bucket][path] == change["after"]
        if change["before"] is None:
            del prior[bucket][path]
        else:
            prior[bucket][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def baseline_repair_history(trust):
    trust = apps_cookie_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == baseline_repair_delta()["afterSha256"]:
        return restore_before_baseline_repair(trust)
    return trust


def baseline_repair_source_history(path, raw):
    raw = apps_cookie_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    for row in baseline_repair_delta()["sourceInverse"]:
        if path == root / row["path"] and sdk.sha(raw) == row["after_sha256"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class BaselineRepairHistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return BaselineRepairHistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __str__(self):
        return str(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        return baseline_repair_source_history(self.path, essential_currentdev_historical_bytes(self.path))

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_baseline_repair_inverse_is_exact_exact_pin_delta_only():
    delta = baseline_repair_delta()
    current = apps_cookie_history(sdk.load_trust())
    prior = restore_before_baseline_repair(current)
    assert delta["beforeSha256"] == "06b039408543b5da502db06e5caa70f33f343f9bfd5d74e3a2b6ac21e7ba59f0"
    assert delta["counts"] == {'programs': 443, 'contracts': 102, 'plan': 93, 'gaps': 180}
    assert delta["beforeCounts"] == {"programs": 439, "contracts": 102, "plan": 93, "gaps": 180}
    assert len(delta["pinDeltas"]) == 7
    assert len(delta["sourceMap"]) == 9
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts"}}
    assert current["plan"] == delta["originalPlans"] and current["gaps"] == delta["originalGaps"]
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert len(current["programs"]) - len(prior["programs"]) == 4
    assert delta["apiCounts"] == {"rust": 2059, "npm": 1542, "python": 1174}
    assert all(value == {"added": [], "removed": []} for value in delta["apiDelta"].values())
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is False
    assert delta["publication"] == "HOLD_PENDING_ROOT_CLASSIFICATION_AND_NORMAL_RECEIPT"


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_baseline_repair_inverse_refuses_unknown_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_baseline_repair(wrong)
    assert baseline_repair_history(wrong) == wrong


def test_baseline_repair_source_inverse_requires_exact_path_and_hash():
    delta = baseline_repair_delta()
    root = AppsCookieHistoricalPath(Path(__file__).resolve().parents[2])
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert baseline_repair_source_history(path, raw) == row["beforeRaw"].encode()
        assert baseline_repair_source_history(path, raw + b"\n") == raw + b"\n"
        assert baseline_repair_source_history(root / "unknown", raw) == raw


def test_baseline_repair_strict_loader_keeps_actual_new_source_and_stale_pin_refusal(tmp_path):
    delta = baseline_repair_delta()
    root = AppsCookieHistoricalPath(Path(__file__).resolve().parents[2])
    sdk.verify_programs(root, sdk.load_trust())
    sdk.verify_programs(BaselineRepairHistoricalPath(root), sdk.load_trust())
    for change in delta["pinDeltas"]:
        raw = (root / change["path"]).read_bytes()
        target = tmp_path / change["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        trust = {"programs": {}, "contracts": {}}
        trust[change["bucket"]][change["path"]] = change["after"]
        target.write_bytes(raw)
        sdk.verify_programs(tmp_path, trust)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, trust)
        if change["before"] is not None:
            target.write_bytes(raw)
            trust[change["bucket"]][change["path"]] = change["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, trust)


def test_baseline_repair_protected_vectors_compiler_locks_and_fixture_status_held():
    delta = baseline_repair_delta()
    root = AppsCookieHistoricalPath(Path(__file__).resolve().parents[2])
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    for name, digest in delta["protected"].items():
        assert sdk.sha((root / name).read_bytes()) == digest
    fixture = json.loads((root / "tests/sdk-conformance/fixtures/direct-skill-retention.json").read_bytes())
    assert fixture["status"] == "proposed_unrun"


# Exact reviewed Apps/security + Cookie SDK registration; source-only, unrun product.
def apps_cookie_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-apps-cookie-delta.json", "da7a77e60490f4d64544e7144f0a10ed409a28dd61adcdd875ecb3548fc80774")


def restore_before_apps_cookie(trust):
    trust = api_key_history(trust)
    delta = apps_cookie_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for change in delta["pinDeltas"]:
        path, bucket = change["path"], change["bucket"]
        assert prior[bucket][path] == change["after"]
        if change["before"] is None:
            del prior[bucket][path]
        else:
            prior[bucket][path] = change["before"]
    prior["plan"] = delta["originalPlans"]
    prior["gaps"] = delta["originalGaps"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def apps_cookie_history(trust):
    trust = api_key_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == apps_cookie_delta()["afterSha256"]:
        return restore_before_apps_cookie(trust)
    return trust


def apps_cookie_source_history(path, raw):
    raw = api_key_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    for row in apps_cookie_delta()["sourceInverse"]:
        if path == root / row["path"] and sdk.sha(raw) == row["after_sha256"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


def apps_cookie_matrix_history(raw):
    raw = api_key_matrix_history(raw)
    root = Path(__file__).resolve().parents[2]
    return apps_cookie_source_history(root / "config/sdk-capabilities.json", raw)


class AppsCookieHistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return AppsCookieHistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __str__(self):
        return str(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        return apps_cookie_source_history(self.path, essential_currentdev_historical_bytes(self.path))

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


class AppsCookieHistoricalSDK:
    # Used ONLY by the older direct11 snapshot test, never by a raw loader test.
    def __init__(self, actual):
        self.actual = actual

    def __getattr__(self, name):
        return getattr(self.actual, name)

    def load_trust(self):
        return apps_cookie_history(self.actual.load_trust())


def test_apps_cookie_exact_source_pin_plan_gap_inverse():
    delta = apps_cookie_delta()
    current = api_key_history(sdk.load_trust())
    prior = restore_before_apps_cookie(current)
    assert delta["beforeSha256"] == "7200ea5d0ee5429247eca9583b55bf9698427b2d2ef5e4c7f0189b1cde0e580e"
    assert {key: len(prior[key]) for key in delta["beforeCounts"]} == {"programs": 443, "contracts": 102, "plan": 93, "gaps": 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert len(delta["sourceMap"]) == 35
    assert len(current["plan"]) == 96 and len(current["gaps"]) == 180
    assert [row for row in current["plan"] if row["capability"] != "sdk.apps"] == prior["plan"]
    assert [row for row in current["plan"] if row["capability"] == "sdk.apps"] == delta["newPlans"]
    assert [row.split(":", 1)[0] for row in current["gaps"]] == [row.split(":", 1)[0] for row in prior["gaps"]]
    assert delta["apiCounts"] == {"rust": 2060, "npm": 1543, "python": 1175}
    assert delta["apiDelta"] == {"rust": {"added": ["client.apps.DirectAppSkillAdmission.check_after_private_gate"], "removed": []}, "npm": {"added": ["SessionClient.runSkill"], "removed": []}, "python": {"added": ["SessionClient.run_skill"], "removed": []}}
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is False
    assert delta["publication"] == "HOLD_NORMAL_SOURCE_RESULT_GUARDS"
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts", "plan", "gaps"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts", "plan", "gaps"}}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_apps_cookie_inverse_refuses_unknown_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_apps_cookie(wrong)
    assert apps_cookie_history(wrong) == wrong


def test_apps_cookie_source_inverse_is_exact_path_hash_only():
    root = ApiKeyHistoricalPath(Path(__file__).resolve().parents[2])
    for row in apps_cookie_delta()["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert apps_cookie_source_history(path, raw) == row["beforeRaw"].encode()
        assert apps_cookie_source_history(path, raw + b"\n") == raw + b"\n"
        assert apps_cookie_source_history(root / "unknown", raw) == raw


def test_apps_cookie_strict_actual_loader_mutated_and_stale_pins_refused(tmp_path):
    root = ApiKeyHistoricalPath(Path(__file__).resolve().parents[2])
    sdk.verify_programs(root, sdk.load_trust())
    sdk.verify_programs(AppsCookieHistoricalPath(root), sdk.load_trust())
    for change in apps_cookie_delta()["pinDeltas"]:
        raw = (root / change["path"]).read_bytes()
        target = tmp_path / change["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        trust = {"programs": {}, "contracts": {}}
        trust[change["bucket"]][change["path"]] = change["after"]
        target.write_bytes(raw)
        sdk.verify_programs(tmp_path, trust)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, trust)
        if change["before"] is not None:
            target.write_bytes(raw)
            trust[change["bucket"]][change["path"]] = change["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, trust)


def test_apps_cookie_shared18_all_three_fixed_plans_partial_and_protected(tmp_path):
    delta = apps_cookie_delta()
    root = ApiKeyHistoricalPath(Path(__file__).resolve().parents[2])
    current = api_key_history(sdk.load_trust())
    matrix = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    retention = (root / "tests/sdk-conformance/fixtures/direct-skill-retention.json").read_bytes()
    root = browser_ts_ci_materialized_historical_root(
        tmp_path, root, matrix, current['plan'], delta['protected'], sdk.sha((root / 'config/sdk-capabilities.json').read_bytes()))
    (root / "tests/sdk-conformance/fixtures/direct-skill-retention.json").write_bytes(retention)
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    assert sdk.execution_plan(root, matrix) == current["plan"]
    assert sdk.matrix_gaps(matrix) == current["gaps"]
    family = next(row for row in matrix["capabilities"] if row["id"] == "sdk.apps")
    assert family["fixture"] == "tests/sdk-conformance/fixtures/session-direct-app-skill.json"
    assert {row["language"] for row in delta["newPlans"]} == {"rust", "npm", "python"}
    assert all(len(row["vectors"]) == 18 for row in delta["newPlans"])
    assert delta["newPlans"][0]["vectors"] == delta["newPlans"][1]["vectors"] == delta["newPlans"][2]["vectors"]
    assert all(value["status"] == "partial" and value["conformance"] is True and value["gaps"] for value in family["languages"].values())
    assert "SessionClient.runSkill" in family["languages"]["npm"]["api"]
    assert "SessionClient.run_skill" in family["languages"]["python"]["api"]
    assert "client.apps.DirectAppSkillAdmission.check_after_private_gate" in family["languages"]["rust"]["api"]
    for name, digest in delta["protected"].items():
        assert sdk.sha((root / name).read_bytes()) == digest
    fixture = json.loads((root / "tests/sdk-conformance/fixtures/direct-skill-retention.json").read_bytes())
    assert fixture["status"] == "proposed_unrun"


# Exact reviewed Explicit API-key SDK registration; source-only, unrun product.
def api_key_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-api-key-delta.json", "8d69530fe59351dbcd4ebce9ca528bc204d28675d3b6f4d4285f719f16f16c5d")


def restore_before_api_key(trust):
    trust = native_invocation_history(trust)
    delta = api_key_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for change in delta["pinDeltas"]:
        path, bucket = change["path"], change["bucket"]
        assert prior[bucket][path] == change["after"]
        if change["before"] is None:
            del prior[bucket][path]
        else:
            prior[bucket][path] = change["before"]
    prior["plan"] = delta["originalPlans"]
    prior["gaps"] = delta["originalGaps"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def api_key_history(trust):
    trust = native_invocation_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == api_key_delta()["afterSha256"]:
        return restore_before_api_key(trust)
    return trust


def api_key_source_history(path, raw):
    raw = native_invocation_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    for row in api_key_delta()["sourceInverse"]:
        if path == root / row["path"] and sdk.sha(raw) == row["after_sha256"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


def api_key_matrix_history(raw):
    root = Path(__file__).resolve().parents[2]
    return api_key_source_history(root / "config/sdk-capabilities.json", raw)


class ApiKeyHistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return ApiKeyHistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __str__(self):
        return str(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        return api_key_source_history(self.path, essential_currentdev_historical_bytes(self.path))

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_api_key_exact_source_pin_plan_gap_inverse():
    delta = api_key_delta()
    current = native_invocation_history(sdk.load_trust())
    prior = restore_before_api_key(current)
    assert delta["beforeSha256"] == "579379fb2736ecba8bd159ae3f687bd5c598a26d52d939c9c170cdf19c11c3dc"
    assert {key: len(prior[key]) for key in delta["beforeCounts"]} == {"programs": 455, "contracts": 104, "plan": 96, "gaps": 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert len(delta["sourceMap"]) == 28
    assert len(current["plan"]) == 99 and len(current["gaps"]) == 180
    assert [row for row in current["plan"] if row["capability"] != "sdk.configuration"] == prior["plan"]
    assert [row for row in current["plan"] if row["capability"] == "sdk.configuration"] == delta["newPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {"rust": 2062, "npm": 1550, "python": 1182}
    assert delta["apiDelta"]["rust"] == {"added": ["sdk.OpenMates.account_info", "sdk.OpenMates.run_app_skill"], "removed": []}
    assert all(not value["removed"] for value in delta["apiDelta"].values())
    assert len(delta["apiDelta"]["npm"]["added"]) == len(delta["apiDelta"]["python"]["added"]) == 7
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is False
    assert delta["publication"] == "HOLD_NORMAL_SOURCE_RESULT_GUARDS"
    assert delta["remainingRequiredMethods"] and "not completed Rust replacement" in delta["legacyForeignApiKeyLibraries"]
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts", "plan", "gaps"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts", "plan", "gaps"}}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_api_key_inverse_refuses_unknown_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_api_key(wrong)
    assert api_key_history(wrong) == wrong


def test_api_key_source_inverse_is_exact_path_hash_only():
    root = NativeInvocationHistoricalPath(Path(__file__).resolve().parents[2])
    for row in api_key_delta()["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert api_key_source_history(path, raw) == row["beforeRaw"].encode()
        assert api_key_source_history(path, raw + b"\n") == raw + b"\n"
        assert api_key_source_history(root / "unknown", raw) == raw


def test_api_key_strict_actual_loader_mutated_and_stale_pins_refused(tmp_path):
    root = NativeInvocationHistoricalPath(Path(__file__).resolve().parents[2])
    sdk.verify_programs(root, sdk.load_trust())
    sdk.verify_programs(ApiKeyHistoricalPath(root), sdk.load_trust())
    for change in api_key_delta()["pinDeltas"]:
        raw = (root / change["path"]).read_bytes()
        target = tmp_path / change["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        trust = {"programs": {}, "contracts": {}}
        trust[change["bucket"]][change["path"]] = change["after"]
        target.write_bytes(raw)
        sdk.verify_programs(tmp_path, trust)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, trust)
        if change["before"] is not None:
            target.write_bytes(raw)
            trust[change["bucket"]][change["path"]] = change["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, trust)


def test_api_key_shared23_all_three_fixed_plans_partial_and_protected(tmp_path):
    delta = api_key_delta()
    root = NativeInvocationHistoricalPath(Path(__file__).resolve().parents[2])
    current = native_invocation_history(sdk.load_trust())
    matrix = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    root = browser_ts_ci_materialized_historical_root(
        tmp_path, root, matrix, current['plan'], delta['protected'], sdk.sha((root / 'config/sdk-capabilities.json').read_bytes()))
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    assert sdk.execution_plan(root, matrix) == current["plan"]
    assert sdk.matrix_gaps(matrix) == current["gaps"]
    family = next(row for row in matrix["capabilities"] if row["id"] == "sdk.configuration")
    assert family["fixture"] == "tests/sdk-conformance/fixtures/api-key-foundation.json"
    assert {row["language"] for row in delta["newPlans"]} == {"rust", "npm", "python"}
    assert all(len(row["vectors"]) == 23 for row in delta["newPlans"])
    assert delta["newPlans"][0]["vectors"] == delta["newPlans"][1]["vectors"] == delta["newPlans"][2]["vectors"]
    assert all(value["status"] == "partial" and value["conformance"] is True and value["gaps"] for value in family["languages"].values())
    for name, digest in delta["protected"].items():
        assert sdk.sha((root / name).read_bytes()) == digest
    cookie = [row for row in current["plan"] if row["capability"] == "sdk.apps"]
    assert len(cookie) == 3 and all(len(row["vectors"]) == 18 for row in cookie)


# Exact reviewed Explicit API-key SDK registration; source-only, unrun product.
def native_invocation_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-native-invocation-delta.json", "31b612db0b6db90158ce658bdf76112e504e43570b37caaa9cb4d59876a2131c")


def restore_before_native_invocation(trust):
    trust = browser_ts_ci_history(trust)
    delta = native_invocation_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for change in delta["pinDeltas"]:
        path, bucket = change["path"], change["bucket"]
        assert prior[bucket][path] == change["after"]
        if change["before"] is None:
            del prior[bucket][path]
        else:
            prior[bucket][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def native_invocation_history(trust):
    trust = browser_ts_ci_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == native_invocation_delta()["afterSha256"]:
        return restore_before_native_invocation(trust)
    return trust


def native_invocation_source_history(path, raw):
    raw = browser_ts_ci_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    for row in native_invocation_delta()["sourceInverse"]:
        if path == root / row["path"] and sdk.sha(raw) == row["after_sha256"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class NativeInvocationHistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return NativeInvocationHistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __str__(self):
        return str(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        return native_invocation_source_history(self.path, essential_currentdev_historical_bytes(self.path))

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_native_invocation_exact_pin_only_inverse_and_original_contracts():
    delta = native_invocation_delta()
    current = browser_ts_ci_history(sdk.load_trust())
    prior = restore_before_native_invocation(current)
    assert delta["beforeSha256"] == "b8a613eee1758547eaed9a4e37fdad524c36a2fd79a8ced73c72c8923e9cd351"
    assert delta["beforeCounts"] == {"programs": 474, "contracts": 106, "plan": 99, "gaps": 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert len(current["plan"]) == 99 and len(current["gaps"]) == 180
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {"rust": 2062, "npm": 1550, "python": 1182}
    assert all(value == {"added": [], "removed": []} for value in delta["apiDelta"].values())
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is False
    assert delta["publication"] == "HOLD_NORMAL_SOURCE_RESULT_GUARDS" and delta["scopeLimits"]
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts"}}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_native_invocation_inverse_refuses_unknown_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_native_invocation(wrong)
    assert native_invocation_history(wrong) == wrong


def test_native_invocation_source_inverse_is_exact_path_and_hash_only():
    root = BrowserTsCiHistoricalPath(Path(__file__).resolve().parents[2])
    for row in native_invocation_delta()["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert native_invocation_source_history(path, raw) == row["beforeRaw"].encode()
        assert native_invocation_source_history(path, raw + b"\n") == raw + b"\n"
        assert native_invocation_source_history(root / "unknown", raw) == raw


def test_native_invocation_actual_strict_loader_mutated_and_stale_pins_refused(tmp_path):
    root = BrowserTsCiHistoricalPath(Path(__file__).resolve().parents[2])
    sdk.verify_programs(root, sdk.load_trust())
    sdk.verify_programs(NativeInvocationHistoricalPath(root), sdk.load_trust())
    for change in native_invocation_delta()["pinDeltas"]:
        raw = (root / change["path"]).read_bytes()
        target = tmp_path / change["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        trust = {"programs": {}, "contracts": {}}
        trust[change["bucket"]][change["path"]] = change["after"]
        target.write_bytes(raw)
        sdk.verify_programs(tmp_path, trust)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, trust)
        if change["before"] is not None:
            target.write_bytes(raw)
            trust[change["bucket"]][change["path"]] = change["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, trust)


def test_native_invocation_matrix99plans180gaps_and_protected_libraries_exact(tmp_path):
    delta = native_invocation_delta()
    root = BrowserTsCiHistoricalPath(Path(__file__).resolve().parents[2])
    current = browser_ts_ci_history(sdk.load_trust())
    matrix = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    root = browser_ts_ci_materialized_historical_root(
        tmp_path, root, matrix, current['plan'], delta['protected'], sdk.sha((root / 'config/sdk-capabilities.json').read_bytes()))
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    assert sdk.execution_plan(root, matrix) == current["plan"]
    assert sdk.matrix_gaps(matrix) == current["gaps"]
    for name, digest in delta["protected"].items():
        assert sdk.sha((root / name).read_bytes()) == digest
    for identity, count in [("sdk.configuration", 23), ("sdk.apps", 18), ("session.work-crud.v1", 23), ("session.saved-chat-read.v1", 103)]:
        cases = [row for row in current["plan"] if row["capability"] == identity]
        assert len(cases) == 3 and all(len(row["vectors"]) == count for row in cases)


# Exact reviewed browser TS/CI source-only registration; source-only, unrun product.
def browser_ts_ci_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-browser-ts-ci105-delta.json", "9154cb9661ad2b9916da253212d15b2daa88ac6db481b7c75cd9532f70dc57bd")


def restore_before_browser_ts_ci(trust):
    trust = sdk_v1_history(trust)
    delta = browser_ts_ci_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for change in delta["pinDeltas"]:
        path, bucket = change["path"], change["bucket"]
        assert prior[bucket][path] == change["after"]
        if change["before"] is None:
            del prior[bucket][path]
        else:
            prior[bucket][path] = change["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def browser_ts_ci_history(trust):
    trust = sdk_v1_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == '52291e6891c1d9137ef8eaf0b48858a18c3707113d6992613b0a31691b44fe90':
        return restore_before_browser_ts_ci(trust)
    return trust


_BROWSER_TS_CI_SOURCE_AFTER = {'backend/apps/ai/testing/mock_replay.py': 'ba9781e1d9ae84c48516e4f1e40be7126079b7ac5a2c0e71c6aca2df7efaf4c3', 'frontend/apps/web_app/src/lib/rustCore/productionLoader.ts': '4398a65e65db3f5c75e72120554b20b0b1b3c61e14ecf23dca15d2372de7c9f5', 'frontend/apps/web_app/tests/rust-core-production-saved-session.spec.ts': '8ca3ab7ec4b76b2444ace12308388f23194141220d27568d04573f58c28b2d37', 'frontend/packages/ui/src/components/ActiveChat.svelte': '3d16e51f0eae143cb3572307af85756dde2af31c5e136ebfd4fb0d5a20f2fbca', 'frontend/packages/ui/src/components/ChatHistory.svelte': '2e3e800ae3dd5c503003373585f5a1ef18ff62ce27ce03f86e2a467ab5e8b59d', 'frontend/packages/ui/src/components/ChatMessageNotification.svelte': '186174e0e560cd3c5c37c068bf7b917b0c3e0898f7d8b679bb1ebef5d2e92b92', 'frontend/packages/ui/src/components/chats/Chat.svelte': '83365eb80ef32b8eeb887f2712853a9c0c01c003fc23d11cfb6d4fab73a7af2a', 'frontend/packages/ui/src/components/chats/ChatSettingsShareSection.svelte': '8924ac7465873c0b965944a72e127d73dd64352b004d82aff6e24a04fc9283c4', 'frontend/packages/ui/src/components/chats/Chats.svelte': '6505042f6349b79b1f5c934918bdc8ceb3cd8221edb9ed625a43b6a04cae8a48', 'frontend/packages/ui/src/components/chats/HiddenChatUnlock.svelte': 'af6636cdf516d6fc37620ebfc589ad5e85ff6d4a1e2a4ba8e634e819986ab7e2', 'frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts': '7a047a8c7c548bf0f46251c90c01c2d9e65083805c87f17866fad786a908e215', 'frontend/packages/ui/src/components/interactive_questions/utils/questionState.ts': '5c2507ffb2a1adba9665789ecf2bea58c2eba0ef8bfa0d8b7f8983f7d4535b40', 'frontend/packages/ui/src/components/settings/SettingsShared.svelte': 'a78aefec0a7241a178b83dcfde3806ff0436ad13f0d0059c5e1f8ee82d8ae727', 'frontend/packages/ui/src/components/settings/share/SettingsShare.svelte': 'eb28022d72dd72584d015b7df50747499547968444cf7485eced6864d9def069', 'frontend/packages/ui/src/services/anonymousChatPromotionService.ts': 'ca53e99e55bf0b3d4852f1e8e5830be51daf3ff947569d53b086a2ef7822cc19', 'frontend/packages/ui/src/services/appsWorkspaceResultsService.ts': '8c8cf890c7ec16150455b11e28bc666efe5b5790e8ed636d4dd3cf69e50e5dd7', 'frontend/packages/ui/src/services/assistantSpeechPreference.ts': 'e222fa2cfd4f99c97f27b9ea8aef6320ac221a1adf0e21603293cd57bc888eb7', 'frontend/packages/ui/src/services/canonicalEmbedWriteCoordinator.ts': '86d00238840ba64f7ddf99a7a246e326f972182a7299973f3d8a067980d25349', 'frontend/packages/ui/src/services/chatImportService.ts': '9e45b56f0fac3cf8cbea1009bf3090ce6667527e35e091aac7831cca78cb040b', 'frontend/packages/ui/src/services/chatSyncService.ts': '6efb1a22a337c2c977e5272eeaff5d3d65b29a16899958cabe4480921b41fe24', 'frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts': '00e2eac60a4c0eacae9b9d83dd14c912f503ac8259985438215ef9ce28d836d4', 'frontend/packages/ui/src/services/chatSyncServiceHandlersAgentContext.ts': 'db50283b8faa236ef6cd742cc9cc9a52bb66a6d21383321ee21e893451ff8ef5', 'frontend/packages/ui/src/services/chatSyncServiceHandlersAppSettings.ts': '0dd0c6d8e1d75c3a0da11f17bbf849367bb8ed7739128dcfa79b161450c4cd27', 'frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts': '1020c5541a0a72148a91d4a84e667baa023ad60afe3dbb10efa55b99314dc44c', 'frontend/packages/ui/src/services/chatSyncServiceHandlersConnectedAccounts.ts': '3997d85af45902f37c519f40241174f26a7e9887662c75faaffe9f2e41460064', 'frontend/packages/ui/src/services/chatSyncServiceHandlersCoreSync.ts': '9cad2fee0d7fa9a05b75cd1917e852aa062ba2ae12cc1459a5427b4496992f9a', 'frontend/packages/ui/src/services/chatSyncServiceHandlersFocusPhases.ts': '0023317303a989411f0e1026ad5af799717e55c395f129cc420b48336fe85ab9', 'frontend/packages/ui/src/services/chatSyncServiceHandlersPhasedSync.ts': 'c441f0f3f492bb65d2e3c7a20232c730ca6a5ac5347590bc33e46a1630821463', 'frontend/packages/ui/src/services/chatSyncServiceHandlersRecovery.ts': 'aac854e5bd4d55409e2fed36769b49b7b01167b8d5ec02a007e0e100d97777eb', 'frontend/packages/ui/src/services/chatSyncServiceHandlersWebhooks.ts': 'fb729b666c5357def2c0feae498ca6f2e68dbd7a03e1d59bba017ee3e01b0069', 'frontend/packages/ui/src/services/composerGhostSuggestion.ts': '4edbd32deca8c288620672708a261b81678aadf16b74c668b69dcd22b4e8f17c', 'frontend/packages/ui/src/services/cryptoKeyStorage.ts': '529d99fe6890a56e4f9e0e7d89f6fe8bcfcedc6208dd6744b9681ed7c62ce9c7', 'frontend/packages/ui/src/services/db.ts': '72236624dfbad3def918ae85a28c4a8c83eaac98321d85fa842c5501f3062a8c', 'frontend/packages/ui/src/services/db/messageHighlights.ts': '6e15068fa64a744f441fd0d7e45a799b2fdb671652567a3b15177de280e7cf66', 'frontend/packages/ui/src/services/deferredDraftDeleteIntent.ts': '7cd0b55efb2ede157de9474e9b4f5c2ecf5d88bb453cef1724c547dd792d97dc', 'frontend/packages/ui/src/services/directChatService.ts': '0e0f1019dcef27812486165a1c5172a82f5b902aa68331736ce00b9b19385336', 'frontend/packages/ui/src/services/draftContextDispatchBarrier.ts': '8c9350e8f3fdf11253d3cb923b7ae992c0f7e5964022e9117b78010f15bef35d', 'frontend/packages/ui/src/services/drafts/draftCore.ts': 'cfe973ae415701bb40eda5b603d55fe49359e9ec6f59a2bef7d4742e55d6e238', 'frontend/packages/ui/src/services/drafts/draftSave.ts': 'a25db8b33f3485b553305a932103a411906ad5e28358f77106b2b5ec344a2a8a', 'frontend/packages/ui/src/services/drafts/draftWebsocket.ts': 'af7633f931ee39ee7c35c641cd2717eb4d32172bbcc86bed505e5d1642a28048', 'frontend/packages/ui/src/services/embedSenders.ts': '261b6d5258f4f7980d7632519e240d74114dd0209064ec825d08e6e9f423ca82', 'frontend/packages/ui/src/services/encryption/MessageEncryptor.ts': '3f7a109ee7e16d9d52aba4ba1430865d739a949c8ddb68d1c21c24c26d0b1fb1', 'frontend/packages/ui/src/services/forkChatService.ts': '67fed072daf16d6cf17b20007743550196bcf97999e78f470a57fef4de8bf53d', 'frontend/packages/ui/src/services/generatedChatMetadataPersistence.ts': 'c5dfbea61c226d030c70a53024689e26d8f3e2b86cc0860bcd4032889b67f1b6', 'frontend/packages/ui/src/services/hiddenChatService.ts': '669ab8b091ea133b8e0fa5f4fafa36bb93ced30a283e7da6e98ac70f95fe1873', 'frontend/packages/ui/src/services/issueReportSubmission.ts': '9cce1ecce3a0ad4718458e222517cc00e30c74803943919bab5d69bb474fde8e', 'frontend/packages/ui/src/services/outboundMessageSends.ts': '68075724196ba592ebf2c275cf852c332aef77dcaaf54b750d308143f5d94ae4', 'frontend/packages/ui/src/services/rustCore/__tests__/localChatWriteDrain.test.cjs': '1ce5c4b76409f904ffd3db4370f5d126e40008b68763128f5cc3583e7caf549a', 'frontend/packages/ui/src/services/rustCore/__tests__/productionSavedChatSend.test.cjs': 'd33dc1279e8c900d82c28fa6d58a31b29dfa74d21ac98a98bf098e2999446296', 'frontend/packages/ui/src/services/rustCore/__tests__/productionSavedChatSession.test.cjs': '3d22f395d041c7657e0476e9dc2ef17edcd6222b509d5344b94554c19a918525', 'frontend/packages/ui/src/services/rustCore/browserAdapters.ts': '64c23e307273f3cb7fb44c47234584a5dc441895d8f06835eaf46710c55e3ff0', 'frontend/packages/ui/src/services/rustCore/browserAssistantReplacementIO.ts': 'cf2aa06d9f0bc6dd7ea589bfc1d8875d32b097902665a3bfda0778a39b2f8584', 'frontend/packages/ui/src/services/rustCore/browserCacheEffects.ts': '7dc0dc4ce93f1ffa8b5b5209b35b9ef13b781c7eda2144b1e2795fc29258264e', 'frontend/packages/ui/src/services/rustCore/browserCacheProtocol.ts': 'a9eabbfb895f224097d3700d654a18492455e6f7a6ed8a51b6b6fef707d727ef', 'frontend/packages/ui/src/services/rustCore/browserIncomingCacheLoop.ts': '22bdbe9f255780148381c45a1576e5cc03caf69615214dcc5897a00b4b3e21db', 'frontend/packages/ui/src/services/rustCore/browserMessageCacheIO.ts': '28e362bed0ea374133b3e21141c131f0178190a95892dbe3f8c3db8521291653', 'frontend/packages/ui/src/services/rustCore/browserMetadataCacheIO.ts': '66c28aea6f1e9132969100098a3a83407e00b3af2973bf5c97a03206994ee297', 'frontend/packages/ui/src/services/rustCore/productionSavedChatSession.ts': '1d9c4b4e70c94d89b4129078fb06a44545de313bfb311819de58f6bc7989b209', 'frontend/packages/ui/src/services/rustCore/protocol.ts': '675bf9a1f6c537d187f27b25a7eac56b63a3acc6932d3affba88e9448baa71b1', 'frontend/packages/ui/src/services/rustCore/savedChatViewPreviewFixture.ts': 'd2e89ec58907183403fe1eb944c8ea34944f618c0ad44127f45978bb999706c5', 'frontend/packages/ui/src/services/rustCore/sendOperation.ts': 'a00543280d43a1dad036a8b5e68d79ca9b489d6fecebed823733b73fbbe00249', 'frontend/packages/ui/src/services/rustCore/sendProtocol.ts': '88761d05cbddd5c19e581e3ef4406c924692ccd3d3f78f0fee154e6970950576', 'frontend/packages/ui/src/services/rustCore/workerHost.ts': 'be821c6d28a997f63448aeb57fb9ce5ddfd4c341326488c36fa5b56200249572', 'frontend/packages/ui/src/services/rustCore/workerRuntime.ts': 'e178a6a7a792746cd19decaba6a743eb4298e9de20e5b140ecb8c3a71b0378b2', 'frontend/packages/ui/src/services/sendersChatManagement.ts': 'bec53a17e33c9b9f8847b409c77a11109def24550aa083d4ab3db352b04b9bc2', 'frontend/packages/ui/src/services/sendersChatMessages.ts': 'bb45a0a44204eec5f405742c35ba9429e58a67df7b4a16f99a0f190e0c5a4173', 'frontend/packages/ui/src/services/sendersDrafts.ts': '8dcf0093bd0949c565baa6536e656c4016a25cafee4fa9b55a2cf66a882a9a12', 'frontend/packages/ui/src/services/sendersEmbeds.ts': '7a1dbb3ac25734edf416ac7323ffc140385d6c386d1c855c3900ff12de115de2', 'frontend/packages/ui/src/services/sendersMessageHighlights.ts': 'ae3a3a485aff0430a56642ada9a42788fce2f7fae6b528fe625114e9f8b3107c', 'frontend/packages/ui/src/services/sendersSync.ts': '06179da81c341c87fb7b98c85a43fc5e7826b1acce4452181ec8397cda842da2', 'frontend/packages/ui/src/services/voiceCallActions.ts': 'f6541f70ade3ffd0d0c291b85e501bc59f5e247afacff47c72faac4c1bd47e6d', 'frontend/packages/ui/src/services/voiceCallMessages.ts': '034ef9bd4320af6d7a1afa272c28ae59c5aa1fea84f81a34d4f015f44d2218fd', 'frontend/packages/ui/src/services/voiceCallMetadata.ts': '3c9bf9dc434da180a9760f1bba18232ec4feaf076912f4d4575c6765bb3b7793', 'frontend/packages/ui/src/services/websocketService.ts': '384f11545623bd2455a9511c02429301a38f3c0ca68457f0f4c79c2b05588d03', 'scripts/ci_coverage_manifest.json': '118100909f3b1dfcffbdb7563f487e4deb5afc78d5d14c0808f00d3063f8d094', 'scripts/ci_environment.py': '8b258d496dad2335b487c3fdbc1735491274c34020850dcfdfdff200b5acb53e'}


def browser_ts_ci_source_history(path, raw):
    raw = sdk_v1_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    # Closed dispatch only. Known source still loads and hashes the immutable
    # witness before inversion; unrelated historical layers stay byte-exact.
    try:
        relative = Path(path).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    expected = _BROWSER_TS_CI_SOURCE_AFTER.get(relative)
    if expected is None or sdk.sha(raw) != expected:
        return raw
    for row in browser_ts_ci_delta()["sourceInverse"]:
        if path == root / row["path"] and sdk.sha(raw) == row["after_sha256"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class BrowserTsCiHistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return BrowserTsCiHistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __str__(self):
        return str(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        return browser_ts_ci_source_history(self.path, essential_currentdev_historical_bytes(self.path))

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_browser_ts_ci_exact_pin_only_inverse_and_original_contracts():
    delta = browser_ts_ci_delta()
    current = sdk_v1_history(sdk.load_trust())
    prior = restore_before_browser_ts_ci(current)
    assert delta["beforeSha256"] == "8ebc10d4c3d09cfbaf750e4d3be28ebc1798528a32c22c5e5793bb48cdfa7f9f"
    assert delta["beforeCounts"] == {"programs": 482, "contracts": 106, "plan": 99, "gaps": 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert len(current["plan"]) == 99 and len(current["gaps"]) == 180
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {"rust": 2062, "npm": 1550, "python": 1182}
    assert all(value == {"added": [], "removed": []} for value in delta["apiDelta"].values())
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is False
    assert delta["publication"] == "HOLD_NORMAL_SOURCE_RESULT_GUARDS" and delta["scopeLimits"]
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts"}}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_browser_ts_ci_inverse_refuses_unknown_authority(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_browser_ts_ci(wrong)
    assert browser_ts_ci_history(wrong) == wrong


def test_browser_ts_ci_source_inverse_is_exact_path_and_hash_only():
    root = SdkV1HistoricalPath(Path(__file__).resolve().parents[2])
    for row in browser_ts_ci_delta()["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert browser_ts_ci_source_history(path, raw) == row["beforeRaw"].encode()
        assert browser_ts_ci_source_history(path, raw + b"\n") == raw + b"\n"
        assert browser_ts_ci_source_history(root / "unknown", raw) == raw


def test_browser_ts_ci_actual_strict_loader_mutated_and_stale_pins_refused(tmp_path):
    root = SdkV1HistoricalPath(Path(__file__).resolve().parents[2])
    sdk.verify_programs(root, sdk.load_trust())
    sdk.verify_programs(BrowserTsCiHistoricalPath(root), sdk.load_trust())
    for change in browser_ts_ci_delta()["pinDeltas"]:
        raw = (root / change["path"]).read_bytes()
        target = tmp_path / change["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        trust = {"programs": {}, "contracts": {}}
        trust[change["bucket"]][change["path"]] = change["after"]
        target.write_bytes(raw)
        sdk.verify_programs(tmp_path, trust)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, trust)
        if change["before"] is not None:
            target.write_bytes(raw)
            trust[change["bucket"]][change["path"]] = change["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, trust)


def test_browser_ts_ci_matrix99plans180gaps_and_protected_libraries_exact(tmp_path):
    delta = browser_ts_ci_delta()
    root = SdkV1HistoricalPath(Path(__file__).resolve().parents[2])
    current = sdk_v1_history(sdk.load_trust())
    matrix = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    root = browser_ts_ci_materialized_historical_root(
        tmp_path, root, matrix, current['plan'], delta['protected'], delta['matrixSha256'])
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    assert sdk.execution_plan(root, matrix) == current["plan"]
    assert sdk.matrix_gaps(matrix) == current["gaps"]
    for name, digest in delta["protected"].items():
        assert sdk.sha((root / name).read_bytes()) == digest
    for identity, count in [("sdk.configuration", 23), ("sdk.apps", 18), ("session.work-crud.v1", 23), ("session.saved-chat-read.v1", 103)]:
        cases = [row for row in current["plan"] if row["capability"] == identity]
        assert len(cases) == 3 and all(len(row["vectors"]) == count for row in cases)


# Decoded tooling data only. Every caller still freshly reads and hashes actual
# bytes in immutable_trust_test_fixture; no runtime/candidate trust cache exists.
_REVIEWED_TRUST_FIXTURE_HASHES = {'sdk-conformance-trust-api-key-delta.json': '8d69530fe59351dbcd4ebce9ca528bc204d28675d3b6f4d4285f719f16f16c5d', 'sdk-conformance-trust-apps-cookie-delta.json': 'da7a77e60490f4d64544e7144f0a10ed409a28dd61adcdd875ecb3548fc80774', 'sdk-conformance-trust-baseline-repair-delta.json': '5c2792159c26fd9d23999ffab0501729b22b890d3d225e50a517776c56fa1189', 'sdk-conformance-trust-binding-compile2-delta.json': 'c857aa26c18b5259c71c8c864274472367cfdf42dee98c652cecf6fa8252199c', 'sdk-conformance-trust-binding-unit-delta.json': '2092ba6774bc920f17405d3fa1d098cfd1667128452ec0096f9e93ddc7304883', 'sdk-conformance-trust-browser-local-wire-cursor-delta.json': 'ce725e243ed00e27f69792e51415ee6fafb0e91c08f42a4a5a466c10bf0b7c1d', 'sdk-conformance-trust-browser-ts-ci105-delta.json': '9154cb9661ad2b9916da253212d15b2daa88ac6db481b7c75cd9532f70dc57bd', 'sdk-conformance-trust-browser41-rich768-delta.json': 'daceb492365176ce6d6141f81ded864e3f3128cec06653a0bae4e02e795381b4', 'sdk-conformance-trust-browser45-delta.json': 'c26b1d584ebc53aa939b3c2277e1070c45d254648346dffd58002132196221fb', 'sdk-conformance-trust-cache-embed-delta.json': '1ecd1ef400930385c3b5f52a2d2c7da4749add05d3ea4aec2bd71523d82a6390', 'sdk-conformance-trust-cache-peer-seeding-delta.json': '08c1e10699cd73c735352e82a02749ced7305af638d70e7b7292a0e9b3cfc8fc', 'sdk-conformance-trust-cache-settlement-adapters-delta.json': '33506804d67aab4f5d301d756583961df30c1bf81a6930b7808bc2c9ee3b3df1', 'sdk-conformance-trust-cache-settlement-source-delta.json': '68c1a85b9c676b9c66c80a0d67ccd7f953f665834071e4a87c7db37305f67ad5', 'sdk-conformance-trust-ci-fixes-delta.json': '01f98cb4570647ae33207ed952ead190191ecd774795a765811a9555d0f7a6f3', 'sdk-conformance-trust-ci-unit-fixture3-delta.json': 'fcc9295f930203001cd4001991f2b18719f71a8dc1f994a4fd26828212a2baba', 'sdk-conformance-trust-cli-json-header-delta.json': 'ad0ed05f84103751776fdf6b85874ede39d7d67a94e057292f6886c86bb439cb', 'sdk-conformance-trust-compiler_publication11-delta.json': '8f6d4449c9c32551baf13d4a8261a1ad344a25645f43946986b24ee8692bbab5', 'sdk-conformance-trust-direct11-delta.json': 'f281e38dd1a2eede63bfb22ae382094ab7daf19aac76797bd8a4db428bf47789', 'sdk-conformance-trust-first-page-browser-delta.json': 'd6879a2407ef465d417ed090ca8db1259d9d5373c67655105b03f21ce65c4acf', 'sdk-conformance-trust-first-page-npm-diagnostic-delta.json': '23b01408c4c497debc97dc680eff97d75de47661f8e80932b809a48132bd3a50', 'sdk-conformance-trust-full29-arrival20-delta.json': 'c481cacb139f93a0a5e533425daa74ca024a2756272b230ef5ada28b76c982d7', 'sdk-conformance-trust-full29-sdk-header-delta.json': '78dae416b6a1d8d107d3081b4b6a492cccb7a07d6fcebd6e228ea1297bcb96dd', 'sdk-conformance-trust-legacy-webcrypto-delta.json': 'c41feecfca6379f5b1f3acde5d0d0aa1363934fba22199d9d897e0ffe247cca4', 'sdk-conformance-trust-message-id-constant-delta.json': 'a209ac576738694f7f8689cc4bcf577c856e053d79bd0698f74f5d1d85ce7ad2', 'sdk-conformance-trust-message-id-delta.json': '2ac9a3303a2cf3e19d1edbeb5d7fdeadceaa5f5aedc578a90b0e6368e8e3bdf9', 'sdk-conformance-trust-native-invocation-delta.json': '31b612db0b6db90158ce658bdf76112e504e43570b37caaa9cb4d59876a2131c', 'sdk-conformance-trust-native5-fixture-delta.json': '228b142eb6319640c55b40965db32119cbb45b0af283db595b5aaaf68a323646', 'sdk-conformance-trust-opaque-read-id-delta.json': 'a53d15220aad3ebf83780b119d936ef9a4a0c40fd05e89afda78697ea96b9a27', 'sdk-conformance-trust-ordinary-retention-delta.json': '13cad8eaa2cbe7ef718f59d0624c11325d2769a555fc4b1737600c2dbd91b90b', 'sdk-conformance-trust-reviewed229-delta.json': 'bdbd7a7d020394bc71d6ab84da1abc9a7fae75c748f04d920c1708c24fa9b969', 'sdk-conformance-trust-rich45-delta.json': 'f5c103597daca63aef57e3463972c676fb3eeeeff9b51543e9f37ddd7aa0b620', 'sdk-conformance-trust-rust-foundation75-delta.json': '5f3de6c653afc102dffdc79a547e0b87c7482f4a4dc7446c951e83a17ca60fca', 'sdk-conformance-trust-security41-delta.json': '3b4247f77720665088de41db3e3e426ccad0db6d1d500c0d1a06ed10747eb1bc', 'sdk-conformance-trust-selected-cli-delta.json': '317cca0866fd683e464e6edc78e978dac265e0206e4dbc205c1d7946014967d9', 'sdk-conformance-trust-selected-sdk-delta.json': 'c11c355aa92d642201ea61d6d4991a31ca72ae112b0b26620e8f1f35f9917306', 'sdk-conformance-trust-version-result-delta.json': 'a12756e8020b6c84f4b67d1d10b050992d032a6cfa6d2a8408bd13dc1fe22672', 'sdk-conformance-trust-window-7edfe1b.json': '22e16b9aeaf520466b0b7281c7dab47e99b088dc6fc1b30df2b705b967dbe383'}
_REVIEWED_TRUST_FIXTURE_DECODE_CACHE = {}
_DEFAULT_TRUST_FIXTURE_JSON_LOADS = json.loads


def _decode_reviewed_trust_fixture(name, expected_sha256, raw, **parsing_options):
    assert sdk.sha(raw) == expected_sha256
    if parsing_options or json.loads is not _DEFAULT_TRUST_FIXTURE_JSON_LOADS or _REVIEWED_TRUST_FIXTURE_HASHES.get(name) != expected_sha256:
        return json.loads(raw, **parsing_options)
    # Finite reviewed-name/hash map bounds this cache. Return fresh mutable
    # structures so no historical test can poison the next caller's witness.
    key = (name, expected_sha256, "stdlib-json-default-v1")
    if key not in _REVIEWED_TRUST_FIXTURE_DECODE_CACHE:
        _REVIEWED_TRUST_FIXTURE_DECODE_CACHE[key] = json.loads(raw)
    return copy.deepcopy(_REVIEWED_TRUST_FIXTURE_DECODE_CACHE[key])


def test_browser_ts_ci_fixture_cache_checks_actual_tampering_and_isolates_nested_mutation(tmp_path, monkeypatch):
    name = 'sdk-conformance-trust-version-result-delta.json'
    expected = _REVIEWED_TRUST_FIXTURE_HASHES[name]
    raw = (Path(__file__).with_name("fixtures") / name).read_bytes()
    target = tmp_path / "fixtures" / name
    target.parent.mkdir()
    target.write_bytes(raw)
    monkeypatch.setattr(sys.modules[__name__], "Path", lambda _value: tmp_path / "test_module.py")
    first = immutable_trust_test_fixture(name, expected)
    assert (name, expected, "stdlib-json-default-v1") in _REVIEWED_TRUST_FIXTURE_DECODE_CACHE
    nested = next(value for value in first.values() if isinstance(value, (dict, list)))
    nested.clear()
    assert immutable_trust_test_fixture(name, expected) == json.loads(raw)
    before = target.stat()
    changed = bytes([raw[0] ^ 1]) + raw[1:]
    target.write_bytes(changed)
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert target.stat().st_size == before.st_size
    with pytest.raises(AssertionError):
        immutable_trust_test_fixture(name, expected)


def test_browser_ts_ci_fixture_cache_skips_nondefault_and_unknown_inputs():
    name = 'sdk-conformance-trust-version-result-delta.json'
    expected = _REVIEWED_TRUST_FIXTURE_HASHES[name]
    raw = (Path(__file__).with_name("fixtures") / name).read_bytes()
    calls = []
    def hook(value):
        calls.append(1)
        return value
    first = _decode_reviewed_trust_fixture(name, expected, raw, object_hook=hook)
    count = len(calls)
    second = _decode_reviewed_trust_fixture(name, expected, raw, object_hook=hook)
    assert count > 0 and len(calls) > count
    assert first == second == json.loads(raw)
    count = len(_REVIEWED_TRUST_FIXTURE_DECODE_CACHE)
    assert _decode_reviewed_trust_fixture("unknown.json", expected, raw) == json.loads(raw)
    assert len(_REVIEWED_TRUST_FIXTURE_DECODE_CACHE) == count
    assert len(_REVIEWED_TRUST_FIXTURE_DECODE_CACHE) <= len(_REVIEWED_TRUST_FIXTURE_HASHES)

# Additive versioned SDK entry: source/packaging proof, never native conformance.
def sdk_v1_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-sdk-v1-entry-delta.json", "0a6eba757b5362cd13b1a22cac87fa82150d4740aff5d243a2d337dbe0189b1c")


def restore_before_sdk_v1(trust):
    trust = rust_foundation_history(trust)
    delta = sdk_v1_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for row in delta["pinDeltas"]:
        assert prior[row["bucket"]][row["path"]] == row["after"]
        if row["before"] is None:
            del prior[row["bucket"]][row["path"]]
        else:
            prior[row["bucket"]][row["path"]] = row["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def sdk_v1_history(trust):
    trust = rust_foundation_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == "f049b7a7af84964f3bf4c0c207c46dcd957293ed45f08a972f55c6e8106bd1a4":
        return restore_before_sdk_v1(trust)
    return trust


_SDK_V1_SOURCE_AFTER = {'frontend/packages/openmates-cli/package.json': '3afef032d5dc981272d89c64eab1d1b438f84a65be76fcbbb4cb428530c0d961', 'tests/sdk-conformance/npm-inventory.mjs': '5ff9c1b05a069828fd7fd92ce5469270a741198911ea136bf4a87109a8265627'}


def sdk_v1_source_history(path, raw):
    raw = rust_foundation_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    try:
        relative = Path(path).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _SDK_V1_SOURCE_AFTER.get(relative):
        return raw
    for row in sdk_v1_delta()["sourceInverse"]:
        if relative == row["path"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class SdkV1HistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return SdkV1HistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __str__(self):
        return str(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        return sdk_v1_source_history(self.path, essential_currentdev_historical_bytes(self.path))

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_sdk_v1_exact_pins_classification_and_preserved_contracts():
    current = rust_foundation_history(sdk.load_trust())
    delta = sdk_v1_delta()
    prior = restore_before_sdk_v1(current)
    assert delta["beforeSha256"] == "52291e6891c1d9137ef8eaf0b48858a18c3707113d6992613b0a31691b44fe90"
    assert delta["beforeCounts"] == {"programs": 569, "contracts": 106, "plan": 99, "gaps": 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {"rust": 2062, "npm": 1550, "python": 1182}
    assert all(change == {"added": [], "removed": []} for change in delta["apiDelta"].values())
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is False
    assert delta["valueExportCount"] == 13 and delta["typeExportCount"] == 70
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts"}}
    assert {r["path"] for r in delta["pinDeltas"] if r["bucket"] == "contracts"} == {"frontend/packages/openmates-cli/package.json", "docs/user-guide/developers/sdk-v1.md"}
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_sdk_v1_unknown_authority_is_not_historical(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_sdk_v1(wrong)
    assert sdk_v1_history(wrong) == wrong


def test_sdk_v1_source_inverse_and_actual_raw_loader_remain_separate(tmp_path):
    root = RustFoundationHistoricalPath(Path(__file__).resolve().parents[2])
    current = sdk.load_trust()
    sdk.verify_programs(root, current)
    sdk.verify_programs(SdkV1HistoricalPath(root), current)
    delta = sdk_v1_delta()
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert sdk_v1_source_history(path, raw) == row["beforeRaw"].encode()
        assert sdk_v1_source_history(path, raw + b"\n") == raw + b"\n"
        assert sdk_v1_source_history(root / "unknown", raw) == raw
    for row in delta["pinDeltas"]:
        raw = (root / row["path"]).read_bytes()
        target = tmp_path / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        trust = {"programs": {}, "contracts": {}}
        trust[row["bucket"]][row["path"]] = row["after"]
        sdk.verify_programs(tmp_path, trust)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, trust)
        if row["before"] is not None:
            target.write_bytes(raw)
            trust[row["bucket"]][row["path"]] = row["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, trust)


def test_sdk_v1_inventory_actually_discovers_versioned_only_values(tmp_path):
    root = RustFoundationHistoricalPath(Path(__file__).resolve().parents[2])
    for filename in ("index.ts", "sdk-entry.ts"):
        (tmp_path / filename).write_text("export {};\n")
    entry = tmp_path / "sdk-session-v1-entry.ts"
    entry.write_text("export class VersionedOnly { read() {} private hidden() {} }\nexport type VersionedTypeOnly = string;\n")
    result = subprocess.run(["node", str(root / "tests/sdk-conformance/npm-inventory.mjs"), "--source-dir", str(tmp_path)], cwd=root, capture_output=True, text=True, check=True, timeout=60)
    assert json.loads(result.stdout)["npm"] == ["VersionedOnly", "VersionedOnly.read"]
    entry.write_text("export {};\n")
    result = subprocess.run(["node", str(root / "tests/sdk-conformance/npm-inventory.mjs"), "--source-dir", str(tmp_path)], cwd=root, capture_output=True, text=True, check=True, timeout=60)
    assert json.loads(result.stdout)["npm"] == []


def test_sdk_v1_protected_sources_and_real_three_sdk_plan_unchanged(tmp_path):
    root = RustFoundationHistoricalPath(Path(__file__).resolve().parents[2])
    current = rust_foundation_history(sdk.load_trust())
    delta = sdk_v1_delta()
    matrix = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    root = browser_ts_ci_materialized_historical_root(
        tmp_path, root, matrix, current['plan'], delta['protected'], sdk.sha((root / 'config/sdk-capabilities.json').read_bytes()))
    assert sdk.execution_plan(root, matrix) == current["plan"]
    assert sdk.matrix_gaps(matrix) == current["gaps"]
    for relative, digest in delta["protected"].items():
        assert sdk.sha((root / relative).read_bytes()) == digest
    for identity in ("sdk.configuration", "sdk.apps", "session.work-crud.v1", "session.saved-chat-read.v1"):
        rows = [row for row in current["plan"] if row["capability"] == identity]
        assert len(rows) == 3 and {row["language"] for row in rows} == {"rust", "npm", "python"}
    assert delta["requiredUnrun"] and delta["defaultRootMixedLegacyRequired"] is True

# Exact reviewed Rust foundation source/classification registration, not execution.
def rust_foundation_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-rust-foundation75-delta.json", "5f3de6c653afc102dffdc79a547e0b87c7482f4a4dc7446c951e83a17ca60fca")


def restore_before_rust_foundation(trust):
    trust = sdk_packaging_history(trust)
    delta = rust_foundation_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for row in delta["pinDeltas"]:
        assert prior[row["bucket"]][row["path"]] == row["after"]
        if row["before"] is None:
            del prior[row["bucket"]][row["path"]]
        else:
            prior[row["bucket"]][row["path"]] = row["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def rust_foundation_history(trust):
    trust = sdk_packaging_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == "142379dc6b6e6aa5ea75c009a7596b00382e9a929b6143bc8c76df9a5bbfc818":
        return restore_before_rust_foundation(trust)
    return trust


_RUST_FOUNDATION_SOURCE_AFTER = {'packages/openmates-browser-bindings/src/browser.rs': 'd93a2759d9358a96e5f253bc3cfbf82513293fae5b13a6dcf720c8b0d3a73f59', 'packages/openmates-browser-bindings/src/browser_cache.rs': 'ab067ea168f269ece0ac0c5a97b7773e882aa2829cb6b139c8604ed5e1cc8496', 'packages/openmates-browser-bindings/src/browser_send.rs': '611d2c9568ef62aa9f4db885b13538f1281e998e2de073556e367d175e06b6fb', 'packages/openmates-rust/src/client.rs': 'd1f62e5ba6ea46642e1c3c846b4f49eb7aa1ce4452806f067d4e3342b99c7075', 'packages/openmates-rust/src/client/auth.rs': '1b89751db9b19b398200ffff5c64552422471eebf7f88d83ca1d196cc1004d8c', 'packages/openmates-rust/src/client/auth_handoff.rs': '92366e8daa72de59ac787edd92ec13a90f3031f735aa02566f0732079fd2975b', 'packages/openmates-rust/src/client/browser.rs': '8b50af7dff74e623d17f8a2220b68450ec9e9fd3034912fa0a7412396e872cd5', 'packages/openmates-rust/src/client/browser_cache_messages.rs': 'c169a0bb33344b503544dab746eb2489bf734b05da724dcf005eb182dee10b27', 'packages/openmates-rust/src/client/browser_cache_metadata.rs': 'aa03699a158879b1462fafa04477d024af6b1aab195291b2c6804b6c8802b3b5', 'packages/openmates-rust/src/client/browser_monitor.rs': 'b2c36d65d2708f3c8c634927e501f58c579512a81341aa528b0ad33cd071606d', 'packages/openmates-rust/src/client/browser_retained_view.rs': '8b1ce5ac72788187035b415df7f22108f1695648b7853bd891d770cf75c96bde', 'packages/openmates-rust/src/client/completion_recovery.rs': '3fb40575a7ab04adeda9aed778582510207d84e1f268d1851b4c6567d59952d4', 'packages/openmates-rust/src/client/draft_read.rs': '4aa121298607a5b42e02884814c4cde2797cf85a99170a53e8787ea77eddb1e2', 'packages/openmates-rust/src/client/monitor.rs': '8960f9d5edc2401d2c5e8a6c05706d024e787dd2a58057fedaace95c5600ffdd', 'packages/openmates-rust/src/client/owned_operation.rs': '721c9338f48865dfbd40df853832767ca08fef6ae80ddbc46b4cd1ca301599f5', 'packages/openmates-rust/src/client/project_task_watch.rs': '0bc3f2ff04c80fff0163b4ddda5214dedb6cb8aca13b776ed488c97d98b31443', 'packages/openmates-rust/src/client/send.rs': 'b10ba3004841ffc491ad68dd72fca69c0c52845e3d497a4eb727a4525dc76d75', 'packages/openmates-rust/src/client/sync.rs': '4b691abec3dce8e2908bf6eddb8f93f2684441c8331412c6765031d848f71cd1', 'packages/openmates-rust/src/client/sync_capability.rs': '7045a05c0c394d1c979c07eb86ef870298676922530b039bfcf388d0f6815412', 'packages/openmates-rust/src/client/sync_windows.rs': 'e60094f7920799e5678ec7dd0fdebb6683c9617e06c4b33e6463d433ac912b0f', 'packages/openmates-rust/src/client/sync_windows_tests.rs': 'e0d26dab90cb66fe876efcafe9a135c95ad323b1d8ba981af846bebb585ce489', 'packages/openmates-rust/src/client/transport.rs': '514d6cf68c6300328de1137d56dc2f025018aaa5b8c0107bd309a856ebd85d76', 'packages/openmates-rust/src/client/transport/owned_read.rs': '1faf6971209bf936eac0818455b18ef6f000faa0b906b08da2ba518877404ddd', 'packages/openmates-rust/src/sdk_drafts.rs': '8cc0548a0a88d2fb020176f5cd18b6e5f3de3ee5a6a02f9fc3f8e0622d909ecd', 'config/sdk-capabilities.json': '5c0b8a010911224dee55bcf5878d71a181177d6761d0dda5b4939654d7357454'}


def rust_foundation_source_history(path, raw):
    raw = sdk_packaging_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    try:
        relative = Path(path).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _RUST_FOUNDATION_SOURCE_AFTER.get(relative):
        return raw
    for row in rust_foundation_delta()["sourceInverse"]:
        if relative == row["path"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class RustFoundationHistoricalPath:
    def __init__(self, path):
        self.path = path

    def __truediv__(self, child):
        return RustFoundationHistoricalPath(self.path / child)

    def __eq__(self, other):
        return self.path == getattr(other, "path", other)

    def __hash__(self):
        return hash(self.path)

    def __str__(self):
        return str(self.path)

    def __fspath__(self):
        return str(self.path)

    def __getattr__(self, name):
        return getattr(self.path, name)

    def read_bytes(self):
        return rust_foundation_source_history(self.path, essential_currentdev_historical_bytes(self.path))

    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_rust_foundation_exact_75_pins_and_original_plan_gap_authority():
    delta = rust_foundation_delta()
    current = sdk_packaging_history(sdk.load_trust())
    prior = restore_before_rust_foundation(current)
    assert delta["beforeSha256"] == "f049b7a7af84964f3bf4c0c207c46dcd957293ed45f08a972f55c6e8106bd1a4"
    assert delta["beforeCounts"] == {"programs": 571, "contracts": 108, "plan": 99, "gaps": 180}
    assert delta["counts"] == {key: len(current[key]) for key in delta["counts"]}
    assert len(delta["sourceMap"]) == 75 and len(delta["pinDeltas"]) == 76
    assert sum(row["before"] is None for row in delta["pinDeltas"]) == 51
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {"rust": 2155, "npm": 1550, "python": 1182}
    assert len(delta["apiDelta"]["rust"]["added"]) == 93 and not delta["apiDelta"]["rust"]["removed"]
    assert delta["apiDelta"]["npm"] == delta["apiDelta"]["python"] == {"added": [], "removed": []}
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is False
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts"}}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_rust_foundation_unknown_authority_cannot_be_normalized(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_rust_foundation(wrong)
    assert rust_foundation_history(wrong) == wrong


def test_rust_foundation_matrix_only_extends_exact_existing_partial_rust_arrays(tmp_path, monkeypatch):
    root = SdkPackagingHistoricalPath(Path(__file__).resolve().parents[2])
    delta = rust_foundation_delta()
    old = json.loads(delta["matrixBeforeRaw"])
    matrix = json.loads((root / "config/sdk-capabilities.json").read_bytes())
    snapshot = sdk_packaging_history(sdk.load_trust())
    root = browser_ts_ci_materialized_historical_root(
        tmp_path, root, matrix, snapshot['plan'], delta['protected'], delta['matrixAfterSha256'])
    manifest = (json.dumps(snapshot, indent=2, sort_keys=True) + "\n").encode()
    require_fixed_historical_manifest(manifest, delta['afterSha256'])
    manifest_path = tmp_path / 'historical-sdk' / 'ci_sdk_conformance_trust.json'
    manifest_path.parent.mkdir()
    manifest_path.write_bytes(manifest)
    monkeypatch.setattr(sdk, '__file__', str(manifest_path.with_name('ci_sdk_conformance.py')))
    additions = delta["apiClassification"]
    assert set(additions) == {"sdk.session-client", "sdk.drafts"}
    assert len(additions["sdk.session-client"]) == 92 and len(additions["sdk.drafts"]) == 1
    assert set(additions["sdk.session-client"] + additions["sdk.drafts"]) == set(delta["apiDelta"]["rust"]["added"])
    assert [family["id"] for family in matrix["capabilities"]] == [family["id"] for family in old["capabilities"]]
    for before, after in zip(old["capabilities"], matrix["capabilities"]):
        expected = copy.deepcopy(before)
        if before["id"] in additions:
            assert before["languages"]["rust"]["status"] == after["languages"]["rust"]["status"] == "partial"
            expected["languages"]["rust"]["api"] = sorted(before["languages"]["rust"]["api"] + additions[before["id"]])
        assert after == expected
    assert sdk.execution_plan(root, matrix) == sdk.load_trust()["plan"]
    assert sdk.matrix_gaps(matrix) == sdk.load_trust()["gaps"] == delta["originalGaps"]


def test_rust_foundation_exact_source_inverse_keeps_actual_loader_strict(tmp_path):
    root = SdkPackagingHistoricalPath(Path(__file__).resolve().parents[2])
    sdk.verify_programs(root, sdk.load_trust())
    sdk.verify_programs(RustFoundationHistoricalPath(root), sdk.load_trust())
    delta = rust_foundation_delta()
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert rust_foundation_source_history(path, raw) == row["beforeRaw"].encode()
        assert rust_foundation_source_history(path, raw + b"\n") == raw + b"\n"
        assert rust_foundation_source_history(root / "unknown", raw) == raw
    for row in delta["pinDeltas"]:
        target = tmp_path / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = (root / row["path"]).read_bytes()
        target.write_bytes(raw)
        trust = {"programs": {}, "contracts": {}}
        trust[row["bucket"]][row["path"]] = row["after"]
        sdk.verify_programs(tmp_path, trust)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, trust)
        if row["before"] is not None:
            target.write_bytes(raw)
            trust[row["bucket"]][row["path"]] = row["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, trust)


def test_rust_foundation_protected_sdk_v1_vectors_and_locks_remain_exact():
    root = SdkPackagingHistoricalPath(Path(__file__).resolve().parents[2])
    delta = rust_foundation_delta()
    current = sdk_packaging_history(sdk.load_trust())
    for relative, digest in delta["protected"].items():
        assert sdk.sha((root / relative).read_bytes()) == digest
    for identity, count in [("sdk.configuration", 23), ("sdk.apps", 18), ("session.work-crud.v1", 23), ("session.saved-chat-read.v1", 103)]:
        rows = [row for row in current["plan"] if row["capability"] == identity]
        assert len(rows) == 3 and all(len(row["vectors"]) == count for row in rows)
    assert delta["sourceOnlyReviewPending"] and delta["requiredUnrun"]

# Exact packaged SDK runtime-validation source registration; execution UNRUN.
def sdk_packaging_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-packaging15-delta.json", "53971d290348307eabb23247a8ff31cd4dd6084cb10e110f6ab225fb276ab027")


def restore_before_sdk_packaging(trust):
    trust = checkpoint28_history(trust)
    delta = sdk_packaging_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for row in delta["pinDeltas"]:
        assert prior[row["bucket"]][row["path"]] == row["after"]
        if row["before"] is None:
            del prior[row["bucket"]][row["path"]]
        else:
            prior[row["bucket"]][row["path"]] = row["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def sdk_packaging_history(trust):
    trust = checkpoint28_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == "22acb7a19a8f99da99362dd664910128ec81e998b14dbb0447db1e98f6a56752":
        return restore_before_sdk_packaging(trust)
    return trust


_SDK_PACKAGING_SOURCE_AFTER = {'tests/sdk-conformance/runners/api-key-foundation.mjs': '131c0c9f06e2045ca8479208c660a59ea97f163501201da9ce36330d19c6c766', 'frontend/packages/openmates-cli/package.json': 'e4f8260ccdf6a080cb9062ad342d2d297818ec17cb2c2f18a6a68928224a3d43', 'scripts/check_sdk_conformance.py': '450546992a8f817a83d1733004d8b6b4a4853e5eaa2213e5b3f1ddc73f3ad1d2', '.github/workflows/publish-cli.yml': 'f41a0d8b0cf3463e74466e91f0d25dde173c2cda7e35079384b9335d31f606cf', '.github/workflows/publish-python-sdk.yml': 'f5172d92a3c307bd7063af93958453878fcbb9f9f2f36681eadfac707f115c2a'}


def sdk_packaging_source_history(path, raw):
    raw = checkpoint28_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    try:
        relative = Path(path).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _SDK_PACKAGING_SOURCE_AFTER.get(relative):
        return raw
    for row in sdk_packaging_delta()["sourceInverse"]:
        if relative == row["path"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class SdkPackagingHistoricalPath:
    def __init__(self, path):
        self.path = path
    def __truediv__(self, child):
        return SdkPackagingHistoricalPath(self.path / child)
    def __eq__(self, other):
        return self.path == getattr(other, "path", other)
    def __hash__(self):
        return hash(self.path)
    def __str__(self):
        return str(self.path)
    def __fspath__(self):
        return str(self.path)
    def __getattr__(self, name):
        return getattr(self.path, name)
    def read_bytes(self):
        return sdk_packaging_source_history(self.path, essential_currentdev_historical_bytes(self.path))
    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_sdk_packaging_exact_registration_and_unchanged_capability_authority():
    current = checkpoint28_history(sdk.load_trust())
    delta = sdk_packaging_delta()
    prior = restore_before_sdk_packaging(current)
    assert delta["beforeSha256"] == "142379dc6b6e6aa5ea75c009a7596b00382e9a929b6143bc8c76df9a5bbfc818"
    assert delta["beforeCounts"] == {"programs": 622, "contracts": 108, "plan": 99, "gaps": 180}
    assert delta["counts"] == {"programs": 626, "contracts": 110, "plan": 99, "gaps": 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {"rust": 2155, "npm": 1550, "python": 1182}
    assert all(value == {"added": [], "removed": []} for value in delta["apiDelta"].values())
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is False
    assert len(delta["pinDeltas"]) == 9
    assert sum(row["before"] is None for row in delta["pinDeltas"]) == 6
    assert {row["path"] for row in delta["pinDeltas"] if row["bucket"] == "contracts"} == {"frontend/packages/openmates-cli/package.json", ".github/workflows/publish-cli.yml", ".github/workflows/publish-python-sdk.yml"}
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts"}}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_sdk_packaging_unknown_authority_never_normalizes(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_sdk_packaging(wrong)
    assert sdk_packaging_history(wrong) == wrong


def test_sdk_packaging_actual_raw_loader_remains_strict_and_source_inverse_is_exact(tmp_path):
    root = Checkpoint28HistoricalPath(Path(__file__).resolve().parents[2])
    current = sdk.load_trust()
    sdk.verify_programs(root, current)
    sdk.verify_programs(SdkPackagingHistoricalPath(root), current)
    delta = sdk_packaging_delta()
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert sdk_packaging_source_history(path, raw) == row["beforeRaw"].encode()
        assert sdk_packaging_source_history(path, raw + b"\n") == raw + b"\n"
        assert sdk_packaging_source_history(root / "unknown", raw) == raw
    for row in delta["pinDeltas"]:
        raw = (root / row["path"]).read_bytes()
        target = tmp_path / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        isolated = {"programs": {}, "contracts": {}}
        isolated[row["bucket"]][row["path"]] = row["after"]
        sdk.verify_programs(tmp_path, isolated)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, isolated)
        if row["before"] is not None:
            target.write_bytes(raw)
            isolated[row["bucket"]][row["path"]] = row["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, isolated)


def test_sdk_packaging_protected_source75_fixtures_and_four_locks_are_unchanged():
    root = Checkpoint28HistoricalPath(Path(__file__).resolve().parents[2])
    delta = sdk_packaging_delta()
    for relative, digest in delta["protected"].items():
        assert sdk.sha((root / relative).read_bytes()) == digest
    assert len(delta["protectedLocks"]) == 4
    assert all(sdk.sha((root / relative).read_bytes()) == digest for relative, digest in delta["protectedLocks"].items())
    assert len(delta["adminMap"]) == 6 and len(delta["candidateMap"]) == 9
    assert delta["source19Status"] == "PENDING_NOT_COMPOSED"
    assert delta["requiredUnrun"]

# Finite checkpoint19 + exact existing draft dependency9 registration only.
def checkpoint28_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-checkpoint28-delta.json", "c2ca8d3d1172273c8da5bba3f39270190154ce4fc23cbc256e2e55edfef627f6")


def restore_before_checkpoint28(trust):
    trust = physical21_history(trust)
    delta = checkpoint28_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for row in delta["pinDeltas"]:
        assert prior[row["bucket"]][row["path"]] == row["after"]
        if row["before"] is None:
            del prior[row["bucket"]][row["path"]]
        else:
            prior[row["bucket"]][row["path"]] = row["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def checkpoint28_history(trust):
    trust = physical21_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == "12cac95c04f359703ed50b9c1df2d4895b29af6207c378163b5fe99a758b323d":
        return restore_before_checkpoint28(trust)
    return trust


_CHECKPOINT28_SOURCE_AFTER = {'frontend/apps/web_app/src/lib/rustCore/production.worker.ts': '2753da29b6b97bb8778a3de96c184e3f95558e7bf41f3215dd3f25fada72d9d8', 'frontend/apps/web_app/src/lib/rustCore/productionLoader.ts': '7b88c9ee8bbf341b418497a492fb3d592d46b7868e4379bbddf4b31e19b3436d', 'frontend/packages/ui/src/services/rustCore/browserAdapters.ts': '13f06bb1291f6d1707699c4abe624e8212059325535e0e101007ff2133ab0203', 'frontend/packages/ui/src/services/rustCore/workerHost.ts': '8175f07d6c36ee5a8a6c990bd135cb05f53ad2b81f82277cd5b818175b9df36e', 'frontend/packages/ui/src/services/rustCore/workerRuntime.ts': '504c25e56fc98db5bbb43727c180b0f1fb72bfa3f5ce2e4b3460ccd22d369535', 'packages/openmates-browser-bindings/src/browser.rs': '5dd7af71bf417c5a08731401fe71057d304e94d482ca23555decabfda3052f4c', 'packages/openmates-rust/src/client.rs': '5ca69538bdd609ae771a28fa3f6d7be13238cc275f6f739e3eb74224024dfbf6', 'packages/openmates-rust/src/platform.rs': '2652d60c1e2932fcdf977fc5239a6ca08b459a2675e7c1b2064da0a2d09c0e7f'}


def checkpoint28_source_history(path, raw):
    raw = physical21_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    try:
        relative = Path(path).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _CHECKPOINT28_SOURCE_AFTER.get(relative):
        return raw
    for row in checkpoint28_delta()["sourceInverse"]:
        if relative == row["path"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class Checkpoint28HistoricalPath:
    def __init__(self, path):
        self.path = path
    def __truediv__(self, child):
        return Checkpoint28HistoricalPath(self.path / child)
    def __eq__(self, other):
        return self.path == getattr(other, "path", other)
    def __hash__(self):
        return hash(self.path)
    def __str__(self):
        return str(self.path)
    def __fspath__(self):
        return str(self.path)
    def __getattr__(self, name):
        return getattr(self.path, name)
    def read_bytes(self):
        return checkpoint28_source_history(self.path, essential_currentdev_historical_bytes(self.path))
    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_checkpoint28_exact_source_registration_preserves_all_capability_authority():
    current = physical21_history(sdk.load_trust())
    delta = checkpoint28_delta()
    prior = restore_before_checkpoint28(current)
    assert delta["beforeSha256"] == "22acb7a19a8f99da99362dd664910128ec81e998b14dbb0447db1e98f6a56752"
    assert delta["beforeCounts"] == {"programs": 626, "contracts": 110, "plan": 99, "gaps": 180}
    assert delta["counts"] == {"programs": 648, "contracts": 110, "plan": 99, "gaps": 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {"rust": 2155, "npm": 1550, "python": 1182}
    assert all(value == {"added": [], "removed": []} for value in delta["apiDelta"].values())
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is delta["physicalReceiptProven"] is False
    assert len(delta["sourceMap"]) == len(delta["pinDeltas"]) == 28
    assert sum(row["before"] is None for row in delta["pinDeltas"]) == 22
    assert all(row["bucket"] == "programs" for row in delta["pinDeltas"])
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key != "programs"} == {key: value for key, value in prior.items() if key != "programs"}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_checkpoint28_unknown_authority_never_normalizes(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_checkpoint28(wrong)
    assert checkpoint28_history(wrong) == wrong


def test_checkpoint28_actual_raw_loader_strict_and_exact_historical_inverse(tmp_path):
    root = Physical21HistoricalPath(Path(__file__).resolve().parents[2])
    current = sdk.load_trust()
    sdk.verify_programs(root, current)
    sdk.verify_programs(Checkpoint28HistoricalPath(root), current)
    delta = checkpoint28_delta()
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert checkpoint28_source_history(path, raw) == row["beforeRaw"].encode()
        assert checkpoint28_source_history(path, raw + b"\n") == raw + b"\n"
        assert checkpoint28_source_history(root / "unknown", raw) == raw
    for row in delta["pinDeltas"]:
        raw = (root / row["path"]).read_bytes()
        target = tmp_path / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        isolated = {"programs": {}, "contracts": {}}
        isolated[row["bucket"]][row["path"]] = row["after"]
        sdk.verify_programs(tmp_path, isolated)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, isolated)
        if row["before"] is not None:
            target.write_bytes(raw)
            isolated[row["bucket"]][row["path"]] = row["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, isolated)


def test_checkpoint28_protected_sources_and_matrix_keep_exact_unrun_gates():
    root = Physical21HistoricalPath(Path(__file__).resolve().parents[2])
    delta = checkpoint28_delta()
    for relative, digest in delta["protected"].items():
        assert sdk.sha((root / relative).read_bytes()) == digest
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    assert delta["requiredUnrun"]

# Finite checkpoint19 + exact existing draft dependency9 registration only.
def physical21_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-physical21-delta.json", "1933b9030ba3b1ce574dc136759de4609a54b5e68a8d42be4eaabf3e6b145c9c")


def restore_before_physical21(trust):
    trust = coreclose11_history(trust)
    delta = physical21_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for row in delta["pinDeltas"]:
        assert prior[row["bucket"]][row["path"]] == row["after"]
        if row["before"] is None:
            del prior[row["bucket"]][row["path"]]
        else:
            prior[row["bucket"]][row["path"]] = row["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def physical21_history(trust):
    trust = coreclose11_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == "fe44e7e9c505f36dfdac5c9bd5cc902dcc3c8e74d3c41fd3a200edee88ef9a62":
        return restore_before_physical21(trust)
    return trust


_PHYSICAL21_SOURCE_AFTER = {'packages/openmates-rust/src/client.rs': 'a1ca6f441d4ba7b0d215646e3b9f44c806e62948597dd213732906473e2bfa5f', 'packages/openmates-rust/src/client/browser.rs': 'e41b258efa9e6b4ac0f9f66ea6f63e5ca3c2784cb25232995f5296d752ee982d', 'packages/openmates-rust/src/client/browser_cache_messages.rs': '2afe8315eb68767f83b57f31ded3e1be9224a65e271a1a6d25fa79db7f4d0f22', 'packages/openmates-rust/src/client/browser_cache_metadata.rs': 'fbaad229b4b15926fa1ba032d297e8c6803bd67dff887b06d609550a717a3f57', 'packages/openmates-rust/src/client/browser_owned_message_read.rs': '69e2856ac853f0dae1d21e41732df4c02386a2870b0dc6d3dc6b4d95cf99a6e0', 'packages/openmates-rust/src/client/completion_recovery.rs': '3975e947b7db9c1eeaaed190eb4af9fa61adb9c67052d68893d872ecc93ab1eb', 'packages/openmates-rust/src/client/completion_recovery/owned_checkpoint_tests.rs': '88002c6b9430008dc5289e41fea092111773a9d4a821e0fecc42be8d4f7ae26c', 'packages/openmates-rust/src/client/completion_recovery/owned_phase_tests.rs': 'd3115f5cda4ebdfa631e80a0748f24b571e1a21a6632d59ad25f897f1973dc43', 'packages/openmates-rust/src/client/completion_recovery_algorithm.rs': '3db59ad6eb9294896398c17e4704b2ae5f3873e1defef35d8207dfd31881dcbb', 'packages/openmates-rust/src/client/completion_recovery_owned.rs': 'f08da745f962e4e3ec92f782fddd0645e800de03ad9355793e935355f3432630', 'packages/openmates-rust/src/client/completion_recovery_owned_checkpoint.rs': 'a4d2425cfb23b5b05d80c1e3000ca00fdcc731920af5dc336e5593bc3a5952ac', 'packages/openmates-rust/src/client/completion_recovery_owned_phase.rs': 'ac6bab44bd708889203e0381aa1273a66d8b3fd28046f171fcf3369c13bc1692', 'packages/openmates-rust/src/client/completion_recovery_phase_runtime.rs': '166d198fb85aacf82f7b47050c932d0fa0f75d368ed48e32a105a59c3d02dbb0', 'config/sdk-capabilities.json': '2c87a025ded003573a451d91cc3577c92d19975e31f60aa5191b2963a24e9296'}


def physical21_source_history(path, raw):
    raw = coreclose11_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    try:
        relative = Path(path).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _PHYSICAL21_SOURCE_AFTER.get(relative):
        return raw
    for row in physical21_delta()["sourceInverse"]:
        if relative == row["path"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class Physical21HistoricalPath:
    def __init__(self, path):
        self.path = path
    def __truediv__(self, child):
        return Physical21HistoricalPath(self.path / child)
    def __eq__(self, other):
        return self.path == getattr(other, "path", other)
    def __hash__(self):
        return hash(self.path)
    def __str__(self):
        return str(self.path)
    def __fspath__(self):
        return str(self.path)
    def __getattr__(self, name):
        return getattr(self.path, name)
    def read_bytes(self):
        return physical21_source_history(self.path, essential_currentdev_historical_bytes(self.path))
    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_physical21_exact_source_registration_preserves_all_capability_authority():
    current = coreclose11_history(sdk.load_trust())
    delta = physical21_delta()
    prior = restore_before_physical21(current)
    assert delta["beforeSha256"] == "12cac95c04f359703ed50b9c1df2d4895b29af6207c378163b5fe99a758b323d"
    assert delta["beforeCounts"] == {'programs': 648, 'contracts': 110, 'plan': 99, 'gaps': 180}
    assert delta["counts"] == {'programs': 656, 'contracts': 110, 'plan': 99, 'gaps': 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {'rust': 2213, 'npm': 1550, 'python': 1182}
    assert delta["apiDelta"] == {'rust': {'added': ['client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryAdoption', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryAdoption.apply', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryApply', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryApply.apply', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryControl', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryControl.cancel', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryDeferred', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryDeferred.kind', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryDriver', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryDriver.control', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryDriver.next', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryDriver.resume', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryIo', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryIo.drive', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryPendingPersistence', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryPendingPersistence.check_original', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryPendingPersistence.checkpoint', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryProgress', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryProgress.ensure_current', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryProgress.kind', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryResume', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryStep', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryStep.Adopt', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryStep.Apply', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryStep.Deferred', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryStep.Io', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryStep.PendingPersistence', 'client.browser_owned_hint_recovery.OwnedBrowserMetadataContinuation.begin_recovery', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointDurable', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointDurable.into_driver', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointNativeWrite', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointNativeWrite.drive', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointNativeWriteResult', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointNativeWriteResult.readback', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointPreparation.wait_ready', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointRead', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointRead.drive', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointReadResult', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointReadResult.into_crypto', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointReadbackCrypto', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointReadbackCrypto.drive', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointReadiness', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointReadiness.start', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointVerified', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointVerified.finish', 'client.browser_owned_hint_recovery_native.BrowserOriginalHintRecoveryCheckpointWrite.start_native', 'client.browser_owned_hint_recovery_native.OwnedBrowserMetadataContinuation.begin_recovery_with_checkpoint_port', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryCheckpointCrypto', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryCheckpointCrypto.drive', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryCheckpointCrypto.into_pending', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryCheckpointPreparation', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryCheckpointPreparation.into_pending', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryCheckpointWrite', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryCheckpointWrite.into_pending', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryPendingPersistence.prepare_checkpoint', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryPersistenceFailure', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryPersistenceFailure.error_kind', 'client.browser_owned_hint_recovery_physical.BrowserOriginalHintRecoveryPersistenceFailure.into_pending'], 'removed': []}, 'npm': {'added': [], 'removed': []}, 'python': {'added': [], 'removed': []}}
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is delta["physicalReceiptProven"] is False
    assert len(delta["sourceMap"]) == 21 and len(delta["pinDeltas"]) == 22
    assert sum(row["before"] is None for row in delta["pinDeltas"]) == 8
    assert sum(row["bucket"] == "programs" for row in delta["pinDeltas"]) == 21
    assert [row["path"] for row in delta["pinDeltas"] if row["bucket"] == "contracts"] == ["config/sdk-capabilities.json"]
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts"}}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_physical21_unknown_authority_never_normalizes(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_physical21(wrong)
    assert physical21_history(wrong) == wrong


def test_physical21_actual_raw_loader_strict_and_exact_historical_inverse(tmp_path):
    root = Coreclose11HistoricalPath(Path(__file__).resolve().parents[2])
    current = sdk.load_trust()
    sdk.verify_programs(root, current)
    sdk.verify_programs(Physical21HistoricalPath(root), current)
    delta = physical21_delta()
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert physical21_source_history(path, raw) == row["beforeRaw"].encode()
        assert physical21_source_history(path, raw + b"\n") == raw + b"\n"
        assert physical21_source_history(root / "unknown", raw) == raw
    for row in delta["pinDeltas"]:
        raw = (root / row["path"]).read_bytes()
        target = tmp_path / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        isolated = {"programs": {}, "contracts": {}}
        isolated[row["bucket"]][row["path"]] = row["after"]
        sdk.verify_programs(tmp_path, isolated)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, isolated)
        if row["before"] is not None:
            target.write_bytes(raw)
            isolated[row["bucket"]][row["path"]] = row["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, isolated)


def test_physical21_protected_sources_and_matrix_keep_exact_unrun_gates():
    root = Coreclose11HistoricalPath(Path(__file__).resolve().parents[2])
    delta = physical21_delta()
    for relative, digest in delta["protected"].items():
        assert sdk.sha((root / relative).read_bytes()) == digest
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    assert delta["requiredUnrun"]

# Finite checkpoint19 + exact existing draft dependency9 registration only.
def coreclose11_delta():
    return immutable_trust_test_fixture("sdk-conformance-trust-coreclose11-delta.json", "3dd0b5d3e75f7133c4ef6de33ca801cbcc6b0f7def020b34f79187ab8b6f4ca9")


def restore_before_coreclose11(trust):
    trust = essential_currentdev_history(trust)
    delta = coreclose11_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == delta["afterSha256"]
    prior = copy.deepcopy(trust)
    for row in delta["pinDeltas"]:
        assert prior[row["bucket"]][row["path"]] == row["after"]
        if row["before"] is None:
            del prior[row["bucket"]][row["path"]]
        else:
            prior[row["bucket"]][row["path"]] = row["before"]
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + "\n").encode()) == delta["beforeSha256"]
    return prior


def coreclose11_history(trust):
    trust = essential_currentdev_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + "\n").encode()) == "73195b9db5f5f0ecdb9c02614d5bcd63e8f1ba81aea3f5431bcaf1873be24317":
        return restore_before_coreclose11(trust)
    return trust


_CORECLOSE11_SOURCE_AFTER = {'frontend/packages/ui/src/services/rustCore/__tests__/recoveryPortProductionHooks.test.cjs': '56e1835ee8fd2b907d365ffde4a5d60291e45179487918643e41da69dae7625e', 'packages/openmates-browser-bindings/Cargo.lock': 'e707ef22b4c743caa049288416a2f70d6441275a4ee8230cfe69fd8538864c8b', 'packages/openmates-browser-bindings/Cargo.toml': '01dff4863b08ffd1ba944fd37de3776339ac5fa47f7c4c0c0fbfe06456f5f0ac', 'packages/openmates-browser-bindings/src/lib.rs': 'a2ec133d1782dbd352b9a5b9a3f399f5fd0e08baa3f380f8f15a4d0891b5500e', 'packages/openmates-rust/src/client.rs': 'eb1a4981a9c113bc760e42e53810e1f6398882eafe4ecbaa49dcfa5424ba5c44', 'packages/openmates-rust/src/client/owned_saved_send.rs': '3707ec809a4d90179ff4ebef0b251824aa4bdaf0a0024a31649c1d1f58940903', 'packages/openmates-rust/src/client/owned_saved_send_phase.rs': '05d3df1046c796057a7888f548c255743e06e923e337dbad1f71c083b9520e7f', 'packages/openmates-rust/src/platform/browser_socket.rs': '509aafef1690e7f83c2b4cc01b2bd3a8104b31fbe09f6948785c547df423fdcb', 'config/sdk-capabilities.json': '5f5a872f2d07bf4720741a683135f5ba59869fb3cae91925366ca2f59ea7bcb1'}


def coreclose11_source_history(path, raw):
    raw = essential_currentdev_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, "path", path)
    try:
        relative = Path(path).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _CORECLOSE11_SOURCE_AFTER.get(relative):
        return raw
    for row in coreclose11_delta()["sourceInverse"]:
        if relative == row["path"]:
            before = row["beforeRaw"].encode()
            assert sdk.sha(before) == row["before_sha256"]
            return before
    return raw


class Coreclose11HistoricalPath:
    def __init__(self, path):
        self.path = path
    def __truediv__(self, child):
        return Coreclose11HistoricalPath(self.path / child)
    def __eq__(self, other):
        return self.path == getattr(other, "path", other)
    def __hash__(self):
        return hash(self.path)
    def __str__(self):
        return str(self.path)
    def __fspath__(self):
        return str(self.path)
    def __getattr__(self, name):
        return getattr(self.path, name)
    def read_bytes(self):
        return coreclose11_source_history(self.path, essential_currentdev_historical_bytes(self.path))
    def read_text(self, encoding="utf-8", errors="strict"):
        return self.read_bytes().decode(encoding, errors)


def test_coreclose11_exact_source_registration_preserves_all_capability_authority():
    current = essential_currentdev_history(sdk.load_trust())
    delta = coreclose11_delta()
    prior = restore_before_coreclose11(current)
    assert delta["beforeSha256"] == "fe44e7e9c505f36dfdac5c9bd5cc902dcc3c8e74d3c41fd3a200edee88ef9a62"
    assert delta["beforeCounts"] == {'programs': 656, 'contracts': 110, 'plan': 99, 'gaps': 180}
    assert delta["counts"] == {'programs': 660, 'contracts': 111, 'plan': 99, 'gaps': 180}
    assert {key: len(current[key]) for key in delta["counts"]} == delta["counts"]
    assert current["plan"] == prior["plan"] == delta["originalPlans"]
    assert current["gaps"] == prior["gaps"] == delta["originalGaps"]
    assert delta["apiCounts"] == {'rust': 2220, 'npm': 1550, 'python': 1182}
    assert delta["apiDelta"] == {'rust': {'added': ['client.owned_saved_send_phase.OwnedSavedSendDriver.take_returned_refusal', 'client.owned_saved_send_phase.OwnedSavedSendRefusalReason', 'client.owned_saved_send_phase.OwnedSavedSendRefusalReason.AdmissionUnverifiable', 'client.owned_saved_send_phase.OwnedSavedSendRefusalReason.ObservationUnavailable', 'client.owned_saved_send_phase.OwnedSavedSendRefusalReason.code', 'client.owned_saved_send_phase.OwnedSavedSendReturnedRefusal', 'client.owned_saved_send_phase.OwnedSavedSendReturnedRefusal.consume_for'], 'removed': []}, 'npm': {'added': [], 'removed': []}, 'python': {'added': [], 'removed': []}}
    assert delta["actualRuntimeExecutions"] == 0 and delta["releaseEligible"] is delta["activated"] is delta["physicalReceiptProven"] is False
    assert len(delta["sourceMap"]) == 11 and len(delta["pinDeltas"]) == 12
    assert sum(row["before"] is None for row in delta["pinDeltas"]) == 5
    assert sum(row["bucket"] == "programs" for row in delta["pinDeltas"]) == 9
    assert {row["path"] for row in delta["pinDeltas"] if row["bucket"] == "contracts"} == {'packages/openmates-browser-bindings/Cargo.lock', 'packages/openmates-browser-bindings/Cargo.toml', 'config/sdk-capabilities.json'}
    for bucket in ("programs", "contracts"):
        assert {path for path in current[bucket] if current[bucket][path] != prior[bucket].get(path)} == {row["path"] for row in delta["pinDeltas"] if row["bucket"] == bucket}
    assert {key: value for key, value in current.items() if key not in {"programs", "contracts"}} == {key: value for key, value in prior.items() if key not in {"programs", "contracts"}}


@pytest.mark.parametrize("bucket", ["programs", "contracts", "plan", "gaps"])
def test_coreclose11_unknown_authority_never_normalizes(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ("programs", "contracts"):
        wrong[bucket][next(iter(wrong[bucket]))] = "0" * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_coreclose11(wrong)
    assert coreclose11_history(wrong) == wrong


def test_coreclose11_actual_raw_loader_strict_and_exact_historical_inverse(tmp_path):
    root = EssentialCurrentdevHistoricalPath(Path(__file__).resolve().parents[2])
    current = sdk.load_trust()
    sdk.verify_programs(root, current)
    sdk.verify_programs(Coreclose11HistoricalPath(root), current)
    delta = coreclose11_delta()
    for row in delta["sourceInverse"]:
        path = root / row["path"]
        raw = path.read_bytes()
        assert sdk.sha(raw) == row["after_sha256"]
        assert coreclose11_source_history(path, raw) == row["beforeRaw"].encode()
        assert coreclose11_source_history(path, raw + b"\n") == raw + b"\n"
        assert coreclose11_source_history(root / "unknown", raw) == raw
    for row in delta["pinDeltas"]:
        raw = (root / row["path"]).read_bytes()
        target = tmp_path / row["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        isolated = {"programs": {}, "contracts": {}}
        isolated[row["bucket"]][row["path"]] = row["after"]
        sdk.verify_programs(tmp_path, isolated)
        target.write_bytes(raw + b"\n")
        with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
            sdk.verify_programs(tmp_path, isolated)
        if row["before"] is not None:
            target.write_bytes(raw)
            isolated[row["bucket"]][row["path"]] = row["before"]
            with pytest.raises(sdk.Refused, match="reviewed_program_changed|reviewed_contract_changed"):
                sdk.verify_programs(tmp_path, isolated)


def test_coreclose11_protected_sources_and_matrix_keep_exact_unrun_gates():
    root = EssentialCurrentdevHistoricalPath(Path(__file__).resolve().parents[2])
    delta = coreclose11_delta()
    for relative, digest in delta["protected"].items():
        assert sdk.sha((root / relative).read_bytes()) == digest
    assert sdk.sha((root / "config/sdk-capabilities.json").read_bytes()) == delta["matrixSha256"]
    assert delta["requiredUnrun"]


@pytest.mark.parametrize("name", ["sdk-conformance-trust-rich45-delta.json", "sdk-conformance-trust-full29-arrival20-delta.json"])
def test_compressed_historical_witness_matches_exact_original_bytes_and_fresh_objects(name):
    import base64
    import gzip
    path = Path(__file__).with_name("fixtures") / name
    packed = path.read_bytes()
    spec = _COMPRESSED_TRUST_WITNESSES[name]
    independent = gzip.decompress(base64.b64decode(json.loads(packed)["payload"], validate=True))
    assert len(independent) == spec[4] and sdk.sha(independent) == spec[5]
    assert _read_compressed_trust_witness(path, name, spec[5]) == independent
    expected = json.loads(independent)
    first = immutable_trust_test_fixture(name, spec[5])
    assert first == expected and first is not expected
    nested = next(value for value in first.values() if isinstance(value, (dict, list)) and value)
    if isinstance(nested, dict):
        nested["__compression_mutation__"] = True
    else:
        nested.append("__compression_mutation__")
    assert immutable_trust_test_fixture(name, spec[5]) == expected
    assert len(_COMPRESSED_TRUST_WITNESS_BYTES) <= 2
    assert all(type(key) is tuple and type(value) is bytes for key, value in _COMPRESSED_TRUST_WITNESS_BYTES.items())


def _compressed_historical_fault_fixture(monkeypatch, fault):
    # Small TOOLING-only codec faults under one of the two closed names. Real
    # witness constants/files are unmodified; equality tests above use their pins.
    import base64
    import gzip
    name = "sdk-conformance-trust-rich45-delta.json"
    decoded = b'{"fixture":"bounded"}\n'
    compressed = gzip.compress(decoded, mtime=0)
    if fault == "truncated":
        compressed = compressed[:-8]
    elif fault == "trailing":
        compressed += b"unobserved tail"
    elif fault == "concatenated":
        compressed += gzip.compress(decoded, mtime=0)
    elif fault == "decoded_hash":
        compressed = gzip.compress(b'{"fixture":"mutated"}\n', mtime=0)
    elif fault == "inflate_bound":
        compressed = gzip.compress(b"x" * 4096, mtime=0)
    size = 1 if fault == "inflate_bound" else len(decoded)
    if fault == "decoded_oversize":
        size = _MAX_DECODED_TRUST_WITNESS + 1
    container = {"format":"openmates-historical-test-witness-gzip-v1", "decodedBytes":size,
        "decodedSha256":sdk.sha(decoded), "compressedBytes":len(compressed),
        "compressedSha256":sdk.sha(compressed), "payload":base64.b64encode(compressed).decode()}
    if fault == "base64":
        container["payload"] = "!not-base64!"
    elif fault == "extra_key":
        container["authority"] = True
    elif fault == "bool_size":
        container["decodedBytes"] = True
    elif fault == "compressed_hash":
        container["compressedSha256"] = "0" * 64
    packed = json.dumps(container).encode()
    if fault == "malformed":
        packed = b"{"
    elif fault == "duplicate":
        packed = b'{"format":"duplicate",' + packed[1:]
    elif fault == "container_oversize":
        packed = b"x" * (_MAX_COMPRESSED_TRUST_CONTAINER + 1)
    spec = (len(packed), sdk.sha(packed), len(compressed), sdk.sha(compressed), size, sdk.sha(decoded))
    monkeypatch.setitem(_COMPRESSED_TRUST_WITNESSES, name, spec)
    monkeypatch.setattr(sys.modules[__name__], "_COMPRESSED_TRUST_WITNESS_BYTES", {})
    return name, spec[5], packed


@pytest.mark.parametrize("fault", ["malformed", "base64", "extra_key", "bool_size", "duplicate", "compressed_hash", "decoded_hash", "truncated", "trailing", "concatenated", "inflate_bound", "decoded_oversize", "container_oversize"])
def test_compressed_historical_witness_closed_bounded_decoder_refuses_faults(monkeypatch, fault):
    name, expected, packed = _compressed_historical_fault_fixture(monkeypatch, fault)
    with pytest.raises(AssertionError):
        _decode_compressed_trust_witness(name, expected, packed)
    assert _COMPRESSED_TRUST_WITNESS_BYTES == {}


def test_compressed_historical_witness_has_no_unknown_name_or_wrong_hash_fallback():
    name = "sdk-conformance-trust-full29-arrival20-delta.json"
    packed = (Path(__file__).with_name("fixtures") / name).read_bytes()
    with pytest.raises(AssertionError):
        _decode_compressed_trust_witness("sdk-conformance-trust-current.json", _COMPRESSED_TRUST_WITNESSES[name][5], packed)
    with pytest.raises(AssertionError):
        _decode_compressed_trust_witness(name, "0" * 64, packed)
    with pytest.raises(AssertionError):
        _decode_compressed_trust_witness(name, _COMPRESSED_TRUST_WITNESSES[name][5], packed[:-1] + bytes([packed[-1] ^ 1]))


def test_compressed_historical_witness_cache_reverifies_actual_file_and_rejects_symlink(tmp_path, monkeypatch):
    import zlib
    name = "sdk-conformance-trust-full29-arrival20-delta.json"
    packed = (Path(__file__).with_name("fixtures") / name).read_bytes()
    target = tmp_path / "fixtures" / name
    target.parent.mkdir()
    target.write_bytes(packed)
    expected = _COMPRESSED_TRUST_WITNESSES[name][5]
    monkeypatch.setattr(sys.modules[__name__], "Path", lambda _value: tmp_path / "test_module.py")
    first = immutable_trust_test_fixture(name, expected)
    # A matching actual source hash may reuse bytes, never a mutable object.
    monkeypatch.setattr(zlib, "decompressobj", lambda **_kwargs: pytest.fail("cached immutable bytes decompressed again"))
    assert immutable_trust_test_fixture(name, expected) == first
    before = target.stat()
    changed = bytes([packed[0] ^ 1]) + packed[1:]
    target.write_bytes(changed)
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert target.stat().st_size == before.st_size
    with pytest.raises(AssertionError):
        immutable_trust_test_fixture(name, expected)
    original = tmp_path / "original-container"
    original.write_bytes(packed)
    target.unlink()
    target.symlink_to(original)
    with pytest.raises(AssertionError):
        immutable_trust_test_fixture(name, expected)


def test_compressed_historical_witness_cached_bytes_cannot_bypass_original_raw_hash(tmp_path, monkeypatch):
    name = "sdk-conformance-trust-full29-arrival20-delta.json"
    packed = (Path(__file__).with_name("fixtures") / name).read_bytes()
    expected = _COMPRESSED_TRUST_WITNESSES[name][5]
    immutable_trust_test_fixture(name, expected)
    monkeypatch.setitem(_COMPRESSED_TRUST_WITNESS_BYTES, (name, sdk.sha(packed)), b"x" * _COMPRESSED_TRUST_WITNESSES[name][4])
    with pytest.raises(AssertionError):
        immutable_trust_test_fixture(name, expected)


def test_compressed_historical_witness_cache_remains_two_immutable_entries(monkeypatch):
    name, expected, packed = _compressed_historical_fault_fixture(monkeypatch, "valid")
    base = _COMPRESSED_TRUST_WITNESSES[name]
    first = None
    for suffix in (b"", b" ", b"  "):
        current = packed + suffix
        monkeypatch.setitem(_COMPRESSED_TRUST_WITNESSES, name, (len(current), sdk.sha(current), *base[2:]))
        decoded = _decode_compressed_trust_witness(name, expected, current)
        assert type(decoded) is bytes and sdk.sha(decoded) == expected
        first = first or (name, sdk.sha(current))
        assert len(_COMPRESSED_TRUST_WITNESS_BYTES) <= 2
    assert len(_COMPRESSED_TRUST_WITNESS_BYTES) == 2 and first not in _COMPRESSED_TRUST_WITNESS_BYTES
    assert all(type(value) is bytes for value in _COMPRESSED_TRUST_WITNESS_BYTES.values())

# Exact essential source registration on one reviewed fresh-dev cohort only.
# Historical test bytes cannot become current source or runtime proof.
def essential_currentdev_delta():
    return immutable_trust_test_fixture('sdk-conformance-trust-essential-currentdev-delta.json', 'db4d46417c4908319e7d97ebd772f1a6f45832159be5870bba606b4c150deeca')


def restore_before_essential_currentdev(trust):
    trust = fresh_compiler_history(trust)
    delta = essential_currentdev_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == delta['afterSha256']
    prior = copy.deepcopy(trust)
    for row in delta['pinDeltas']:
        assert prior[row['bucket']].get(row['path']) == row['after']
        if row['after'] is None:
            assert row['path'] not in prior[row['bucket']]
        if row['before'] is None:
            del prior[row['bucket']][row['path']]
        else:
            prior[row['bucket']][row['path']] = row['before']
    for row in delta['planDeltas']:
        assert prior['plan'][row['index']] == row['after']
        prior['plan'][row['index']] = row['before']
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + '\n').encode()) == delta['beforeSha256']
    return prior


def essential_currentdev_history(trust):
    trust = fresh_compiler_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == '40ddbd54f2659721c4b77d3dc877d22e758b49425d1c605d2ab56d8fe7b23f1a':
        return restore_before_essential_currentdev(trust)
    return trust


_ESSENTIAL_CURRENTDEV_SOURCE_AFTER = {'backend/core/api/app/routes/auth_routes/auth_pair_v2.py': 'cf7f1c885afb200dde7be62e8f8a003e2618bc5147fa4d1897e6d9c5109f5ef1', 'backend/core/api/app/routes/auth_routes/auth_session.py': '6c26bfc2fd83bee22ddadf78301e6e4a1dbf8f1de82da7e598e3c50d3dcea49e', 'backend/core/api/app/routes/handlers/websocket_handlers/chat_recovery_job_handlers.py': '3bbf7c64d30deb20d98ecbbbd8b636bce896bd1fb93f0695dac7f5cffae4871c', 'backend/core/api/app/routes/websockets.py': '024d93aaf13c903d9018b973c73a0cfddd7c3e17bad5d83e3c0af403c4654564', 'backend/core/directus/extensions/chat-recovery-transaction/src/operations.js': 'e004e4203246be991a25bba8445b9bda41ed55a9b581028d56f1b5ebe96e9150', 'backend/core/directus/extensions/chat-recovery-transaction/test/operations.test.js': 'e0b077b77163835e70efb9ca32b86951fcf63b96bf656651c9179dd626c437df', 'backend/tests/test_ci_replay_terminal_gate.py': '49a6e9ecee60366558a4a86ad7da473b70d4dee9d39efdde4f44497fb6aec74c', 'backend/tests/test_completion_inventory_discovery.py': 'f9cdbb6dba8a9da721752c9512449f9bae4e826746a466009a4b9a640ec86e31', 'docs/user-guide/developers/sdk-v1.md': 'caa5eb719bc87a5b2455dabcced76e9a4f680038ceb3c65b574a8fa80e2d9c04', 'frontend/apps/web_app/src/lib/rustCore/productionLoader.ts': '7d06d5336a6249ae3c1d5962f06d6a09d1d917a096a41a8a042a2f4b10d5f1ed', 'frontend/apps/web_app/tests/rust-core-native-recovery-port.spec.ts': 'ab38fcfc8548db82f207a37a8668db8faaf672b02325122997bda5d7941024e4', 'frontend/packages/openmates-cli/src/client.ts': '386cc749c165bc2ff52025b2446540790e0425f77d722b10dc5fdd572e493a65', 'frontend/packages/openmates-cli/src/generated/appSkills.ts': 'c85a00e8220f80da8b3d87c03b5332cfe9b508d26d673f9833270e75f715d7f0', 'frontend/packages/openmates-cli/src/index.ts': 'ede6b9f05cf32590c8e9448535865d2ff24db7b85b2db259a997e4e064b86cec', 'frontend/packages/openmates-cli/src/sdkSession.ts': '3bec7b587bd2c0115d6f809141ac8eb4241c08521ad750bc8cb494e6f59826da', 'frontend/packages/ui/src/components/ActiveChat.svelte': '8a1bad92f5ac4aa4bc138f7136229bd104b68f58c684efb2051fe29db4dc2fac', 'frontend/packages/ui/src/components/Login.svelte': '95072a173802e4d536725b3ed3505dab8f1456e0c55adf9b482e6fffa3a956c3', 'frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersChatUpdates.test.ts': '46c6c153ed2a99c193f2ce87223c4758a6661d5970112cb0fc63acd612e4c8ad', 'frontend/packages/ui/src/services/__tests__/sendersDrafts.test.ts': '5c71580fa09a0045a1e0887b03ced783b79d81fc9895cfbfdf8f78fb273e53bf', 'frontend/packages/ui/src/services/chatSyncService.ts': '4f52ac1249e12be444f2e8bbe5e71a5b058a658a50e01d19af7dd954d000a380', 'frontend/packages/ui/src/services/chatSyncServiceHandlersAI.ts': 'b4cce75174f474ad857c1d5047c0068f81c64fc2f00b24c6d9c00fe7064cbada', 'frontend/packages/ui/src/services/chatSyncServiceHandlersAppSettings.ts': '888a4d1f52b5d0b04af8112311e375e6256802ee38fef1dc17231a757b4228fa', 'frontend/packages/ui/src/services/chatSyncServiceHandlersChatUpdates.ts': '1747b1c0d5fe2095df7899f59684371995c126fa23c4f7cb5b7ac870937b8248', 'frontend/packages/ui/src/services/chatSyncServiceHandlersRecovery.ts': '0896305eff41223520537d8c17a0813fbb80986d854e403321a547717d0a920d', 'frontend/packages/ui/src/services/db.ts': '95121be3e3cc2a0f6e992cc87ed1f902c1d933e789ee17e6124db65f30872610', 'frontend/packages/ui/src/services/db/chatCrudOperations.ts': 'af3f77c442bba5c96c1f1fcde6172b81ba5e13237ab98c956b6278fc748eee2d', 'frontend/packages/ui/src/services/drafts/__tests__/draftSave.test.ts': 'ba7874a5b0d5034f2278abe8bb5217dc6427054abfcdd8fcbb398a0b76679f83', 'frontend/packages/ui/src/services/drafts/draftSave.ts': 'e16d64595d491b1d0acb2bde026d281fce38f1f8ca59d871c937e3ba81a8c864', 'frontend/packages/ui/src/services/embedSenders.ts': 'd8ddae3fc05423499ed2f30345aa5b122efa2473e1830cfe38d45c82061cf6b5', 'frontend/packages/ui/src/services/rustCore/__tests__/fixedProductionRetirement.test.cjs': '8880b18d2e32487fd5324d873d25efcc2ad5a70830637c54b2e34afc21e2d292', 'frontend/packages/ui/src/services/rustCore/__tests__/ownedCacheWorker.test.cjs': '2f4f15ccb5826c47659cb0d86dd6fc4f110b56c3884086ff7a15d95fad90f953', 'frontend/packages/ui/src/services/rustCore/__tests__/productionSavedChatSession.test.cjs': 'c1157babeceb4fd3d21b1f27f19b954d154c61a1b5257382443cf1b4a8727699', 'frontend/packages/ui/src/services/rustCore/browserCacheProtocol.ts': '5215791538d4e384a497acc6ef0931962aa0b08732d2be8e08e13016401dffa0', 'frontend/packages/ui/src/services/rustCore/productionLegacyProducerRetirement.ts': '15ad0f2b5b9bc03655d8da2f1b6eee8886b3e49c6816158a90b7c595ca7bbc22', 'frontend/packages/ui/src/services/rustCore/productionSavedChatSession.ts': '8126ca056a4ec19f12f30c5e6f1192b23dec86b19957ee89e678420acda18b91', 'frontend/packages/ui/src/services/rustCore/protocol.ts': '39a0f8a0380ba4cd95a02720b68a00cc7f74af4d5917b1171c4fc4e85bc3fa32', 'frontend/packages/ui/src/services/rustCore/workerHost.ts': '3d2ddaa7fb31686146418889a4e080053bf84fd2b90a2bc713bab8712ab09208', 'frontend/packages/ui/src/services/rustCore/workerRuntime.ts': 'bba44ee5cf4efa0ff9f1621a932165f9304e7c17b418c4e9d681179386a6aee8', 'frontend/packages/ui/src/services/sendersChatMessages.ts': 'b5c87cf47f533f9ae9f8724bec88842c800052498e70f6ccb580f094379f4a87', 'frontend/packages/ui/src/services/sendersDrafts.ts': 'f9dbb4031ffa86368eca20286ac71458af8e092d687d9970d925e883eae76841', 'frontend/packages/ui/src/services/sendersEmbeds.ts': 'ebab06374980fc3996b4e1544ea1cefd97e3dc7d61dba5970228d09b9bff15cd', 'frontend/packages/ui/src/services/voiceCallActions.ts': None, 'frontend/packages/ui/src/services/voiceCallMessages.ts': '693795e5d5f465b0f51793de860b5fcd7f975312cd45de3faa3213cab8f1b10a', 'frontend/packages/ui/src/services/voiceCallMetadata.ts': None, 'frontend/packages/ui/src/services/websocketService.ts': 'e46aea6fd4821460d2ef765c89c48c26cc46ac352dc531742236c273f584993a', 'packages/openmates-browser-bindings/src/browser_owned_message_read.rs': '1ce72cdad7d2bcec24e25d50bc68037b9f9197cad0e13d1e7240841c3ef13f1c', 'packages/openmates-python/openmates/generated/app_skills.py': 'b59d3998a53be3baedd26ec7bfa65b7bb14a018c1174e3c3c29ac27a991ede7a', 'packages/openmates-python/openmates/session_client.py': 'bce7c8844671bfeb9abfcf813d6fefd6933ffac2278e7f1760b2838875554294', 'packages/openmates-rust/src/client.rs': '5be55bc72cac7eaf84ede785867a511f7fe1476f411a6c987c6c29433a239a38', 'packages/openmates-rust/src/client/browser_owned_hint_recovery.rs': '4878207b40c3d36e753912faa5fc4a60bfce8f49ea0792584a9f0cc136fceae0', 'packages/openmates-rust/src/client/browser_owned_hint_recovery_native.rs': 'c446d44d2ccddc2e06fa009dd4c12e63d1d6b04e5f093f2fec45c613bd62ecfd', 'packages/openmates-rust/src/client/browser_owned_message_read_tests.rs': '5d235dae7e9ae71322fc9f19e40e1e56bec49332eca57994ef42db3cc2840580', 'packages/openmates-rust/src/client/completion_recovery.rs': '63f81dda7a8a274775491987cef4df5d32b0adf9cdd6a8a49555be48d402da5f', 'packages/openmates-rust/src/client/completion_recovery/original_result_tests.rs': '609842062830671cfdb5c38dd2f8bc2593b949f3f9cb56ae07038e0d5d1827f3', 'packages/openmates-rust/src/client/completion_recovery/owned_phase_tests.rs': '27242c22b2c3fbb4c32bdffef9d1f3aa74d0b8c15f94b5e59cd940fdd1a4f941', 'packages/openmates-rust/src/client/completion_recovery/tests.rs': '4af235bd7078227382b2e318542a52bff0929e827d46b5bb64de619216eba764', 'packages/openmates-rust/src/client/completion_recovery_algorithm.rs': '36e11dd8f017f5cc5e8e394f20090e78f22b6a70668fe56fb4470be2d5dfed72', 'packages/openmates-rust/src/client/completion_recovery_io_algorithm.rs': 'f0193032d0e4c3772b2d76992c164914270b0213d445bd1489e7fada0d1d7cb3', 'packages/openmates-rust/src/client/completion_recovery_owned.rs': '03a24750a58f63542b8dfdb5ad2f743a9054bdab18666a6db781a617a9e8efd3', 'packages/openmates-rust/src/client/completion_recovery_owned_phase.rs': 'c5ce071fcc733fe0698ca90a7125bc17968ab26a541590a3aa8244e05e2e0730', 'packages/openmates-rust/src/client/completion_recovery_phase_runtime.rs': 'ba0080a24f335823dd84fe14d922349446907b84b873e09fb85cce1b73a2092a', 'packages/openmates-rust/src/client/monitor.rs': '643792844935231a26f2dc17578f7733c2b923f73b52ab695efe71590332a2fd', 'packages/openmates-rust/src/client/monitor_hint_work.rs': '26872a94aec27e6b63de6016911884c8bfb287e1373732f5a0f785cb280ad29f', 'packages/openmates-rust/src/client/monitor_hint_work_tests.rs': '80338fb036a1ccc3f5a5ac10b1d3302a3aee787c375ee005403000d556a2b786', 'packages/openmates-rust/src/client/monitor_live_tests.rs': '2218d02aeeee94753c8e5c81b79e90127c4f588ed8536a39fe33ef5a95d5f368', 'packages/openmates-rust/src/client/owned_operation.rs': '15c44037785ef89c70e11f741420fa835af5cae880e347d154479cd7beb814f6', 'packages/openmates-rust/src/client/sync.rs': 'dd415c4b467607f4d1b1a21e3b2ac7bff375c3a653f4c1560bdcc079e8d0a24e', 'packages/openmates-rust/src/client/sync_fresh_inventory_tests.rs': 'b851b5b2179101b585aae4feb42692558d1a174f705890b29e83092eafb5adff', 'packages/openmates-rust/src/client/transport/owned_read.rs': 'b783fc3dda7a0aa2033d78d245633b7635783db91a6f2686f7bed2713fbdb936', 'packages/openmates-rust/src/client/workspaces.rs': '3849df81ba793e7b5d7e560b5ca1409a15b3fc2ea1c026f124de60e387b31ad3', 'packages/openmates-rust/src/generated.rs': '108ac5a64c96dd5c9e1cdfea3dbdca878f95473f0800aae81ac539fd547945eb', 'packages/openmates-rust/src/generated/metadata.json': '8c6945ede03b9f1d7e97a73e5a5aa0dcd824fba4d04e7ad39c4b82776ec6f522', 'packages/openmates-session-bindings/examples/support/essential_session.rs': '9992da3ed7d4c2e3ba6692e7afe3f2b87a0b13bc5bfa189b4db8c73f13c47816', 'packages/openmates-session-bindings/examples/support/saved_stream.rs': '10003d50d3b18abcac5a462eab025ee377d46fcc2010df3e88758865370d6cdc', 'packages/openmates-session-bindings/examples/support/selected_recovery.rs': '974556fe9264c52494067b16897c9bec40aff8215a850133b4fa498ea59d61b9', 'packages/openmates-session-bindings/src/node.rs': '3623e41e3133139da082145d39f623a905f0775a49c67bee5286bb001a07ece9', 'packages/openmates-session-bindings/src/python.rs': 'b600f4fe9ab070ee50c692b81bdc88ad4c0dafbd20df44c2f3f1e7eb3cdfff5d', 'packages/openmates-session-bindings/src/session.rs': 'b9d9ec2ed00409434d964559b4a7e761a3d244dda69ffb4d80f32652fbac6640', 'packages/openmates-session-bindings/src/session_anonymous.rs': '769d1c50756c9794c9d5632e07c7af54126f9c127273248676fb361f05cc028d', 'packages/openmates-session-bindings/src/session_app_skill.rs': 'cddaf2d0a3ce4078def3ac30c32ad531d9a1e89ff7eefb17cc47ccf4dca35c21', 'packages/openmates-session-bindings/src/session_auth_transition.rs': 'c24a85878e0215721b05d3045b8a6d3a33d0cc1c6bfa999f436df9c22782fd93', 'packages/openmates-session-bindings/src/session_chat_details.rs': 'a6a39e094b5030401d71ce03dca9b2fd448ff26c32d32aac2cebc320b7d4d382', 'packages/openmates-session-bindings/src/session_essential/selected_tests.rs': '5291b08535146d33edb46d53a8e01ab88e410821c828d43a52ea4897df349cb9', 'packages/openmates-session-bindings/src/session_full_read.rs': '4680c04965c5f24f813d7e1969d55871ac68d39df5668a6dfa176ffe5a50134e', 'packages/openmates-session-bindings/src/session_saved_stream.rs': '7e0c360ab811745b433ae9ecef78eb146c2bce8874bcd4052a76f4ffa27b20bd', 'packages/openmates-session-bindings/src/session_saved_stream_tests.rs': '96e4a0d0c6c892b56c44c9249271a48b0778ded520e496dc24004039b0431314', 'scripts/ci_chat_metadata_recovery.mjs': 'c32c3d1fe562fce988bc0a1ec5fee07dfc7d27f40222ebdf0d00ecee6dcfbc72', 'tests/sdk-conformance/essential_session_server.py': '5e1ad46b9d1db3a6ae124d7f48fec2a13c7c146e6730c212a69c97078b1dcf9d', 'tests/sdk-conformance/fixtures/session-foreground-completion-recovery.json': '571361fc15779b3182eb6faa6f0dc2c286257150501da179580afd3f264b89a9', 'tests/sdk-conformance/fixtures/session-work.json': 'bc05558c648e6a4c39e3c8cc57d3ed1233a702ddcbea6bbf7ea7278d6be007d1', 'tests/sdk-conformance/runners/essential-session.mjs': '53ec68f404dbef966e648aad6d0ec693b58e35f9c664e2ab7a0ae0ef36fa4973', 'tests/sdk-conformance/runners/essential_session.py': '6925c05c0049ea89cbae8252d5b9d9148e4272ae6f1d21caabd5c75f95a0ca82', 'tests/sdk-conformance/runners/selected-recovery.mjs': 'a611c329bfd4fddba7755dce4b854ba67c88ec7bb1e6bb482f0e3d63e5f7db96', 'tests/sdk-conformance/runners/selected_recovery.py': '9535b95d979eb2076e2bfc2a3a022a79d7e80569dd5a3064df69dd0f008979ce', 'tests/sdk-conformance/runners/session_saved_stream.py': 'd7bb6dad44eb7a8ea2b953a3e7e0cfddf4f02402dacdbea4025bc1efc0f58d86', 'tests/sdk-conformance/runners/support/saved-stream.mjs': '505dd98b7be514e9575c9b37e39d38a22d460905f147099206f7f3f5af60ace1', 'tests/sdk-conformance/schemas/session-foreground-completion-recovery.schema.json': '2dcfbd703de972386920622a9461d7d5c3d6dbcb06f391433e234fc576c07d9f', 'tests/sdk-conformance/schemas/session-work.schema.json': 'ef65924154f5331b996f5f947c300cb384356f81d018cf635ed6b3723d9e69df', 'tests/sdk-conformance/session_saved_stream_peer.py': '11bc7f2dfac0ff3932c506c41259593557cf6797c8fa90b92f7e2124a18a7160', 'tests/sdk-conformance/test_essential_session_server.py': '3b18a4207b864a61e1ee218c289924c201afebb15d6916a009aa0d4e693f3f0c', 'tests/sdk-conformance/test_saved_stream_contract.py': 'b50eb4751b40383c4f7f8149ffb9794da1e0b08d4a3bf4fd6bea0a4584c21360', 'tests/sdk-conformance/test_selected_recovery_contract.py': 'a720a5b1f85e7000f6c098c540a7c353a7ea0eb80e597f6bd28978b7cb858a3c', 'config/sdk-capabilities.json': '8fdbc1cdc868bcfa63ab3ccded3c03b6f9fd24e9d3a1c36f53b0f37d0820ca40'}


def essential_currentdev_source_history(path, raw):
    raw = fresh_compiler_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    path = getattr(path, 'path', path)
    try:
        relative = Path(path).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _ESSENTIAL_CURRENTDEV_SOURCE_AFTER.get(relative):
        return raw
    for row in essential_currentdev_delta()['sourceInverse']:
        if relative == row['path']:
            before = row['beforeRaw'].encode()
            assert sdk.sha(before) == row['before_sha256']
            return before
    return raw


def essential_currentdev_historical_bytes(path):
    # Only test Path adapters call this. Runtime regular/os.open remains strict.
    actual = getattr(path, 'path', path)
    try:
        raw = essential_currentdev_source_history(actual, actual.read_bytes())
        return full29_inventory_dependency_source_history(actual, raw)
    except FileNotFoundError:
        root = Path(__file__).resolve().parents[2]
        try:
            relative = Path(actual).relative_to(root).as_posix()
        except (TypeError, ValueError):
            raise
        if Path(actual).is_symlink() or Path(actual).exists() or Path(actual).parent.resolve() != Path(actual).parent:
            raise
        for row in essential_currentdev_delta()['sourceInverse']:
            if relative == row['path'] and row['after_sha256'] is None:
                before = row['beforeRaw'].encode()
                assert sdk.sha(before) == row['before_sha256']
                return before
        raise


class EssentialCurrentdevHistoricalPath:
    def __init__(self, path):
        self.path = path
    def __truediv__(self, child):
        return EssentialCurrentdevHistoricalPath(self.path / child)
    def __eq__(self, other):
        return self.path == getattr(other, 'path', other)
    def __hash__(self):
        return hash(self.path)
    def __str__(self):
        return str(self.path)
    def __fspath__(self):
        return str(self.path)
    def __getattr__(self, name):
        return getattr(self.path, name)
    def read_bytes(self):
        return essential_currentdev_source_history(self.path, essential_currentdev_historical_bytes(self.path))
    def read_text(self, encoding='utf-8', errors='strict'):
        return self.read_bytes().decode(encoding, errors)


def test_essential_currentdev_exact_authority_inverse_and_six_known_plan_changes():
    current = fresh_compiler_history(sdk.load_trust())
    delta = essential_currentdev_delta()
    before = restore_before_essential_currentdev(current)
    assert delta['beforeSha256'] == '73195b9db5f5f0ecdb9c02614d5bcd63e8f1ba81aea3f5431bcaf1873be24317'
    assert {key: len(current[key]) for key in delta['counts']} == delta['counts']
    assert len(current['plan']) == len(before['plan']) == 99
    assert current['gaps'] == before['gaps'] == delta['originalGaps']
    assert len(current['gaps']) == 180
    def identities(plan):
        return [(row['capability'], row['language']) for row in plan]
    assert identities(current['plan']) == identities(before['plan'])
    assert len(delta['planDeltas']) == 6
    assert {(row['after']['capability'], row['after']['language']) for row in delta['planDeltas']} == {(cap, language) for cap in ['session.work-crud.v1', 'session.foreground-completion-recovery.v1'] for language in ['rust', 'npm', 'python']}
    assert all({key: value for key, value in row['after'].items() if key not in {'vectors', 'fixtureSha256'}} == {key: value for key, value in row['before'].items() if key not in {'vectors', 'fixtureSha256'}} for row in delta['planDeltas'])
    assert all(set(row['before']['vectors']) < set(row['after']['vectors']) for row in delta['planDeltas'])
    assert delta['matrixStatusesConformanceEvidenceAndGapStringsExact'] is True
    assert delta['actualRuntimeExecutions'] == 0 and delta['releaseEligible'] is delta['activated'] is False
    assert delta['referenceDevHead'] == '9d8d23c325e7d065a4665a21669a86c793228f57'
    assert all(not row['path'].startswith('/') for row in delta['sourceMap'])
    assert delta['requiredUnrun']
    for bucket in ['programs', 'contracts']:
        changed = {path for path in set(current[bucket]) | set(before[bucket]) if current[bucket].get(path) != before[bucket].get(path)}
        assert changed == {row['path'] for row in delta['pinDeltas'] if row['bucket'] == bucket}
    assert {key: value for key, value in current.items() if key not in {'programs', 'contracts', 'plan'}} == {key: value for key, value in before.items() if key not in {'programs', 'contracts', 'plan'}}


@pytest.mark.parametrize('bucket', ['programs', 'contracts', 'plan', 'gaps'])
def test_essential_currentdev_unknown_authority_never_normalizes(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ['programs', 'contracts']:
        wrong[bucket][next(iter(wrong[bucket]))] = '0' * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_essential_currentdev(wrong)
    assert essential_currentdev_history(wrong) == wrong


def test_essential_currentdev_actual_raw_loader_and_all_source_pin_mutations_remain_strict(tmp_path):
    root = FreshCompilerHistoricalPath(Path(__file__).resolve().parents[2])
    current = sdk.load_trust()
    sdk.verify_programs(root, current)
    sdk.verify_programs(EssentialCurrentdevHistoricalPath(root), current)
    delta = essential_currentdev_delta()
    for row in delta['pinDeltas']:
        actual = root / row['path']
        if row['after'] is None:
            assert not actual.exists() and row['path'] not in current[row['bucket']]
            with pytest.raises((sdk.Refused, OSError)):
                sdk.verify_programs(root, {'programs': {row['path']: row['before']}, 'contracts': {}})
            continue
        raw = actual.read_bytes()
        assert sdk.sha(raw) == row['after']
        target = tmp_path / row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        isolated = {'programs': {}, 'contracts': {}}
        isolated[row['bucket']][row['path']] = row['after']
        sdk.verify_programs(tmp_path, isolated)
        target.write_bytes(raw + b'\n')
        with pytest.raises(sdk.Refused, match='reviewed_program_changed|reviewed_contract_changed'):
            sdk.verify_programs(tmp_path, isolated)
        if row['before'] is not None:
            target.write_bytes(raw)
            isolated[row['bucket']][row['path']] = row['before']
            with pytest.raises(sdk.Refused, match='reviewed_program_changed|reviewed_contract_changed'):
                sdk.verify_programs(tmp_path, isolated)


def test_essential_currentdev_deleted_sources_are_historical_only_and_unknown_absence_refuses():
    root = FreshCompilerHistoricalPath(Path(__file__).resolve().parents[2])
    delta = essential_currentdev_delta()
    removed = [row for row in delta['sourceInverse'] if row['after_sha256'] is None]
    assert {row['path'] for row in removed} == {'frontend/packages/ui/src/services/voiceCallActions.ts', 'frontend/packages/ui/src/services/voiceCallMetadata.ts'}
    for row in delta['sourceInverse']:
        actual = root / row['path']
        if row['after_sha256'] is None:
            assert not actual.exists()
            assert essential_currentdev_historical_bytes(actual) == row['beforeRaw'].encode()
        else:
            raw = actual.read_bytes()
            assert sdk.sha(raw) == row['after_sha256']
            assert essential_currentdev_source_history(actual, raw) == row['beforeRaw'].encode()
            assert essential_currentdev_source_history(actual, raw + b'\n') == raw + b'\n'
    with pytest.raises(FileNotFoundError):
        essential_currentdev_historical_bytes(root / 'unknown-essential-history-file')


def test_essential_currentdev_third_closed_container_fresh_objects_and_held_source_pins():
    name = 'sdk-conformance-trust-essential-currentdev-delta.json'
    spec = _COMPRESSED_TRUST_WITNESSES[name]
    raw = _read_compressed_trust_witness(Path(__file__).with_name('fixtures') / name, name, spec[5])
    assert sdk.sha(raw) == 'db4d46417c4908319e7d97ebd772f1a6f45832159be5870bba606b4c150deeca' and len(raw) == spec[4]
    decoded = json.loads(raw)
    first = essential_currentdev_delta()
    first['pinDeltas'].append({'untrusted': True})
    assert essential_currentdev_delta() == decoded
    assert len(_COMPRESSED_TRUST_WITNESS_BYTES) <= 2
    assert all(type(value) is bytes for value in _COMPRESSED_TRUST_WITNESS_BYTES.values())
    root = FreshCompilerHistoricalPath(Path(__file__).resolve().parents[2])
    for path, digest in decoded['protected'].items():
        assert sdk.sha((root / path).read_bytes()) == digest
    assert decoded['apiDelta'] == {'npm': {'added': ['OpenMates.apps.web.browse', 'buildCalendarEventFile'], 'removed': []}, 'python': {'added': ['OpenMates.apps.web.browse'], 'removed': []}, 'rust': {'added': ['client.Client.apply_owned_apps_inventory_headers', 'client.Client.finish_owned_apps_inventory', 'client.Client.list_apps_inventory_compatibility', 'client.Client.prepare_owned_apps_inventory', 'client.browser_owned_hint_recovery.BrowserOriginalHintRecoveryControl.wait_cancelled', 'client.browser_owned_hint_recovery_native.OwnedBrowserMetadataContinuation.next_recovery_offer', 'client.completion_recovery.CompletionRecoveryJob.created_at', 'client.owned_apps_inventory.AppsInventoryPublication', 'client.owned_apps_inventory.AppsInventoryPublication.check', 'client.owned_apps_inventory.AppsInventoryPublication.encode_json', 'client.owned_apps_inventory.AppsInventoryPublication.take_items', 'client.owned_apps_inventory.CompletedOwnedAppsInventory', 'client.owned_apps_inventory.OwnedAppsInventoryBody', 'client.owned_apps_inventory.OwnedAppsInventoryBody.receive_body', 'client.owned_apps_inventory.OwnedAppsInventoryControl', 'client.owned_apps_inventory.OwnedAppsInventoryControl.cancel', 'client.owned_apps_inventory.OwnedAppsInventoryHeaders', 'client.owned_apps_inventory.PreparedOwnedAppsInventory', 'client.owned_apps_inventory.PreparedOwnedAppsInventory.control', 'client.owned_apps_inventory.PreparedOwnedAppsInventory.receive_headers', 'generated.WebSkills.browse'], 'removed': []}}

# Closed fourth historical tooling witness; runtime SDK loaders stay strict.
def fresh_compiler_delta():
    return immutable_trust_test_fixture('sdk-conformance-trust-fresh-compiler-delta.json', 'ae731196eba37ee0750391bae99b3337b6731c20de1bc4b22379191ffa854989')


def restore_before_fresh_compiler(trust):
    trust = next_native_sdk_history(trust)
    delta = fresh_compiler_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == delta['afterSha256']
    prior = copy.deepcopy(trust)
    for row in delta['pinDeltas']:
        assert prior[row['bucket']].get(row['path']) == row['after']
        if row['before'] is None:
            del prior[row['bucket']][row['path']]
        else:
            prior[row['bucket']][row['path']] = row['before']
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + '\n').encode()) == delta['beforeSha256']
    return prior


def fresh_compiler_history(trust):
    trust = next_native_sdk_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == '4e8fe621943497ea5e4b8d47b24e29b5793b2ebe108e476fbb80f1b129310c4e':
        return restore_before_fresh_compiler(trust)
    return trust


_FRESH_COMPILER_SOURCE_AFTER = {'backend/apps/ai/testing/mock_replay.py': '4b230b75a1a2a190c95595c6e58eba0ec87d4f76760c179e4e0ff97b07401520', 'backend/core/api/app/routes/chats.py': '26f8ee7d21e6951379e50bb533311ed8af1fe3d939de042fed757f1e70cdb5b9', 'frontend/packages/ui/src/components/ChatHistory.svelte': '73d67b93e92f5f8e58e3bc35599a846741b553a547d20b354dbd34651392dcd2', 'frontend/packages/ui/src/components/ChatMessageNotification.svelte': 'c14642160ee21c56595294ede8f24e23bff044426c04cf152a30cc5db8fd3113', 'frontend/packages/ui/src/components/chats/Chat.svelte': 'd431395b1b1179967ffed11937ed93db65d230abbe49bf835dc87bbe1027293d', 'frontend/packages/ui/src/components/chats/Chats.svelte': 'badbd77f28e227e915f8229efd4d7a923319fd8f8abae4d50de7a5a889d0355e', 'frontend/packages/ui/src/components/enter_message/handlers/sendHandlers.ts': '22e2d193f3213ef7feb7ccdbe7c458d02a290614e0716f90096db59aa475be76', 'packages/openmates-python/openmates/__init__.py': '92c0de6bc9c7629ef922060b074295625f84a765d5b270e29f07ce228aa52c25', 'packages/openmates-rust/src/client/browser_draft_tests.rs': 'ec70fec8ec7656400d6c84abd26d7a71f5a7f6ab76466e3c8adf0bd4960b92cc', 'packages/openmates-rust/src/client/browser_owned_message_read_tests.rs': 'be5bc9c7be074559c0bba329896fe40ecd0cf9d7febea6b9c9cea97888b71b88', 'packages/openmates-rust/src/client/completion_recovery/owned_phase_tests.rs': '825c60b185eb7aa0c0f7686fd21643cad4ce7467e8b965a48c13547be353a610', 'packages/openmates-rust/src/client/completion_recovery_owned_checkpoint.rs': '5aadb409cb22c56c34cc70fac20a5aefef88a2e4a801df22689cc623c88caadd', 'packages/openmates-rust/src/client/completion_recovery_owned_phase.rs': '51fff7c0100db8c50874bc9b68aaddec0b443476e2c5f64a2ffd4f8a0809cead', 'packages/openmates-rust/src/client/completion_recovery_phase_runtime.rs': '17847e83d9ede5b85cc328fe0a60bbe726848b15627be673f27d422264751fde', 'packages/openmates-rust/src/client/owned_apps_inventory.rs': '9dccf31232341b3823d3a84f2e622e6b654c8ddd79ebe5f5220f9d1b1feccd6a', 'packages/openmates-rust/src/client/owned_apps_inventory_tests.rs': 'b4ec5280f8e1d6656015755d8bf20d2d356731b26584b98842feb6e7183b41f6', 'packages/openmates-rust/src/client/owned_operation.rs': '94271849b7bf6977f79ca46f9e4f9625e3349c51d29406cb53a4741af8b2752d', 'packages/openmates-rust/src/client/owned_saved_send_phase.rs': 'e76fce756f31c47f3d4cb0204168c362c9fb3e883b02cb4b7acb21da3e81ef5e', 'packages/openmates-rust/src/client/sync/canonical_history.rs': 'a2f062c1390386921f94788eaa0592a5550f5538252691b4d2761b8a0ee8ae4a', 'packages/openmates-rust/src/client/sync/canonical_owned.rs': 'dc3bf7ad5fbe4127aa1f0d84aeb1440355ffab849ba03ec0a6d31d34a88cf6c4', 'packages/openmates-rust/src/client/transport/owned_read.rs': '880c0cb08085291e0118dedbddb374a298da2291502946344080e347f16fac89', 'packages/openmates-session-bindings/src/session_apps_inventory.rs': 'a1c9227ae9bb1d690964b53ca664a4417bdeb8a20f3f72e6e56171eae94daf34', 'scripts/ci_coverage_manifest.json': '3ed2445ddfe297e2f37f5ac568548c9350404656b76b58b6b25eaf76a533352b', 'frontend/packages/openmates-cli/package.json': 'fc2863c6f5c54a0a3c2e56f15a7a91e3cfdb3e3d73a05638cfb3759a3d978737', 'config/sdk-capabilities.json': '73e6a5ac49a524b2aec2f28a15c48aa02a561f18a0bf0eb161d06bb43bd75032'}


def fresh_compiler_source_history(path, raw):
    raw = next_native_sdk_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    actual = getattr(path, 'path', path)
    try:
        relative = Path(actual).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _FRESH_COMPILER_SOURCE_AFTER.get(relative):
        return raw
    for row in fresh_compiler_delta()['sourceInverse']:
        if row['path'] == relative:
            before = row['beforeRaw'].encode()
            assert sdk.sha(before) == row['before_sha256']
            return before
    return raw


class FreshCompilerHistoricalPath:
    def __init__(self, path): self.path = path
    def __truediv__(self, child): return FreshCompilerHistoricalPath(self.path / child)
    def __getattr__(self, name): return getattr(self.path, name)
    def __eq__(self, other): return self.path == getattr(other, 'path', other)
    def __hash__(self): return hash(self.path)
    def __fspath__(self): return str(self.path)
    def __str__(self): return str(self.path)
    def read_bytes(self): return fresh_compiler_source_history(self.path, self.path.read_bytes())
    def read_text(self, encoding='utf-8', errors='strict'): return self.read_bytes().decode(encoding, errors)


def test_fresh_compiler_exact_inverse_held_plans_gaps_and_fourth_closed_witness():
    current = next_native_sdk_history(sdk.load_trust())
    delta = fresh_compiler_delta()
    prior = restore_before_fresh_compiler(current)
    assert delta['beforeSha256'] == '40ddbd54f2659721c4b77d3dc877d22e758b49425d1c605d2ab56d8fe7b23f1a'
    assert current['plan'] == prior['plan'] == delta['originalPlans']
    assert current['gaps'] == prior['gaps'] == delta['originalGaps']
    assert len(current['plan']) == 99 and len(current['gaps']) == 180
    assert {k: len(current[k]) for k in delta['counts']} == delta['counts']
    assert delta['actualRuntimeExecutions'] == 0 and delta['releaseEligible'] is delta['activated'] is False
    assert len(_COMPRESSED_TRUST_WITNESSES) == 8
    assert len(_COMPRESSED_TRUST_WITNESS_BYTES) <= 2
    first = fresh_compiler_delta()
    first['pinDeltas'].clear()
    assert fresh_compiler_delta() == delta
    root = Path(__file__).resolve().parents[2]
    sdk.verify_programs(root, sdk.load_trust())
    for row in delta['sourceInverse']:
        path = root / row['path']
        raw = next_native_sdk_source_history(path, path.read_bytes())
        assert sdk.sha(raw) == row['after_sha256']
        assert fresh_compiler_source_history(path, raw) == row['beforeRaw'].encode()
        assert fresh_compiler_source_history(path, raw + b'\n') == raw + b'\n'
    assert delta['apiCounts'] == {'rust': 2241, 'npm': 1552, 'python': 1186}


@pytest.mark.parametrize('bucket', ['programs', 'contracts', 'plan', 'gaps'])
def test_fresh_compiler_unknown_authority_never_normalizes(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ['programs', 'contracts']:
        wrong[bucket][next(iter(wrong[bucket]))] = '0' * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_fresh_compiler(wrong)
    assert fresh_compiler_history(wrong) == wrong


def test_fresh_baseline_repair_closed_compression_preserves_original_bytes():
    import base64
    import gzip
    name = 'sdk-conformance-trust-baseline-repair-delta.json'
    spec = _COMPRESSED_TRUST_WITNESSES[name]
    path = Path(__file__).with_name('fixtures') / name
    decoded = gzip.decompress(base64.b64decode(json.loads(path.read_bytes())['payload'], validate=True))
    assert len(decoded) == spec[4] and sdk.sha(decoded) == spec[5]
    assert _read_compressed_trust_witness(path, name, spec[5]) == decoded
    first = immutable_trust_test_fixture(name, spec[5])
    first['untrusted_mutation'] = True
    assert immutable_trust_test_fixture(name, spec[5]) == json.loads(decoded)
    assert len(_COMPRESSED_TRUST_WITNESS_BYTES) <= 2


# Closed next-cohort witness. Runtime loaders and release guards remain strict.
def next_native_sdk_delta():
    return immutable_trust_test_fixture('sdk-conformance-trust-next-native-sdk-delta.json', '22389488f4f03140cc03a6e5987322a84c97f14fb8f583d3f5b17dfb432a43be')


def restore_before_next_native_sdk(trust):
    trust = phase1_currentdev_history(trust)
    delta = next_native_sdk_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == delta['afterSha256']
    prior = copy.deepcopy(trust)
    for row in delta['pinDeltas']:
        assert prior[row['bucket']].get(row['path']) == row['after']
        if row['before'] is None:
            del prior[row['bucket']][row['path']]
        else:
            prior[row['bucket']][row['path']] = row['before']
    for row in delta['planDeltas']:
        assert prior['plan'].count(row['after']) == 1
        prior['plan'][prior['plan'].index(row['after'])] = row['before']
    for row in delta['newPlans']:
        assert prior['plan'].count(row) == 1
        prior['plan'].remove(row)
    assert prior['gaps'][-len(delta['newGaps']):] == delta['newGaps']
    del prior['gaps'][-len(delta['newGaps']):]
    assert prior['plan'] == delta['originalPlans'] and prior['gaps'] == delta['originalGaps']
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + '\n').encode()) == delta['beforeSha256']
    return prior


def next_native_sdk_history(trust):
    trust = phase1_currentdev_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == '4f3246c73081cc4040efd314fbfde86b9ba9f8eeae97e0097e3051371fe370f0':
        return restore_before_next_native_sdk(trust)
    return trust


_NEXT_NATIVE_SDK_SOURCE_AFTER = {'frontend/packages/openmates-cli/src/sdk-session-v1-entry.ts': '7ff67b73fb0e95fcda23663615e4b3544b56810c832ac26cc3822213dd38ee28', 'frontend/packages/openmates-cli/src/sdkApiKeyRust.ts': 'd685966590fcf8b0d7afac4b49ff9fe253bb8e6ce885b7da0bbc31c78ecb8b72', 'frontend/packages/openmates-cli/src/sdkSession.ts': 'd61855f045d1f1f1f147af16e25fd3cfbc737b801d10ae007a640ac121c614e3', 'packages/openmates-python/openmates/__init__.py': '1da53299b4c29a01e82ee1c9b98a2596b26d3e0b9fcb66b96cf8ec3710958b4d', 'packages/openmates-python/openmates/rust_api_key.py': '8966f3f1678ee813b1fff7b0050437cab5b610992fe2033082c56507dcabc817', 'packages/openmates-python/openmates/session_client.py': '69b10b8864e2107baea56d7937de230208e992ff13e5e3f1874c419e6a85603f', 'packages/openmates-rust/src/account.rs': '367cc4b9305bfb8e483a5f53777e07bfd5e2f3e99743cfbd9d6a3132539403e7', 'packages/openmates-rust/src/client.rs': '5043a5dcab21cd9077dadb484d3175c43f124377e76062c2901531415c837f71', 'packages/openmates-rust/src/client/transport.rs': '4c2c53afbcc9e20f9c925de56d18cb926e91987c968dfc51622a91f085898ea6', 'packages/openmates-rust/src/work/projects.rs': '777acd687595a5e8f2a18ffbe063b3915994ecb586dcef1a9f557b15c8cb3c6c', 'packages/openmates-session-bindings/examples/session-project-sources-conformance.rs': 'c0c08f03e720fda0152b38b9c23bdcf267ac12af1f307422256dc604f2fd6efc', 'packages/openmates-session-bindings/src/api_key.rs': '9e7f2080f7b592d4398d65d8b37efb3cf441568c951a7e8aa727dce72ee23fc7', 'packages/openmates-session-bindings/src/node.rs': '2d6f88801fd8ea8e7a44d9c66b0f24447e753952efcde3335eaa10d4c307b4bb', 'packages/openmates-session-bindings/src/node_api_key.rs': 'a94090818ea007f88165890dc44307ee87f9c3a84f1da5e598836935ffab62cb', 'packages/openmates-session-bindings/src/python.rs': '04a4fccbe8dfd60a548227e4a74217e92fa47fc51b49d8ecd2157d836965a13e', 'packages/openmates-session-bindings/src/python_api_key.rs': '513fa1e985ac55550d3bc119d4bbebeecba4185a055f9402076d3fd63c9dc187', 'packages/openmates-session-bindings/src/session.rs': '2643e3c8a89cf2d3e197774a5c2a1c05e0f5da1dc694124d4afc741a493b2ec2', 'packages/openmates-session-bindings/src/session_work.rs': 'fb2c527f37309651d82e4f85cc1729eaaa4e9cd88b1fa58949e55d58151da77e', 'scripts/check_sdk_conformance.py': 'f0c75096f221fcd803954bc32e93abf8a9ac5c737b56c94f3922331b35cb4dc8', 'tests/sdk-conformance/runners/session-project-sources.mjs': '1a53b97e5e532915d40c21502b56efed3655c84735807de96f55d66120a4131c', 'tests/sdk-conformance/runners/session-project-sources.py': '08a0f8be98f2b41c12af8c23f99b9f16071e084ad27ce28fc566f36c15cac457', 'tests/sdk-conformance/session_project_sources_server.py': 'e48df42d91709f3b401dcbb06cf3017ef9bc20f69764dadea2f459dc9d7325dc', 'tests/sdk-conformance/test_session_project_sources.py': '6d7342914853a9e4e46597eebb7b2c22f542c253b871d0a97fe796925dbfc49b', 'frontend/packages/openmates-cli/src/sdkProjectSources.ts': '5dabe32726d54c8f06a7dfeddfbd75d924f08ad2cb39a24f1f1157b677c97515', 'frontend/packages/openmates-tui-native/scripts/pty-proof.py': '1258909d325bc8e63b6cc47b831443158e7a4bf1a138f01217d850b8b62d19eb', 'frontend/packages/openmates-tui-native/src/cli/account.rs': 'ce42340b185928989f52dd583184a5f47fb13d19dcce59681e546cd6954cc2bf', 'frontend/packages/openmates-tui-native/src/cli/global_history.rs': '6e5cbcfe87b1b0cdb3442c58e4f1b85b7c309865a4f33e0f39e6564a7011cd87', 'frontend/packages/openmates-tui-native/src/cli/projects.rs': '55817b097642a20a6430947b97669403f88f1a40d1b6368918eec5501b383927', 'frontend/packages/openmates-tui-native/src/ui.rs': 'f7babdf6561a0f8ff8054b2ca1a81b4a4aa89d6a2aef59fbaae2e9aaa881f804', 'packages/openmates-python/openmates/project_sources.py': '081c8006d947cacf5de62dca6e79c0a26c983c46103aef88ba658a435a6393ae', 'config/sdk-capabilities.json': 'b5af71b59f312ecd61237569584bc07d26690069d9b28960b0a905889594dcab', 'tests/sdk-conformance/fixtures/session-project-sources.json': 'bc6f1b92f15f66f1a252e1d8669a8219a38d322f638687a33aafadffcecbd8e2', '.github/workflows/isolated-tests.yml': 'c5db0bc7d182d65f369a32ac122696e2c4cb1ed611911ee77d73c69cfa4448fc', '.github/workflows/selfhost-smoke-rust.yml': '7fe2abca15bc650eea5389e38274ddaa395f41a27d7a9d4285d80ba4fbb00678'}


def next_native_sdk_source_history(path, raw):
    raw = phase1_currentdev_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    actual = getattr(path, 'path', path)
    try:
        relative = Path(actual).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _NEXT_NATIVE_SDK_SOURCE_AFTER.get(relative):
        return raw
    for row in next_native_sdk_delta()['sourceInverse']:
        if row['path'] == relative:
            before = row['beforeRaw'].encode()
            assert sdk.sha(before) == row['before_sha256']
            return before
    return raw


def test_next_native_sdk_exact_source_pins_additive_plans_gaps_and_no_execution(tmp_path):
    delta = next_native_sdk_delta()
    current = phase1_currentdev_history(sdk.load_trust())
    prior = restore_before_next_native_sdk(current)
    assert delta['beforeSha256'] == '4e8fe621943497ea5e4b8d47b24e29b5793b2ebe108e476fbb80f1b129310c4e'
    assert {k: len(current[k]) for k in delta['counts']} == delta['counts']
    assert len(prior['plan']) == 99 and len(current['plan']) == 102
    assert len(prior['gaps']) == 180 and current['gaps'][:180] == prior['gaps'] and len(current['gaps']) == 183
    assert len(delta['planDeltas']) == len(delta['newPlans']) == len(delta['newGaps']) == 3
    assert len([row for row in prior['plan'] if row not in [change['before'] for change in delta['planDeltas']]]) == 96
    for row in delta['planDeltas']:
        before, after = row['before'], row['after']
        assert before['capability'] == after['capability'] == 'session.project-source-authoring.v1'
        assert {k: v for k, v in before.items() if k not in {'fixtureSha256', 'vectors'}} == {k: v for k, v in after.items() if k not in {'fixtureSha256', 'vectors'}}
        assert len(before['vectors']) == 25 and len(after['vectors']) == 36
        assert [value for value in after['vectors'] if value in before['vectors']] == before['vectors']
    assert delta['apiCounts'] == {'rust': 2256, 'npm': 1564, 'python': 1198}
    assert all(row['removed'] == [] for row in delta['apiDelta'].values())
    assert delta['actualRuntimeExecutions'] == 0 and delta['releaseEligible'] is delta['activated'] is False
    assert {k: v for k, v in current.items() if k not in {'programs', 'contracts', 'plan', 'gaps'}} == {k: v for k, v in prior.items() if k not in {'programs', 'contracts', 'plan', 'gaps'}}
    root = Path(__file__).resolve().parents[2]
    sdk.verify_programs(root, sdk.load_trust())
    matrix = json.loads((root / 'config/sdk-capabilities.json').read_bytes())
    actual_root = root
    root = phase1_currentdev_materialized_prior_fixture_root(actual_root, tmp_path / 'next-sdk-prior-fixtures')
    assert sdk.execution_plan(root, matrix) == current['plan']
    root = actual_root
    assert sdk.matrix_gaps(matrix) == current['gaps']
    new = next(row for row in matrix['capabilities'] if row['id'] == 'session.settings-reminders-read')
    assert all(row['status'] == 'partial' and row['conformance'] is True for row in new['languages'].values())
    for row in delta['sourceInverse']:
        path = root / row['path']
        raw = phase1_currentdev_source_history(path, path.read_bytes())
        assert sdk.sha(raw) == row['after_sha256']
        assert next_native_sdk_source_history(path, raw) == row['beforeRaw'].encode()
        assert next_native_sdk_source_history(path, raw + b'\n') == raw + b'\n'
    assert next_native_sdk_source_history(root / 'unknown-next-source', b'unknown') == b'unknown'
    assert len(_COMPRESSED_TRUST_WITNESSES) == 8
    assert len(_COMPRESSED_TRUST_WITNESS_BYTES) <= 2
    first = next_native_sdk_delta()
    first['pinDeltas'].clear()
    assert next_native_sdk_delta() == delta


@pytest.mark.parametrize('bucket', ['programs', 'contracts', 'plan', 'gaps'])
def test_next_native_sdk_unknown_authority_never_normalizes(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ['programs', 'contracts']:
        wrong[bucket][next(iter(wrong[bucket]))] = '0' * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_next_native_sdk(wrong)
    assert next_native_sdk_history(wrong) == wrong


# Fixed prior inventory dependencies were unpinned before fresh compiler admission.
# This view restores only exact known bytes; current source/runtime IO is unchanged.
def full29_inventory_dependency_source_history(path, raw):
    root = Path(__file__).resolve().parents[2]
    actual = getattr(path, 'path', path)
    try:
        relative = Path(actual).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    expected = {'packages/openmates-rust/src/client/focus.rs': '832cbc3cba5957d37a9efb7c71b1d5862356296b2754917e4d9a68e35f5ccd68', 'frontend/packages/openmates-cli/src/cli.ts': 'f7bc6e7afef5186dcfacd16f5188038ff07f9031070428ae4be1393fa0a4ac90', 'frontend/packages/openmates-cli/src/embedRenderers.ts': 'c3b1cd21db3a7b31c96be419cd67e5174d0c4ea43bf1d566db8dacdc5f85fe2a', 'frontend/packages/openmates-cli/src/server.ts': 'e109a9d53a73a957c56c4d51bcae2fc990bbde5ad2f421540750c437bbb51455', 'frontend/packages/openmates-cli/src/serverCaddyUpdate.ts': '9c4b76b5655e7b5ae60c0697382192e6b77aa23fe3ceb82b15e27e12d626869b', 'frontend/packages/openmates-cli/src/serverConfig.ts': '176e33dfbedf3ea00d48bebca2da2d89c1a5c5acaf3c207a17bd689f75e82df2', 'frontend/packages/openmates-cli/src/tuiEmbedPreviews.ts': '827bee15795d2caf63d8a0e4c57525079a0b9bf4af1a327a0312efd53419c4b1', 'frontend/packages/openmates-cli/src/ws.ts': '886a429ce8b61d2413cb289d22ce2e34f66a941a749f8635730a52bd66ee9ced'}
    if sdk.sha(raw) != expected.get(relative):
        return raw
    witness = immutable_trust_test_fixture('sdk-conformance-trust-full29-inventory-dependencies-delta.json', 'd2e44327da4353234386612681a1a2def4df8c63ae31cedd2a76173545c7e797')
    for row in witness['sourceInverse']:
        if row['path'] == relative:
            assert row['afterSha256'] == expected[relative]
            before = row['beforeRaw'].encode()
            assert sdk.sha(before) == row['beforeSha256']
            return before
    return raw


def test_browser_ts_ci_closed_lossless_compression_preserves_exact_original():
    import base64
    import gzip
    name = 'sdk-conformance-trust-browser-ts-ci105-delta.json'
    spec = _COMPRESSED_TRUST_WITNESSES[name]
    path = Path(__file__).with_name('fixtures') / name
    container = path.read_bytes()
    decoded = gzip.decompress(base64.b64decode(json.loads(container)['payload'], validate=True))
    assert len(decoded) == 4627690 and sdk.sha(decoded) == '9154cb9661ad2b9916da253212d15b2daa88ac6db481b7c75cd9532f70dc57bd'
    assert spec[4:] == (len(decoded), sdk.sha(decoded))
    assert _read_compressed_trust_witness(path, name, spec[5]) == decoded
    expected = json.loads(decoded)
    first = browser_ts_ci_delta()
    assert first == expected and first is not expected
    first['sourceInverse'].clear()
    assert browser_ts_ci_delta() == expected
    assert _MAX_COMPRESSED_TRUST_CONTAINER == 8 * 1024**2
    assert _MAX_DECODED_TRUST_WITNESS == 24 * 1024**2
    assert _MAX_CACHED_COMPRESSED_TRUST_WITNESSES == 2
    assert len(_COMPRESSED_TRUST_WITNESS_BYTES) <= 2
    assert all(type(value) is bytes for value in _COMPRESSED_TRUST_WITNESS_BYTES.values())


# sdk.execution_plan uses strict OS reads, so historical fixtures must be real files.
# This temporary tree belongs only to fixed historical plan assertions.
def browser_ts_ci_materialized_historical_root(target, source, matrix, plan, protected, matrix_sha256):
    expected = dict(protected)
    expected['config/sdk-capabilities.json'] = matrix_sha256
    for row in plan:
        previous = expected.setdefault(row['fixture'], row['fixtureSha256'])
        assert previous == row['fixtureSha256']
    fixtures = {row.get('fixture', matrix['fixture']) for row in matrix['capabilities']}
    assert fixtures <= set(expected)
    for relative, digest in expected.items():
        path = Path(relative)
        assert not path.is_absolute() and '..' not in path.parts
        raw = (source / relative).read_bytes()
        assert sdk.sha(raw) == digest
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    return target


# Fixed Phase1/current-dev/canonical-history source-only registration witness.
def phase1_currentdev_delta():
    return immutable_trust_test_fixture('sdk-conformance-trust-phase1-currentdev-history-delta.json', '5cb68db06550428cdb09850ebc7a16d81a9fca382efa8d88428f976e1aca1f07')


def restore_before_phase1_currentdev(trust):
    trust = ancillary_import_history(trust)
    delta = phase1_currentdev_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == delta['afterSha256']
    prior = copy.deepcopy(trust)
    for row in delta['pinDeltas']:
        assert prior[row['bucket']].get(row['path']) == row['after']
        if row['before'] is None:
            del prior[row['bucket']][row['path']]
        else:
            prior[row['bucket']][row['path']] = row['before']
    for row in delta['planDeltas']:
        assert prior['plan'].count(row['after']) == 1
        prior['plan'][prior['plan'].index(row['after'])] = row['before']
    assert prior['plan'] == delta['originalPlans'] and prior['gaps'] == delta['originalGaps']
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + '\n').encode()) == delta['beforeSha256']
    return prior


def phase1_currentdev_history(trust):
    trust = ancillary_import_history(trust)
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == 'bb18462a3c18618ed7f7cbfb1dc7d7e73b51d6861954eecfc76b1004b5ecc571':
        return restore_before_phase1_currentdev(trust)
    return trust


_PHASE1_CURRENTDEV_SOURCE_AFTER = {'packages/openmates-rust/src/client/sync_read_phase_tests.rs': '49044d8da5069cf138eefa836a6c65fb8816bb2ccf1c8da07d763388d7a5b4b0', 'packages/openmates-rust/src/client/sync_windows.rs': 'ec1056e4aac050d73ed07e44fcd2cce658fa8c2e706650f3398d91bd1fb395d3', 'packages/openmates-rust/src/client/sync_windows_tests.rs': '66c5a414f887571732e2e8ec061babba4d983ea30400bf298e84f4e633f4babc', 'packages/openmates-session-bindings/examples/support/essential_session.rs': '99e1bd5d8466b48a160e76fb8052f6202aacab6dd6bb5f809648dda6a8989d6b', 'tests/sdk-conformance/essential_session_server.py': '66e8add79de9c069cee2bc3367d7bdf6ef64279347328d4ec308cf283ecaff3e', 'tests/sdk-conformance/fixtures/session-chat-change-monitor.json': 'd0c2a8b80fdf9d98aed6b7eb04b26e085e0822e750142706db3d313b8da6e03b', 'tests/sdk-conformance/runners/essential-session.mjs': '0ead7de1f99099841e4f3edf2a22c927791cebafc866cb9eeed4a806553784f7', 'tests/sdk-conformance/runners/essential_session.py': '295444ebfacd97060c4f9457862e197bf0df3cf810801d7cecb0fe98fb36e119', 'tests/sdk-conformance/test_essential_session_server.py': 'c0669ac2f2008156d44983d85627e3bdebbb8c1b3c4eeeee19779769f14eacba', 'frontend/packages/ui/src/services/sendersChatMessages.ts': '6d4cd54f6f341638734078f27fc506a92d6a9deae24963359dcfde25b434f128', 'frontend/packages/ui/src/services/embedSenders.ts': '6717fabf0536a6a4b84a48d76daee41ef73cf7bf4d954aaa0d9a22b05ada8d3f', 'frontend/packages/ui/src/services/db/chatKeyManagement.ts': '9e4a95bdd2bcf07ffe95c5429da1870bb92d1597a7b255dee0a71ca31e297057', 'frontend/packages/ui/src/services/streamedEmbedRevisionHistory.ts': '959560538bdcfad639bb24691f9199745339b3ea9234e443b2f1ffe5a6934bf8', 'frontend/packages/ui/src/services/__tests__/embedSendersReceipts.test.ts': 'f1c0fe740870614101cc76a38580c651b523ee716bd057d203bbd5d28681196c', 'frontend/packages/ui/src/services/__tests__/personalChatTurnBarrier.test.ts': 'c364fc5be81b5f527e329c50788adf23fa212d0c6d5b2360b36eacaebd5f85c4', 'frontend/packages/ui/src/services/__tests__/sendersChatMessagesAIResponse.test.ts': 'd70a5bd6af0d8551fc3fe76b72e089712d51d28e27354591c02abc8d468a548e', 'frontend/packages/ui/src/services/__tests__/streamedEmbedRevisionHistory.test.ts': 'cdf83c1aa5aeef80f72c3776d66b389d4c3985173a34f7aea357a471ae20c9bc', 'backend/apps/ai/testing/mock_replay.py': '56857769bf1cfc2b04edf109c149b8e4bc585c939b94cd900c9b9c884ba2dd8a', 'backend/apps/ai/tasks/stream_consumer.py': '8189d762d5bfb24a8db78cbb71d22f7cbe04127196f13fda97ac0f87b868c274', 'backend/apps/ai/tasks/ask_skill_task.py': 'a1c2442c6da25d115013f7a9b922eced33ec295135d1c299ca5024393db52a44', 'backend/core/api/app/routes/handlers/websocket_handlers/cancel_ai_task_handler.py': 'efaf958d4294e411606ed2b5733c876aa3f361f51667d33065740ee802fc530c', 'backend/tests/test_legacy_queued_handoff.py': '9835b52e48f74bdb0b543e8cf219dc550b4376c9d939ab9370c940be6f683829', 'backend/core/api/app/routes/handlers/websocket_handlers/store_embed_diff_handler.py': '3ced2fe8efe2ff7b48ecc782e1daea18e0470edbaac5752fcefb6b5ff2872bca', 'backend/core/api/app/services/embed_version_transaction_service.py': '1defd74de0fcf17b141e1be290fe2e9b5e31c4c43aa7264f1da9dbc33f9bf3ad', 'backend/core/directus/extensions/embed-version-transaction/src/index.js': 'bd320beebd74b5e73ed9046eed929bf51fe0c139c5d067e6169b5f54765a05d3', 'backend/core/directus/extensions/embed-version-transaction/src/operations.js': 'ab6e8f53faea5f4001431c037c3169b73b6b9e18f007e63aea01e397084d39ce', 'backend/core/directus/extensions/embed-version-transaction/test/operations.test.js': '3219f1677f27bfc555274187bbf130591df06cf568002591aaedf2d8edc4b38a', 'backend/tests/test_store_embed_diff_authorization.py': '0461ade3c8bbd9b8bba19e5e0f09b18ccf44c95d88b7eda920727810f920d6f6', 'scripts/ci_coverage_manifest.json': '8e11d4bd844ab56eebccb615ee93cc97ac4936c9cc3f7f2fef017bf05e430d56', 'packages/openmates-rust/src/client/persistence.rs': 'd69ff72ee1000c3f3fd32e35cdecec69063686fe598f09f9bd552eaafa3aa88d', 'packages/openmates-rust/src/client/persistence_opaque_tests.rs': '8cdca9f022575565f7d7128f0eacda8d4df5a8826aca9f87ed3d249a416df5ed', 'packages/openmates-rust/src/client/recovery.rs': '578bcfeccc583bb199dc4e1d82251388e9e1f037f8e99ee67c59af090c0a4b9c', 'packages/openmates-rust/src/client/transport.rs': '16fac4249b30bb9bcf02e0d620bc722943a086d29987ad50c3bec063527aff61', 'frontend/packages/ui/src/services/personalChatTurnBarrier.ts': '57fff97ed0e3aef488aabe1285d4f54d581e61d01d9b975cd542382a12aaedd6', 'packages/openmates-session-bindings/src/api_key.rs': '1fa6ccf019f7eb0de7dc63aa85c72a54a394864cbdd10b46a1f31393f3da8b63'}


def phase1_currentdev_source_history(path, raw):
    raw = ancillary_import_source_history(path, raw)
    root = Path(__file__).resolve().parents[2]
    actual = getattr(path, 'path', path)
    try:
        relative = Path(actual).relative_to(root).as_posix()
    except (TypeError, ValueError):
        return raw
    if sdk.sha(raw) != _PHASE1_CURRENTDEV_SOURCE_AFTER.get(relative):
        return raw
    for row in phase1_currentdev_delta()['sourceInverse']:
        if row['path'] == relative:
            assert row['beforeExists'] is True
            before = row['beforeRaw'].encode()
            assert sdk.sha(before) == row['before_sha256']
            return before
    return raw


def phase1_currentdev_materialized_prior_fixture_root(actual_root, target_root):
    delta = phase1_currentdev_delta()
    expected = {}
    for row in delta['originalPlans']:
        existing = expected.setdefault(row['fixture'], row['fixtureSha256'])
        assert existing == row['fixtureSha256']
    assert 0 < len(expected) <= len(delta['originalPlans']) == 102
    target_root.mkdir(parents=True, exist_ok=False)
    for name, digest in expected.items():
        assert name.startswith('tests/sdk-conformance/fixtures/') and '..' not in Path(name).parts
        raw = phase1_currentdev_source_history(actual_root / name, (actual_root / name).read_bytes())
        assert sdk.sha(raw) == digest
        target = target_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    return target_root


def test_phase1_currentdev_exact_inverse_monitor_only_plans_and_complete_beforeimages():
    delta = phase1_currentdev_delta()
    current = sdk.load_trust()
    prior = restore_before_phase1_currentdev(current)
    assert delta['beforeSha256'] == '4f3246c73081cc4040efd314fbfde86b9ba9f8eeae97e0097e3051371fe370f0'
    assert {k: len(current[k]) for k in delta['counts']} == delta['counts']
    assert current['gaps'] == prior['gaps'] == delta['originalGaps'] and len(current['gaps']) == 183
    assert len(current['plan']) == len(prior['plan']) == 102
    assert len(delta['planDeltas']) == 3 and delta['heldPlanObjects'] == 99
    changed_before = [row['before'] for row in delta['planDeltas']]
    assert [row for row in current['plan'] if row['capability'] != 'session.chat-change-monitor.v1'] == [row for row in prior['plan'] if row not in changed_before]
    for row in delta['planDeltas']:
        old, new = row['before'], row['after']
        assert old['capability'] == new['capability'] == 'session.chat-change-monitor.v1'
        assert {k: v for k, v in old.items() if k not in {'fixtureSha256', 'vectors'}} == {k: v for k, v in new.items() if k not in {'fixtureSha256', 'vectors'}}
        assert len(old['vectors']) == 11 and len(new['vectors']) == 12
        assert [x for x in new['vectors'] if x in old['vectors']] == old['vectors']
        assert set(new['vectors']) - set(old['vectors']) == {'monitor-phase1-all-metadata-content20'}
    assert delta['apiCounts'] == {'rust': 2256, 'npm': 1564, 'python': 1198}
    assert all(row == {'added': [], 'removed': []} for row in delta['apiDelta'].values())
    assert delta['actualRuntimeExecutions'] == 0 and delta['releaseEligible'] is delta['activated'] is False
    assert delta['protectedRunTestsIncluded'] is False
    assert 'scripts/ci_run_tests.py' not in current['programs'] and 'scripts/ci_run_tests.py' not in current['contracts']
    assert {k: v for k, v in current.items() if k not in {'programs', 'contracts', 'plan'}} == {k: v for k, v in prior.items() if k not in {'programs', 'contracts', 'plan'}}
    root = Path(__file__).resolve().parents[2]
    sdk.verify_programs(root, current)
    matrix = json.loads((root / 'config/sdk-capabilities.json').read_bytes())
    assert sdk.execution_plan(root, matrix) == current['plan'] and sdk.matrix_gaps(matrix) == current['gaps']
    for row in delta['sourceInverse']:
        raw = (root / row['path']).read_bytes()
        assert sdk.sha(raw) == row['after_sha256']
        assert row['beforeExists'] is (row['beforeRaw'] is not None)
        if row['beforeExists']:
            assert sdk.sha(row['beforeRaw'].encode()) == row['before_sha256']
            assert phase1_currentdev_source_history(root / row['path'], raw) == row['beforeRaw'].encode()
        else:
            assert row['before_sha256'] is None
        assert phase1_currentdev_source_history(root / row['path'], raw + b'\n') == raw + b'\n'
    assert {row['path'] for row in delta['sourceInverse'] if row['beforeExists'] and not row['previouslyPinned']} == set(delta['newlyPinnedExistingBefore'])
    assert phase1_currentdev_source_history(root / 'unknown-phase1-history', b'unknown') == b'unknown'
    assert _MAX_COMPRESSED_TRUST_CONTAINER == 8 * 1024**2 and _MAX_DECODED_TRUST_WITNESS == 24 * 1024**2
    assert _MAX_CACHED_COMPRESSED_TRUST_WITNESSES == 2 and len(_COMPRESSED_TRUST_WITNESSES) == 8
    first = phase1_currentdev_delta()
    first['sourceInverse'].clear()
    assert phase1_currentdev_delta() == delta


@pytest.mark.parametrize('bucket', ['programs', 'contracts', 'plan', 'gaps'])
def test_phase1_currentdev_unknown_authority_never_normalizes(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ['programs', 'contracts']:
        wrong[bucket][next(iter(wrong[bucket]))] = '0' * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_phase1_currentdev(wrong)
    assert phase1_currentdev_history(wrong) == wrong


def test_phase1_currentdev_prior_fixture_tree_keeps_real_regular_io(tmp_path):
    actual = Path(__file__).resolve().parents[2]
    historical = phase1_currentdev_materialized_prior_fixture_root(actual, tmp_path / 'prior')
    matrix = json.loads((actual / 'config/sdk-capabilities.json').read_bytes())
    assert sdk.execution_plan(historical, matrix) == phase1_currentdev_delta()['originalPlans']
    name = 'tests/sdk-conformance/fixtures/session-chat-change-monitor.json'
    old = sdk.regular(historical / name)
    current = sdk.regular(actual / name)
    assert old != current
    assert len(json.loads(old)['capabilities']['session.chat-change-monitor.v1']['vectors']) == 11
    assert len(json.loads(current)['capabilities']['session.chat-change-monitor.v1']['vectors']) == 12


# One fixed, small, plain tooling witness; compressed registry/bounds stay unchanged.
def ancillary_import_delta():
    return immutable_trust_test_fixture('sdk-conformance-trust-ancillary-import-hygiene-delta.json', 'f8c0130f0469d493967c2b1dae1984887e58cb90a89558a6d6940c4327ff4faa')


def restore_before_ancillary_import(trust):
    delta = ancillary_import_delta()
    assert sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == delta['afterSha256']
    prior = copy.deepcopy(trust)
    assert prior['programs'][delta['path']] == delta['afterProgramSha256']
    prior['programs'][delta['path']] = delta['beforeProgramSha256']
    assert sdk.sha((json.dumps(prior, indent=2, sort_keys=True) + '\n').encode()) == delta['beforeSha256']
    return prior


def ancillary_import_history(trust):
    if sdk.sha((json.dumps(trust, indent=2, sort_keys=True) + '\n').encode()) == '5b4d44475fafbcb4b0a6d39b4cb186f0181e10a0a390494146c32573668e646a':
        return restore_before_ancillary_import(trust)
    return trust


def ancillary_import_source_history(path, raw):
    root = Path(__file__).resolve().parents[2]
    actual = getattr(path, 'path', path)
    if actual != root / 'scripts/tests/test_sdk_session_embed_version_gate.py' or sdk.sha(raw) != '3299d5affc1ee17b37112efb1962facefb5cfa31cca23013ecc00f09a0ec6416':
        return raw
    delta = ancillary_import_delta()
    before = delta['beforeRaw'].encode()
    assert sdk.sha(before) == delta['beforeProgramSha256']
    return before


def test_ancillary_import_hygiene_exact_pin_only_inverse_and_real_source():
    current = sdk.load_trust()
    delta = ancillary_import_delta()
    prior = restore_before_ancillary_import(current)
    assert delta['beforeSha256'] == 'bb18462a3c18618ed7f7cbfb1dc7d7e73b51d6861954eecfc76b1004b5ecc571'
    assert {key: len(current[key]) for key in delta['counts']} == {'programs': 744, 'contracts': 124, 'plan': 102, 'gaps': 183}
    assert {key: value for key, value in current.items() if key != 'programs'} == {key: value for key, value in prior.items() if key != 'programs'}
    assert {name for name in current['programs'] if current['programs'][name] != prior['programs'].get(name)} == {delta['path']}
    assert delta['productAPIChanged'] is False and delta['runtimeExecutions'] == 0
    root = Path(__file__).resolve().parents[2]
    sdk.verify_programs(root, current)
    actual = (root / delta['path']).read_bytes()
    assert sdk.sha(actual) == delta['afterProgramSha256']
    assert ancillary_import_source_history(root / delta['path'], actual) == delta['beforeRaw'].encode()
    assert ancillary_import_source_history(root / delta['path'], actual + b'\n') == actual + b'\n'
    assert ancillary_import_source_history(root / 'unknown-import-history', actual) == actual
    assert len(_COMPRESSED_TRUST_WITNESSES) == 8 and _MAX_CACHED_COMPRESSED_TRUST_WITNESSES == 2


@pytest.mark.parametrize('bucket', ['programs', 'contracts', 'plan', 'gaps'])
def test_ancillary_import_hygiene_unknown_authority_refuses(bucket):
    wrong = copy.deepcopy(sdk.load_trust())
    if bucket in ['programs', 'contracts']:
        wrong[bucket][next(iter(wrong[bucket]))] = '0' * 64
    else:
        wrong[bucket].pop()
    with pytest.raises(AssertionError):
        restore_before_ancillary_import(wrong)
    assert ancillary_import_history(wrong) == wrong


def require_fixed_historical_manifest(raw, expected):
    assert sdk.sha(raw) == expected
