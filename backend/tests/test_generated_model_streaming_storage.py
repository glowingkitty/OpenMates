# backend/tests/test_generated_model_streaming_storage.py
#
# Contract tests for versioned streamed master-model decryption. A model master
# must not be converted back into a whole-object plaintext buffer at download.

import asyncio
import sys
import types

import pytest
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

if "slowapi" not in sys.modules:
    slowapi_module = types.ModuleType("slowapi")

    class _Limiter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def limit(self, *_args, **_kwargs):
            return lambda function: function

    slowapi_module.Limiter = _Limiter
    sys.modules["slowapi"] = slowapi_module
    slowapi_util_module = types.ModuleType("slowapi.util")
    slowapi_util_module.get_remote_address = lambda _request: "test-client"
    sys.modules["slowapi.util"] = slowapi_util_module

from backend.core.api.app.routes.generated_assets_api import download_generated_asset
from backend.shared.python_utils.generated_assets import (
    decrypt_generated_asset_variant,
    encrypt_chunked_stream,
)
from backend.core.api.app.services.s3.service import S3UploadService
from backend.shared.python_utils.generated_assets import create_download_token
from backend.shared.python_utils.generated_assets.service import _token_secret


async def _source(*chunks: bytes):
    for chunk in chunks:
        yield chunk


async def _collect(source) -> bytes:
    return b"".join([chunk async for chunk in source])


@pytest.mark.asyncio
async def test_chunked_master_variant_decrypts_from_fragmented_s3_stream() -> None:
    key = b"\x8a" * 32
    original = b"glTF" + (b"model-data" * 100_000)
    encrypted = await _collect(encrypt_chunked_stream(_source(original), key=key, chunk_size=64 * 1024))

    decrypted = await _collect(
        decrypt_generated_asset_variant(
            {"encryption": "chunked-aes-256-gcm-v1"},
            _source(encrypted[:17], encrypted[17:333], encrypted[333:]),
            aes_key=key,
        )
    )

    assert decrypted == original


@pytest.mark.asyncio
async def test_unknown_generated_asset_encryption_version_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unsupported generated asset encryption"):
        await _collect(
            decrypt_generated_asset_variant(
                {"encryption": "future-version"},
                _source(b"ciphertext"),
                aes_key=b"\x8a" * 32,
            )
        )


class _FakeStreamingBody:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0
        self.closed = False

    def read(self, size: int) -> bytes:
        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        self.closed = True


class _FakeS3Client:
    def __init__(self, body: _FakeStreamingBody) -> None:
        self.body = body

    def get_object(self, **_kwargs):
        return {"Body": self.body}


@pytest.mark.asyncio
async def test_s3_stream_reads_fixed_chunks_and_closes_body() -> None:
    body = _FakeStreamingBody(b"abcdefghijklmnopqrstuvwxyz")
    service = S3UploadService(secrets_manager=None)
    service.client = _FakeS3Client(body)

    chunks = [
        chunk
        async for chunk in service.get_file_stream(
            bucket_name="chatfiles",
            object_key="models/master.glb",
            chunk_size=8,
        )
    ]

    assert chunks == [b"abcdefgh", b"ijklmnop", b"qrstuvwx", b"yz"]
    assert body.closed is True


class _FakeMultipartUploadClient:
    def __init__(self) -> None:
        self.parts = []
        self.completed = None
        self.aborted = False

    def create_multipart_upload(self, **_kwargs):
        return {"UploadId": "upload-1"}

    def upload_part(self, **kwargs):
        self.parts.append(kwargs["Body"])
        return {"ETag": f"etag-{kwargs['PartNumber']}"}

    def complete_multipart_upload(self, **kwargs):
        self.completed = kwargs

    def abort_multipart_upload(self, **_kwargs):
        self.aborted = True


class _FakeS3MetadataClient:
    def generate_presigned_url(self, *_args, **_kwargs):
        return "https://s3.example.test/signed"


@pytest.mark.asyncio
async def test_s3_stream_upload_uses_bounded_multipart_parts() -> None:
    part_size = 5 * 1024 * 1024
    upload_client = _FakeMultipartUploadClient()
    service = S3UploadService(secrets_manager=None)
    service.client = _FakeS3MetadataClient()
    service.upload_client = upload_client
    service.base_domain = "s3.example.test"
    service.environment = "development"

    async def source():
        yield b"a" * (2 * 1024 * 1024)
        yield b"b" * (3 * 1024 * 1024)
        yield b"c" * (1024 * 1024)

    result = await service.upload_file_stream(
        bucket_key="chatfiles",
        file_key="models/master.glb",
        source=source(),
        content_type="application/octet-stream",
        part_size=part_size,
    )

    assert [len(part) for part in upload_client.parts] == [part_size, 1024 * 1024]
    assert upload_client.completed["MultipartUpload"]["Parts"] == [
        {"PartNumber": 1, "ETag": "etag-1"},
        {"PartNumber": 2, "ETag": "etag-2"},
    ]
    assert result["url"].endswith("models/master.glb")
    assert upload_client.aborted is False


