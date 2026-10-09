"""Native cache replay remains Vault ciphertext across the API queue boundary."""

# contract-test-file: infrastructure
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.core.api.app.schemas.ai_skill_schemas import AskSkillRequest
from backend.core.api.app.schemas.chat import AIHistoryMessage, MessageInCache
from backend.core.api.app.services.cache_chat_mixin import ChatCacheMixin
from backend.shared.python_utils.native_cache_history import (
    add_history_with_optional_native_context, canonical_content_sha256,
    canonical_history_content_sha256, retained_native_cache_contexts,
)


def _row(message_id: str, role: str, content: str, *, ciphertext: str | None = None) -> str:
    return MessageInCache(
        id=message_id, chat_id="chat", role=role, encrypted_content=f"vault:{content}",
        encrypted_native_cache_context=ciphertext, sender_name="user" if role == "user" else None,
        status="delivered", created_at=1,
    ).model_dump_json()


def _client(message_id: str, role: str, content: str) -> dict:
    return {"message_id": message_id, "role": role, "content": content, "created_at": 1}


def test_queue_serializes_only_encrypted_replay() -> None:
    message = AIHistoryMessage(
        message_id="assistant", role="assistant", content="Answer", created_at=1,
        encrypted_native_cache_context="vault-native-ciphertext",
        native_cache_context={"secret": "PRIVATE-REPLAY-PLAINTEXT"},
    )
    request = AskSkillRequest(user_id="owner", user_id_hash="hash", chat_id="chat",
                              message_id="current", message_history=[message])
    serialized = request.model_dump_json()
    queued_message = json.loads(serialized)["message_history"][0]
    assert "vault-native-ciphertext" in serialized
    assert queued_message["encrypted_native_cache_context"] == "vault-native-ciphertext"
    assert "native_cache_context" not in queued_message
    assert "PRIVATE-REPLAY-PLAINTEXT" not in serialized
    assert "PRIVATE-REPLAY-PLAINTEXT" not in repr(message)
    assert "vault-native-ciphertext" not in repr(message)
    assert AIHistoryMessage(
        role="user", content="Hello", created_at=1,
    ).model_dump().get("encrypted_native_cache_context") is None


def test_canonical_hash_uses_original_history_content_and_ignores_client_claim():
    original = "Before embed reference ```json\n{\"embed_ref\":\"image.png\"}\n```"
    resolved = "Before embed reference [TOON image description]"
    client_row = {"content": original, "native_cache_canonical_content_sha256": "f" * 64}
    digest = canonical_history_content_sha256(client_row)
    assert digest == canonical_content_sha256(original)
    assert digest != canonical_content_sha256(resolved)
    client_row["native_cache_canonical_content_sha256"] = "0" * 64
    assert canonical_history_content_sha256(client_row) == digest

    document = {"type": "doc", "content": [{"type": "text", "text": "Hello"}]}
    assert canonical_history_content_sha256({"content": document}) == canonical_content_sha256(
        json.dumps(document),
    )

    message = AIHistoryMessage(
        message_id="user", role="user", content=resolved, created_at=1,
        native_cache_canonical_content_sha256=digest,
    )
    queued = message.model_dump_json()
    assert digest in queued
    assert original not in queued
    assert digest not in repr(message)


