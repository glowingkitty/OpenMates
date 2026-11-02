"""Pure schema/wire-oracle checks: no sockets, SDK imports, accounts or builds."""

# contract-test-file: tooling
import copy
import importlib.util
import json
from pathlib import Path
from urllib.parse import quote, urlencode
import pytest
import jsonschema

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "history_peer_subject", ROOT / "api_key_history_peer.py"
)
peer_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(peer_module)
FIXTURE = json.loads((ROOT / "fixtures/sdk-api-key-history.json").read_text())
SUITE = FIXTURE["capabilities"]["sdk.history"]
SCHEMA = json.loads((ROOT / "fixtures/sdk-api-key-history.schema.json").read_text())


def request(vector, language):
    token = SUITE["api_keys"][vector["owner"]].split(".")[0]
    headers = {
        "Authorization": "Bearer " + token,
        "X-OpenMates-Device-Identity": SUITE["device_id"],
        "X-OpenMates-SDK": {"rust": "rust", "npm": "npm", "python": "pip"}[language],
    }
    route = "/v1/workspace/history"
    if vector["operation"] == "list":
        query = (
            vector.get("npm_expected_query", vector["expected_query"])
            if language == "npm"
            else vector["expected_query"]
        )
        if query:
            route += "?" + urlencode(query, doseq=True)
    else:
        route += (
            "/"
            + quote(vector["change_set_id"], safe="")
            + ("/undo" if vector["operation"] == "undo" else "")
        )
    return (
        ("POST" if vector["operation"] == "undo" else "GET"),
        route,
        headers,
        ({} if vector["operation"] == "undo" else None),
    )


def test_shared_schema_and_exact_vector_coverage():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    jsonschema.validate(FIXTURE, SCHEMA)
    vectors = SUITE["vectors"]
    assert len(vectors) == 19 and len({v["id"] for v in vectors}) == 19
    assert {v["operation"] for v in vectors} == {"list", "show", "undo"}
    assert {v["http_status"] for v in vectors if v["expected_error"]} == {
        400,
        401,
        403,
        404,
        409,
        410,
        422,
        429,
        500,
    }
    assert (
        next(v for v in vectors if v["id"] == "show-other-owner-denied")["owner"] == "b"
    )


@pytest.mark.parametrize("language", ["rust", "npm", "python"])
@pytest.mark.parametrize("vector", SUITE["vectors"], ids=lambda v: v["id"])
def test_wire_oracle_accepts_exact_positive_and_negative_contract(vector, language):
    peer = peer_module.HistoryPeer(SUITE, vector, language)
    assert peer.dispatch(*request(vector, language)) == (
        vector["http_status"],
        vector["response"],
    )
    assert peer.requests == 1 and peer.failure is None


@pytest.mark.parametrize(
    "fault",
    [
        "wrong-owner",
        "cookie",
        "session",
        "anonymous",
        "owner-override",
        "suffix",
        "bootstrap",
        "wrong-method",
        "wrong-id",
        "plaintext-body",
        "retry",
        "team",
    ],
)
def test_wire_oracle_refuses_credential_owner_route_body_and_retry_drift(fault):
    vector = next(
        v
        for v in SUITE["vectors"]
        if v["operation"] == "undo" and not v["expected_error"]
    )
    peer = peer_module.HistoryPeer(SUITE, vector, "rust")
    method, route, headers, body = request(vector, "rust")
    if fault == "wrong-owner":
        headers["Authorization"] = "Bearer sk-api-historyOwnerB"
    elif fault == "cookie":
        headers["Cookie"] = "auth_refresh_token=fixture"
    elif fault == "session":
        headers["X-Session-ID"] = "fixture"
    elif fault == "anonymous":
        headers["X-OpenMates-Anonymous-ID"] = "fixture"
    elif fault == "owner-override":
        headers["X-OpenMates-Task-Owner"] = "forged"
    elif fault == "suffix":
        headers["X-Extra"] = "localSetupSuffix"
    elif fault == "bootstrap":
        route = "/v1/sdk/session"
    elif fault == "wrong-method":
        method = "GET"
    elif fault == "wrong-id":
        route = "/v1/workspace/history/other/undo"
    elif fault == "plaintext-body":
        body = {"snapshot": "private plaintext"}
    elif fault == "team":
        route += "?team_id=foreign"
    elif fault == "retry":
        assert peer.dispatch(method, route, headers, body)[0] == 200
    assert peer.dispatch(method, route, headers, body)[0] == 400
    assert peer.failure is not None


@pytest.mark.parametrize(
    "fault",
    [
        "extra-field",
        "bad-operation",
        "fractional-limit",
        "missing-outcome",
        "excess-vectors",
    ],
)
def test_schema_rejects_unreviewed_vector_shapes(fault):
    doc = copy.deepcopy(FIXTURE)
    vectors = doc["capabilities"]["sdk.history"]["vectors"]
    v = vectors[0]
    if fault == "extra-field":
        v["new_authority"] = True
    elif fault == "bad-operation":
        v["operation"] = "restore"
    elif fault == "fractional-limit":
        v["filters"]["limit"] = 1.5
    elif fault == "missing-outcome":
        del v["expected"]
    else:
        vectors.extend(copy.deepcopy(vectors))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, SCHEMA)
