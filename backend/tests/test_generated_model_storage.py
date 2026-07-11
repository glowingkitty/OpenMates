# backend/tests/test_generated_model_storage.py
#
# Contract tests for large generated-model encryption.
# Master and print artifacts use independently authenticated chunks so download
# paths can stream without buffering a complete 30-100 MB plaintext model.
# These tests pin format versioning, ordering, integrity, and corruption failure.

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from backend.shared.python_utils.generated_assets import decrypt_chunked_stream, encrypt_chunked_stream


async def _source(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


async def _collect(source: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in source])


@pytest.mark.asyncio
async def test_chunked_model_round_trip_preserves_first_middle_and_last_chunks() -> None:
    key = b"\x42" * 32
    plaintext = [b"first-", b"middle-contents-", b"last"]
    encrypted = await _collect(encrypt_chunked_stream(_source(*plaintext), key=key, chunk_size=8))
    decrypted = await _collect(decrypt_chunked_stream(_source(encrypted), key=key))

    assert encrypted.startswith(b"OMGAEAD1")
    assert decrypted == b"".join(plaintext)


@pytest.mark.asyncio
async def test_chunked_model_corruption_fails_authentication() -> None:
    key = b"\x42" * 32
    encrypted = bytearray(
        await _collect(encrypt_chunked_stream(_source(b"a" * 40), key=key, chunk_size=8))
    )
    first_ciphertext_offset = 8 + 4 + 12
    encrypted[first_ciphertext_offset] ^= 0x01

    with pytest.raises(ValueError, match="authentication"):
        await _collect(decrypt_chunked_stream(_source(bytes(encrypted)), key=key))


@pytest.mark.asyncio
async def test_chunked_model_rejects_wrong_key_and_truncated_frame() -> None:
    encrypted = await _collect(
        encrypt_chunked_stream(_source(b"model-bytes"), key=b"\x42" * 32, chunk_size=4)
    )

    with pytest.raises(ValueError):
        await _collect(decrypt_chunked_stream(_source(encrypted), key=b"\x24" * 32))
    with pytest.raises(ValueError, match="truncated"):
        await _collect(decrypt_chunked_stream(_source(encrypted[:-3]), key=b"\x42" * 32))


@pytest.mark.asyncio
async def test_chunked_model_rejects_oversized_declared_frame() -> None:
    envelope = b"OMGAEAD1" + (0xFFFFFFFF).to_bytes(4, "big")
    with pytest.raises(ValueError, match="frame size"):
        await _collect(decrypt_chunked_stream(_source(envelope), key=b"\x42" * 32))


@pytest.mark.asyncio
async def test_chunked_model_rejects_trailing_data_after_empty_transport_chunk() -> None:
    key = b"\x42" * 32
    encrypted = await _collect(encrypt_chunked_stream(_source(b"model"), key=key, chunk_size=8))
    with pytest.raises(ValueError, match="trailing"):
        await _collect(decrypt_chunked_stream(_source(encrypted, b"", b"unexpected"), key=key))


@pytest.mark.asyncio
async def test_chunked_model_rejects_oversized_transport_chunk() -> None:
    oversized = b"x" * (8 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="transport chunk"):
        await _collect(decrypt_chunked_stream(_source(oversized), key=b"\x42" * 32))
