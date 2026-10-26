# contract-test-file: tooling
"""Pure supplier/profile tests. No Cargo, frontend build, account or browser IO."""
import ast
import hashlib
import importlib.util
import json
from itertools import permutations
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]

def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

lane = load("scripts.ci_rust_wasm", "ci_rust_wasm.py")
load("scripts.ci_results", "ci_results.py")
supplier = load("scripts.ci_production_rust_browser", "ci_production_rust_browser.py")

def environment():
    return {"GITHUB_ACTIONS":"true", "RUNNER_ENVIRONMENT":"github-hosted", "OPENMATES_CI_ISOLATED":"1",
        "CI_TEST_MODE":"e2e", "CI_SPECS_JSON":json.dumps([supplier.SPEC])}

@pytest.mark.parametrize("targets", [[], [lane.BROWSER_SPEC], [supplier.SPEC, lane.BROWSER_SPEC],
    ["nested/"+supplier.SPEC], ["rust-core-production-saved-session-extra.spec.ts"]])
def test_supplier_rejects_every_nonexact_spec_or_batch(targets):
    ambient = {**environment(), "CI_SPECS_JSON":json.dumps(targets)}
    with pytest.raises(lane.sdk.Refused):
        supplier.require_selector(ambient)

@pytest.mark.parametrize("key,value", [("GITHUB_ACTIONS","false"),("RUNNER_ENVIRONMENT","self-hosted"),
    ("OPENMATES_CI_ISOLATED","0"),("CI_TEST_MODE","component"),("CI_CASE_TITLE","partial"),
    ("CI_CAPACITY_CONFIGURATION","unrelated")])
def test_supplier_requires_existing_isolated_profile_guards(key, value):
    with pytest.raises(lane.sdk.Refused):
        supplier.require_selector({**environment(), key:value})

