# backend/tests/test_generated_media_provenance.py
#
# Metadata-only provenance tests for generated media helpers.
# These tests deliberately avoid asserting any visual/pixel watermark because
# OpenMates provenance must not visually alter generated images.

from backend.core.api.app.utils.image_processing import process_svg_for_storage
from backend.shared.python_utils.generated_assets.service import index_generated_asset
import pytest


def test_process_svg_for_storage_keeps_original_svg_bytes_visual_safe():
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>'
    result = process_svg_for_storage(
        svg,
        metadata={
            "prompt": "red square icon",
            "model": "recraftv4_1_vector",
            "software": "OpenMates",
            "source": "OpenMates AI",
            "generated_at": "2026-05-24T00:00:00Z",
        },
    )

    assert result["original"] == svg
    assert result["preview_webp"]


class _FakeDirectus:
    def __init__(self):
        self.created_record = None
        self.updated_user = None

    async def create_item(self, collection, record):
        self.created_record = (collection, record)
        return True, None

    async def get_user_fields_direct(self, user_id, fields):
        return {"storage_used_bytes": 0}

    async def update_user(self, user_id, data):
        self.updated_user = (user_id, data)


class _FakeTask:
    def __init__(self):
        self._directus_service = _FakeDirectus()


@pytest.mark.asyncio
async def test_index_generated_asset_stores_provenance_metadata():
    task = _FakeTask()
    stored = await index_generated_asset(
        task,
        user_id="user-1",
        embed_id="embed-1",
        media_type="video",
        files_metadata={"original": {"s3_key": "x", "size_bytes": 12}},
        s3_base_url="https://s3.example.test",
        aes_key_b64="key",
        nonce_b64="nonce",
        vault_wrapped_aes_key="wrapped",
        created_at=123,
        content_hash_source=b"video",
        original_filename="video.mp4",
        content_type="video/mp4",
        log_prefix="[test]",
        provenance_metadata={"labeling": "metadata_only", "visual_watermark": False},
    )

    assert stored is True
    collection, record = task._directus_service.created_record
    assert collection == "upload_files"
    assert record["ai_detection"]["ai_generated"] == 1.0
    assert record["ai_detection"]["provenance"]["visual_watermark"] is False
