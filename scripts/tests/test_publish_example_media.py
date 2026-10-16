# contract-test-file: tooling
"""Local-only authorization and manifest tests for reviewed media publication."""

from __future__ import annotations

import argparse
import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from backend.shared.python_utils.media_encryption import encrypt_media_variants
from backend.shared.python_utils.generated_assets import CHUNKED_MODEL_ENCRYPTION
from backend.shared.python_utils.generated_assets.chunked_encryption import encrypt_chunked_stream
from scripts import publish_example_media as publisher


USER_ID = "owner-1"
CHAT_ID = "4b6afae0-f3aa-481b-9ba0-c586d177bb9f"
EMBED_ID = "c8057f50-682e-40f9-886a-cedcadf76539"
def raster_bytes(file_format: str) -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 8), "green").save(output, format=file_format)
    return output.getvalue()


PNG = raster_bytes("PNG")


class FakeDirectus:
    def __init__(self, *, owned: bool = True) -> None:
        self.owned = owned
        self.rows = {
            "chats": [{
                "id": CHAT_ID,
                "hashed_user_id": hashlib.sha256((USER_ID if owned else "other-owner").encode()).hexdigest(),
                "hashed_team_id": None,
            }],
            "embeds": [{
                "embed_id": EMBED_ID,
                "hashed_chat_id": hashlib.sha256(CHAT_ID.encode()).hexdigest(),
                "hashed_user_id": hashlib.sha256(USER_ID.encode()).hexdigest(),
            }],
            "upload_files": [],
        }

    async def get_items(self, collection, *, params, **kwargs):
        assert kwargs["admin_required"] is True
        return self.rows[collection]


class FakeS3:
    environment = "production"
    base_domain = "nbg1.your-objectstorage.com"

    def __init__(self, encrypted: bytes) -> None:
        self.encrypted = encrypted
        self.uploaded = []

    async def get_file(self, *, bucket_name, object_key):
        prefix = "dev-" if self.environment == "development" else ""
        assert bucket_name == f"{prefix}openmates-chatfiles"
        if isinstance(self.encrypted, dict):
            return self.encrypted[object_key]
        assert object_key == "private/source.enc"
        return self.encrypted

    async def upload_file(self, bucket_key, file_key, content, content_type, metadata, region):
        assert region == "nbg1"
        self.uploaded.append((bucket_key, file_key, content, content_type, metadata))
        prefix = "dev-" if self.environment == "development" else ""
        return {"url": f"https://{prefix}openmates-public-examples.{self.base_domain}/{file_key}"}


def args(tmp_path, *, reviewed=True):
    return argparse.Namespace(
        chat_id=CHAT_ID, user_id=USER_ID, embed_id=[EMBED_ID],
        output=tmp_path / "media.json", reviewed=reviewed, print_manifest=False,
    )


@pytest.mark.asyncio
async def test_publishes_only_owned_reviewed_variant_with_public_safe_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "get_bucket_name", lambda key, environment: {
        "chatfiles": "openmates-chatfiles", "public_example_media": "openmates-public-examples",
    }[key])
    encrypted = encrypt_media_variants({"preview": PNG}, write_version=2)
    directus = FakeDirectus()
    directus.rows["upload_files"] = [{
        "embed_id": EMBED_ID, "user_id": USER_ID,
        "ai_detection": {"source": "openmates_application_preview_generate"},
        "files_metadata": {"preview": {
            "s3_key": "private/source.enc", "mime_type": "image/png",
            **encrypted.metadata["preview"],
        }},
        "aes_key": encrypted.aes_key_b64,
        "aes_nonce": "",
    }]
    s3 = FakeS3(encrypted.payloads["preview"])
    manifest = await publisher.publish(args(tmp_path), directus=directus, s3=s3, encryption=object())

    assert s3.uploaded[0][0] == "public_example_media"
    assert s3.uploaded[0][2] == PNG
    assert s3.uploaded[0][3] == "image/png"
    digest = hashlib.sha256(PNG).hexdigest()
    assert s3.uploaded[0][1] == f"reviewed-media/application_preview/preview/sha256-{digest}.png"
    assert manifest["embeds"][0]["variants"][0]["sha256"] == digest
    assert set(manifest) == {"reviewed", "source_chat_id", "embeds"}
    assert not any(word in args(tmp_path).output.read_text() for word in (USER_ID, "aes_key", "private/source.enc", "vault"))


