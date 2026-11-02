"""Pure offline wire-oracle/schema tests. No sockets, SDK imports or processes."""

# contract-test-file: tooling
import importlib.util
import json
from pathlib import Path
import pytest
import jsonschema

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "draft_peer_subject", ROOT / "api_key_drafts_rust_peer.py"
)
peer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(peer_module)
DOCUMENT = json.loads((ROOT / "fixtures/sdk-api-key-drafts.json").read_text())
SUITE = DOCUMENT["capabilities"]["sdk.drafts"]


def headers():
    return {
        "Authorization": "Bearer sk-api-synthetic",
        "X-OpenMates-Device-Identity": "synthetic-device",
        "X-OpenMates-SDK": "rust",
    }


def test_shared_fixture_schema_and_exact_case_ids():
    schema = json.loads(
        (ROOT / "schemas/sdk-api-key-drafts-fixture.schema.json").read_text()
    )
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(DOCUMENT, schema)
    ids = {v["id"] for v in SUITE["vectors"]}
    assert len(ids) == len(SUITE["vectors"]) == 15
    assert {v["kind"] for v in SUITE["vectors"]} == {
        "record",
        "wrong-account-key",
        "project-grant-not-account-key",
        "corrupt-markdown",
        "missing",
        "empty-list",
        "anonymous",
        "http-error",
    }
    assert {v["status"] for v in SUITE["vectors"] if v["kind"] == "http-error"} == {
        401,
        403,
        409,
        429,
        503,
    }
    assert SUITE["open_parity_limits"][0]["status"] == "open-existing-sdk-divergence"


@pytest.mark.parametrize(
    "vector",
    SUITE["vectors"]
    + [dict(v, kind="open-parity-limit") for v in SUITE["open_parity_limits"]],
    ids=lambda v: v["id"],
)
def test_oracle_accepts_only_declared_sequence_and_payload(vector):
    peer = peer_module.Peer(SUITE, vector)
    for method, path, status, payload in peer.expected:
        body = (
            {"sdk_name": "rust", "device_identity": "synthetic-device"}
            if method == "POST"
            else None
        )
        assert peer.dispatch(method, path, headers(), body) == (status, payload)
    assert peer.failure is None and peer.requests == len(peer.expected)


@pytest.mark.parametrize(
    "fault",
    [
        "wrong-owner",
        "cookie",
        "anonymous",
        "suffix",
        "route",
        "method",
        "plaintext-body",
        "retry",
    ],
)
def test_oracle_rejects_credential_route_body_and_replay_drift(fault):
    vector = SUITE["vectors"][0]
    peer = peer_module.Peer(SUITE, vector)
    method, path, _status, _payload = peer.expected[0]
    request_headers = headers()
    body = None
    if fault == "wrong-owner":
        request_headers["Authorization"] = "Bearer sk-api-other"
    if fault == "cookie":
        request_headers["Cookie"] = "auth_refresh_token=synthetic"
    if fault == "anonymous":
        request_headers["X-OpenMates-Anonymous-ID"] = "synthetic"
    if fault == "suffix":
        request_headers["X-Extra"] = ".synthetic"
    if fault == "route":
        path = "/v1/sdk/session"
    if fault == "method":
        method = "POST"
    if fault == "plaintext-body":
        body = {"markdown": "synthetic private draft"}
    if fault == "retry":
        assert peer.dispatch(method, path, request_headers, body)[0] == 200
    assert peer.dispatch(method, path, request_headers, body)[0] == 400
    assert peer.failure is not None


@pytest.mark.parametrize("vector", SUITE["vectors"], ids=lambda v: v["id"])
def test_result_oracle_cannot_report_incorrect_success_or_wrong_error(vector):
    kind = vector["kind"]
    if "expected_error" in vector:
        observed = {"ok": False, "error": vector["expected_error"]}
    elif kind == "record":
        observed = {
            "ok": True,
            "value": {"markdown": vector["markdown"], "preview": vector["preview"]},
        }
    else:
        observed = {"ok": True, "value": [] if kind == "empty-list" else None}
    peer_module.check(SUITE, vector, observed)
    with pytest.raises(AssertionError):
        peer_module.check(SUITE, vector, {"ok": True, "value": "invented success"})
