"""Regenerate the synthetic API-key chat read fixture deterministically.

All keys, ids and plaintexts are synthetic. Ciphertexts use fixed IVs so the
fixture bytes (and therefore the conformance fixture hash) are reproducible:

    python3 tests/sdk-conformance/generate_sdk_api_key_chats.py
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "tests/sdk-conformance/fixtures/sdk-api-key-chats.json"
CAPABILITY = "sdk.chats"
API_KEY = "sk-api-chatOwnerA.localSetupSuffix"
DEVICE = "synthetic-chat-device"
MASTER = bytes([0x11] * 32)
SALT = bytes([0x21] * 16)
WRAP_IV = bytes([0x31] * 12)
_counter = [0]


def _iv() -> bytes:
    _counter[0] += 1
    return _counter[0].to_bytes(12, "big")


def fingerprint(key: bytes) -> bytes:
    value = 0x811C9DC5
    for byte in key:
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value.to_bytes(4, "big")


def seal(plaintext: bytes, key: bytes) -> str:
    iv = _iv()
    return base64.b64encode(b"OM" + fingerprint(key) + iv + AESGCM(key).encrypt(iv, plaintext, None)).decode()


def text(value: str, key: bytes) -> str:
    return seal(value.encode(), key)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def key_wrapper() -> dict:
    secret = API_KEY.split(".", 1)[1].encode()
    wrapping = hashlib.pbkdf2_hmac("sha256", secret, SALT, 100_000, 32)
    return {
        "salt": base64.b64encode(SALT).decode(),
        "key_iv": base64.b64encode(WRAP_IV).decode(),
        "encrypted_key": base64.b64encode(AESGCM(wrapping).encrypt(WRAP_IV, MASTER, None)).decode(),
    }


ALPHA = "a1a1a1a1-1111-4111-8111-111111111111"
BETA = "b2b2b2b2-2222-4222-8222-222222222222"
PLAIN = "c3c3c3c3-3333-4333-8333-333333333333"
TWIN1 = "d4d4d4d4-4444-4444-8444-444444444444"
TWIN2 = "e5e5e5e5-5555-4555-8555-555555555555"
K_ALPHA = bytes([0x41] * 32)
K_BETA = bytes([0x42] * 32)
K_TWIN = bytes([0x43] * 32)
K_DECOY = bytes([0x44] * 32)
K_OTHER = bytes([0x45] * 32)
K_EMBED_MASTER = bytes([0x51] * 32)
K_EMBED_PARENT = bytes([0x52] * 32)


def chat_row(chat_id, key, *, title, summary=None, category=None, slug=None, bad_category=False):
    row = {"id": chat_id, "encrypted_chat_key": seal(key, MASTER), "created_at": 1700000000, "updated_at": 1700000100}
    row["encrypted_title"] = text(title, key)
    if summary is not None:
        row["encrypted_chat_summary"] = text(summary, key)
    if category is not None:
        row["encrypted_category"] = text(category, K_OTHER if bad_category else key)
    if slug is not None:
        row["encrypted_slug"] = text(slug, key)
    return row


def projected(chat_id, *, title=None, summary=None, category=None, slug=None):
    return {"id": chat_id, "title": title, "chat_summary": summary, "category": category, "slug": slug}


def build() -> dict:
    alpha = chat_row(ALPHA, K_ALPHA, title="Alpha Notes", summary="Weekly alpha summary", category="work", slug="alpha-notes")
    beta = chat_row(BETA, K_BETA, title="Beta  Plans", category="travel", slug="beta-plans", bad_category=True)
    plain = {"id": PLAIN, "created_at": 1700000000, "updated_at": 1700000100}
    twin1 = chat_row(TWIN1, K_TWIN, title="Same Title")
    twin2 = chat_row(TWIN2, K_TWIN, title="same   title")
    every = [alpha, beta, plain, twin1, twin2]
    p_alpha = projected(ALPHA, title="Alpha Notes", summary="Weekly alpha summary", category="work", slug="alpha-notes")
    p_beta = projected(BETA, title="Beta  Plans", category=None, slug="beta-plans")
    p_plain = projected(PLAIN)
    p_twin2 = projected(TWIN2, title="same   title")

    # Loaded Alpha: the master wrapper wins over a decoy row-level key.
    loaded_chat = dict(alpha)
    loaded_chat["encrypted_chat_key"] = seal(K_DECOY, MASTER)
    child_content = json.dumps({"url": "https://example.invalid/a", "rank": 1}, separators=(",", ":"))
    payload = {
        "chat": loaded_chat,
        "chat_key_wrappers": [
            {"key_type": "master", "hashed_chat_id": sha(ALPHA), "encrypted_chat_key": seal(K_ALPHA, MASTER)},
        ],
        "messages": [
            {"message_id": "m1", "role": "user", "encrypted_content": text("Hello alpha", K_ALPHA)},
            json.dumps({
                "message_id": "m2", "role": "assistant",
                "encrypted_content": text("Hi, here are results.", K_ALPHA),
                "encrypted_category": text("general_knowledge", K_ALPHA),
            }),
        ],
        "embeds": [
            {"embed_id": "emb-master", "encrypted_type": text("code-code", K_EMBED_MASTER),
             "encrypted_content": text("print('hi')", K_EMBED_MASTER)},
            {"embed_id": "emb-parent", "encrypted_type": text("web-search", K_EMBED_PARENT),
             "encrypted_content": text(json.dumps({"query": "alpha"}), K_EMBED_PARENT)},
            {"embed_id": "emb-child", "parent_embed_id": "emb-parent",
             "encrypted_type": text("web-website", K_EMBED_PARENT), "encrypted_content": text(child_content, K_EMBED_PARENT)},
            {"embed_id": "emb-orphan", "encrypted_type": text("hidden", K_OTHER)},
        ],
        "embed_keys": [
            {"hashed_embed_id": sha("emb-master"), "key_type": "master", "encrypted_embed_key": seal(K_EMBED_MASTER, MASTER)},
            {"hashed_embed_id": sha("emb-parent"), "key_type": "chat", "encrypted_embed_key": seal(K_EMBED_PARENT, K_ALPHA)},
        ],
    }
    loaded_expected = {
        "chat": p_alpha,
        "messages": [
            {"message_id": "m1", "role": "user", "content": "Hello alpha", "category": None},
            {"message_id": "m2", "role": "assistant", "content": "Hi, here are results.", "category": "general_knowledge"},
        ],
        "embeds": [
            {"embed_id": "emb-master", "type": "code-code", "content": "print('hi')"},
            {"embed_id": "emb-parent", "type": "web-search", "content": {"query": "alpha"}},
            {"embed_id": "emb-child", "type": "web-website", "content": {"url": "https://example.invalid/a", "rank": 1}},
            {"embed_id": "emb-orphan", "type": None, "content": None},
        ],
    }
    load_alpha = {"method": "GET", "path": f"/v1/sdk/chats/{ALPHA}", "status": 200, "response": payload}
    list_all = {"method": "GET", "path": "/v1/sdk/chats", "query": {"limit": "0", "offset": "0"}, "status": 200, "response": {"chats": every}}

    def vector(identity, operation, routes, *, expected=None, error=None, session=True, **arguments):
        return {"id": identity, "operation": operation, "arguments": arguments, "routes": routes,
                "session": session, "expected": expected, "expected_error": error}

    vectors = [
        vector("list-default-decrypts-metadata", "list",
               [{"method": "GET", "path": "/v1/sdk/chats", "query": {"limit": "10", "offset": "0"}, "status": 200,
                 "response": {"chats": [alpha, beta, plain]}}],
               expected=[p_alpha, p_beta, p_plain]),
        vector("list-explicit-page", "list",
               [{"method": "GET", "path": "/v1/sdk/chats", "query": {"limit": "2", "offset": "4"}, "status": 200,
                 "response": {"chats": [twin2]}}],
               expected=[p_twin2], limit=2, offset=4),
        vector("list-empty-needs-no-key", "list",
               [{"method": "GET", "path": "/v1/sdk/chats", "query": {"limit": "10", "offset": "0"}, "status": 200,
                 "response": {"chats": []}}],
               expected=[], session=False),
        vector("list-keyless-row-unchanged", "list",
               [{"method": "GET", "path": "/v1/sdk/chats", "query": {"limit": "10", "offset": "0"}, "status": 200,
                 "response": {"chats": [plain]}}],
               expected=[p_plain], session=False),
        vector("search-matches-decrypted-title", "search", [list_all], expected=[p_alpha], query="  ALPHA "),
        vector("search-pages-local-matches", "search", [list_all], expected=[p_twin2], query="title", limit=1, offset=1),
        vector("load-uuid-wrapper-precedence", "load", [load_alpha], expected=loaded_expected, chat_id=ALPHA),
        vector("load-by-slug", "load", [list_all, load_alpha], expected=loaded_expected, chat_id="Alpha-Notes"),
        vector("load-by-id-prefix", "load", [list_all, load_alpha], expected=loaded_expected, chat_id="a1a1a1a1-11"),
        vector("load-by-collapsed-title", "load", [list_all, {**load_alpha, "path": f"/v1/sdk/chats/{BETA}",
               "response": {"chat": beta, "messages": []}}],
               expected={"chat": p_beta, "messages": [], "embeds": None}, chat_id="  beta plans "),
        vector("load-ambiguous-title-refused", "load", [list_all], error="invalid", chat_id="Same Title"),
        vector("load-unknown-name-refused", "load", [list_all], error="invalid", chat_id="no such chat"),
        vector("load-missing-uuid-invalid", "load",
               [{"method": "GET", "path": f"/v1/sdk/chats/{PLAIN}", "status": 404, "response": {"detail": "Not found"}}],
               error="invalid", session=False, chat_id=PLAIN),
        vector("list-unauthenticated", "list",
               [{"method": "GET", "path": "/v1/sdk/chats", "query": {"limit": "10", "offset": "0"}, "status": 401,
                 "response": {"detail": "Invalid API key"}}],
               error="authentication", session=False),
        vector("load-forbidden", "load",
               [{"method": "GET", "path": f"/v1/sdk/chats/{ALPHA}", "status": 403, "response": {"detail": "Forbidden"}}],
               error="forbidden", session=False, chat_id=ALPHA),
        vector("list-server-unavailable", "list",
               [{"method": "GET", "path": "/v1/sdk/chats", "query": {"limit": "10", "offset": "0"}, "status": 503,
                 "response": {"detail": "Unavailable"}}],
               error="offline", session=False),
    ]
    return {
        "schema_version": 1,
        "capabilities": {
            CAPABILITY: {
                "api_key": API_KEY,
                "device_id": DEVICE,
                "session": {"key_wrapper": key_wrapper(), "user": {"id": "synthetic-chat-owner"}},
                "vectors": vectors,
            }
        },
    }


def main() -> None:
    OUTPUT.write_text(json.dumps(build(), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