def source_fixture(root):
    expected = {}
    for crate in ("packages/openmates-rust", "packages/openmates-browser-bindings"):
        for name in ("Cargo.toml", "Cargo.lock", "src/lib.rs"):
            path = root / crate / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((crate+name).encode())
            expected[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return expected

def test_projection_preserves_compiler_bytes_and_plugin_exact_receipt_shape():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        expected = source_fixture(root)
        files = {"openmates_browser.js":b"export const synthetic=true;", "openmates_browser_bg.wasm":b"\0asm\x01\0\0\0", "openmates_browser.d.ts":b"export {};"}
        manifest = {"target":"wasm32-unknown-unknown", "toolchain":"1.98.1", "wasmBindgenVersion":"0.2.129", "inputWasmSha256":"a"*64, "toolSha256":"b"*64}
        projected = json.loads(supplier.project_receipt(root, manifest, expected, files))
        assert projected["browserExecutionVerified"] is False and projected["applicationActivated"] is False
        assert projected["sourceInputs"] == {name:{"sha256":digest,"bytes":len((root/name).read_bytes())} for name,digest in expected.items()}
        rows = projected["inventory"]["files"]
        assert projected["inventory"]["inventorySha256"] == hashlib.sha256(json.dumps(rows,separators=(",", ":")).encode()).hexdigest()
        assert {row["path"]:row["sha256"] for row in rows} == {name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}
        (root/"packages/openmates-rust/src/lib.rs").write_bytes(b"mutated")
        with pytest.raises(lane.sdk.Refused):
            supplier.project_receipt(root, manifest, expected, files)

@pytest.mark.parametrize("fault", ["unattested-source", "root-config", "symlink-source"])
def test_projection_refuses_inputs_the_original_compiler_did_not_attest(fault):
    with TemporaryDirectory() as directory:
        root = Path(directory)
        expected = source_fixture(root)
        path = root / "packages/openmates-rust/src/extra.rs"
        if fault == "unattested-source":
            path.write_bytes(b"unattested")
        elif fault == "root-config":
            path = root / ".cargo/config.toml"
            path.parent.mkdir()
            path.write_bytes(b"[build]")
        else:
            path.symlink_to(root / "packages/openmates-rust/src/lib.rs")
        with pytest.raises(lane.sdk.Refused):
            supplier.project_receipt(root, {}, expected, {})

def test_fresh_destination_refuses_preexisting_or_symlinked_projection():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        destination = root / supplier.DESTINATION
        destination.parent.mkdir()
        destination.symlink_to(root, target_is_directory=True)
        with pytest.raises(lane.sdk.Refused):
            supplier.safe_destination(root, fresh=True)
        destination.unlink()
        destination.mkdir()
        with pytest.raises(lane.sdk.Refused):
            supplier.safe_destination(root, fresh=True)

def test_build_uses_exact_child_only_optin_and_verifies_before_and_after():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        ambient = {**environment(), "OPENMATES_RUST_CORE_ARTIFACT":"a"*64,
            "OPENMATES_RUST_CORE_ASSETS":"caller-controlled", "OPENMATES_RUST_CORE_MANIFEST":"/wrong"}
        unchanged = dict(ambient)
        with patch.object(supplier, "verify_for_e2e") as verify, patch.object(supplier.subprocess,"run") as command:
            supplier.build(root, ambient)
        assert ambient == unchanged
        assert verify.call_count == 2
        args, kwargs = command.call_args
        assert args[0] == ["pnpm","--dir","frontend/apps/web_app","exec","vite","build"]
        assert kwargs["env"]["OPENMATES_RUST_CORE_ASSETS"] == "1"
        assert kwargs["env"]["OPENMATES_RUST_CORE_MANIFEST"] == str(root/supplier.DESTINATION/"receipt.json")
        assert kwargs["timeout"] == 900 and kwargs["check"] is True

def test_workflow_forces_fresh_build_and_preserves_ordinary_supplier_order_and_limits():
    steps = next(iter(yaml.safe_load((ROOT/".github/workflows/isolated-tests.yml").read_text())["jobs"].values()))["steps"]
    named = {step.get("name"):step for step in steps}
    prepare = named["Prepare exact production-loader browser package"]
    assert prepare["if"] == "inputs.mode == 'e2e' && " + production_workflow_predicate()
    assert steps.index(prepare) < steps.index(named["Build local web app"])
    assert supplier.SPEC in named["Build local web app"]["if"]
    assert supplier.SPEC in named["Generate UI build inputs once"]["if"]
    assert "ci_production_rust_browser.py build" in named["Build local web app"]["run"]
    assert "pnpm --dir frontend/apps/web_app exec vite build" in named["Build local web app"]["run"]
    assert "OPENMATES_RUST_CORE_ASSETS" not in json.dumps(named)
    assert lane.BROWSER_BUDGET == 1800 and lane.BUDGET == 2700
    source = (ROOT/"scripts/ci_run_tests.py").read_text()
    run = next(node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef) and node.name=="run_e2e")
    segment = ast.get_source_segment(source,run)
    assert segment.index("verify_for_e2e(ROOT)") < segment.index("subprocess.Popen")
    assert 'if production_browser:' in segment
    assert 'len(specs) != 1 or artifact or component or visual_smoke or case_title' in segment
    environment_source = (ROOT/"scripts/ci_environment.py").read_text()
    private = next(node for node in ast.parse(environment_source).body if isinstance(node,ast.Assign)
        and any(isinstance(target,ast.Name) and target.id=="PRIVATE_BACKEND_SPECS" for target in node.targets))
    assert supplier.SPEC in ast.literal_eval(private.value.args[0])
    assert supplier.SPEC in source[source.index("MARKER_CHAT_EPOCH_SPECS"):source.index("BILLING_STORAGE_PROFILES")]

@pytest.mark.parametrize("fault", [None,"receipt-pin","manifest-pin","package-bytes","source-changed",
    "receipt-source","receipt-harness","receipt-run","receipt-inputs","receipt-locks","receipt-stages","receipt-argv","receipt-release"])
