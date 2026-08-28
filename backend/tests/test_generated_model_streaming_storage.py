# backend/tests/test_generated_model_streaming_storage.py
#
# Contract tests for versioned streamed master-model decryption. A model master
# must not be converted back into a whole-object plaintext buffer at download.

import asyncio
import hashlib
import sys
import types

import pytest
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

if "boto3" not in sys.modules:
    boto3_module = types.ModuleType("boto3")
    boto3_module.client = lambda *_args, **_kwargs: None
    sys.modules["boto3"] = boto3_module

if "botocore" not in sys.modules:
    class _FakeClientError(Exception):
        def __init__(self, response, operation_name):
            super().__init__(operation_name)
            self.response = response

    class _FakeEndpointConnectionError(Exception):
        def __init__(self, *args, endpoint_url=None):
            super().__init__(endpoint_url or (args[0] if args else "endpoint unavailable"))

    _FakeClientError.__name__ = "ClientError"
    _FakeEndpointConnectionError.__name__ = "EndpointConnectionError"

    botocore_module = types.ModuleType("botocore")
    botocore_config_module = types.ModuleType("botocore.config")
    botocore_config_module.Config = lambda *_args, **_kwargs: None
    botocore_exceptions_module = types.ModuleType("botocore.exceptions")
    botocore_exceptions_module.ClientError = _FakeClientError
    botocore_exceptions_module.ConnectionClosedError = type("ConnectionClosedError", (Exception,), {})
    botocore_exceptions_module.ReadTimeoutError = type("ReadTimeoutError", (Exception,), {})
    botocore_exceptions_module.ConnectTimeoutError = type("ConnectTimeoutError", (Exception,), {})
    botocore_exceptions_module.EndpointConnectionError = _FakeEndpointConnectionError
    botocore_exceptions_module.HTTPClientError = type("HTTPClientError", (Exception,), {})
    sys.modules["botocore"] = botocore_module
    sys.modules["botocore.config"] = botocore_config_module
    sys.modules["botocore.exceptions"] = botocore_exceptions_module

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
from backend.core.api.app.services.s3.service import ClientError, EndpointConnectionError, S3UploadService
from backend.shared.python_utils.generated_assets import create_download_token
from backend.shared.python_utils.generated_assets.service import _token_secret
from backend.shared.python_utils.media_encryption import MEDIA_ENCRYPTION_V2
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


async def _source(*chunks: bytes):
    for chunk in chunks:
        yield chunk


async def _collect(source) -> bytes:
    return b"".join([chunk async for chunk in source])


# contract-test: supporting surface=rest_api assertions=storage.privacy.ciphertext-boundary
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


# contract-test: supporting surface=rest_api assertions=storage.privacy.ciphertext-boundary
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