@pytest.mark.asyncio
async def test_rejects_unreviewed_or_foreign_chat_before_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "get_bucket_name", lambda key, environment: "openmates-chatfiles")
    directus = FakeDirectus(owned=False)
    s3 = FakeS3(b"encrypted")
    with pytest.raises(RuntimeError, match="--reviewed"):
        await publisher.publish(args(tmp_path, reviewed=False), directus=directus, s3=s3, encryption=object())
    with pytest.raises(RuntimeError, match="owner"):
        await publisher.publish(args(tmp_path), directus=directus, s3=s3, encryption=object())
    assert s3.uploaded == []
    assert not args(tmp_path).output.exists()


@pytest.mark.asyncio
async def test_rejects_asset_from_another_owner_even_with_matching_embed(tmp_path):
    directus = FakeDirectus()
    directus.rows["upload_files"] = [{"embed_id": EMBED_ID, "user_id": "other-owner"}]
    s3 = FakeS3(b"encrypted")
    with pytest.raises(RuntimeError, match="owner"):
        await publisher.publish(args(tmp_path), directus=directus, s3=s3, encryption=object())
    assert s3.uploaded == []


@pytest.mark.asyncio
async def test_reads_real_chunked_model_variant_before_publication(monkeypatch):
    monkeypatch.setattr(publisher, "get_bucket_name", lambda key, environment: "openmates-chatfiles")
    key = b"x" * 32
    model = b"glTF" + b"model bytes" * 100

    async def source():
        yield model

    encrypted = b"".join([chunk async for chunk in encrypt_chunked_stream(source(), key=key, chunk_size=64)])

    class ModelS3(FakeS3):
        def get_file_stream(self, *, bucket_name, object_key):
            assert bucket_name == "openmates-chatfiles"
            assert object_key == "private/source.enc"

            async def chunks():
                yield encrypted[:100]
                yield encrypted[100:]

            return chunks()

    plaintext = await publisher._read_plaintext(
        ModelS3(encrypted),
        metadata={"s3_key": "private/source.enc", "encryption": CHUNKED_MODEL_ENCRYPTION},
        key=key,
        nonce="",
    )
    assert plaintext == model


def owned_asset(variants, *, source="openmates_image_generate"):
    encrypted = encrypt_media_variants({name: body for name, (body, _) in variants.items()}, write_version=2)
    directus = FakeDirectus()
    directus.rows["upload_files"] = [{
        "embed_id": EMBED_ID, "user_id": USER_ID,
        "ai_detection": {"source": source},
        "files_metadata": {name: {
            "s3_key": f"private/{name}.enc", **metadata, **encrypted.metadata[name],
        } for name, (_, metadata) in variants.items()},
        "aes_key": encrypted.aes_key_b64, "aes_nonce": "",
    }]
    return directus, FakeS3({f"private/{name}.enc": body for name, body in encrypted.payloads.items()})