def test_reuse_retains_full_existing_package_provenance_without_second_compile(fault):
    fixture_module = load("production_supplier_wasm_fixture", "tests/test_ci_rust_wasm.py")
    _, receipt, _, kwargs = fixture_module.WasmReceiptTests().fixture()
    receipt.update(runtime_profile="rust-browser-package-for-e2e", requestedMode="e2e", requestedTargets=[supplier.SPEC])
    receipt["workerProof"] = None
    receipt["steps"] = receipt["steps"][:len(lane.STAGES)]
    manifest = json.loads(kwargs["package_manifest"])
    manifest.update(requestedMode="e2e", requestedTargets=[supplier.SPEC])
    manifest_bytes = json.dumps(manifest).encode()
    receipt["package"]["manifestSha256"] = hashlib.sha256(manifest_bytes).hexdigest()
    if fault is not None and fault.startswith("receipt-") and fault != "receipt-pin":
        import copy
        receipt = copy.deepcopy(receipt)
        corrupt_compiler_receipt(receipt, {"receipt-source":"source_commit", "receipt-harness":"harness_commit",
            "receipt-run":"run_id", "receipt-inputs":"inputSetSha256", "receipt-locks":"lock_3",
            "receipt-stages":"steps_missing", "receipt-argv":"argv_2", "receipt-release":"releaseProof"}[fault])
    receipt_bytes = json.dumps(receipt).encode()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        folder = root/"test-results/rust-wasm"
        (folder/"package").mkdir(parents=True)
        (root/"test-results/ci-rust-wasm.json").write_bytes(receipt_bytes)
        (folder/"package-manifest.json").write_bytes(manifest_bytes)
        (folder/lane.WASM_NAME).write_bytes(fixture_module.WASM)
        for name, raw in kwargs["package_files"].items():
            path = folder/"package"/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw)
        projected = b'{"synthetic_projection":true}'
        destination = root/supplier.DESTINATION
        (destination/"pkg").mkdir(parents=True)
        (destination/"receipt.json").write_bytes(projected)
        for name,raw in kwargs["package_files"].items():
            path=destination/"pkg"/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw)
        for directory_path in [folder/"package", destination/"pkg"]:
            directory_path.chmod(0o700)
            for child in directory_path.rglob("*"):
                if child.is_dir():
                    child.chmod(0o700)
                else:
                    child.chmod(0o600)
        ambient = {**environment(), "BUILD_COMMIT_SHA":"d"*40,"CI_CANDIDATE_TREE":"e"*40,
            "GITHUB_RUN_ID":"123","CI_HARNESS_COMMIT":"f"*40,
            supplier.RECEIPT_PIN:hashlib.sha256(receipt_bytes).hexdigest(),
            "OPENMATES_BROWSER_PACKAGE_MANIFEST_SHA256":hashlib.sha256(manifest_bytes).hexdigest(),
            "OPENMATES_RUST_CORE_ARTIFACT":hashlib.sha256(projected).hexdigest()}
        if fault=="receipt-pin":
            ambient[supplier.RECEIPT_PIN]="0"*64
        elif fault=="manifest-pin":
            ambient["OPENMATES_BROWSER_PACKAGE_MANIFEST_SHA256"]="0"*64
        elif fault=="package-bytes":
            (folder/"package"/lane.PACKAGE_FILES[0]).write_bytes(b"altered")
        def git(_root,*args):
            return "e"*40 if args[-1]=="HEAD^{tree}" else "d"*40
        with patch.object(lane.sdk,"git",side_effect=git), patch.object(lane,"source_inputs_from_git",return_value=kwargs["expected_inputs"]), \
             patch.object(lane,"snapshot",return_value={} if fault=="source-changed" else kwargs["expected_inputs"]), \
             patch.object(supplier,"project_receipt",return_value=projected), patch.object(lane,"run") as compile_again:
            if fault:
                with pytest.raises(lane.sdk.Refused):
                    supplier.verify_for_e2e(root,environ=ambient)
            else:
                assert supplier.verify_for_e2e(root,environ=ambient)=={"OPENMATES_RUST_CORE_ARTIFACT":hashlib.sha256(projected).hexdigest()}
            compile_again.assert_not_called()


def compiler_values():
    """Existing synthetic compiler fixture, never a fabricated E2E report."""
    fixture_module = load("production_supplier_full_compiler_fixture", "tests/test_ci_rust_wasm.py")
    _, receipt, job, kwargs = fixture_module.WasmReceiptTests().fixture()
    receipt.update(runtime_profile="rust-browser-package-for-e2e", requestedMode="e2e", requestedTargets=[supplier.SPEC])
    receipt["workerProof"] = None
    receipt["steps"] = receipt["steps"][:len(lane.STAGES)]
    job.update(mode="e2e", specs=json.dumps([supplier.SPEC]))
    manifest = json.loads(kwargs["package_manifest"])
    manifest.update(requestedMode="e2e", requestedTargets=[supplier.SPEC])
    kwargs["package_manifest"] = json.dumps(manifest).encode()
    receipt["package"]["manifestSha256"] = hashlib.sha256(kwargs["package_manifest"]).hexdigest()
    return receipt, job, kwargs