@pytest.mark.asyncio
async def test_s3_stream_upload_aborts_on_cancellation() -> None:
    upload_client = _FakeMultipartUploadClient()
    service = S3UploadService(secrets_manager=None)
    service.client = _FakeS3MetadataClient()
    service.upload_client = upload_client
    service.base_domain = "s3.example.test"
    service.environment = "development"

    async def source():
        yield b"a" * 1024
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await service.upload_file_stream(
            bucket_key="chatfiles",
            file_key="models/master.glb",
            source=source(),
            content_type="application/octet-stream",
        )

    assert upload_client.aborted is True


@pytest.mark.asyncio
async def test_s3_stream_closes_body_when_consumer_stops_early() -> None:
    body = _FakeStreamingBody(b"abcdefghijklmnopqrstuvwxyz")
    service = S3UploadService(secrets_manager=None)
    service.client = _FakeS3Client(body)
    stream = service.get_file_stream(bucket_name="chatfiles", object_key="models/master.glb", chunk_size=8)

    assert await anext(stream) == b"abcdefgh"
    await stream.aclose()

    assert body.closed is True


class _FakeDirectus:
    def __init__(self, record) -> None:
        self.record = record

    async def get_items(self, *_args, **_kwargs):
        return [self.record]


class _FakeGeneratedAssetS3:
    environment = "development"

    async def get_file(self, *_args, **_kwargs):
        raise AssertionError("chunked masters must not use whole-object get_file")

    async def get_file_stream(self, *_args, **_kwargs):
        for chunk in self.encrypted_chunks:
            yield chunk


@pytest.mark.asyncio
async def test_chunked_master_download_uses_streaming_response() -> None:
    key = b"\x71" * 32
    original = b"glTF" + b"x" * 128_000
    encrypted = await _collect(encrypt_chunked_stream(_source(original), key=key, chunk_size=32 * 1024))
    s3 = _FakeGeneratedAssetS3()
    s3.encrypted_chunks = (encrypted[:64], encrypted[64:])
    token = create_download_token(asset_id="model-1", user_id="user-1", variant="master")
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    directus = _FakeDirectus(
        {
            "content_type": "model/gltf-binary",
            "files_metadata": {
                "master": {
                    "s3_key": "models/master.glb",
                    "format": "glb",
                    "mime_type": "model/gltf-binary",
                    "encryption": "chunked-aes-256-gcm-v1",
                }
            },
            "aes_key": __import__("base64").b64encode(key).decode(),
            "aes_nonce": "",
            "original_filename": "model.glb",
        }
    )

    response = await download_generated_asset(
        asset_id="model-1",
        variant="master",
        request=request,
        token=token,
        directus_service=directus,
        s3_service=s3,
    )

    assert isinstance(response, StreamingResponse)
    assert await _collect(response.body_iterator) == original


@pytest.mark.asyncio
async def test_unknown_master_encryption_is_rejected_before_response() -> None:
    token = create_download_token(asset_id="model-1", user_id="user-1", variant="master")
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    directus = _FakeDirectus(
        {
            "content_type": "model/gltf-binary",
            "files_metadata": {
                "master": {"s3_key": "models/master.glb", "encryption": "unknown-version"}
            },
            "aes_key": __import__("base64").b64encode(b"\x71" * 32).decode(),
            "aes_nonce": "",
            "original_filename": "model.glb",
        }
    )

    with pytest.raises(HTTPException, match="unsupported encryption"):
        await download_generated_asset(
            asset_id="model-1",
            variant="master",
            request=request,
            token=token,
            directus_service=directus,
            s3_service=_FakeGeneratedAssetS3(),
        )


def test_download_token_issuance_fails_closed_in_production_without_secret(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    monkeypatch.delenv("GENERATED_ASSET_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("INTERNAL_API_SHARED_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="token secret"):
        _token_secret()


@pytest.mark.asyncio
async def test_chunked_master_rejects_invalid_key_and_unsafe_filename_before_streaming() -> None:
    token = create_download_token(asset_id="model-1", user_id="user-1", variant="master")
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    directus = _FakeDirectus(
        {
            "content_type": "model/gltf-binary",
            "files_metadata": {
                "master": {"s3_key": "models/master.glb", "encryption": "chunked-aes-256-gcm-v1"}
            },
            "aes_key": "not-a-valid-key",
            "aes_nonce": "",
            "original_filename": "model\r\nInjected: value.glb",
        }
    )

    with pytest.raises(HTTPException, match="Failed to decrypt"):
        await download_generated_asset(
            asset_id="model-1",
            variant="master",
            request=request,
            token=token,
            directus_service=directus,
            s3_service=_FakeGeneratedAssetS3(),
        )