# contract-test: supporting surface=rest_api assertions=storage.privacy.ciphertext-boundary
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
    def __init__(
        self,
        *,
        fail_completion_precondition: bool = False,
        completion_failure: str | None = None,
    ) -> None:
        self.parts = []
        self.completed = None
        self.aborted = False
        self.completion_failure = "precondition" if fail_completion_precondition else completion_failure

    def create_multipart_upload(self, **_kwargs):
        return {"UploadId": "upload-1"}

    def upload_part(self, **kwargs):
        self.parts.append(kwargs["Body"])
        return {"ETag": f"etag-{kwargs['PartNumber']}"}

    def complete_multipart_upload(self, **kwargs):
        if self.completion_failure == "precondition":
            error = ClientError({"Error": {"Code": "PreconditionFailed"}}, "CompleteMultipartUpload")
            error.response = {"Error": {"Code": "PreconditionFailed"}}
            raise error
        if self.completion_failure == "service_unavailable":
            error = ClientError(
                {"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}},
                "CompleteMultipartUpload",
            )
            error.response = {"Error": {"Code": "ServiceUnavailable"}, "ResponseMetadata": {"HTTPStatusCode": 503}}
            raise error
        if self.completion_failure == "transport":
            try:
                raise EndpointConnectionError(endpoint_url="https://nbg1.example.invalid")
            except TypeError as exc:
                raise EndpointConnectionError("https://nbg1.example.invalid") from exc
        self.completed = kwargs

    def abort_multipart_upload(self, **_kwargs):
        self.aborted = True


class _FakeS3MetadataClient:
    def __init__(self, existing_checksum: str | None = None) -> None:
        self.existing_checksum = existing_checksum

    def head_object(self, **_kwargs):
        if self.existing_checksum:
            return {"Metadata": {"openmates-sha256": self.existing_checksum}}
        error = ClientError({"Error": {"Code": "NoSuchKey"}}, "HeadObject")
        error.response = {"Error": {"Code": "NoSuchKey"}}
        raise error

    def generate_presigned_url(self, *_args, **_kwargs):
        return "https://s3.example.test/signed"


class _FakeReplicationDirectus:
    def __init__(self) -> None:
        self.created_items = []

    async def get_items(self, collection, **_kwargs):
        if collection == "storage_deletion_tombstones":
            return []
        if collection == "storage_replication_jobs":
            return []
        if collection == "storage_region_health":
            return []
        return []

    async def create_item(self, collection, payload, **_kwargs):
        created = {"id": f"{collection}-1", **dict(payload)}
        self.created_items.append((collection, created))
        return True, created


class _RacingS3MetadataClient(_FakeS3MetadataClient):
    def __init__(self, checksum: str) -> None:
        super().__init__(checksum)
        self.head_calls = 0

    def head_object(self, **kwargs):
        self.head_calls += 1
        if self.head_calls == 1:
            existing_checksum = self.existing_checksum
            self.existing_checksum = None
            try:
                return super().head_object(**kwargs)
            finally:
                self.existing_checksum = existing_checksum
        return super().head_object(**kwargs)


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox,storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_s3_stream_upload_uses_bounded_multipart_parts() -> None:
    part_size = 5 * 1024 * 1024
    upload_client = _FakeMultipartUploadClient()
    directus = _FakeReplicationDirectus()
    service = S3UploadService(secrets_manager=None, directus_service=directus)
    metadata_client = _FakeS3MetadataClient()
    service.client = metadata_client
    service.upload_client = upload_client
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": metadata_client}
    service.upload_region_clients = {"nbg1": upload_client}
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
    assert directus.created_items[0][0] == "storage_replication_jobs"
    assert directus.created_items[0][1]["active_region"] == "nbg1"


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.asyncio
async def test_s3_stream_retry_accepts_matching_immutable_object() -> None:
    content = b"existing-encrypted-model"
    metadata_client = _FakeS3MetadataClient(hashlib.sha256(content).hexdigest())
    upload_client = _FakeMultipartUploadClient()
    directus = _FakeReplicationDirectus()
    service = S3UploadService(secrets_manager=None, directus_service=directus)
    service.client = metadata_client
    service.upload_client = upload_client
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": metadata_client}
    service.upload_region_clients = {"nbg1": upload_client}
    service.environment = "development"

    async def source():
        yield content

    result = await service.upload_file_stream(
        bucket_key="chatfiles",
        file_key="models/existing-master.glb",
        source=source(),
        content_type="application/octet-stream",
    )

    assert result["url"].endswith("models/existing-master.glb")
    assert upload_client.parts == []
    assert upload_client.completed is None
    assert directus.created_items[0][0] == "storage_replication_jobs"
    assert directus.created_items[0][1]["active_region"] == "nbg1"


# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.asyncio
async def test_s3_stream_completion_race_accepts_matching_winner() -> None:
    content = b"racing-encrypted-model"
    metadata_client = _RacingS3MetadataClient(hashlib.sha256(content).hexdigest())
    upload_client = _FakeMultipartUploadClient(fail_completion_precondition=True)
    directus = _FakeReplicationDirectus()
    service = S3UploadService(secrets_manager=None, directus_service=directus)
    service.client = metadata_client
    service.upload_client = upload_client
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": metadata_client}
    service.upload_region_clients = {"nbg1": upload_client}
    service.environment = "development"

    async def source():
        yield content

    result = await service.upload_file_stream(
        bucket_key="chatfiles",
        file_key="models/racing-master.glb",
        source=source(),
        content_type="application/octet-stream",
    )

    assert result["url"].endswith("models/racing-master.glb")
    assert upload_client.aborted is True
    assert metadata_client.head_calls == 2
    assert directus.created_items[0][0] == "storage_replication_jobs"
    assert directus.created_items[0][1]["active_region"] == "nbg1"


@pytest.mark.asyncio
@pytest.mark.parametrize("completion_failure", ["service_unavailable", "transport"])
# contract-test: direct surface=rest_api assertions=storage.replication.active-write-durable-outbox
async def test_s3_stream_ambiguous_completion_accepts_matching_committed_object(
    completion_failure: str,
) -> None:
    content = b"committed-encrypted-model"
    metadata_client = _RacingS3MetadataClient(hashlib.sha256(content).hexdigest())
    upload_client = _FakeMultipartUploadClient(completion_failure=completion_failure)
    directus = _FakeReplicationDirectus()
    service = S3UploadService(secrets_manager=None, directus_service=directus)
    service.client = metadata_client
    service.upload_client = upload_client
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": metadata_client}
    service.upload_region_clients = {"nbg1": upload_client}
    service.environment = "development"

    async def source():
        yield content

    result = await service.upload_file_stream(
        bucket_key="chatfiles",
        file_key="models/committed-master.glb",
        source=source(),
        content_type="application/octet-stream",
    )

    assert result["url"].endswith("models/committed-master.glb")
    assert upload_client.aborted is False
    assert metadata_client.head_calls == 2
    assert directus.created_items[0][0] == "storage_replication_jobs"
    assert directus.created_items[0][1]["active_region"] == "nbg1"


# contract-test: supporting surface=rest_api assertions=storage.replication.active-write-durable-outbox
@pytest.mark.asyncio
async def test_s3_stream_upload_aborts_on_cancellation() -> None:
    upload_client = _FakeMultipartUploadClient()
    service = S3UploadService(secrets_manager=None)
    metadata_client = _FakeS3MetadataClient()
    service.client = metadata_client
    service.upload_client = upload_client
    service.region_name = "nbg1"
    service.region_clients = {"nbg1": metadata_client}
    service.upload_region_clients = {"nbg1": upload_client}
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

    assert upload_client.aborted is False


# contract-test: supporting surface=rest_api assertions=storage.privacy.ciphertext-boundary
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
    def __init__(self, record, user_profile=None) -> None:
        self.record = record
        self.user_profile = user_profile

    async def get_items(self, *_args, **_kwargs):
        return [self.record]

    async def get_user_profile(self, user_id):
        assert user_id == "user-1"
        return True, self.user_profile, "ok"


class _FakeEncryption:
    async def decrypt_with_user_key(self, wrapped_key, vault_key_id):
        assert wrapped_key == "wrapped-media-key"
        assert vault_key_id == "vault-key-1"
        return __import__("base64").b64encode(b"\x73" * 32).decode()


class _FakeGeneratedAssetS3:
    environment = "development"

    async def get_file(self, *_args, **_kwargs):
        raise AssertionError("chunked masters must not use whole-object get_file")

    async def get_file_stream(self, *_args, **_kwargs):
        for chunk in self.encrypted_chunks:
            yield chunk


class _FakeBoundedAssetS3:
    environment = "development"

    def __init__(self, encrypted: bytes) -> None:
        self.encrypted = encrypted

    async def get_file(self, *_args, **_kwargs):
        return self.encrypted


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary
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


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary
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


# contract-test: supporting surface=rest_api assertions=storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_bounded_variant_uses_its_own_nonce_not_legacy_record_nonce() -> None:
    key = b"\x72" * 32
    variant_nonce = b"\x31" * 12
    encrypted = AESGCM(key).encrypt(variant_nonce, b"provider-poster", None)
    token = create_download_token(asset_id="model-1", user_id="user-1", variant="poster")
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    directus = _FakeDirectus(
        {
            "content_type": "model/gltf-binary",
            "files_metadata": {
                "poster": {
                    "s3_key": "models/poster.webp.enc",
                    "format": "webp",
                    "mime_type": "image/webp",
                    "aes_nonce": __import__("base64").b64encode(variant_nonce).decode(),
                }
            },
            "aes_key": __import__("base64").b64encode(key).decode(),
            "aes_nonce": __import__("base64").b64encode(b"\x32" * 12).decode(),
            "original_filename": "model.glb",
        }
    )

    response = await download_generated_asset(
        asset_id="model-1",
        variant="poster",
        request=request,
        token=token,
        directus_service=directus,
        s3_service=_FakeBoundedAssetS3(encrypted),
    )

    assert response.body == b"provider-poster"
    assert response.media_type == "image/webp"


# contract-test: supporting surface=rest_api assertions=storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_v2_bounded_variant_uses_prefixed_nonce() -> None:
    key = b"\x73" * 32
    nonce = b"\x33" * 12
    plaintext = b"v2-provider-poster"
    encrypted = nonce + AESGCM(key).encrypt(nonce, plaintext, None)
    token = create_download_token(asset_id="model-1", user_id="user-1", variant="poster")
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    directus = _FakeDirectus(
        {
            "content_type": "model/gltf-binary",
            "files_metadata": {
                "poster": {
                    "s3_key": "models/poster.webp.enc",
                    "format": "webp",
                    "mime_type": "image/webp",
                    "encryption": MEDIA_ENCRYPTION_V2,
                }
            },
            "aes_key": __import__("base64").b64encode(key).decode(),
            "aes_nonce": __import__("base64").b64encode(b"\x34" * 12).decode(),
            "original_filename": "model.glb",
        }
    )

    response = await download_generated_asset(
        asset_id="model-1",
        variant="poster",
        request=request,
        token=token,
        directus_service=directus,
        s3_service=_FakeBoundedAssetS3(encrypted),
    )

    assert response.body == plaintext


# contract-test: supporting surface=rest_api assertions=storage.privacy.ciphertext-boundary
@pytest.mark.asyncio
async def test_v2_bounded_variant_unwraps_key_when_raw_key_is_absent() -> None:
    key = b"\x73" * 32
    nonce = b"\x35" * 12
    plaintext = b"wrapped-key-provider-poster"
    encrypted = nonce + AESGCM(key).encrypt(nonce, plaintext, None)
    token = create_download_token(asset_id="model-1", user_id="user-1", variant="poster")
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": []})
    directus = _FakeDirectus(
        {
            "content_type": "model/gltf-binary",
            "files_metadata": {
                "poster": {
                    "s3_key": "models/poster.webp.enc",
                    "format": "webp",
                    "mime_type": "image/webp",
                    "encryption": MEDIA_ENCRYPTION_V2,
                }
            },
            "vault_wrapped_aes_key": "wrapped-media-key",
            "aes_nonce": "",
            "original_filename": "model.glb",
        },
        user_profile={"vault_key_id": "vault-key-1"},
    )

    response = await download_generated_asset(
        asset_id="model-1",
        variant="poster",
        request=request,
        token=token,
        directus_service=directus,
        s3_service=_FakeBoundedAssetS3(encrypted),
        encryption_service=_FakeEncryption(),
    )

    assert response.body == plaintext


# contract-test: supporting surface=rest_api assertions=storage.privacy.ciphertext-boundary
def test_download_token_issuance_fails_closed_in_production_without_secret(monkeypatch) -> None:
    monkeypatch.setenv("SERVER_ENVIRONMENT", "production")
    monkeypatch.delenv("GENERATED_ASSET_TOKEN_SECRET", raising=False)
    monkeypatch.delenv("INTERNAL_API_SHARED_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="token secret"):
        _token_secret()


# contract-test: direct surface=rest_api assertions=storage.privacy.ciphertext-boundary
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
