"""Pure contract checks: no native library, listener or product access."""

# contract-test-file: tooling
import copy
import importlib.util
import json
from pathlib import Path
import pytest
import jsonschema

ROOT = Path(__file__).resolve().parents[2]
CAP = "session.cache-preferred-settlement.v1"
FIXTURE = "tests/sdk-conformance/fixtures/session-cache-preferred-settlement.json"
SCHEMA = "tests/sdk-conformance/schemas/session-cache-preferred-settlement.schema.json"


def documents():
    fixture = json.loads((ROOT / FIXTURE).read_bytes())
    schema = json.loads((ROOT / SCHEMA).read_bytes())
    return fixture, schema


def test_shared_vectors_are_unique_and_schema_checked():
    fixture, schema = documents()
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(fixture, schema)
    vectors = fixture["capabilities"][CAP]["vectors"]
    assert len(vectors) == len({v["id"] for v in vectors}) == 8
    assert fixture["capabilities"][CAP]["required_unverified"]


def test_schema_rejects_wrong_scenario_pair_and_unreviewed_mode():
    fixture, schema = documents()
    for field, value in [
        ("mode", "fabricated"),
        ("mode", "selected-denied"),
        ("id", "fabricated"),
    ]:
        modified = copy.deepcopy(fixture)
        modified["capabilities"][CAP]["vectors"][0][field] = value
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(modified, schema)


def test_fixture_reuses_exact_reviewed_peer_crypto_protocol():
    fixture, _ = documents()
    prior = json.loads(
        (
            ROOT / "tests/sdk-conformance/fixtures/session-chat-change-monitor.json"
        ).read_bytes()
    )["capabilities"]["session.chat-change-monitor.v1"]
    suite = fixture["capabilities"][CAP]
    assert suite["account"] == prior["account"]
    assert suite["protocol"] == prior["protocol"]


def test_gate_dispatch_requires_all_three_libraries_without_claiming_implementation():
    spec = importlib.util.spec_from_file_location(
        "cache_gate_contract", ROOT / "scripts/check_sdk_conformance.py"
    )
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    assert gate.FIXTURE_SCHEMAS[FIXTURE] == SCHEMA
    adapters = {
        language: gate.ADAPTER_OVERRIDES[(language, CAP)]
        for language in ("rust", "npm", "python")
    }
    assert (
        adapters["rust"][0] == "cargo"
        and "session-cache-preferred-settlement-conformance" in adapters["rust"]
    )
    assert adapters["npm"] == [
        "node",
        "tests/sdk-conformance/runners/session-cache-preferred-settlement.mjs",
    ]
    assert (
        adapters["python"][1]
        == "tests/sdk-conformance/runners/session-cache-preferred-settlement.py"
    )
    matrix = json.loads((ROOT / "config/sdk-capabilities.json").read_bytes())
    row = next(row for row in matrix["capabilities"] if row["id"] == CAP)
    assert row["fixture"] == FIXTURE
    for support in row["languages"].values():
        assert support["status"] == "partial" and support["conformance"] is True
        assert support["gaps"]