COMPILER_REFUSALS = [
    "source_commit", "source_tree", "harness_commit", "run_id", "inputs", "inputSetSha256",
    "missing_schema_field", "schema_version", "status", "code", "runtime_profile", "requestedMode", "requestedTargets",
    "compilationProof", "packagingProof", "browserRuntimeProof", "conformanceProof", "releaseProof", "publication",
    "services", "cleanupVerified", "sourceHeld", "workerProof", "steps_missing", "steps_extra", "steps_order",
    "step_status", "step_started", "step_returncode", "step_terminated", "step_tool", "step_admission", "step_entry_package",
    "step_executable_sha", "step_executable_bytes", "step_executable_kind",
    *["lock_"+str(i) for i in range(4)],
    *["stage_"+str(i) for i in range(6)],
    *["argv_"+str(i) for i in range(6)],
    *["elapsed_"+str(i) for i in range(6)],
]


def corrupt_compiler_receipt(receipt, facet):
    if facet in {"source_commit", "source_tree", "harness_commit", "run_id", "inputSetSha256"}:
        receipt[facet] = "0" * 64
    elif facet == "inputs":
        receipt[facet] = {"unattested.rs":"a"*64}
    elif facet == "missing_schema_field":
        del receipt["code"]
    elif facet == "schema_version":
        receipt["schemaVersion"] = 2
    elif facet in {"status", "runtime_profile", "requestedMode"}:
        receipt[facet] = "different"
    elif facet == "requestedTargets":
        receipt[facet] = [lane.BROWSER_SPEC]
    elif facet == "code":
        receipt[facet] = "failed"
    elif facet in {"compilationProof", "packagingProof", "cleanupVerified", "sourceHeld"}:
        receipt[facet] = False
    elif facet in {"browserRuntimeProof", "conformanceProof", "releaseProof", "publication"}:
        receipt[facet] = True
    elif facet == "services":
        receipt[facet] = {"api":"not permitted"}
    elif facet == "workerProof":
        receipt[facet] = {"browser_success":True}
    elif facet == "steps_missing":
        receipt["steps"].pop()
    elif facet == "steps_extra":
        receipt["steps"].append(dict(receipt["steps"][-1]))
    elif facet == "steps_order":
        receipt["steps"][0], receipt["steps"][1] = receipt["steps"][1], receipt["steps"][0]
    elif facet.startswith("lock_"):
        del receipt["locks"][lane.LOCKS[int(facet.split("_")[1])]]
    elif facet.startswith("stage_"):
        receipt["steps"][int(facet.split("_")[1])]["stage"] = "different"
    elif facet.startswith("argv_"):
        receipt["steps"][int(facet.split("_")[1])]["command"]["argvSha256"] = "0"*64
    elif facet.startswith("elapsed_"):
        i = int(facet.split("_")[1])
        receipt["steps"][i]["elapsedSeconds"] = lane.STAGE_SECONDS[i] + 7
    else:
        field, value = {
            "step_status":("status","failed"), "step_started":("started",False),
            "step_returncode":("returncode",1), "step_terminated":("terminatedReturncode",1),
            "step_tool":("tool","different"), "step_admission":("admission","relaxed"),
            "step_entry_package":("entryPackage","unreviewed"), "step_executable_sha":("executableSha256","not-a-sha"),
            "step_executable_bytes":("executableBytes",0), "step_executable_kind":("executableKind","unknown"),
        }[facet]
        target = receipt["steps"][0] if field in {"status","started","returncode","terminatedReturncode"} else receipt["steps"][0]["command"]
        target[field] = value


