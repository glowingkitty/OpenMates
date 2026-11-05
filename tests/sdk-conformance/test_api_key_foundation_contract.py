"""Pure independent fixture/source/gate checks; no native/peer execution credit."""

# contract-test-file: tooling
from pathlib import Path
import ast
import importlib.util
import json
import pytest
import jsonschema
from source_contract import assert_python_contains, python_contains

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/sdk-conformance/fixtures/api-key-foundation.json"


def suite():
    return json.loads(FIXTURE.read_text())["capabilities"]["sdk.configuration"]


def test_schema_and_original_app18_four_are_unchanged():
    jsonschema.validate(
        json.loads(FIXTURE.read_text()),
        json.loads(
            (
                ROOT / "tests/sdk-conformance/schemas/api-key-foundation.schema.json"
            ).read_text()
        ),
    )
    old = json.loads(
        (
            ROOT / "tests/sdk-conformance/fixtures/session-direct-app-skill.json"
        ).read_text()
    )["capabilities"]["sdk.apps"]
    assert suite()["vectors"][:4] == [
        v for v in old["vectors"] if v["credential"] == "api_key"
    ]
    assert (
        len(suite()["vectors"]) == 23
        and len({v["id"] for v in suite()["vectors"]}) == 23
    )


def test_actual_three_fixed_adapters_and_peer_oracle_cannot_skip():
    source = (ROOT / "tests/sdk-conformance/runners/api-key-foundation.py").read_text()
    assert_python_contains(
        source,
        '"rust"',
        '"npm"',
        '"python"',
        "api-key-foundation-conformance",
        "result.returncode==0",
        'wire["failure"] is None',
        'wire["auth"]==0',
        "actual-rust-api-key-library",
        "expected_error",
        "fixtureSha256",
        "len(results)==23",
    )
    assert "skip" not in source.replace("skip,", "")
    assert (
        "class ApiKeyFoundationPeer(DirectSkillPeer)"
        in (ROOT / "tests/sdk-conformance/api_key_foundation_peer.py").read_text()
    )


def test_original_guard_native_allocator_and_no_mutex_across_io():
    source = (ROOT / "packages/openmates-session-bindings/src/api_key.rs").read_text()
    assert (
        "Arc<OpenMates>" in source
        and "tokio::sync::Mutex" not in source
        and "DriverLane" not in source
    )
    assert (
        "let sdk=self.state.driver(&self.call)?;" in source and "drop(sdk);" in source
    )
    assert (
        "self.state.check(&self.call)?;let value=encode(&self.output)?;self.state.check(&self.call)?;"
        in source
    )
    assert (
        "self.output.zeroize();result" in source
        and "self.requests.try_lock()" in source
    )
    for f, allocation in [
        ("node_api_key.rs", "env.create_string(text)"),
        ("python_api_key.rs", "PyString::new(py,text)"),
    ]:
        abi = (ROOT / "packages/openmates-session-bindings/src" / f).read_text()
        assert (
            "output.encode_with(" in abi and allocation in abi and "release_json" in abi
        )
    for f in ["sdkApiKeyRust.ts", "../unused"][:1]:
        facade = (ROOT / "frontend/packages/openmates-cli/src" / f).read_text()
        assert (
            "request=this.native.request()" in facade
            and "output=await operation(request)" in facade
        )
        assert "request.cancel()" in facade and "native_binding_unavailable" in facade
        assert (
            "child_process" not in facade
            and "homedir" not in facade
            and "process.env" not in facade
        )
    py = (ROOT / "packages/openmates-python/openmates/rust_api_key.py").read_text()
    ast.parse(py)
    assert "asyncio.shield(task)" in py and "return await operation(request)" in py
    assert "subprocess" not in py and "Path.home" not in py and "os.environ" not in py


def test_standard_gate_full_vector_and_typed_error_negatives():
    spec = importlib.util.spec_from_file_location(
        "sdk_gate", ROOT / "scripts/check_sdk_conformance.py"
    )
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    gate.validate_fixture_error_oracles({"sdk.configuration": suite()})
    ids = {v["id"] for v in suite()["vectors"]}
    result = {
        "capability": "sdk.configuration",
        "language": "rust",
        "status": "passed",
        "fixtureSha256": "synthetic-hash",
        "results": [{"id": id, "status": "passed"} for id in ids],
    }
    gate.validate_result(result, "sdk.configuration", "rust", "synthetic-hash", ids)
    for bad in [
        dict(result, results=result["results"][:-1]),
        dict(result, status="skipped"),
    ]:
        with pytest.raises(ValueError):
            gate.validate_result(
                bad, "sdk.configuration", "rust", "synthetic-hash", ids
            )
    bad = json.loads(json.dumps(suite()))
    bad["vectors"][-1]["expected_error"] = "raw-private-server-text"
    with pytest.raises(ValueError):
        gate.validate_fixture_error_oracles({"sdk.configuration": bad})


def test_each_genuine_runner_selects_the_same_registered_fixture_suite():
    py = (ROOT / "tests/sdk-conformance/runners/api_key_foundation_case.py").read_text()
    npm = (ROOT / "tests/sdk-conformance/runners/api-key-foundation.mjs").read_text()
    rust = (
        ROOT
        / "packages/openmates-session-bindings/examples/api-key-foundation-conformance.rs"
    ).read_text()
    assert python_contains(
        py,
        'suite=json.loads(Path(fixture).read_text())["capabilities"]["sdk.configuration"]',
    )
    assert '.capabilities["sdk.configuration"]' in npm
    assert 'let suite=&suite["capabilities"]["sdk.configuration"];' in rust
