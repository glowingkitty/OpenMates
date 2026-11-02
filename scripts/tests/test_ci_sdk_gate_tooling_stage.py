# contract-test-file: tooling
"""Fixed isolated tooling stage; synthetic recipe only, no SDK/build/product/CI."""

import json
import os
from pathlib import Path
import sys
import time
import pytest
from scripts import ci_sdk_conformance as sdk
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "sdk_recipe_test_helpers", Path(__file__).with_name("test_ci_sdk_conformance.py")
)
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
gate_fixture = _helpers.gate_fixture
synthetic_trust = _helpers.synthetic_trust

UNIT = "scripts/tests/test_sdk_conformance_gate.py"
ORDER = [
    "rust-toolchain",
    "python-environment",
    "node-dependencies",
    "python-dependencies",
    "sdk-library-units",
    "binding-library-units",
    "napi-build",
    "python-binding-build",
    "sdk-facade-build",
    "sdk-gate-tooling",
    "napi-load",
    "python-load",
    "real-conformance",
]


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "child_failed",
        "stage_deadline",
        "deadline",
        "source_before",
        "source_after",
        "program_before",
        "program_after",
        "helper_before",
        "helper_after",
        "contract_before",
        "contract_after",
        "unpinned",
    ],
)
def test_actual_recipe_fixed_tooling_stage_is_fenced_and_blocks_later_product_stages(
    tmp_path, monkeypatch, fault
):
    root, gate = gate_fixture(tmp_path)
    (root / "test-results").mkdir()
    unit = root / UNIT
    unit.parent.mkdir(parents=True)
    unit.write_text("# synthetic pinned tooling fixture\n")
    helper = root / "fixed-helper.py"
    helper.write_text("# separately pinned import fixture\n")
    trust = synthetic_trust(root)
    trust["programs"] = {"fixed-helper.py": sdk.sha(helper.read_bytes())}
    if fault != "unpinned":
        trust["programs"][UNIT] = sdk.sha(unit.read_bytes())
    gate["trustedProgramsSha256"] = sdk.sha(
        json.dumps(trust["programs"], sort_keys=True).encode()
    )
    monkeypatch.setattr(sdk, "load_trust", lambda: trust)
    if hasattr(sdk, "load_trust_for_source"):
        monkeypatch.setattr(sdk, "load_trust_for_source", lambda *args, **kwargs: trust)
    pyproject = root / "packages/openmates-python/pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text("[project]\ndependencies=[]\n")
    monkeypatch.setattr(sdk.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        sdk, "git", lambda root, *args: "a" * 40 if args[-1] == "HEAD" else "b" * 40
    )
    monkeypatch.setattr(
        sdk.subprocess, "run", lambda *a, **k: type("Result", (), {"returncode": 1})()
    )
    monkeypatch.setattr(sdk.shutil, "which", lambda name: "/synthetic/tools/" + name)
    inputs = {name: "c" * 64 for name in sdk.LOCKS}
    inputs[UNIT] = sdk.sha(unit.read_bytes())
    monkeypatch.setattr(sdk, "snapshot", lambda root: dict(inputs))
    monkeypatch.setattr(
        sdk, "source_inputs_from_git", lambda root, source: dict(inputs)
    )
    began = time.monotonic()
    environment = {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "OPENMATES_CI_ISOLATED": "1",
        "BUILD_COMMIT_SHA": "a" * 40,
        "CI_CANDIDATE_TREE": "b" * 40,
        "CI_SPECS_JSON": json.dumps([sdk.TARGET]),
        "CI_SDK_STARTED_MONOTONIC": str(began),
        "CI_SDK_DEADLINE_MONOTONIC": str(began + sdk.BUDGET),
        "GITHUB_RUN_ID": "123",
        "CI_HARNESS_COMMIT": "d" * 40,
    }
    node = root / "frontend/packages/openmates-cli/native/linux-x64.node"
    py = root / "packages/openmates-python/openmates/_native.abi3.so"
    blob = bytearray(96)
    blob[:6] = b"\x7fELF\x02\x01"
    blob[18:20] = (62).to_bytes(2, "little")
    calls = []
    fences = []
    command_environments = []
    verify = sdk.verify_programs

    def checked(root, trust):
        fences.append(len(calls))
        return verify(root, trust)

    monkeypatch.setattr(sdk, "verify_programs", checked)

    def command(self, stage, argv, **kwargs):
        self.check()
        command_environments.append(self.env)
        calls.append((stage, argv))
        self.steps.append({"stage": stage, "status": "passed"})
        assert (self.env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD") == "1") == (
            stage == "sdk-gate-tooling"
        )
        assert not {
            "NODE_OPTIONS",
            "NODE_PATH",
            "OPENMATES_API_KEY",
            "GH_TOKEN",
        }.intersection(self.env)
        if stage == "napi-build":
            node.parent.mkdir(parents=True)
            node.write_bytes(blob)
        elif stage == "python-binding-build":
            py.parent.mkdir(parents=True)
            py.write_bytes(blob + b"python")
        elif stage == "sdk-facade-build":
            dist = root / "frontend/packages/openmates-cli/dist"
            dist.mkdir()
            (dist / "sdk-entry.js").write_bytes(b"fixture")
            if fault == "source_before":
                inputs["mutated"] = "f" * 64
            if fault == "program_before":
                unit.write_text("# changed\n")
            if fault == "helper_before":
                helper.write_text("# changed\n")
            if fault == "contract_before":
                (root / "config/sdk-capabilities.json").write_text("{}")
        elif stage == "sdk-gate-tooling":
            assert argv == [
                str(self.private / "venv/bin/python"),
                "-m",
                "pytest",
                "--noconftest",
                "-q",
                "-p",
                "no:cacheprovider",
                UNIT,
            ]
            assert kwargs == {"seconds": 60} and sdk.command_tool(stage) == "python"
            assert (
                self.deadline == began + sdk.BUDGET
                and sdk.BUDGET == 2700
                and sdk.RESERVE == 2 * 1024**3
            )
            if fault in {"child_failed", "stage_deadline"}:
                raise sdk.Refused(fault)
            if fault == "deadline":
                self.deadline = time.monotonic() - 1
                self.check()
            if fault == "source_after":
                inputs["mutated"] = "f" * 64
            if fault == "program_after":
                unit.write_text("# changed\n")
            if fault == "helper_after":
                helper.write_text("# changed\n")
            if fault == "contract_after":
                (root / "config/sdk-capabilities.json").write_text("{}")
        elif stage == "real-conformance":
            gate["packagedSdkV1"]["nativeSha256"] = sdk.sha(node.read_bytes())
            Path(argv[3]).write_text(json.dumps(gate))

    monkeypatch.setattr(sdk.Commands, "run", command)
    results = []
    sdk.run(
        root, results, "/synthetic/node", environ=environment, verify_node=lambda: None
    )
    assert all(
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in env for env in command_environments
    )
    evidence = json.loads((root / "test-results/ci-sdk-conformance.json").read_text())
    stages = [a for a, _ in calls]
    assert evidence["cleanupVerified"] is True and not list(
        (root / "test-results/ci-private").iterdir()
    )
    if fault is None:
        assert (
            stages == ORDER
            and evidence["status"] == "passed"
            and results[0]["exit_code"] == 0
        )
        assert (
            9 in fences and 10 in fences
        )  # full real PROGRAM/CONTRACT fences bracket actual stage
    else:
        expected = {
            "source_before": "source_changed",
            "source_after": "source_changed",
            "program_before": "reviewed_program_changed",
            "program_after": "reviewed_program_changed",
            "helper_before": "reviewed_program_changed",
            "helper_after": "reviewed_program_changed",
            "contract_before": "reviewed_contract_changed",
            "contract_after": "reviewed_contract_changed",
            "unpinned": "tooling_test_unpinned",
        }.get(fault, fault)
        assert (
            evidence["status"] == "failed"
            and evidence["code"] == expected
            and results[0]["exit_code"] == 1
        )
        assert not {"napi-load", "python-load", "real-conformance"}.intersection(stages)
        if fault in {
            "source_before",
            "program_before",
            "helper_before",
            "contract_before",
            "unpinned",
        }:
            assert "sdk-gate-tooling" not in stages


