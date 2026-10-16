"""Producer boundary checks with real raster bytes and no paid provider/storage."""

import base64
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from backend.apps.images.tasks import generate_task as producer
from backend.core.api.app.services.embed_service import EmbedService
from backend.shared.python_utils import generated_media_graph
from backend.shared.python_utils.image_safety import PipelineDecision
from backend.shared.python_utils.media_encryption import decrypt_media_payload


def raster_bytes(file_format):
    output = BytesIO()
    Image.new("RGB", (8, 8), "green").save(output, format=file_format)
    return output.getvalue()


class FakeCache:
    @property
    def client(self):
        async def client():
            return None
        return client()


def prepare_producer(monkeypatch, image_bytes):
    task = SimpleNamespace(
        request=SimpleNamespace(id="unit-image-mime"),
        initialize_core_services=AsyncMock(), cleanup_services=AsyncMock(),
        _secrets_manager=object(), _cache_service=FakeCache(),
        _directus_service=SimpleNamespace(get_user_profile=AsyncMock(return_value=(True, {"vault_key_id": "unit-key"}, None))),
        _encryption_service=SimpleNamespace(encrypt_with_user_key=AsyncMock(return_value=("unit-wrapped-key", None))),
        _s3_service=SimpleNamespace(base_domain="unit.invalid", upload_file=AsyncMock(return_value={"url": "https://unit.invalid/stored"})),
    )
    pipeline = SimpleNamespace(
        validate_input=AsyncMock(return_value=PipelineDecision(allowed=True)),
        validate_output=AsyncMock(return_value=PipelineDecision(allowed=True)),
    )
    monkeypatch.setattr(producer, "get_pipeline", lambda: pipeline)
    monkeypatch.setattr(producer, "generate_image_google", AsyncMock(return_value=image_bytes))
    monkeypatch.setattr(producer, "initialize_task_storage", AsyncMock(return_value=task._s3_service))
    monkeypatch.setattr(producer, "require_storage_available", AsyncMock())
    monkeypatch.setattr(producer, "_check_cached_safety_rejection", AsyncMock(return_value=None))
    monkeypatch.setattr(producer, "_estimate_image_generation_credits", AsyncMock(return_value=1))
    monkeypatch.setattr(producer, "ensure_credit_headroom", AsyncMock())
    monkeypatch.setattr(producer, "_charge_image_generation_credits", AsyncMock())
    monkeypatch.setattr(producer, "get_bucket_name", lambda key: "unit-private")
    monkeypatch.setattr(producer, "create_download_token", lambda **kwargs: "unit-token")
    index = AsyncMock(return_value=True)
    monkeypatch.setattr(producer, "index_generated_asset", index)
    monkeypatch.setattr(EmbedService, "assert_registered_output_can_generate", AsyncMock())
    send_child = AsyncMock()
    monkeypatch.setattr(generated_media_graph, "send_generated_media_child", send_child)
    return task, pipeline, index, send_child