@pytest.mark.asyncio
@pytest.mark.parametrize("change,expected", [
    ("none", {"a2": "cipher-a2", "a4": "cipher-a4"}),
    ("edit_prior", {"a2": "cipher-a2"}),
    ("remove_prior", {}),
    ("edit_assistant", {}),
    ("alter_user_sender", {}),
    ("alter_assistant_sender", {}),
    ("alter_category", {"a2": "cipher-a2"}),
    ("alter_timestamp", {"a2": "cipher-a2"}),
    ("alter_assistant_timestamp", {}),
    ("assistant_default_name", {"a2": "cipher-a2", "a4": "cipher-a4"}),
])
async def test_recache_retains_only_exact_canonical_prefix(change, expected):
    client = [_client("u1", "user", "First"), _client("a2", "assistant", "Answer 1"),
              _client("u3", "user", "Follow up"), _client("a4", "assistant", "Answer 2")]
    if change == "edit_prior":
        client[2]["content"] = "Edited follow up"
    elif change == "remove_prior":
        client.pop(0)
    elif change == "edit_assistant":
        client[1]["content"] = "Edited answer"
    elif change == "alter_user_sender":
        client[0]["sender_name"] = "Pat"
    elif change == "alter_assistant_sender":
        client[1]["sender_name"] = "Different assistant"
    elif change == "alter_category":
        client[2]["category"] = "changed"
    elif change == "alter_timestamp":
        client[2]["created_at"] = 2
    elif change == "alter_assistant_timestamp":
        client[1]["created_at"] = 2
    elif change == "assistant_default_name":
        client[1]["sender_name"] = "assistant"
    client[-1]["encrypted_native_cache_context"] = "CLIENT-FORGED-CIPHERTEXT"
    newest_first = [
        _row("current", "user", "Current"),
        _row("a4", "assistant", "Answer 2", ciphertext="cipher-a4"),
        _row("u3", "user", "Follow up"),
        _row("a2", "assistant", "Answer 1", ciphertext="cipher-a2"),
        _row("u1", "user", "First"),
    ]
    decrypt = AsyncMock(side_effect=lambda cipher, _key: cipher.removeprefix("vault:"))
    retained = await retained_native_cache_contexts(
        client, newest_first, current_message_id="current", chat_id="chat",
        encryption_service=SimpleNamespace(decrypt_with_user_key=decrypt),
        user_vault_key_id="vault-key",
    )
    assert retained == expected
    assert "CLIENT-FORGED-CIPHERTEXT" not in repr(retained)


