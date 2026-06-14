# backend/tests/test_radar_embed_cleanup.py
#
# Regression tests for durable rain radar S3 cleanup.
# Rain radar embeds reuse the shared embed.s3_file_keys deletion path so all
# preview/blob objects are removed when the owning embed is deleted.
#
# Architecture: docs/specs/weather-rain-radar/spec.yml

from __future__ import annotations

import asyncio


class FakeS3Service:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    async def delete_file(self, bucket_key: str, file_key: str) -> None:
        self.deleted.append((bucket_key, file_key))


def test_embed_s3_cleanup_deletes_rain_radar_preview_and_blob_files() -> None:
    from backend.core.api.app.services.directus.embed_methods import EmbedMethods

    service = EmbedMethods.__new__(EmbedMethods)
    s3_service = FakeS3Service()

    asyncio.run(service._delete_s3_files_for_embeds(
        [
            {
                "embed_id": "radar-embed-1",
                "s3_file_keys": [
                    {"bucket": "chatfiles", "key": "user/radar-preview.webp"},
                    {"bucket": "chatfiles", "key": "user/radar-blob.br"},
                ],
            }
        ],
        s3_service,
    ))

    assert s3_service.deleted == [
        ("chatfiles", "user/radar-preview.webp"),
        ("chatfiles", "user/radar-blob.br"),
    ]