def test_full_compiler_validation_needs_no_future_e2e_report():
    receipt, job, kwargs = compiler_values()
    assert supplier.valid_rust_wasm_compiler_receipt(receipt, job, "f"*40, **kwargs)
    result_source = (ROOT/"scripts/ci_results.py").read_text()
    function = next(node for node in ast.parse(result_source).body if isinstance(node,ast.FunctionDef) and node.name=="valid_rust_wasm_compiler_receipt")
    assert "report" not in [arg.arg for arg in function.args.args]
    source = (ROOT/"scripts/ci_production_rust_browser.py").read_text()
    assert "valid_rust_wasm_receipt(" not in source
    assert "valid_rust_wasm_compiler_receipt(receipt, job," in source


@pytest.mark.parametrize("facet", COMPILER_REFUSALS)
def test_full_compiler_checks_every_identity_lock_step_and_no_runtime_claim(facet):
    import copy
    receipt, job, kwargs = compiler_values()
    receipt = copy.deepcopy(receipt)
    corrupt_compiler_receipt(receipt, facet)
    assert not supplier.valid_rust_wasm_compiler_receipt(receipt, job, "f"*40, **kwargs)


def test_completed_report_wrapper_keeps_its_existing_report_requirements():
    retrieval = load("production_supplier_result_wrapper", "ci_results.py")
    fixture_module = load("production_supplier_original_wrapper_fixture", "tests/test_ci_rust_wasm.py")
    report, original, original_job, original_kwargs = fixture_module.WasmReceiptTests().fixture()
    assert retrieval.valid_rust_wasm_receipt(report,original,original_job,"f"*40,**original_kwargs)
    assert not retrieval.valid_rust_wasm_receipt({"runtime_profile":"e2e"},original,original_job,"f"*40,**original_kwargs)
    assert not retrieval.valid_rust_wasm_receipt({"runtime_profile":"rust-wasm","results":[]},original,original_job,"f"*40,**original_kwargs)


def test_build_refuses_postbuild_compiler_validation_failure_without_returning_proof():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        ambient = {**environment(), "OPENMATES_RUST_CORE_ARTIFACT":"a"*64}
        with patch.object(supplier,"verify_for_e2e",side_effect=[{},lane.sdk.Refused("outputs")]) as verify, \
             patch.object(supplier.subprocess,"run") as command:
            with pytest.raises(lane.sdk.Refused):
                supplier.build(root,ambient)
        assert verify.call_count == 2
        command.assert_called_once()


ORIGINAL_PRODUCTION_SUBSETS = [
    [lane.PRODUCTION_BROWSER_SPEC], [lane.PRODUCTION_BROWSER_PLATFORM_SPEC],
    [lane.PRODUCTION_BROWSER_SPEC,lane.PRODUCTION_BROWSER_PLATFORM_SPEC],
    [lane.PRODUCTION_BROWSER_PLATFORM_SPEC,lane.PRODUCTION_BROWSER_SPEC],
]

THREE_PRODUCTION_SUBSETS = ORIGINAL_PRODUCTION_SUBSETS + [[lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC]] + [
    list(pair) for pair in permutations([lane.PRODUCTION_BROWSER_SPEC, lane.PRODUCTION_BROWSER_PLATFORM_SPEC,
                                   lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC], 2)
    if lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC in pair
]


FOUR_PRODUCTION_SUBSETS = THREE_PRODUCTION_SUBSETS + [[lane.PRODUCTION_BROWSER_SAVED_PAGING_SPEC]] + [
    list(pair) for pair in permutations([lane.PRODUCTION_BROWSER_SPEC, lane.PRODUCTION_BROWSER_PLATFORM_SPEC,
                                        lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC, lane.PRODUCTION_BROWSER_SAVED_PAGING_SPEC], 2)
    if lane.PRODUCTION_BROWSER_SAVED_PAGING_SPEC in pair
]


PRODUCTION_SUBSETS = FOUR_PRODUCTION_SUBSETS + [[lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC]] + [
    list(pair) for pair in permutations([lane.PRODUCTION_BROWSER_SPEC, lane.PRODUCTION_BROWSER_PLATFORM_SPEC,
                                        lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC, lane.PRODUCTION_BROWSER_SAVED_PAGING_SPEC,
                                        lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC], 2)
    if lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC in pair
]


