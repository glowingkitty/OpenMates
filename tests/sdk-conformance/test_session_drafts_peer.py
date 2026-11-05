"""Pure protocol/schema oracle tests: no listener, subprocess or native SDK."""

# contract-test-file: tooling
import importlib.util
import json
from pathlib import Path
import sys
import pytest
import jsonschema

ROOT = Path(__file__).resolve().parent
# The existing generic RFC6455 test transport is not executed here.
if not (ROOT / "recovery_server.py").exists():
    current = Path.cwd() / "tests/sdk-conformance"
    sys.path.insert(0, str(current))
else:
    sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location(
    "session_drafts_peer_subject", ROOT / "session_drafts_server.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
DOC = json.loads((ROOT / "fixtures/session-drafts.json").read_text())
SUITE = DOC["capabilities"]["session.drafts.v1"]


def headers(identity):
    return {
        "Cookie": "auth_refresh_token=synthetic-cookie",
        "X-OpenMates-SDK": identity,
        "Origin": SUITE["protocol"]["app_origin"],
    }


def test_closed_schema_and_all_reviewed_modes():
    schema = json.loads((ROOT / "schemas/session-drafts.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(DOC, schema)
    assert len(SUITE["vectors"]) == len({v["id"] for v in SUITE["vectors"]}) == 20


@pytest.mark.parametrize("identity", ["rust", "npm", "pip"])
@pytest.mark.parametrize("vector", SUITE["vectors"], ids=lambda v: v["id"])
def test_pure_oracle_exact_declared_protocol_counts(vector, identity):
    peer = module.SessionDraftPeer(SUITE, vector, identity)
    assert peer.server is None
    closed = (
        vector["mode"] in ("noauth", "policy-denied", "team")
        or vector["expected_error"] == "invalid_argument"
    )
    if not closed:
        route = "/v1/drafts/" + SUITE["protocol"]["chat_id"]
        if vector["preflight_get"]:
            assert peer.http("GET", route, headers(identity), None)[0] == 200
        if vector["operation"] == "get":
            peer.http("GET", route, headers(identity), None)
        ws = (
            vector["operation"] == "list"
            or (vector["operation"] == "sync" and vector["preflight_get"])
            or vector["mode"] == "network-fallback"
        )
        if ws:
            assert (
                peer.http(
                    "POST",
                    "/v1/auth/session",
                    headers(identity),
                    {"session_id": "synthetic-session"},
                )[0]
                == 200
            )
            peer.counts["ws"] += 1
            peer.event(
                "native_client_lifecycle",
                {"client_type": identity, "interactive": False},
            )

            def versions(old):
                return peer.event(
                    "get_draft_versions",
                    {
                        "chats": [
                            {
                                "chat_id": SUITE["protocol"]["chat_id"],
                                "client_draft_v": old,
                            }
                        ]
                    },
                )

            if vector["preflight_get"] or vector["mode"] == "network-fallback":
                versions(4 if vector["preflight_get"] else 0)
            if vector["operation"] == "list" or vector["mode"] == "network-fallback":
                payload = {
                    "phase": "phase2",
                    "context_epoch": 23,
                    "client_chat_ids": [],
                    "client_chat_versions": {},
                }
                if vector["mode"] == "network-fallback":
                    payload["refresh_chat_ids"] = [SUITE["protocol"]["chat_id"]]
                frames = peer.event("phased_sync_request", payload)
                assert (
                    frames[-1][0] == "phased_sync_complete"
                    and frames[-1][1]["context_epoch"] == 23
                )
                if vector["mode"] == "updated":
                    assert frames[0][1]["chats"][0]["chat_details"]["draft_v"] == 5
            if vector["mode"] == "network-fallback":
                versions(4)
    assert peer.counts == vector["expected_counts"] and peer.server is None


@pytest.mark.parametrize(
    "fault", ["cookie", "bearer", "guest", "owner", "all", "active-chat", "history"]
)
def test_oracle_rejects_credential_and_protocol_escalation(fault):
    peer = module.SessionDraftPeer(SUITE, SUITE["vectors"][0], "rust")
    if fault in ("cookie", "bearer", "guest", "owner"):
        h = headers("rust")
        if fault == "cookie":
            h["Cookie"] = "auth_refresh_token=foreign"
        else:
            h[
                {
                    "bearer": "Authorization",
                    "guest": "X-OpenMates-Anonymous-ID",
                    "owner": "X-OpenMates-Task-Owner",
                }[fault]
            ] = "foreign"
        with pytest.raises(AssertionError):
            peer.headers(h)
    else:
        kind = {
            "all": "phased_sync_request",
            "active-chat": "set_active_chat",
            "history": "get_messages",
        }[fault]
        with pytest.raises(AssertionError):
            peer.event(kind, {"phase": "all", "chat_id": SUITE["protocol"]["chat_id"]})
