"""Public video approval is bound to exact copy, not language-dependent tokens."""
from backend.apps.ai.daily_inspiration.media_coherence import (
    editorial_review_digest, is_inspiration_media_coherent,
)
import pytest


def reviewed_japanese():
    row = {"content_type": "video", "youtube_id": "DOH-HNotTaE",
           "video_title": "雪の結晶ができる仕組み", "video_description": "水蒸気と六角形の氷。",
           "title": "空から届く氷のかたち", "phrase": "小さな氷にはどんな秘密があるでしょう。",
           "assistant_response": "雲の中の水蒸気が氷になります。結晶には六角形が現れます。",
           "follow_up_suggestions": ["氷の形を説明して"]}
    row["editorial_review"] = editorial_review_digest(row)
    return row


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
@pytest.mark.parametrize("field", ["title", "phrase", "assistant_response", "video_title",
                                   "video_description", "video_thumbnail_url", "youtube_id",
                                   "follow_up_suggestions", "video_channel_name"])
def test_changed_copy_source_or_thumbnail_invalidates_semantic_approval(field):
    row = reviewed_japanese()
    assert is_inspiration_media_coherent(row)
    row[field] = ["Unrelated"] if field == "follow_up_suggestions" else "Unrelated Paris subject"
    assert not is_inspiration_media_coherent(row)


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_unreviewed_and_old_policy_videos_are_withheld_without_lexical_exemptions():
    row = reviewed_japanese()
    row.pop("editorial_review")
    assert not is_inspiration_media_coherent(row)
    row["editorial_review"] = "daily-editorial-v4:old"
    assert not is_inspiration_media_coherent(row)


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_string_encoded_followups_preserve_persisted_proof():
    import json
    row = reviewed_japanese()
    row["follow_up_suggestions"] = json.dumps(row["follow_up_suggestions"])
    assert is_inspiration_media_coherent(row)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_default_persistence_preserves_every_field_bound_to_review():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.services.directus.daily_inspiration_defaults_methods import DailyInspirationDefaultsMethods
    source = {**reviewed_japanese(), "id": "reviewed-row", "language": "ja"}
    source["editorial_review"] = editorial_review_digest(source)
    service = SimpleNamespace(delete_items=AsyncMock(return_value=True),
        create_item=AsyncMock(return_value=(True, {})))
    defaults = DailyInspirationDefaultsMethods(service)
    assert await defaults.set_defaults_for_date("2026-10-20", "ja", [source]) == 1
    persisted = service.create_item.call_args.args[1]
    assert is_inspiration_media_coherent(persisted)
    assert persisted["video_description"] == source["video_description"]