def production_workflow_predicate():
    return "(" + " || ".join("inputs.specs_json == '" + json.dumps(targets, separators=(",", ":")) + "'"
                            for targets in PRODUCTION_SUBSETS) + ")"


@pytest.mark.parametrize("targets", PRODUCTION_SUBSETS)
def test_five_production_selectors_share_one_package_and_keep_full_receipt_target_binding(targets):
    assert lane.production_browser_e2e_targets(targets) and lane.browser_e2e_targets(targets)
    supplier.require_selector({**environment(),"CI_SPECS_JSON":json.dumps(targets,separators=(",",":"))})
    receipt,job,kwargs = compiler_values()
    receipt["requestedTargets"] = targets
    job["specs"] = json.dumps(targets)
    manifest = json.loads(kwargs["package_manifest"])
    manifest["requestedTargets"] = targets
    kwargs["package_manifest"] = json.dumps(manifest).encode()
    receipt["package"]["manifestSha256"] = hashlib.sha256(kwargs["package_manifest"]).hexdigest()
    assert supplier.valid_rust_wasm_compiler_receipt(receipt,job,"f"*40,**kwargs)
    if len(targets)==2:
        job["specs"] = json.dumps(list(reversed(targets)))
        assert not supplier.valid_rust_wasm_compiler_receipt(receipt,job,"f"*40,**kwargs)


@pytest.mark.parametrize("targets", [[], [lane.PRODUCTION_BROWSER_SPEC]*2,
    [lane.PRODUCTION_BROWSER_PLATFORM_SPEC]*2, [lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC]*2,
    [lane.PRODUCTION_BROWSER_SAVED_PAGING_SPEC]*2, [lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC]*2,
    [lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC,lane.BROWSER_PASSWORD_SPEC], ["nested/"+lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC],
    [lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC+".extra"], [lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC,None], sorted({lane.PRODUCTION_BROWSER_SPEC,lane.PRODUCTION_BROWSER_PLATFORM_SPEC,lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC}),
    [lane.PRODUCTION_BROWSER_SAVED_PAGING_SPEC,lane.BROWSER_PASSWORD_SPEC], ["nested/"+lane.PRODUCTION_BROWSER_SAVED_PAGING_SPEC],
    sorted(lane.PRODUCTION_BROWSER_SPECS), [lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC,lane.BROWSER_PASSWORD_SPEC],
    ["nested/"+lane.PRODUCTION_BROWSER_LOCAL_CURSOR_SPEC], [lane.PRODUCTION_BROWSER_SPEC,lane.BROWSER_SPEC],
    [lane.PRODUCTION_BROWSER_PLATFORM_SPEC,"unknown.spec.ts"], ["nested/"+lane.PRODUCTION_BROWSER_PLATFORM_SPEC],
    [lane.PRODUCTION_BROWSER_SPEC,lane.PRODUCTION_BROWSER_PLATFORM_SPEC,lane.PRODUCTION_BROWSER_SPEC],
    [None], [{"spec":lane.PRODUCTION_BROWSER_PLATFORM_SPEC}], lane.PRODUCTION_BROWSER_PLATFORM_SPEC])
def test_production_subset_refuses_duplicates_unknown_legacy_and_arbitrary_selectors(targets):
    assert not lane.production_browser_e2e_targets(targets)
    with pytest.raises(lane.sdk.Refused):
        supplier.require_selector({**environment(),"CI_SPECS_JSON":json.dumps(targets)})


