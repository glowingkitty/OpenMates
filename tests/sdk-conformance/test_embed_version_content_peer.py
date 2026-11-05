"""Pure schema/protocol checks only; no listener, native extension or SDK IO."""

from copy import deepcopy
from pathlib import Path
import json
import pytest
import jsonschema
from api_key_embed_version_peer import VersionContentPeer, CAPABILITY

HERE = Path(__file__).resolve().parent
DOCUMENT = json.loads((HERE / "fixtures/sdk-embed-version-content.json").read_text())
SUITE = DOCUMENT["capabilities"][CAPABILITY]


@pytest.mark.parametrize("language", ["rust", "npm", "python"])
@pytest.mark.parametrize("vector", SUITE["vectors"], ids=lambda v: v["id"])
# contract-test: tooling
def test_exact_owned_read_protocol_and_no_extra_requests(language, vector):
    peer = VersionContentPeer(SUITE, vector, language)
    identity = {"rust": "rust", "npm": "npm", "python": "pip"}[language]
    headers = {
        "Authorization": "Bearer " + SUITE["api_key"].split(".", 1)[0],
        "X-OpenMates-SDK": identity,
        "X-OpenMates-Device-Identity": SUITE["device_id"],
    }
    for method, path in peer.sequence():
        body = (
            {"sdk_name": identity, "device_identity": SUITE["device_id"]}
            if path == "/v1/sdk/session"
            else None
        )
        peer.dispatch(method, path, headers, body)
    result = (
        {"ok": False, "error": vector["expected_error"]}
        if vector["expected_error"]
        else {"ok": True, "value": vector["expected"]}
    )
    peer.check(result)
    peer.dispatch("GET", "/v1/sdk/embeds/forbidden", headers, None)
    assert peer.failure is not None


@pytest.mark.parametrize(
    "bad",
    [
        "Cookie",
        "X-Session-ID",
        "X-OpenMates-Anonymous-ID",
        "X-OpenMates-Task-Owner",
        "X-OpenMates-Task-Actor",
    ],
)
# contract-test: tooling
def test_ambient_or_alternate_authority_refuses(bad):
    peer = VersionContentPeer(SUITE, SUITE["vectors"][0], "rust")
    headers = {
        "Authorization": "Bearer " + SUITE["api_key"].split(".", 1)[0],
        "X-OpenMates-SDK": "rust",
        "X-OpenMates-Device-Identity": SUITE["device_id"],
        bad: "synthetic",
    }
    peer.dispatch(*peer.sequence()[0], headers, None)
    assert peer.failure


# contract-test: tooling
def test_closed_schema_mirrors_and_old_opaque_version_boundary():
    schema = json.loads(
        (HERE / "schemas/sdk-embed-version-content.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(schema).validate(DOCUMENT)
    bad = deepcopy(DOCUMENT)
    bad["capabilities"][CAPABILITY]["vectors"][0]["expected_error"] = "invented"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
    assert len(SUITE["reconstruction"]) == 90 and len(SUITE["cli_cases"]) == 6
    assert all(set(item["flags"]) <= {"json", "output"} for item in SUITE["cli_cases"])
