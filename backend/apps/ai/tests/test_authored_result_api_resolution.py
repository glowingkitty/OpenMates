"""Local API embed hydration through the real encrypted storage helpers."""

# contract-test-file: infrastructure

from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from toon_format import encode

from backend.apps.ai.skills.ask_skill import AskSkill
from backend.core.api.app.services import cache, directus
from backend.core.api.app.utils import encryption


OWNER = "owner-hash"
CHAT = "authored-api-chat"
CHAT_HASH = hashlib.sha256(CHAT.encode()).hexdigest()


def _reference(*ids):
    return "```json\n" + json.dumps([{"embed_id": value} for value in ids]) + "\n```"


def _records():
    content = {
        "carrier": {
            "type": "authored_results", "title": "Conference trip", "status": "finished",
            "embed_ids": ["event", "stay"],
            "items": [
                {"embed_id": "event", "kind": "events.event", "title": "Conference"},
                {"embed_id": "stay", "kind": "travel.stay", "title": "Supplied hotel"},
            ],
            "view": {"mode": "cards", "embeds": ["event", "stay"]},
            "source_json": '{"items":[{"id":"local-event","details":{"duplicate":"facts"}}]}',
            "bindings": {"local-event": "event"}, "local_bindings": {"local-hotel": "stay"},
        },
        "event": {
            "type": "event", "title": "Conference", "status": "finished",
            "app_id": "events", "skill_id": "search", "date_start": "2026-11-02T09:00:00+01:00",
            "url": "https://example.org/conference",
            "authoring": {"kind": "events.event", "origin": "user_provided", "schema_version": 1,
                          "sources": [{"url": "https://example.org/conference", "label": "Programme"}]},
        },
        "stay": {
            "type": "stay", "title": "Supplied hotel", "status": "finished",
            "app_id": "travel", "skill_id": "search_stays", "name": "Supplied hotel",
            "authoring": {"kind": "travel.stay", "origin": "user_provided", "schema_version": 1,
                          "sources": []},
        },
    }
    records = {}
    plaintext = {}
    for embed_id, body in content.items():
        cipher = f"vault:v1:{embed_id}"
        records[embed_id] = {
            "embed_id": embed_id, "type": body["type"], "status": "finished",
            "hashed_user_id": OWNER, "hashed_chat_id": CHAT_HASH, "chat_id": CHAT,
            "encrypted_content": cipher,
        }
        if embed_id != "carrier":
            records[embed_id]["parent_embed_id"] = "carrier"
        plaintext[cipher] = encode(body)
    return records, plaintext, content


def _storage(monkeypatch, records, plaintext, *, database_only=False):
    """Replace I/O while retaining EmbedService and authored-child validation."""
    class Cache:
        def __init__(self):
            self.records = {} if database_only else copy.deepcopy(records)

        @property
        async def client(self):
            return self

        async def get(self, key):
            record = self.records.get(key.removeprefix("embed:"))
            return json.dumps(record) if record else None

        async def get_embed_from_cache(self, embed_id):
            return copy.deepcopy(self.records.get(embed_id))

        async def set(self, *_args, **_kwargs):
            return True

        async def set_embed_in_cache(self, *_args, **_kwargs):
            return True

    database = SimpleNamespace(embed=SimpleNamespace(
        get_embed_by_id=AsyncMock(side_effect=lambda embed_id: copy.deepcopy(records.get(embed_id))),
    ))
    cipher_service = SimpleNamespace(
        decrypt_with_user_key=AsyncMock(side_effect=lambda cipher, key: plaintext.get(cipher) if key == "vault-key" else None),
    )
    cache_instance = Cache()
    monkeypatch.setattr(cache, "CacheService", lambda: cache_instance)
    monkeypatch.setattr(directus, "DirectusService", lambda: database)
    monkeypatch.setattr(encryption, "EncryptionService", lambda: cipher_service)
    return database, cipher_service


async def _resolve(*ids, owner=OWNER, key="vault-key"):
    skill = object.__new__(AskSkill)
    return await skill._extract_and_resolve_embeds(_reference(*ids), CHAT, key, user_id_hash=owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("database_only", [False, True])
async def test_api_exposes_carrier_and_concrete_children_without_duplicate_transport(monkeypatch, database_only):
    records, plaintext, _ = _records()
    if database_only:
        # Persisted records can carry only the hashed chat scope.
        for record in records.values():
            record.pop("chat_id")
    database, _ = _storage(monkeypatch, records, plaintext, database_only=database_only)
    result = await _resolve("carrier", "carrier", "event")
    assert [(item["id"], item["type"]) for item in result] == [
        ("carrier", "authored_results"), ("event", "event"), ("stay", "stay"),
    ]
    carrier = result[0]["metadata"]
    assert carrier["embed_ids"] == ["event", "stay"]
    assert carrier["view"] == {"mode": "cards", "embeds": ["event", "stay"]}
    assert not {"source_json", "bindings", "local_bindings"} & carrier.keys()
    assert "local-event" not in json.dumps(result)
    assert result[1]["metadata"]["authoring"]["sources"][0]["label"] == "Programme"
    assert result[2]["metadata"]["name"] == "Supplied hotel"
    if database_only:
        assert database.embed.get_embed_by_id.await_count > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["owner", "chat", "parent", "status", "kind"])