@pytest.mark.asyncio
async def test_recache_vault_failure_resets_remaining_prefix():
    async def fail_on_second(cipher, _key):
        if cipher == "vault:Answer 1":
            raise RuntimeError("vault unavailable")
        return cipher.removeprefix("vault:")

    retained = await retained_native_cache_contexts(
        [_client("u1", "user", "First"), _client("a2", "assistant", "Answer 1"),
         _client("a3", "assistant", "Answer 2")],
        [_row("a3", "assistant", "Answer 2", ciphertext="cipher-a3"),
         _row("a2", "assistant", "Answer 1", ciphertext="cipher-a2"),
         _row("u1", "user", "First")],
        current_message_id="current", chat_id="chat",
        encryption_service=SimpleNamespace(decrypt_with_user_key=fail_on_second),
        user_vault_key_id="vault-key",
    )
    assert retained == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("change,reason", [
    ("timestamp", "timestamp_mismatch"),
    ("content", "content_mismatch"),
    ("category", "category_mismatch"),
    ("sender", "sender_mismatch"),
    ("id", "id_mismatch"),
    ("role", "role_mismatch"),
    ("chat", "chat_mismatch"),
])
async def test_recache_fixture_logs_only_fixed_boundary_reason(monkeypatch, caplog, change, reason):
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("OPENMATES_CI_ISOLATED", "1")
    client = [_client("u1", "user", "PRIVATE_USER_SENTINEL"),
              _client("a2", "assistant", "PRIVATE_ASSISTANT_SENTINEL"),
              _client("current", "user", "<<<TEST_LIVE_MOCK:native_cache_tools_v1>>>")]
    cached = [_row("current", "user", "Current"),
              _row("a2", "assistant", "PRIVATE_ASSISTANT_SENTINEL", ciphertext="PRIVATE_CIPHER_SENTINEL"),
              _row("u1", "user", "PRIVATE_USER_SENTINEL")]
    if change == "timestamp":
        client[1]["created_at"] = 2
    elif change == "content":
        client[1]["content"] = "EDITED_PRIVATE_ASSISTANT_SENTINEL"
    elif change == "category":
        client[1]["category"] = "changed"
    elif change == "sender":
        client[1]["sender_name"] = "changed"
    elif change == "id":
        client[1]["message_id"] = "changed"
    elif change == "role":
        client[1]["role"] = "user"
    elif change == "chat":
        row = json.loads(cached[1])
        row["chat_id"] = "changed"
        cached[1] = json.dumps(row)
    decrypt = AsyncMock(side_effect=lambda cipher, _key: cipher.removeprefix("vault:"))
    with caplog.at_level(logging.INFO, logger="backend.shared.python_utils.native_cache_history"):
        retained = await retained_native_cache_contexts(
            client, cached, current_message_id="current", chat_id="chat",
            encryption_service=SimpleNamespace(decrypt_with_user_key=decrypt),
            user_vault_key_id="vault-key",
        )
    assert retained == {}
    diagnostic_logs = [record.getMessage() for record in caplog.records
                       if "Native fixture retention:" in record.getMessage()]
    assert diagnostic_logs == [f"Native fixture retention: reason={reason} matched_count=1"]
    assert all("PRIVATE_" not in message for message in diagnostic_logs)

    caplog.clear()
    monkeypatch.delenv("OPENMATES_CI_ISOLATED")
    with caplog.at_level(logging.INFO, logger="backend.shared.python_utils.native_cache_history"):
        await retained_native_cache_contexts(
            client, cached, current_message_id="current", chat_id="chat",
            encryption_service=SimpleNamespace(decrypt_with_user_key=decrypt),
            user_vault_key_id="vault-key",
        )
    assert not any("Native fixture retention:" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("first_failure", [False, RuntimeError("cache admission error")])
async def test_optional_ciphertext_admission_retries_canonical_encrypted_row(first_failure):
    serialized_attempts = []

    async def add(_user, _chat, serialized):
        row = json.loads(serialized)
        serialized_attempts.append(row)
        if len(serialized_attempts) == 1:
            if first_failure:
                raise first_failure
            return False
        return True

    cached = MessageInCache(id="assistant", chat_id="chat", role="assistant",
        encrypted_content="vault:Answer", encrypted_native_cache_context="vault:replay",
        status="delivered", created_at=1)
    inference = AIHistoryMessage(message_id="assistant", role="assistant",
        content="Answer", created_at=1, encrypted_native_cache_context="vault:replay")
    assert await add_history_with_optional_native_context(
        SimpleNamespace(add_message_to_chat_history=add), "owner", "chat", cached, inference,
    )
    assert len(serialized_attempts) == 2
    assert serialized_attempts[0]["encrypted_native_cache_context"] == "vault:replay"
    assert serialized_attempts[1].get("encrypted_native_cache_context") is None
    assert serialized_attempts[1]["encrypted_content"] == "vault:Answer"
    assert inference.encrypted_native_cache_context is None


class _DeleteAIHistoryCache(ChatCacheMixin):
    def __init__(self, *, existing: bool = False, unavailable: bool = False):
        self.redis = SimpleNamespace(
            delete=AsyncMock(
                side_effect=RuntimeError("Redis unavailable") if unavailable else None,
                return_value=int(existing),
            ),
            zrem=AsyncMock(return_value=int(existing)),
            hdel=AsyncMock(return_value=int(existing)),
        )

    @property
    async def client(self):
        return self.redis


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_ai_history_delete_is_idempotent_for_evicted_or_present_key(existing):
    cache = _DeleteAIHistoryCache(existing=existing)

    assert await cache.delete_ai_messages_history("owner", "chat") is True
    cache.redis.delete.assert_awaited_once_with(cache._get_ai_messages_key("owner", "chat"))
    cache.redis.zrem.assert_awaited_once_with(cache._get_ai_cache_lru_key("owner"), "chat")
    cache.redis.hdel.assert_awaited_once_with(cache._get_ai_cache_bytes_key("owner"), "chat")


@pytest.mark.asyncio
async def test_ai_history_delete_reports_redis_failure():
    cache = _DeleteAIHistoryCache(unavailable=True)

    assert await cache.delete_ai_messages_history("owner", "chat") is False
    cache.redis.zrem.assert_not_awaited()
    cache.redis.hdel.assert_not_awaited()
