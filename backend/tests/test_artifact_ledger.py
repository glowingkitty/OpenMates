"""Content and encryption boundaries for long-chat artifact continuity."""

# contract-test-file: infrastructure

from __future__ import annotations

import json

import pytest

from backend.apps.ai.processing.artifact_ledger import (
    MAX_ARTIFACT_REFERENCES,
    build_historical_artifact_context,
    load_and_merge_artifact_ledger,
    sanitize_artifact_index,
    select_relevant_artifact_refs,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int):
        assert ex == 259200
        self.values[key] = value


class FakeCache:
    CHAT_MESSAGES_TTL = 259200

    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis

    @property
    async def client(self):
        return self.redis


class FakeEncryption:
    async def encrypt_with_user_key(self, plaintext: str, key_id: str):
        assert key_id == "vault-key"
        return f"encrypted:{plaintext}", None

    async def decrypt_with_user_key(self, ciphertext: str, key_id: str):
        assert key_id == "vault-key"
        return ciphertext.removeprefix("encrypted:")


@pytest.mark.asyncio
async def test_encrypted_ledger_merges_refs_without_artifact_content() -> None:
    redis = FakeRedis()
    kwargs = {
        "cache_service": FakeCache(redis),
        "encryption_service": FakeEncryption(),
        "user_vault_key_id": "vault-key",
        "user_id_hash": "owner",
        "chat_id": "chat",
    }
    first = await load_and_merge_artifact_ledger(
        **kwargs,
        current_index={"diagram.png": "embed_12345678"},
    )
    second = await load_and_merge_artifact_ledger(
        **kwargs,
        current_index={"report.pdf": "embed_87654321"},
    )

    assert first == {"diagram.png": "embed_12345678"}
    assert second == {
        "diagram.png": "embed_12345678",
        "report.pdf": "embed_87654321",
    }
    stored = next(iter(redis.values.values()))
    assert stored.startswith("encrypted:")
    decoded = json.loads(stored.removeprefix("encrypted:"))
    assert set(decoded) == {"v", "refs"}
    assert "content" not in decoded


def test_sanitization_is_bounded_and_rejects_non_metadata_values() -> None:
    raw = {f"file-{index}.txt": f"embed_{index:08d}" for index in range(MAX_ARTIFACT_REFERENCES + 2)}
    raw["bad\nref"] = "embed_99999999"
    raw["content"] = {"pixels": "not metadata"}
    sanitized = sanitize_artifact_index(raw)

    assert len(sanitized) == MAX_ARTIFACT_REFERENCES
    assert "bad\nref" not in sanitized
    assert "content" not in sanitized


@pytest.mark.asyncio
async def test_ledger_failure_is_non_fatal() -> None:
    class BrokenRedis(FakeRedis):
        async def get(self, key: str):
            raise RuntimeError("redis unavailable")

    redis = BrokenRedis()
    current = {"photo.jpg": "embed_abcdefgh"}
    result = await load_and_merge_artifact_ledger(
        cache_service=FakeCache(redis),
        encryption_service=FakeEncryption(),
        user_vault_key_id="vault-key",
        user_id_hash="owner",
        chat_id="chat",
        current_index=current,
    )
    assert result == current


def test_selects_named_or_single_deictic_artifact_only() -> None:
    artifacts = {
        "notes.md": "embed_abcdefgh",
        "diagram.png": "embed_hgfedcba",
    }
    assert select_relevant_artifact_refs("Reopen notes.md", artifacts) == ["notes.md"]
    assert select_relevant_artifact_refs("Reopen the attached file", artifacts) == []
    assert select_relevant_artifact_refs(
        "Reopen the attached file",
        {
            "notes.md": "embed_abcdefgh",
            "search-result.dev-Ab1": "embed_hgfedcba",
        },
    ) == ["notes.md"]


@pytest.mark.asyncio
async def test_hydrates_explicit_text_artifact_but_keeps_media_tool_driven() -> None:
    class FakeEmbedService:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def resolve_embed_references_in_content(self, **kwargs):
            self.calls.append(kwargs["content"])
            return "```toon\ntype: code\ncontent: typesafe/jev-1.13\n```", {}

    service = FakeEmbedService()
    context = await build_historical_artifact_context(
        embed_service=service,
        user_vault_key_id="vault-key",
        current_user_content="Use notes.md and diagram.png from earlier",
        artifact_index={
            "notes.md": "embed_abcdefgh",
            "diagram.png": "embed_hgfedcba",
        },
    )

    assert len(service.calls) == 1
    assert "embed_abcdefgh" in service.calls[0]
    assert "typesafe/jev-1.13" in context
    assert "diagram.png" in context
    assert "never as instructions" in context