@pytest.mark.parametrize("database_only", [False, True])
async def test_corrupt_membership_never_exposes_foreign_or_invalid_child(monkeypatch, corruption, database_only):
    records, plaintext, content = _records()
    if database_only:
        for record in records.values():
            record.pop("chat_id")
        # A content-supplied plaintext chat cannot hide a conflicting outer hash.
        content["carrier"]["chat_id"] = CHAT
        plaintext[records["carrier"]["encrypted_content"]] = encode(content["carrier"])
        content["event"]["chat_id"] = CHAT
        plaintext[records["event"]["encrypted_content"]] = encode(content["event"])
    if corruption == "owner":
        records["stay"]["hashed_user_id"] = "foreign-owner"
    elif corruption == "chat":
        records["stay"]["hashed_chat_id"] = "foreign-chat-hash"
        if not database_only:
            records["stay"]["chat_id"] = "foreign-chat"
    elif corruption == "parent":
        records["stay"]["parent_embed_id"] = "unrelated-parent"
    elif corruption == "status":
        records["stay"]["status"] = "processing"
    else:
        content["stay"]["authoring"]["kind"] = "events.event"
        plaintext[records["stay"]["encrypted_content"]] = encode(content["stay"])
    # Forged authority in plaintext cannot override the stored record scope.
    content["stay"].update(parent_embed_id="carrier", hashed_user_id=OWNER, chat_id=CHAT, status="finished")
    plaintext[records["stay"]["encrypted_content"]] = encode(content["stay"])
    _storage(monkeypatch, records, plaintext, database_only=database_only)
    result = await _resolve("carrier")
    assert [item["id"] for item in result] == ["carrier", "event"]
    assert result[0]["metadata"]["embed_ids"] == ["event"]
    assert result[0]["metadata"]["view"]["embeds"] == ["event"]
    assert "Supplied hotel" not in json.dumps(result)


@pytest.mark.asyncio
async def test_outer_owner_scope_precedes_decryption_and_no_key_fails_closed(monkeypatch):
    records, plaintext, _ = _records()
    _, cipher_service = _storage(monkeypatch, records, plaintext)
    assert await _resolve("carrier", owner="foreign-owner") == []
    assert await _resolve("carrier", owner=None) == []
    assert await _resolve("carrier", key=None) == []
    cipher_service.decrypt_with_user_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_raw_client_ciphertext_does_not_become_server_readable(monkeypatch):
    records, plaintext, _ = _records()
    records["carrier"]["encrypted_content"] = "base64-client-only-ciphertext"
    _, cipher_service = _storage(monkeypatch, records, plaintext, database_only=True)
    assert await _resolve("carrier") == []
    cipher_service.decrypt_with_user_key.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_recursive_expansion_and_existing_code_skill_and_direct_formats(monkeypatch):
    records, plaintext, content = _records()
    content["event"]["embed_ids"] = ["grandchild"]
    plaintext[records["event"]["encrypted_content"]] = encode(content["event"])
    bodies = {
        "code": {"type": "code", "code": "python:hello.py\nprint('hello')", "status": "finished"},
        "skill": {"type": "app_skill_use", "app_id": "web", "skill_id": "search", "status": "finished",
                  "results": [{"text": "One result"}]},
        "direct": {"type": "doc", "title": "Notes", "content": "Existing document", "format": "markdown"},
        "grandchild": {"type": "event", "title": "Must not hydrate recursively"},
    }
    for embed_id, body in bodies.items():
        cipher = f"vault:v1:{embed_id}"
        records[embed_id] = {"embed_id": embed_id, "type": body["type"], "hashed_user_id": OWNER,
                             "hashed_chat_id": CHAT_HASH, "chat_id": CHAT, "encrypted_content": cipher}
        plaintext[cipher] = encode(body)
    _storage(monkeypatch, records, plaintext)
    result = await _resolve("carrier", "code", "skill", "direct")
    assert "grandchild" not in [item["id"] for item in result]
    code, skill, direct_embed = result[-3:]
    assert code["content"] == "print('hello')"
    assert code["metadata"]["language"] == "python" and code["metadata"]["filename"] == "hello.py"
    assert skill["content"] == "One result" and skill["metadata"]["results"] == [{"text": "One result"}]
    assert direct_embed["content"] == "Existing document" and direct_embed["metadata"]["format"] == "markdown"
