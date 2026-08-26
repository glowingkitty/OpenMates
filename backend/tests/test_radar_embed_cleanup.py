# backend/tests/test_radar_embed_cleanup.py
#
# Regression tests for durable rain radar S3 cleanup.
# Rain radar embeds reuse the shared embed.s3_file_keys deletion path so all
# preview/blob objects receive regional tombstones before their row is deleted.
#
# Architecture: docs/specs/weather-rain-radar/spec.yml

from __future__ import annotations

import asyncio


class FakeDirectus:
    def __init__(self) -> None:
        self.created: list[dict] = []

    async def create_item(self, collection: str, payload: dict, **_kwargs: object):
        assert collection == "storage_deletion_tombstones"
        self.created.append(payload)
        return True, {"id": f"tombstone-{len(self.created)}", **payload}

    async def get_items(self, *_args: object, **_kwargs: object) -> list[dict]:
        return []


# contract-test: supporting surface=rest_api assertions=storage.deletion.global-authoritative
def test_embed_s3_cleanup_tombstones_rain_radar_preview_and_blob_files() -> None:
    from backend.core.api.app.services.directus.embed_methods import EmbedMethods

    service = EmbedMethods(FakeDirectus())

    asyncio.run(service._persist_s3_tombstones_for_embeds(
        [
            {
                "embed_id": "radar-embed-1",
                "s3_file_keys": [
                    {"bucket": "chatfiles", "key": "user/radar-preview.webp"},
                    {"bucket": "chatfiles", "key": "user/radar-blob.br"},
                ],
            }
        ],
        surviving_embeds=[],
    ))

    assert {
        (row["logical_bucket"], row["object_key"])
        for row in service.directus_service.created
    } == {
        ("chatfiles", "user/radar-preview.webp"),
        ("chatfiles", "user/radar-blob.br"),
    }
