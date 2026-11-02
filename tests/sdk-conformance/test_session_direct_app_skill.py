"""Pure schema/independent wire/standard gate oracles; never starts a peer."""

# contract-test-file: tooling
# contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import jsonschema
import pytest
from session_direct_app_skill_peer import DirectSkillPeer

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "sdk-conformance/fixtures/session-direct-app-skill.json"
SCHEMA = ROOT / "sdk-conformance/schemas/session-direct-app-skill.schema.json"


def document():
    return json.loads(FIXTURE.read_text())


def peer(credential="cookie"):
    value = DirectSkillPeer.__new__(DirectSkillPeer)  # no socket/port/thread
    value.suite = document()["capabilities"]["sdk.apps"]
    value.vector = next(
        v for v in value.suite["vectors"] if v["credential"] == credential
    )
    value.identity, value.endpoint = "rust", "http://127.0.0.1:12345"
    value.lock = threading.Lock()
    value.counts = {"auth": 0, "skill_posts": 0, "retention_posts": 0, "downloads": 0}
    return value


def test_fixture_schema_requires_all18_vectors_original_scope_and_zero_retention():
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))
    validator.validate(document())
    suite = document()["capabilities"]["sdk.apps"]
    assert len(suite["vectors"]) == len({v["id"] for v in suite["vectors"]}) == 18
    for field in [
        "expected_skill_posts",
        "expected_downloads",
        "expected_retention_posts",
    ]:
        changed = document()
        changed["capabilities"]["sdk.apps"]["vectors"][0].pop(field)
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(changed)
    changed = document()
    changed["capabilities"]["sdk.apps"]["vectors"][0]["expected_downloads"] = 1
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(changed)


@pytest.mark.parametrize(
    "field", ["model", "provider", "piiMappings", "chat_id", "private_memory"]
)
def test_independent_wire_oracle_refuses_added_routing_or_private_context(field):
    p = peer()
    p.validate_input(p.suite["request"]["input"])
    altered = deepcopy(p.suite["request"]["input"])
    altered[field] = "forbidden fixture value"
    with pytest.raises(AssertionError):
        p.validate_input(altered)


@pytest.mark.parametrize("credential", ["cookie", "api_key"])
def test_peer_requires_explicit_credential_kind_identity_and_origin(credential):
    p = peer(credential)
    a = p.suite["account"]
    headers = {"X-OpenMates-SDK": "rust", "Origin": p.endpoint}
    if credential == "cookie":
        headers["Cookie"] = "auth_refresh_token=" + a["cookie"]
    else:
        headers["Authorization"] = "Bearer " + a["api_key"].split(".", 1)[0]
        headers["X-OpenMates-Device-Identity"] = a["device_id"]
    p.headers(SimpleNamespace(headers=headers))
    for field in [
        "Origin",
        "X-OpenMates-SDK",
        "Cookie" if credential == "cookie" else "Authorization",
    ]:
        altered = dict(headers)
        altered[field] = "wrong"
        with pytest.raises(AssertionError):
            p.headers(SimpleNamespace(headers=altered))
    altered = dict(headers)
    altered["Authorization" if credential == "cookie" else "Cookie"] = (
        "forbidden escalation"
    )
    with pytest.raises(AssertionError):
        p.headers(SimpleNamespace(headers=altered))


def test_standard_gate_still_requires_hash_all_case_ids_and_all_three_fixed_runners():
    path = ROOT.parent / "scripts/check_sdk_conformance.py"
    spec = importlib.util.spec_from_file_location("direct_sdk_gate_private", path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    for language in ["rust", "npm", "python"]:
        assert (language, "sdk.apps") in gate.ADAPTER_OVERRIDES
    gate.validate_fixture_document(
        "tests/sdk-conformance/fixtures/session-direct-app-skill.json",
        document(),
        ROOT.parent,
    )
    ids = {v["id"] for v in document()["capabilities"]["sdk.apps"]["vectors"]}
    result = {
        "capability": "sdk.apps",
        "language": "rust",
        "status": "passed",
        "fixtureSha256": "synthetic-hash",
        "results": [{"id": identity, "status": "passed"} for identity in ids],
    }
    gate.validate_result(result, "sdk.apps", "rust", "synthetic-hash", ids)
    for field, value in [
        ("fixtureSha256", "wrong"),
        ("results", result["results"][:-1]),
        ("language", "npm"),
        ("status", "skipped"),
    ]:
        altered = {**result, field: value}
        with pytest.raises(ValueError):
            gate.validate_result(altered, "sdk.apps", "rust", "synthetic-hash", ids)
    rust_runner = (
        ROOT / "sdk-conformance/runners/session-direct-app-skill.py"
    ).read_text()
    assert '"--exact", "--nocapture"' in " ".join(rust_runner.split())
    assert "1 passed; 0 failed; 0 ignored;" in rust_runner
    assert 'result["fixtureSha256"] == fixture_hash' in rust_runner
    assert 'actual["peer"]["failure"] is None' in rust_runner


def test_new_slice_cannot_silently_skip_one_language_or_claim_one_sdk_only():
    path = ROOT.parent / "scripts/check_sdk_conformance.py"
    spec = importlib.util.spec_from_file_location("direct_sdk_gate_all3_private", path)
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    capability = {
        "id": "sdk.apps",
        "fixture": "tests/sdk-conformance/fixtures/session-direct-app-skill.json",
        "languages": {
            language: {"conformance": True} for language in ["rust", "npm", "python"]
        },
    }
    gate.require_direct_skill_adapters(capability)
    for language in ["rust", "npm", "python"]:
        missing = deepcopy(capability)
        missing["languages"][language]["conformance"] = False
        with pytest.raises(ValueError):
            gate.require_direct_skill_adapters(missing)
