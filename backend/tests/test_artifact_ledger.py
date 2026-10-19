"""Content and encryption boundaries for long-chat artifact continuity."""

# contract-test-file: infrastructure

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from backend.apps.ai.processing.artifact_ledger import (
    MAX_ARTIFACT_REFERENCES,
    MAX_IMAGE_ALIAS_EMBEDS,
    build_historical_artifact_context,
    enrich_historical_image_aliases,
    load_and_merge_artifact_ledger,
    recover_inline_upload_artifacts,
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
    assert select_relevant_artifact_refs(
        "Reopen typesafe-jev.md",
        {"typesafe-jev-md-7a0d7e9f-9709-41fe-949a--331740": "embed_abcdefgh"},
    ) == ["typesafe-jev-md-7a0d7e9f-9709-41fe-949a--331740"]


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


@pytest.mark.asyncio
async def test_recovers_cli_inline_upload_ref_from_unique_chat_embed_prefix() -> None:
    class InlineCache:
        async def get_chat_embed_ids(self, chat_id: str):
            assert chat_id == "chat"
            return [
                "7a0d7e9f-9709-41fe-949a-519215cbead0",
                "014fe34e-6e54-4385-a7cc-adf684ca32f8",
            ]

    recovered = await recover_inline_upload_artifacts(
        cache_service=InlineCache(),
        chat_id="chat",
        message_history=[
            {
                "content": "[!](embed:typesafe-jev-md-7a0d7e9f-9709-41fe-949a--331740)"
            }
        ],
    )

    assert recovered == {
        "typesafe-jev-md-7a0d7e9f-9709-41fe-949a--331740":
            "7a0d7e9f-9709-41fe-949a-519215cbead0"
    }


def _upload_ref(filename: str, suffix: str) -> str:
    return filename.replace(".", "-") + f"-{suffix}-1111-4111-8111--331740"


def _image_record(filename: str) -> dict:
    from toon_format import encode

    return {
        "hashed_user_id": "owner-hash",
        "encrypted_content": "encrypted:" + encode({
            "app_id": "images", "skill_id": "upload", "type": "image",
            "filename": filename,
        }),
    }


async def _image_aliases(index, records, *, persisted=None):
    class MetadataCache:
        calls = []

        async def get_embed_from_cache(self, embed_id):
            self.calls.append(embed_id)
            return records.get(embed_id)

    class MetadataEncryption:
        calls = []

        async def decrypt_with_user_key(self, ciphertext, key_id):
            assert key_id == "vault-key"
            self.calls.append(ciphertext)
            return ciphertext.removeprefix("encrypted:")

    db_calls = []

    async def get_embed_by_id(embed_id):
        db_calls.append(embed_id)
        return (persisted or {}).get(embed_id)

    cache, encryption = MetadataCache(), MetadataEncryption()
    result = await enrich_historical_image_aliases(
        artifact_index=index, cache_service=cache,
        directus_service=SimpleNamespace(embed=SimpleNamespace(get_embed_by_id=get_embed_by_id)),
        encryption_service=encryption, user_vault_key_id="vault-key",
        user_id="owner", user_id_hash="owner-hash",
    )
    return result, cache.calls, encryption.calls, db_calls


@pytest.mark.asyncio
async def test_three_prior_images_gain_verified_filename_and_mixed_aliases() -> None:
    names = ["front.png", "side.jpg", "detail.webp"]
    ids = ["server_embed_0001", "server_embed_0002", "server_embed_0003"]
    # Client UUIDs deliberately have no relationship to the server embed IDs.
    index = {_upload_ref(name, f"{position:08d}"): embed_id
             for position, (name, embed_id) in enumerate(zip(names, ids))}
    records = {embed_id: _image_record(name) for name, embed_id in zip(names, ids)}
    result, calls, _, db_calls = await _image_aliases(index, records)
    assert all(result[ref] == embed_id for ref, embed_id in index.items())
    assert [result[names[0]], result[list(index)[1]], result[names[2]]] == ids
    assert len(calls) == 3
    assert db_calls == []


@pytest.mark.asyncio
async def test_duplicate_filename_keeps_canonical_refs_and_removes_bare_alias() -> None:
    first, second = _upload_ref("cloth.png", "11111111"), _upload_ref("cloth.png", "22222222")
    index = {first: "server_embed_0001", second: "server_embed_0002", "cloth.png": "server_embed_0002"}
    result, _, _, _ = await _image_aliases(index, {
        "server_embed_0001": _image_record("cloth.png"),
        "server_embed_0002": _image_record("cloth.png"),
    })
    assert result == {first: "server_embed_0001", second: "server_embed_0002"}


@pytest.mark.asyncio
async def test_multiple_refs_for_same_embed_are_not_ambiguous_or_reloaded() -> None:
    index = {
        _upload_ref("cloth.png", "11111111"): "server_embed_0001",
        "cloth.png (2)": "server_embed_0001",
    }
    result, calls, decryptions, _ = await _image_aliases(index, {
        "server_embed_0001": _image_record("cloth.png"),
    })
    assert result == {**index, "cloth.png": "server_embed_0001"}
    assert calls == ["server_embed_0001"]
    assert len(decryptions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    None,
    {"hashed_user_id": "foreign", "encrypted_content": "never decrypt"},
    {"user_id": "foreign", "hashed_user_id": "owner-hash", "encrypted_content": "never decrypt"},
    {"hashed_user_id": "owner-hash", "expires_at": 1, "encrypted_content": "never decrypt"},
    {"hashed_user_id": "owner-hash", "expires_at": True, "encrypted_content": "never decrypt"},
    {"hashed_user_id": "owner-hash"},
])
async def test_missing_foreign_or_expired_competitor_vetoes_filename(invalid) -> None:
    first, second = _upload_ref("cloth.png", "11111111"), _upload_ref("cloth.png", "22222222")
    index = {first: "server_embed_0001", second: "server_embed_0002"}
    result, _, decryptions, db_calls = await _image_aliases(index, {
        "server_embed_0001": _image_record("cloth.png"), "server_embed_0002": invalid,
    })
    assert result == index
    assert len(decryptions) == 1
    assert db_calls == (["server_embed_0002"] if invalid is None else [])