def test_tooling_stage_admits_only_current_managed_python_image(tmp_path):
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "--noconftest",
        "-q",
        "-p",
        "no:cacheprovider",
        UNIT,
    ]
    with sdk.admitted_command("sdk-gate-tooling", argv, {"PATH": os.defpath}) as entry:
        assert entry.python and entry.metadata["tool"] == "python"
        assert entry.metadata["admission"] == "current-python-kernel-fd"
        assert (
            entry.metadata["executableKind"] == "elf"
            and len(entry.metadata["executableSha256"]) == 64
        )
        entry.held()
    shell = tmp_path / "python"
    shell.write_text("#!/bin/sh\nexit 0\n")
    shell.chmod(0o700)
    with pytest.raises(sdk.Refused):
        with sdk.admitted_command(
            "sdk-gate-tooling", [str(shell), "-m", "pytest", UNIT], {"PATH": os.defpath}
        ):
            pass


def test_original_global_deadline_refuses_before_any_tooling_launch(
    tmp_path, monkeypatch
):
    commands = sdk.Commands(
        tmp_path, tmp_path, {"PATH": os.defpath}, time.monotonic() - 1
    )
    monkeypatch.setattr(
        sdk.subprocess,
        "Popen",
        lambda *a, **k: pytest.fail("deadline must prevent launch"),
    )
    with pytest.raises(sdk.Refused, match="^deadline$"):
        commands.run(
            "sdk-gate-tooling", [sys.executable, "-m", "pytest", UNIT], seconds=60
        )
    assert commands.steps == []


