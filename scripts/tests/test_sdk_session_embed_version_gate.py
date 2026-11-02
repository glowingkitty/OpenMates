"""Pure source registration checks; no SDK runtime or adapter is executed."""
# contract-test-file: tooling
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("version_gate", ROOT / "scripts/check_sdk_conformance.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
IDENTITY = "session.embeds.version-content.v1"
FIXTURE = "tests/sdk-conformance/fixtures/session-embed-version-content.json"


def test_fixed_version_content_library_adapters():
    stem = "session-embed-version-content"
    assert gate.ADAPTER_OVERRIDES[("rust", IDENTITY)] == [*gate.RUST_SESSION_RUNNER[:-2], stem + "-conformance", "--"]
    assert gate.ADAPTER_OVERRIDES[("npm", IDENTITY)] == ["node", "tests/sdk-conformance/runners/" + stem + ".mjs"]
    assert gate.ADAPTER_OVERRIDES[("python", IDENTITY)] == [gate.sys.executable, "tests/sdk-conformance/runners/" + stem + ".py"]
    assert gate.FIXTURE_SCHEMAS[FIXTURE] == "tests/sdk-conformance/schemas/session-embed-version-content.schema.json"

def test_real_version_fixture_schema_and_complete_identity_set():
    raw = (ROOT / FIXTURE).read_bytes()
    document = json.loads(raw)
    gate.validate_fixture_document(FIXTURE, document)
    vectors = document["capabilities"][IDENTITY]["vectors"]
    assert len(vectors) == len({v["id"] for v in vectors}) == 21
    gate.validate_fixture_error_oracles(document["capabilities"])


def test_invalid_version_fixture_refused_before_adapter(tmp_path, monkeypatch):
    fixture = tmp_path / FIXTURE
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{}")
    schema_name = gate.FIXTURE_SCHEMAS[FIXTURE]
    schema = tmp_path / schema_name
    schema.parent.mkdir(parents=True)
    schema.write_bytes((ROOT / schema_name).read_bytes())
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid version fixture must not start adapters")
    monkeypatch.setattr(gate.subprocess, "run", forbidden)
    with pytest.raises(jsonschema.ValidationError):
        gate.conformance({"fixture": FIXTURE, "capabilities": [{"id": IDENTITY}]}, tmp_path)


def test_missing_version_vectors_fail_closed():
    raw = (ROOT / FIXTURE).read_bytes()
    vectors = json.loads(raw)["capabilities"][IDENTITY]["vectors"]
    result = {"capability": IDENTITY, "language": "rust", "status": "passed", "fixtureSha256": hashlib.sha256(raw).hexdigest(), "results": [{"id": v["id"], "status": "passed"} for v in vectors[:-1]]}
    with pytest.raises(ValueError, match="not fully executed"):
        gate.validate_result(result, IDENTITY, "rust", result["fixtureSha256"], {v["id"] for v in vectors})


def test_gate_dispatches_all_three_complete_version_plans(tmp_path, monkeypatch):
    fixture = tmp_path / FIXTURE
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes((ROOT / FIXTURE).read_bytes())
    schema_name = gate.FIXTURE_SCHEMAS[FIXTURE]
    schema = tmp_path / schema_name
    schema.parent.mkdir(parents=True)
    schema.write_bytes((ROOT / schema_name).read_bytes())
    vectors = json.loads(fixture.read_bytes())["capabilities"][IDENTITY]["vectors"]
    matrix = {"fixture": FIXTURE, "capabilities": [{"id": IDENTITY, "languages": {lang: {"status": "partial", "conformance": True} for lang in gate.LANGUAGES}}]}
    calls = []
    def simulated(command, **kwargs):
        language = gate.LANGUAGES[len(calls)]
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"capability": IDENTITY, "language": language, "status": "passed", "fixtureSha256": hashlib.sha256(fixture.read_bytes()).hexdigest(), "results": [{"id": v["id"], "status": "passed"} for v in vectors]}))
    monkeypatch.setattr(gate.subprocess, "run", simulated)
    results = gate.conformance(matrix, tmp_path)
    assert len(results) == 3
    assert calls == [gate.ADAPTER_OVERRIDES[(lang, IDENTITY)] + ["--fixture", str(fixture), "--capability", IDENTITY] for lang in gate.LANGUAGES]
    assert all(c["languages"][lang]["status"] == "partial" for c in matrix["capabilities"] for lang in gate.LANGUAGES)


@pytest.mark.parametrize("mutation", ["root-extra", "vector-extra", "error-extra", "vector-omission"])
def test_cookie_closed_fixture_rejects_unknown_fields_errors_and_missing_vectors(mutation):
    document = json.loads((ROOT / FIXTURE).read_bytes())
    vectors = document["capabilities"][IDENTITY]["vectors"]
    if mutation == "root-extra":
        document["unknown"] = True
    elif mutation == "vector-extra":
        vectors[0]["unknown"] = True
    elif mutation == "error-extra":
        vectors[0]["error"] = "unknown"
    else:
        vectors.pop()
    with pytest.raises(jsonschema.ValidationError):
        gate.validate_fixture_document(FIXTURE, document)


@pytest.mark.parametrize("language", ["rust", "npm", "python"])
def test_cookie_coordinator_emits_fixture_bound_result_without_sdk_execution(language, monkeypatch, capsys):
    """Exercise envelope serialization only; no SDK, subprocess or peer listener."""
    import sys
    from types import ModuleType

    runner_path = ROOT / "tests/sdk-conformance/runners/session-embed-version-content.py"
    runner_spec = importlib.util.spec_from_file_location("cookie_version_runner", runner_path)
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    raw = (ROOT / FIXTURE).read_bytes()
    vectors = json.loads(raw)["capabilities"][IDENTITY]["vectors"]
    checked, closed, invoked = [], [], []
    observation = object()

    class EnvelopePeer:
        def __init__(self, suite, vector, identity):
            self.vector = vector
            assert identity == {"rust": "rust", "npm": "npm", "python": "pip"}[language]
            self.endpoint = "http://127.0.0.1:1"

        def start(self):
            return self

        def check(self, observed):
            assert observed is observation
            checked.append(self.vector["id"])

        def close(self):
            closed.append(self.vector["id"])

    peer_module = ModuleType("session_embed_version_peer")
    peer_module.CookieVersionPeer = EnvelopePeer
    monkeypatch.setitem(sys.modules, "session_embed_version_peer", peer_module)

    def envelope_only(argv, case):
        invoked.append(case["vector"]["id"])
        return observation

    monkeypatch.setattr(runner, "invoke", envelope_only)
    def forbidden(*args, **kwargs):
        pytest.fail("Envelope check must not start product adapters or subprocesses")
    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    monkeypatch.setattr(runner, "python_case", forbidden)
    monkeypatch.setattr(sys, "argv", [str(runner_path), "--fixture", str(ROOT / FIXTURE),
        "--capability", IDENTITY, "--language", language,
        "--rust-executable", str(runner_path)])
    runner.main()
    result = json.loads(capsys.readouterr().out)
    ids = [v["id"] for v in vectors]
    assert checked == closed == invoked == ids
    fixture_hash = hashlib.sha256(raw).hexdigest()
    gate.validate_result(result, IDENTITY, language, fixture_hash, set(ids))
    for bad_hash in (None, "0" * 64):
        bad_result = {**result, "fixtureSha256": bad_hash}
        with pytest.raises(ValueError, match="fixtureSha256"):
            gate.validate_result(bad_result, IDENTITY, language, fixture_hash, set(ids))
