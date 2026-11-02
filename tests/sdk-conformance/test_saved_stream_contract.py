"""Pure fixture/independent-admission oracles; no sockets/native runtime are run."""

# contract-test-file: tooling
from __future__ import annotations
import base64
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import threading

import jsonschema
import pytest
from cryptography.exceptions import InvalidTag
from recovery_server import encrypt
from session_saved_stream_peer import SavedStreamPeer

ROOT = Path(__file__).parent
SUITE = json.loads((ROOT / "fixtures/session-work.json").read_text())["capabilities"][
    "session.work-crud.v1"
]


def target():
    # Deliberately do not call __init__: pure validation must never bind a port.
    peer = SavedStreamPeer.__new__(SavedStreamPeer)
    peer.vector = next(
        v for v in SUITE["vectors"] if v["mode"] == "saved_consumer_close"
    )
    peer.protocol = SUITE["saved_stream"]["protocol"]
    peer.master = base64.b64decode(SUITE["saved_stream"]["account"]["master_key"])
    peer.turns, peer.message_ids, peer.admitted_chats = set(), set(), []
    peer.admitted_messages = []
    peer.saved_messages, peer.checks = {}, set()
    peer.counts = {"admissions": 0}
    peer._lock = threading.Lock()
    return peer


def payload(peer):
    key = bytes(range(64, 96))
    return {
        "chat_id": "22222222-2222-4222-8222-222222222222",
        "turn_id": "33333333-3333-4333-8333-333333333333",
        "message_id": "44444444-4444-4444-8444-444444444444",
        "encrypted_chat_key": encrypt(key, peer.master),
        "encrypted_user_message": {
            "encrypted_content": encrypt(peer.protocol["input"].encode(), key),
            "client_message_id": "44444444-4444-4444-8444-444444444444",
            "chat_id": "22222222-2222-4222-8222-222222222222",
            "role": "user",
            "created_at": 1,
            "updated_at": 1,
        },
        "protocol_version": 1,
        "chat_key_version": 1,
        "inference_request": {"message": {"content": peer.protocol["input"]}},
        "privacy_receipt_id": "synthetic-saved-privacy",
        "privacy_generation": 1,
        "expected_messages_v": 0,
    }


class Socket:
    def __init__(self):
        self.frames = []

    def send(self, kind, value):
        self.frames.append((kind, value))


# contract-test: supporting surface=sdks.rust assertions=sdk.library.explicit-headless,cli.surface.semantic-parity
def test_schema_requires_saved_selector_terminal_counts_and_rejects_unknown_mode():
    fixture = json.loads((ROOT / "fixtures/session-work.json").read_text())
    schema = json.loads((ROOT / "schemas/session-work.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )
    validator.validate(fixture)
    assert len(SUITE["vectors"]) == 26
    assert [vector["mode"] for vector in SUITE["vectors"][-3:]] == [
        "saved_owned_apps_success",
        "saved_owned_apps_cancel_headers",
        "saved_owned_apps_pre_cancel",
    ]
    for key in ("chat_selector", "expected_admissions", "required_assertions"):
        altered = deepcopy(fixture)
        altered["capabilities"]["session.work-crud.v1"]["vectors"][-1].pop(key)
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(altered)
    altered = deepcopy(fixture)
    altered["capabilities"]["session.work-crud.v1"]["vectors"][-1]["mode"] = (
        "invented-rearm"
    )
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(altered)


def test_peer_requires_actual_authenticated_ciphertext_and_rejects_replayed_turn():
    peer, socket = target(), Socket()
    body = payload(peer)
    peer.admit_saved(socket, body)
    assert peer.counts["admissions"] == 1
    assert [kind for kind, _ in socket.frames] == [
        "chat_turn_preflight_ack",
        "chat_message_confirmed",
    ]
    assert len(peer.turns) == len(peer.message_ids) == 1
    assert "no-replay-of-turn-or-message-identities" in peer.checks
    with pytest.raises(AssertionError):
        peer.admit_saved(socket, body)
    assert peer.counts["admissions"] == 1


@pytest.mark.parametrize(
    "mutation", ["ciphertext", "route", "version", "receipt", "generation"]
)
def test_peer_rejects_bad_ciphertext_routing_revision_and_receipt_before_admission(
    mutation,
):
    peer, socket = target(), Socket()
    body = payload(peer)
    if mutation == "ciphertext":
        body["encrypted_user_message"]["encrypted_content"] = encrypt(
            peer.protocol["input"].encode(), peer.master
        )
    elif mutation == "route":
        body["inference_request"]["provider"] = "forbidden-override"
    elif mutation == "version":
        body["expected_messages_v"] = 9
    elif mutation == "generation":
        body["privacy_generation"] = 2
    else:
        body["privacy_receipt_id"] = "replaced-scope"
    with pytest.raises((AssertionError, InvalidTag)):
        peer.admit_saved(socket, body)
    assert peer.counts["admissions"] == 0 and not socket.frames


def test_owned_apps_vectors_append_original23_without_relaxing_saved_lifecycle_contract():
    original = json.dumps(
        SUITE["vectors"][:23], sort_keys=True, separators=(",", ":")
    ).encode()
    assert (
        hashlib.sha256(original).hexdigest()
        == "c2f12d6ba301f43c3e7a17bb3d1162a9de4048f4c744f71b0ed6f3469f478cf7"
    )
    assert [vector["id"] for vector in SUITE["vectors"][-3:]] == [
        "saved-owned-apps-success",
        "saved-owned-apps-cancel-headers",
        "saved-owned-apps-pre-cancel",
    ]
    assert all(
        vector["expected_admissions"] == 1 and vector["chat_selector"] == "new"
        for vector in SUITE["vectors"][-3:]
    )
    schema = json.loads((ROOT / "schemas/session-work.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    fixture = json.loads((ROOT / "fixtures/session-work.json").read_text())
    for index in range(23, 26):
        changed = deepcopy(fixture)
        changed["capabilities"]["session.work-crud.v1"]["vectors"][index].pop(
            "required_assertions"
        )
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(changed)