@pytest.mark.parametrize(
    "nested",
    [
        "frontend/apps/web_app/tests/helpers/native-embed-command-diagnostic.cjs",
        "frontend/packages/openmates-tui-native/tests/fixtures/chats-show-json.schema.json",
        "frontend/packages/openmates-tui-native/src/list_stage_diagnostic.rs",
    ],
)
@pytest.mark.parametrize("fault", ["missing", "tamper", "untracked"])
def test_actual_snapshot_fences_nested_vm_fixture_and_rust_text_inputs(
    tmp_path, monkeypatch, nested, fault
):
    names = [*sdk.LOCKS, "scripts/check_sdk_conformance.py", nested]
    assert any(nested == p or nested.startswith(p + "/") for p in sdk.TOOLING_INPUTS)
    for name in names:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"original fixed source")
    monkeypatch.setattr(sdk, "git", lambda *_: "")

    def listing(argv, **kwargs):
        assert (
            argv == ["git", "ls-files", "-z", "--", *sdk.INPUTS]
            and kwargs["cwd"] == tmp_path
        )
        return ("\0".join(names) + "\0").encode()

    monkeypatch.setattr(sdk.subprocess, "check_output", listing)
    before = sdk.snapshot(tmp_path)
    assert nested in before
    if fault == "missing":
        (tmp_path / nested).unlink()
        with pytest.raises(OSError):
            sdk.snapshot(tmp_path)
    elif fault == "tamper":
        (tmp_path / nested).write_bytes(b"changed fixed source")
        assert sdk.snapshot(tmp_path) != before
    else:
        monkeypatch.setattr(sdk, "git", lambda *_: "new-untracked-input")
        with pytest.raises(sdk.Refused, match="^untracked_source_input$"):
            sdk.snapshot(tmp_path)


@pytest.mark.parametrize("implicit", ["conftest", "entrypoint-plugin"])
def test_actual_pytest_isolates_implicit_unpinned_code(tmp_path, implicit):
    import subprocess

    unit = tmp_path / "test_fixed.py"
    unit.write_text("def test_fixed():\n    assert True\n")
    marker = tmp_path / "implicit-code-ran"
    if implicit == "conftest":
        (tmp_path / "conftest.py").write_text(
            "from pathlib import Path\nPath("
            + repr(str(marker))
            + ').write_text("ran")\nraise RuntimeError("implicit")\n'
        )
    else:
        (tmp_path / "unbound_plugin.py").write_text(
            "from pathlib import Path\nPath("
            + repr(str(marker))
            + ').write_text("ran")\nraise RuntimeError("implicit")\n'
        )
        dist = tmp_path / "unbound_plugin-1.0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: unbound-plugin\nVersion: 1.0\n"
        )
        (dist / "entry_points.txt").write_text(
            "[pytest11]\nunbound_plugin = unbound_plugin\n"
        )
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "--noconftest",
        "-q",
        "-p",
        "no:cacheprovider",
        str(unit),
    ]
    environment = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }
    fixed = subprocess.run(
        argv, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10
    )
    assert fixed.returncode == 0 and not marker.exists()
    # Negative control proves the synthetic implicit-code fixture is discoverable.
    if implicit == "conftest":
        argv.remove("--noconftest")
    else:
        environment.pop("PYTEST_DISABLE_PLUGIN_AUTOLOAD")
    unsafe = subprocess.run(
        argv, cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=10
    )
    assert unsafe.returncode != 0 and marker.read_text() == "ran"