@pytest.mark.asyncio
async def test_alias_metadata_cache_miss_uses_exact_persisted_embed() -> None:
    ref = _upload_ref("cloth.png", "11111111")
    result, _, _, db_calls = await _image_aliases({ref: "server_embed_0001"}, {}, persisted={
        "server_embed_0001": _image_record("cloth.png"),
    })
    assert result == {ref: "server_embed_0001", "cloth.png": "server_embed_0001"}
    assert db_calls == ["server_embed_0001"]


@pytest.mark.asyncio
async def test_fresh_upload_alias_preserves_absolute_expiry_without_decryption() -> None:
    ref = _upload_ref("cloth.png", "11111111")
    created_at = int(time.time()) - 60
    record = {
        "user_id": "owner", "embed_id": "server_embed_0001", "filename": "cloth.png",
        "created_at": created_at, "expires_at": created_at + 86400,
        "content_type": "image/png", "files": {"original": {"s3_key": "private-placeholder"}},
        "vault_wrapped_aes_key": "wrapped-placeholder",
    }
    original = dict(record)
    result, _, decryptions, db_calls = await _image_aliases({ref: "server_embed_0001"}, {
        "server_embed_0001": record,
    })
    assert result == {ref: "server_embed_0001", "cloth.png": "server_embed_0001"}
    assert record == original
    assert decryptions == db_calls == []


