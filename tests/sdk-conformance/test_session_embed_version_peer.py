"""Pure independent Cookie protocol/schema oracles. No listener/adapter IO."""

# contract-test-file: tooling

from copy import deepcopy
from pathlib import Path
import hashlib
import json
import pytest
import jsonschema
from session_embed_version_peer import CookieVersionPeer, CAPABILITY

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DOCUMENT = json.loads(
    (HERE / "fixtures/session-embed-version-content.json").read_text()
)
SUITE = DOCUMENT["capabilities"][CAPABILITY]


@pytest.mark.parametrize("identity", ["rust", "npm", "pip"])
@pytest.mark.parametrize("vector", SUITE["vectors"], ids=lambda v: v["id"])
def test_closed_cookie_read_sequence_and_output(identity, vector):
    p = CookieVersionPeer(SUITE, vector, identity)
    assert p.server is None
    h = {
        "Cookie": "auth_refresh_token=synthetic-cookie",
        "Origin": SUITE["protocol"]["app_origin"],
        "X-OpenMates-SDK": identity,
    }
    v = vector
    early = (
        v["mode"] in ("noauth", "policy-denied", "team")
        or type(v["version"]) is not int
        or v["version"] < 1
        or len(v["embed_id"]) != 36
    )
    if not early:
        p.http("POST", "/v1/auth/session", h, {"session_id": "synthetic-session"})
        path = f"/v1/embeds/{v['embed_id']}/versions/{v['version']}"
        p.http("GET", path + "?capability=bounded-v1", h, None)
        if v["fallback409"]:
            p.http("GET", path, h, None)
        r = v["response"]
        invalid = (
            r.get("embed_id") != v["embed_id"]
            or r.get("version_number") != v["version"]
            or (
                not isinstance(r.get("content"), str)
                and (
                    r["rows"][-1]["version_number"] != v["version"]
                    or any(row["version_number"] > v["version"] for row in r["rows"])
                )
            )
        )
        encrypted = (
            v["status"] == 200 and not invalid and not isinstance(r.get("content"), str)
        )
        if encrypted:
            p.http("POST", "/v1/auth/session", h, {"session_id": "synthetic-session"})
            p.counts["ws"] = 1  # Admission oracle only, never a simulated runtime pass.
            p.event(
                "native_client_lifecycle",
                {"client_type": identity, "interactive": False},
            )
            for id in v["heads"]:
                p.event("request_embed", {"embed_id": id})
    observed = (
        {"ok": False, "error": v["error"]}
        if v["error"]
        else {"ok": True, "value": v["expected"]}
    )
    p.check(observed)
    with pytest.raises(AssertionError):
        p.event("recovery_job_claim", {})


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "X-OpenMates-Anonymous-ID",
        "X-OpenMates-Task-Owner",
        "X-OpenMates-Task-Actor",
    ],
)
def test_no_key_anonymous_task_or_privilege_header_fallback(name):
    p = CookieVersionPeer(SUITE, SUITE["vectors"][0], "rust")
    with pytest.raises(AssertionError):
        p.headers(
            {
                "Cookie": "auth_refresh_token=synthetic-cookie",
                "Origin": SUITE["protocol"]["app_origin"],
                "X-OpenMates-SDK": "rust",
                name: "synthetic",
            }
        )


def test_fixture_schema_mirror_original_api_key_and_old_output_cases_preserved():
    schema = json.loads(
        (HERE / "schemas/session-embed-version-content.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(schema).validate(DOCUMENT)
    assert (
        len(SUITE["vectors"]) == 21 and len({v["id"] for v in SUITE["vectors"]}) == 21
    )
    assert (HERE / "fixtures/session-embed-version-content.json").read_bytes() == (
        ROOT
        / "packages/openmates-rust/tests/fixtures/session-embed-version-content.json"
    ).read_bytes()
    original = (HERE / "fixtures/sdk-embed-version-content.json").read_bytes()
    assert (
        hashlib.sha256(original).hexdigest()
        == SUITE["source_reconstruction_fixture_sha256"]
    )
    old = json.loads(original)["capabilities"]["sdk.embeds.version-content"]
    assert len(old["vectors"]) == 102 and len(old["cli_cases"]) == 6
    bad = deepcopy(DOCUMENT)
    bad["capabilities"][CAPABILITY]["vectors"][0]["unexpected"] = "refuse"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)