# contract-test: supporting surface=rest_api assertions=app-skills.media.parent-children-and-attribution,app-skills.media.visible-assistant-results
@pytest.mark.asyncio
@pytest.mark.parametrize("encoding,requested_format,provider_mime,stored_mime", [
    ("JPEG", "png", "image/jpeg", "image/png"),
    ("PNG", "jpg", "image/png", "image/jpeg"),
    ("PNG", "png", "image/png", "image/png"),
    ("WEBP", "png", "image/webp", "image/png"),
])
async def test_provider_safety_mime_and_requested_storage_format_remain_distinct(monkeypatch, encoding, requested_format, provider_mime, stored_mime):
    image_bytes = raster_bytes(encoding)
    task, pipeline, index, send_child = prepare_producer(monkeypatch, image_bytes)
    result = await producer._async_generate_image(task, "images", "generate", {
        "prompt": "A small green botanical study", "user_id": "unit-owner",
        "embed_id": "unit-image", "full_model_reference": "google/unit-image-model",
        "output_filetype": requested_format, "external_request": True,
    })
    assert pipeline.validate_output.await_args.kwargs["image_bytes"] == image_bytes
    assert pipeline.validate_output.await_args.kwargs["mime_type"] == provider_mime
    indexed = index.await_args.kwargs
    assert indexed["content_type"] == stored_mime
    assert indexed["original_filename"].endswith(f".{requested_format}")
    original = indexed["files_metadata"]["original"]
    assert original["format"] == requested_format
    assert original["mime_type"] == stored_mime
    assert original["s3_key"].endswith(f"_original.{requested_format}")
    assert result["output_filetype"] == requested_format
    assert result["files"]["original"]["mime_type"] == stored_mime
    assert send_child.await_args.kwargs["content"]["files"]["original"]["mime_type"] == stored_mime
    stored_bytes = decrypted_original(task, indexed)
    with Image.open(BytesIO(stored_bytes)) as stored_image:
        assert stored_image.format == ("PNG" if requested_format == "png" else "JPEG")
        stored_image.verify()
    for variant in ("full", "preview"):
        assert indexed["files_metadata"][variant]["format"] == "webp"
        assert result["files"][variant]["mime_type"] == "image/webp"
    task.cleanup_services.assert_awaited_once()


# contract-test: supporting surface=rest_api assertions=app-skills.media.visible-assistant-results
@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [b"\x89PNG\r\n\x1a\ntruncated", raster_bytes("GIF"), b"<svg/>"])
async def test_invalid_provider_raster_never_reaches_billing_or_storage(monkeypatch, invalid):
    task, pipeline, index, _ = prepare_producer(monkeypatch, invalid)
    with pytest.raises(ValueError, match="unsupported raster"):
        await producer._async_generate_image(task, "images", "generate", {
            "prompt": "A small green botanical study", "user_id": "unit-owner",
            "embed_id": "unit-image", "full_model_reference": "google/unit-image-model",
            "media_batch": True,
        })
    pipeline.validate_output.assert_not_awaited()
    producer._charge_image_generation_credits.assert_not_awaited()
    task._s3_service.upload_file.assert_not_awaited()
    index.assert_not_awaited()
    task.cleanup_services.assert_awaited_once()


def decrypted_original(task, indexed):
    original = indexed["files_metadata"]["original"]
    encrypted = next(call.kwargs["content"] for call in task._s3_service.upload_file.await_args_list
                     if call.kwargs["file_key"] == original["s3_key"])
    return decrypt_media_payload(
        encrypted_data=encrypted, aes_key=base64.b64decode(indexed["aes_key_b64"]),
        variant=original, legacy_nonce_b64=indexed["nonce_b64"],
    )


# contract-test: supporting surface=rest_api assertions=app-skills.media.parent-children-and-attribution,app-skills.media.visible-assistant-results
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["RGBA", "P"])
async def test_requested_jpeg_composites_alpha_and_palette_transparency_on_white(monkeypatch, mode):
    output = BytesIO()
    if mode == "RGBA":
        Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(output, format="PNG")
    else:
        palette_image = Image.new("P", (8, 8), 0)
        palette_image.putpalette([255, 0, 0] + [0] * 765)
        palette_image.save(output, format="PNG", transparency=0)
    provider_bytes = output.getvalue()
    task, pipeline, index, _ = prepare_producer(monkeypatch, provider_bytes)
    result = await producer._async_generate_image(task, "images", "generate", {
        "prompt": "A small green botanical study", "user_id": "unit-owner",
        "embed_id": "unit-image", "full_model_reference": "google/unit-image-model",
        "output_filetype": "jpg", "external_request": True,
    })
    assert pipeline.validate_output.await_args.kwargs["image_bytes"] == provider_bytes
    assert pipeline.validate_output.await_args.kwargs["mime_type"] == "image/png"
    assert result["files"]["original"]["mime_type"] == "image/jpeg"
    with Image.open(BytesIO(decrypted_original(task, index.await_args.kwargs))) as stored_image:
        assert stored_image.format == "JPEG"
        assert stored_image.convert("RGB").getpixel((4, 4)) == (255, 255, 255)
