"""Pure oracle/fixture supporting tests. Never claim an adapter or runtime pass."""

# contract-test-file: tooling
from pathlib import Path
import base64
import hashlib
import json
from urllib.parse import urlencode
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from session_embed_share_peer import CookieSharePeer, CAPABILITY

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SUITE = json.loads((HERE / "fixtures/session-embed-share-bindings.json").read_text())[
    "capabilities"
][CAPABILITY]


def sealed(value, password, salt):
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000, 32)
    nonce = bytes([31]) * 12  # Oracle fixture only, never production randomness.
    return (
        base64.urlsafe_b64encode(
            nonce + AESGCM(key).encrypt(nonce, value.encode(), None)
        )
        .decode()
        .rstrip("=")
    )


def oracle_url(peer, fields=None):
    v, s = peer.vector, peer.suite
    key = base64.b64encode(bytes.fromhex(s["key_hex"])).decode()
    if v["password"]:
        key = sealed(key, v["password"], ("openmates-pwd-" + s["embed_id"]).encode())
    value = fields or {
        "embed_encryption_key": key,
        "generated_at": str(peer.started),
        "duration_seconds": str(v["expires"]),
        "pwd": "1" if v["password"] else "0",
    }
    return (
        "http://127.0.0.1/share/embed/"
        + s["embed_id"]
        + "#key="
        + sealed(urlencode(value), s["embed_id"], b"openmates-share-v1")
    )


@pytest.mark.parametrize("identity", ["rust", "npm", "pip"])
@pytest.mark.parametrize("vector", SUITE["vectors"][:3], ids=lambda v: v["id"])
def test_oracle_accepts_four_fields_and_rejects_wrong_duration_or_extra_key(
    identity, vector
):
    p = CookieSharePeer(SUITE, vector, identity)
    assert p.server is None
    # Explicit oracle-only ledger setup. Actual runner obtains these from real IO.
    p.counts.update(http=2, ws=1, lifecycle=1)
    p.requests.append(SUITE["embed_id"])
    p.check({"ok": True, "value": oracle_url(p)})
    for fields in [
        {"duration_seconds": "999"},
        {
            "embed_encryption_key": "not-the-selected-key",
            "generated_at": str(p.started),
            "duration_seconds": str(vector["expires"]),
            "pwd": "0",
        },
        {
            "embed_encryption_key": "x",
            "generated_at": str(p.started),
            "duration_seconds": "0",
            "pwd": "0",
            "owner": "DTO-is-not-authority",
        },
    ]:
        with pytest.raises((AssertionError, ValueError)):
            p.check({"ok": True, "value": oracle_url(p, fields)})


def test_original_share_vector_objects_and_mirrored_bytes_are_exact():
    old = json.loads((HERE / "fixtures/session-embed-admitted-share.json").read_text())
    assert SUITE["vectors"][:3] == old["vectors"]
    assert SUITE["status"] == "partial-authored-unrun"
    assert len(SUITE["vectors"]) == len({v["id"] for v in SUITE["vectors"]}) == 16
    assert (HERE / "fixtures/session-embed-share-bindings.json").read_bytes() == (
        ROOT
        / "packages/openmates-rust/tests/fixtures/session-embed-share-bindings.json"
    ).read_bytes()


def test_protocol_oracle_forbids_key_headers_sync_and_mutation():
    p = CookieSharePeer(SUITE, SUITE["vectors"][0], "rust")
    h = {
        "Cookie": "auth_refresh_token=synthetic-cookie",
        "Origin": SUITE["protocol"]["app_origin"],
        "X-OpenMates-SDK": "rust",
    }
    for name in ["Authorization", "X-OpenMates-Anonymous-ID", "X-OpenMates-Task-Owner"]:
        with pytest.raises(AssertionError):
            p.headers({**h, name: "synthetic"})
    for kind in ["phased_sync_request", "store_embed", "recovery_job_claim"]:
        with pytest.raises(AssertionError):
            p.event(kind, {})
    with pytest.raises(AssertionError):
        p.http("GET", "/v1/embeds/any", h, None)
    for vector in SUITE["vectors"][3:]:
        denied = CookieSharePeer(SUITE, vector, "rust")
        with pytest.raises(AssertionError):
            denied.check({"ok": True, "value": "synthetic-key-url"})
