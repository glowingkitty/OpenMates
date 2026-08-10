"""Versioned chunked AES-GCM envelope for large generated assets.

Each frame is authenticated independently so download routes can decrypt and
stream large model files with bounded memory. The binary format is internal and
versioned; callers must treat it as opaque encrypted storage.
"""

from __future__ import annotations

import os
import struct
from collections.abc import AsyncIterable, AsyncIterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MAGIC = b"OMGAEAD1"
_LENGTH = struct.Struct(">I")
_NONCE_BYTES = 12
_TAG_BYTES = 16
MAX_CHUNK_SIZE = 4 * 1024 * 1024


class _AsyncByteReader:
    def __init__(self, source: AsyncIterable[bytes]) -> None:
        self._iterator = source.__aiter__()
        self._buffer = bytearray()
        self._finished = False

    async def read_exact(self, size: int) -> bytes:
        while len(self._buffer) < size and not self._finished:
            try:
                chunk = await self._iterator.__anext__()
            except StopAsyncIteration:
                self._finished = True
                break
            if chunk:
                if len(chunk) > MAX_CHUNK_SIZE:
                    raise ValueError("Chunked encrypted asset transport chunk exceeds the limit")
                self._buffer.extend(chunk)
        if len(self._buffer) < size:
            raise ValueError("Chunked encrypted asset is truncated")
        result = bytes(self._buffer[:size])
        del self._buffer[:size]
        return result

    async def has_trailing_data(self) -> bool:
        while True:
            if self._buffer:
                return True
            if self._finished:
                return False
            try:
                chunk = await self._iterator.__anext__()
            except StopAsyncIteration:
                self._finished = True
                return False
            if chunk:
                if len(chunk) > MAX_CHUNK_SIZE:
                    raise ValueError("Chunked encrypted asset transport chunk exceeds the limit")
                return True


def _aad(index: int, plaintext_size: int) -> bytes:
    return MAGIC + index.to_bytes(8, "big") + _LENGTH.pack(plaintext_size)


async def encrypt_chunked_stream(
    source: AsyncIterable[bytes],
    *,
    key: bytes,
    chunk_size: int,
) -> AsyncIterator[bytes]:
    """Encrypt arbitrary input chunks into independently authenticated frames."""
    if len(key) != 32:
        raise ValueError("Chunked generated assets require a 32-byte key")
    if not 0 < chunk_size <= MAX_CHUNK_SIZE:
        raise ValueError(f"chunk_size must be between 1 and {MAX_CHUNK_SIZE}")
    aesgcm = AESGCM(key)
    pending = bytearray()
    index = 0
    yield MAGIC
    async for incoming in source:
        view = memoryview(incoming)
        while view:
            take = min(chunk_size - len(pending), len(view))
            pending.extend(view[:take])
            view = view[take:]
            if len(pending) == chunk_size:
                plaintext = bytes(pending)
                pending.clear()
                nonce = os.urandom(_NONCE_BYTES)
                ciphertext = aesgcm.encrypt(nonce, plaintext, _aad(index, len(plaintext)))
                yield _LENGTH.pack(len(plaintext)) + nonce + ciphertext
                index += 1
    if pending:
        plaintext = bytes(pending)
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = aesgcm.encrypt(nonce, plaintext, _aad(index, len(plaintext)))
        yield _LENGTH.pack(len(plaintext)) + nonce + ciphertext
    yield _LENGTH.pack(0)


async def decrypt_chunked_stream(
    source: AsyncIterable[bytes],
    *,
    key: bytes,
) -> AsyncIterator[bytes]:
    """Authenticate and decrypt frames while preserving streaming semantics."""
    if len(key) != 32:
        raise ValueError("Chunked generated assets require a 32-byte key")
    reader = _AsyncByteReader(source)
    if await reader.read_exact(len(MAGIC)) != MAGIC:
        raise ValueError("Unsupported chunked encrypted asset format")
    aesgcm = AESGCM(key)
    index = 0
    while True:
        plaintext_size = _LENGTH.unpack(await reader.read_exact(_LENGTH.size))[0]
        if plaintext_size == 0:
            if await reader.has_trailing_data():
                raise ValueError("Chunked encrypted asset has trailing data")
            return
        if plaintext_size > MAX_CHUNK_SIZE:
            raise ValueError("Chunked encrypted asset frame size exceeds the limit")
        nonce = await reader.read_exact(_NONCE_BYTES)
        ciphertext = await reader.read_exact(plaintext_size + _TAG_BYTES)
        try:
            yield aesgcm.decrypt(nonce, ciphertext, _aad(index, plaintext_size))
        except InvalidTag as exc:
            raise ValueError("Chunked encrypted asset authentication failed") from exc
        index += 1