@pytest.mark.asyncio
async def test_legacy_png_label_publishes_valid_jpeg_bytes_with_actual_mime_and_same_digest(tmp_path, monkeypatch):
    monkeypatch.setattr(publisher, "get_bucket_name", lambda key, environment: {
        "chatfiles": "openmates-chatfiles", "public_example_media": "openmates-public-examples",
    }[key])
    jpeg = raster_bytes("JPEG")
    directus, s3 = owned_asset({"original": (jpeg, {"mime_type": "image/png", "format": "png"})})
    manifest = await publisher.publish(args(tmp_path), directus=directus, s3=s3, encryption=object())
    digest = hashlib.sha256(jpeg).hexdigest()
    expected_key = f"reviewed-media/image/original/sha256-{digest}.jpg"
    assert s3.uploaded[0][1:4] == (expected_key, jpeg, "image/jpeg")
    assert manifest["embeds"][0]["variants"][0] == {
        "variant": "original", "sha256": digest, "mime_type": "image/jpeg",
        "public_url": f"https://openmates-public-examples.nbg1.your-objectstorage.com/{expected_key}",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_bytes", [
    b"\x89PNG\r\n\x1a\ncorrupt pixels", b"<svg xmlns='http://www.w3.org/2000/svg'/>",
    raster_bytes("GIF"), raster_bytes("JPEG")[:-20], b"ID3audio data",
])
async def test_rejects_corrupt_unsupported_or_non_raster_bytes_before_any_upload(tmp_path, monkeypatch, bad_bytes):
    monkeypatch.setattr(publisher, "get_bucket_name", lambda key, environment: "openmates-chatfiles")
    directus, s3 = owned_asset({
        "full": (raster_bytes("WEBP"), {"mime_type": "image/webp"}),
        "original": (bad_bytes, {"mime_type": "image/png", "format": "png"}),
    })
    with pytest.raises(RuntimeError, match="invalid or unsupported raster"):
        await publisher.publish(args(tmp_path), directus=directus, s3=s3, encryption=object())
    assert not s3.uploaded
    assert not args(tmp_path).output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [
    {"mime_type": "audio/mpeg", "format": "mp3"},
    {"mime_type": "image/png", "format": "mp3"},
])
async def test_rejects_mixed_media_labels_and_image_bytes_as_audio(tmp_path, monkeypatch, metadata):
    monkeypatch.setattr(publisher, "get_bucket_name", lambda key, environment: "openmates-chatfiles")
    directus, s3 = owned_asset({"original": (PNG, metadata)}, source="openmates_audio_generate")
    with pytest.raises(RuntimeError, match="media"):
        await publisher.publish(args(tmp_path), directus=directus, s3=s3, encryption=object())
    assert not s3.uploaded
    assert not args(tmp_path).output.exists()


@pytest.mark.asyncio
async def test_runtime_publisher_uses_dev_bucket_without_configuring_buckets(tmp_path, monkeypatch):
    from backend.core.api.app.services import directus as directus_module
    from backend.core.api.app.services.s3 import service as s3_module
    from backend.core.api.app.utils import encryption as encryption_module
    from backend.core.api.app.utils import secrets_manager as secrets_module

    directus, s3 = owned_asset({"original": (raster_bytes("JPEG"), {"mime_type": "image/png"})})
    directus.close = AsyncMock()
    s3.environment = "development"
    s3.initialize = AsyncMock()
    monkeypatch.setattr(directus_module, "DirectusService", lambda: directus)
    monkeypatch.setattr(s3_module, "S3UploadService", lambda **kwargs: s3)
    monkeypatch.setattr(encryption_module, "EncryptionService", lambda: object())
    monkeypatch.setattr(secrets_module, "SecretsManager", lambda: SimpleNamespace(initialize=AsyncMock()))
    monkeypatch.setattr(publisher, "get_bucket_name", lambda key, environment: {
        "chatfiles": "dev-openmates-chatfiles", "public_example_media": "dev-openmates-public-examples",
    }[key])
    manifest = await publisher.publish(args(tmp_path))
    s3.initialize.assert_awaited_once_with(configure_buckets=False)
    directus.close.assert_awaited_once()
    assert manifest["embeds"][0]["variants"][0]["public_url"].startswith(
        "https://dev-openmates-public-examples.nbg1.your-objectstorage.com/"
    )