def test_all_specs_get_isolated_accounts_and_share_only_one_prebuild_supplier():
    source=(ROOT/"scripts/ci_environment.py").read_text()
    tree=ast.parse(source)
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {"browser_account_slots","browser_account_count"}]
    direct=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="DIRECT_CHAT_SPECS" for t in n.targets))
    values={"DIRECT_CHAT_SPECS":frozenset(ast.literal_eval(direct.value.args[0]))}
    exec(compile(ast.Module(body=functions,type_ignores=[]),"account_slots_fixture","exec"),values)
    assert all(values["browser_account_count"](targets)==2*len(targets) for targets in PRODUCTION_SUBSETS)
    private=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="PRIVATE_BACKEND_SPECS" for t in n.targets))
    assert lane.PRODUCTION_BROWSER_SPECS <= ast.literal_eval(private.value.args[0])
    runner=(ROOT/"scripts/ci_run_tests.py").read_text()
    parsed=ast.parse(runner)
    markers=next(n for n in parsed.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="MARKER_CHAT_EPOCH_SPECS" for t in n.targets))
    assert lane.PRODUCTION_BROWSER_SPECS <= ast.literal_eval(markers.value.args[0])
    run=next(n for n in parsed.body if isinstance(n,ast.FunctionDef) and n.name=="run_e2e")
    segment=ast.get_source_segment(runner,run)
    assert segment.count("verify_for_e2e(ROOT)")==1 and segment.index("verify_for_e2e(ROOT)") < segment.index("for index, name in enumerate(specs)")
    assert "first_identity_index = identity_index" in segment and "identity_index += account_slots" in segment
    coverage=load("production_supplier_runtime_batches","ci_coverage.py")
    coverage.validate_runtime_batch(PRODUCTION_SUBSETS[2])
    assert coverage.runtime_batches(PRODUCTION_SUBSETS[2],2)==[PRODUCTION_SUBSETS[2]]
    workflow=yaml.safe_load((ROOT/".github/workflows/isolated-tests.yml").read_text())
    steps=next(iter(workflow["jobs"].values()))["steps"]
    assert sum(step.get("name")=="Prepare exact production-loader browser package" for step in steps)==1


def test_exact_twenty_five_orders_preserve_two_spec_and_four_account_limits():
    assert len(PRODUCTION_SUBSETS) == 25
    assert len({tuple(targets) for targets in PRODUCTION_SUBSETS}) == 25
    assert PRODUCTION_SUBSETS[:16] == FOUR_PRODUCTION_SUBSETS
    assert len(FOUR_PRODUCTION_SUBSETS) == 16
    assert all(targets in PRODUCTION_SUBSETS for targets in THREE_PRODUCTION_SUBSETS)
    assert len(THREE_PRODUCTION_SUBSETS) == 9
    assert {tuple(targets) for targets in PRODUCTION_SUBSETS} == {
        targets for size in (1, 2) for targets in permutations(lane.PRODUCTION_BROWSER_SPECS, size)
    }
    coverage = load("production_supplier_five_target_batches", "ci_coverage.py")
    batches = coverage.runtime_batches(sorted(lane.PRODUCTION_BROWSER_SPECS), 2)
    assert [len(batch) for batch in batches] == [2, 2, 1]
    original_four = sorted(lane.PRODUCTION_BROWSER_SPECS - {lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC})
    assert [len(batch) for batch in coverage.runtime_batches(original_four, 2)] == [2, 2]
    original_three = sorted(lane.PRODUCTION_BROWSER_SPECS - {lane.PRODUCTION_BROWSER_SAVED_PAGING_SPEC, lane.PRODUCTION_BROWSER_ORDINARY_LOGIN_SPEC})
    assert [len(batch) for batch in coverage.runtime_batches(original_three, 2)] == [2, 1]
    assert not lane.production_browser_e2e_targets(original_three)
    assert all(lane.production_browser_e2e_targets(batch) for batch in batches)
    assert not lane.production_browser_e2e_targets(sorted(lane.PRODUCTION_BROWSER_SPECS))


def test_workflow_admits_only_closed_orders_at_every_existing_supply_build_and_capture_gate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/isolated-tests.yml").read_text())
    steps = next(iter(workflow["jobs"].values()))["steps"]
    predicate = production_workflow_predicate()
    guarded = [step for step in steps if predicate in step.get("if", "")]
    assert len(guarded) == 5
    named = {step.get("name"): step for step in guarded}
    assert {"Start bounded same-source browser package clock", "Prepare exact production-loader browser package",
            "Generate UI build inputs once", "Build local web app"} <= set(named)
    build = named["Build local web app"]["run"]
    case_line = next(line.strip() for line in build.splitlines() if line.strip().startswith("'e2e:"))
    assert case_line == "|".join("'e2e:" + json.dumps(targets, separators=(",", ":")) + "'"
                                 for targets in PRODUCTION_SUBSETS) + ")"
    assert "timeout-minutes: 30" in (ROOT / ".github/workflows/isolated-tests.yml").read_text()