@pytest.mark.asyncio
async def test_non_upload_metadata_never_creates_an_image_alias() -> None:
    from toon_format import encode

    ref = _upload_ref("cloth.png", "11111111")
    record = _image_record("cloth.png")
    record["encrypted_content"] = "encrypted:" + encode({
        "app_id": "images", "skill_id": "view", "filename": "cloth.png",
    })
    result, _, _, _ = await _image_aliases({ref: "server_embed_0001"}, {"server_embed_0001": record})
    assert result == {ref: "server_embed_0001"}


@pytest.mark.asyncio
async def test_alias_enrichment_is_bounded_and_never_evicts_canonical_refs() -> None:
    index = {_upload_ref(f"image-{position}.png", f"{position:08d}"): f"server_embed_{position:04d}"
             for position in range(MAX_ARTIFACT_REFERENCES)}
    records = {embed_id: _image_record(f"image-{position}.png")
               for position, embed_id in enumerate(index.values())}
    result, calls, _, _ = await _image_aliases(index, records)
    assert result == index
    assert len(calls) == MAX_IMAGE_ALIAS_EMBEDS


@pytest.mark.asyncio
@pytest.mark.parametrize("fields", [
    {"expires_at": 1}, {"created_at": 1}, {"content_type": "application/pdf"},
    {"files": {}}, {"vault_wrapped_aes_key": ""},
])
async def test_invalid_fresh_upload_metadata_cannot_add_alias(fields) -> None:
    ref = _upload_ref("cloth.png", "11111111")
    created_at = int(time.time()) - 60
    record = {
        "user_id": "owner", "filename": "cloth.png", "created_at": created_at,
        "expires_at": created_at + 86400, "content_type": "image/png",
        "files": {"original": {"s3_key": "private-placeholder"}},
        "vault_wrapped_aes_key": "wrapped-placeholder", **fields,
    }
    result, _, decryptions, _ = await _image_aliases({ref: "server_embed_0001"}, {
        "server_embed_0001": record,
    })
    assert result == {ref: "server_embed_0001"}
    assert decryptions == []


@pytest.mark.asyncio
@pytest.mark.parametrize("filename, competitor", [
    ("cloth.png", "cloth.png (2)"),
    ("a-very-long-original-reference-image-filename.png", "a-very-long-original-reference-image-file"[:40] + "-abcdef"),
    ("cloth.png", "cloth-png-22222222-1111-4111-8111-111111-abcdef"),
])
async def test_unavailable_numbered_or_truncated_cli_ref_vetoes_alias(filename, competitor) -> None:
    first = _upload_ref(filename, "11111111")
    index = {first: "server_embed_0001", competitor: "server_embed_0002"}
    result, _, _, _ = await _image_aliases(index, {"server_embed_0001": _image_record(filename)})
    assert result == index


@pytest.mark.asyncio
async def test_filename_collision_never_removes_another_upload_canonical_ref() -> None:
    first = _upload_ref("first.png", "11111111")
    second = _upload_ref("second.png", "22222222")
    index = {first: "server_embed_0001", second: "server_embed_0002"}
    result, _, _, _ = await _image_aliases(index, {
        "server_embed_0001": _image_record(second),
        "server_embed_0002": _image_record("second.png"),
    })
    assert result == {**index, "second.png": "server_embed_0002"}


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [
    None,
    {"hashed_user_id": "foreign", "encrypted_content": "never decrypt"},
    {"hashed_user_id": "owner-hash", "expires_at": 1, "encrypted_content": "never decrypt"},
])
async def test_unverifiable_competitor_removes_preexisting_bare_filename_alias(invalid) -> None:
    first, second = _upload_ref("cloth.png", "11111111"), _upload_ref("cloth.png", "22222222")
    index = {first: "server_embed_0001", second: "server_embed_0002", "cloth.png": "server_embed_0002"}
    result, _, _, _ = await _image_aliases(index, {
        "server_embed_0001": _image_record("cloth.png"), "server_embed_0002": invalid,
    })
    assert result == {first: "server_embed_0001", second: "server_embed_0002"}
