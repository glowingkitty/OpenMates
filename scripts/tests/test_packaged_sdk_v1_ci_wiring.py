# contract-test-file: tooling
"""INERT CI wiring/receipt fixtures only; no package/native/product execution."""
import ast
import hashlib
import json
from pathlib import Path
import types
import pytest
from scripts import ci_sdk_conformance as sdk
from scripts import ci_sdk_conformance_exec as executor
from scripts.ci_results import valid_sdk_conformance_receipt
from test_ci_sdk_conformance import gate_fixture, synthetic_trust, green_sdk_evidence


@pytest.mark.parametrize("fault", [None, "missing_archive", "duplicate_archive", "wrong_native", "changed_archive", "child_failure", "missing_barrel"])
def test_fixed_real_package_commands_are_mandatory_but_inert_here(tmp_path, monkeypatch, fault):
    root = tmp_path / "subject"
    package = root / "frontend/packages/openmates-cli"
    (package / "dist").mkdir(parents=True)
    (package / "native").mkdir()
    if fault != "missing_barrel":
        (package / "dist/sdk-session-v1-entry.js").write_bytes(b"INERT built barrel DATA")
    (package / "dist/sdk-session-v1-entry.d.ts").write_bytes(b"INERT types DATA")
    native = b"INERT native DATA never loaded"
    (package / "native/linux-x64.node").write_bytes(native)
    private = tmp_path / "private"
    private.mkdir()
    calls = []
    monkeypatch.setattr(executor.shutil, "which", lambda *a, **k: "/synthetic/npm")
    monkeypatch.setattr(executor, "verify_programs", lambda *args: None)
    class InertDriver:
        def __init__(self):
            self.root, self.trust = root, {}
        def run(self, command, **options):
            calls.append((command, options))
            assert options == {"cwd": root, "capture_output": True, "text": True, "timeout": 120 if len(calls) == 1 else 300}
            if fault == "child_failure":
                raise sdk.Refused("driver_failed")
            if len(calls) == 1:
                assert command == ["/synthetic/npm", "pack", str(package), "--ignore-scripts", "--json", "--pack-destination", str(private / "sdk-v1-package")]
                if fault != "missing_archive":
                    (private / "sdk-v1-package/actual.tgz").write_bytes(b"INERT archive DATA never extracted")
                if fault == "duplicate_archive":
                    (private / "sdk-v1-package/extra.tgz").write_bytes(b"INERT duplicate")
            else:
                assert command[1] == str(root / "scripts/check_packaged_sdk_v1.py")
                assert command[2:] == [str(private / "sdk-v1-package/actual.tgz"), "--output", str(private / "packaged-sdk-v1.json")]
                data = (private / "sdk-v1-package/actual.tgz").read_bytes()
                report = {"artifactSha256": sdk.sha(data), "nativeSha256": sdk.sha(native) if fault != "wrong_native" else "e" * 64}
                (private / "packaged-sdk-v1.json").write_text(json.dumps(report))
                if fault == "changed_archive":
                    (private / "sdk-v1-package/actual.tgz").write_bytes(b"changed")
            return types.SimpleNamespace(returncode=0)
    if fault is None:
        actual = executor.run_packaged_sdk_v1(InertDriver(), private / "gate.json")
        assert actual["nativeSha256"] == sdk.sha(native)
        assert len(calls) == 2
    else:
        with pytest.raises(sdk.Refused):
            executor.run_packaged_sdk_v1(InertDriver(), private / "gate.json")
        if fault in {"missing_archive", "duplicate_archive", "missing_barrel", "child_failure"}:
            assert len(calls) < 2


@pytest.mark.parametrize("fault", ["missing", "reordered_ids", "wrong_fixture", "wrong_entrypoint", "wrong_adapter", "ambient_read", "CLI", "raw_trace", "no_explicit_credentials"])
def test_producer_never_projects_missing_or_weakened_packaging_evidence(tmp_path, fault):
    root, report = gate_fixture(tmp_path)
    value = report["packagedSdkV1"]
    if fault == "missing":
        value = None
    elif fault == "reordered_ids":
        value["vectorIds"].reverse()
    else:
        key, replacement = {"wrong_fixture": ("fixtureSha256", "a" * 64), "wrong_entrypoint": ("entrypoint", "openmates/sdk"), "wrong_adapter": ("nativeAdapter", "fixture"), "ambient_read": ("ambientSyntheticCliStateAccess", True), "CLI": ("cliLauncherObserved", True), "raw_trace": ("rawTracePublished", True), "no_explicit_credentials": ("explicitFixtureCredentials", False)}[fault]
        value[key] = replacement
    with pytest.raises(sdk.Refused):
        sdk.packaged_sdk_v1_receipt(root, value, trust=synthetic_trust(root))


@pytest.mark.parametrize("fault", ["missing", "wrong_native", "wrong_count", "boolean_count", "ambient_read", "wrong_fixture", "CLI", "wrong_digest", "reordered_digest"])
def test_actual_retriever_requires_separate_closed_packaging_proof(tmp_path, fault):
    report, evidence, job, expectation = green_sdk_evidence(tmp_path)
    assert valid_sdk_conformance_receipt(report, evidence, job, "b" * 40, **expectation)
    packaged = evidence["gate"]["packagedSdkV1"]
    if fault == "missing":
        del evidence["gate"]["packagedSdkV1"]
    else:
        key, value = {"wrong_native": ("nativeSha256", "e" * 64), "wrong_count": ("vectorCount", 22), "boolean_count": ("vectorCount", True), "ambient_read": ("ambientSyntheticCliStateAccess", True), "wrong_fixture": ("fixtureSha256", "e" * 64), "CLI": ("cliLauncherObserved", True), "wrong_digest": ("vectorIdsSha256", "a" * 64), "reordered_digest": ("vectorIdsSha256", hashlib.sha256(json.dumps([row["id"] for row in reversed(json.loads(expectation["expected_packaged_fixture"])["capabilities"]["sdk.configuration"]["vectors"])], separators=(",", ":")).encode()).hexdigest())}[fault]
        packaged[key] = value
    assert not valid_sdk_conformance_receipt(report, evidence, job, "b" * 40, **expectation)


def test_direct_release_cannot_claim_missing_managed_packaging_provenance(tmp_path):
    source = Path(__file__).resolve().parents[2] / "scripts/check_sdk_conformance.py"
    function = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == "run")
    module = ast.Module(body=[function], type_ignores=[])
    namespace = {"Path": Path, "ROOT": tmp_path, "MATRIX": "matrix.json", "json": json, "hashlib": hashlib,
        "check_generated": lambda root: None, "discover_inventory": lambda root: {}, "validate_matrix": lambda *args: [], "conformance": lambda *args: []}
    (tmp_path / "matrix.json").write_text("{}")
    # This fixture deliberately has no managed execution; it cannot authorize
    # release. A separate positive fixture verifies the actual fixed-call seam.
    namespace["verified_packaged_sdk_v1_release"] = lambda root: (_ for _ in ()).throw(ValueError("SDK publication requires managed isolated CI packaged openmates/sdk/v1 evidence"))
    exec(compile(module, "inert-release-policy", "exec"), namespace)
    with pytest.raises(ValueError, match="managed isolated CI packaged openmates/sdk/v1 evidence"):
        namespace["run"](release=True, root=tmp_path)
