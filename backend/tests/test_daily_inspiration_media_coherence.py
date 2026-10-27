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
    row["editorial_review"] = editorial_review_digest(row).replace("daily-editorial-v10:", "daily-editorial-v5:")
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


def reviewed_wiki():
    row = {
        "id": "wiki-source", "language": "de", "content_type": "wiki", "category": "science",
        "title": "Wie entsteht das Leuchten?", "phrase": "Tiere erzeugen Licht. Wie funktioniert das?",
        "assistant_response": "Chemische Reaktionen erzeugen Licht.",
        "follow_up_suggestions": ["Wie entsteht das Licht?", "Welche Tiere leuchten?", "Was sind chemische Reaktionen?"],
        "wiki_metadata": {"wiki_title": "Biolumineszenz", "source_language": "de",
            "title": "Biolumineszenz", "description": "Licht lebender Organismen",
            "extract": "Tiere erzeugen durch chemische Reaktionen Licht.",
            "wikidata_id": "Q184600", "thumbnail_url": "https://example.test/wiki.jpg"},
    }
    row["editorial_review"] = editorial_review_digest(row)
    return row


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
@pytest.mark.parametrize("field", ["wiki_title", "source_language", "title", "description", "extract", "wikidata_id"])
def test_wiki_source_identity_edition_and_passage_are_bound(field):
    row = reviewed_wiki()
    assert is_inspiration_media_coherent(row)
    row["wiki_metadata"][field] = "Changed source evidence"
    assert not is_inspiration_media_coherent(row)


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
@pytest.mark.parametrize("field", ["language", "title", "phrase", "assistant_response", "category", "follow_up_suggestions", "content_type"])
def test_wiki_output_and_type_are_bound(field):
    row = reviewed_wiki()
    row[field] = ["Changed"] if field == "follow_up_suggestions" else "Changed"
    assert not is_inspiration_media_coherent(row)


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
@pytest.mark.parametrize("proof", [None, "daily-editorial-v5:legacy", "daily-editorial-v10:wrong"])
def test_old_or_missing_dynamic_wiki_proof_is_withheld(proof):
    row = reviewed_wiki()
    row["editorial_review"] = proof
    assert not is_inspiration_media_coherent(row)


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
@pytest.mark.parametrize("missing", ["wiki_metadata", "wiki_title", "source_language", "title", "extract"])
def test_wiki_proof_requires_actual_identity_edition_and_passage(missing):
    row = reviewed_wiki()
    if missing == "wiki_metadata":
        row.pop(missing)
    else:
        row["wiki_metadata"].pop(missing)
    # Generated title, intro, language and phrase cannot fill missing source data.
    with pytest.raises(ValueError):
        editorial_review_digest(row)
    assert not is_inspiration_media_coherent(row)


# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_wiki_metadata_and_followup_json_roundtrip_preserves_digest():
    import json
    row = reviewed_wiki()
    digest = row["editorial_review"]
    row["wiki_metadata"] = json.dumps(dict(reversed(list(row["wiki_metadata"].items()))), ensure_ascii=True)
    row["follow_up_suggestions"] = json.dumps(row["follow_up_suggestions"], ensure_ascii=True)
    assert editorial_review_digest(row) == digest
    assert is_inspiration_media_coherent(row)


def load_pool_review_helpers(review):
    """Execute the actual scheduled admission helpers without the Celery service graph."""
    import ast
    import json
    from pathlib import Path
    from typing import Any, Dict
    from backend.apps.ai.daily_inspiration.media_coherence import canonical_wiki_review_source
    from backend.apps.ai.daily_inspiration.feature_suggestions import feature_requires_authentication
    path = Path(__file__).resolve().parents[1] / "core/api/app/tasks/default_inspiration_tasks.py"
    names = {"_review_pool_entries", "_is_public_default_candidate", "_feature_metadata"}
    nodes = [node for node in ast.parse(path.read_text()).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    scope = {"json": json, "review_candidates": review, "Dict": Dict, "Any": Any,
             "canonical_wiki_review_source": canonical_wiki_review_source,
             "editorial_review_digest": editorial_review_digest,
             "is_inspiration_media_coherent": is_inspiration_media_coherent,
             "feature_requires_authentication": feature_requires_authentication}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), scope)
    return scope


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_actual_scheduled_wiki_review_stamps_persistable_current_proof():
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from backend.core.api.app.services.directus.daily_inspiration_defaults_methods import DailyInspirationDefaultsMethods
    captured = []
    async def review(candidates, *_args, **_kwargs):
        captured.extend(candidates)
        return candidates
    scope = load_pool_review_helpers(review)
    row = reviewed_wiki()
    row.pop("editorial_review")
    assert not scope["_is_public_default_candidate"](row)
    reviewed = await scope["_review_pool_entries"]([row], None, "test")
    assert len(reviewed) == 1
    assert "editorial_review" not in row  # Stored history is untouched.
    assert captured[0]["title"] == row["wiki_metadata"]["title"]
    assert captured[0]["wiki_title"] == row["wiki_metadata"]["wiki_title"]
    assert captured[0]["extract"] == row["wiki_metadata"]["extract"]
    assert scope["_is_public_default_candidate"](reviewed[0])
    service = SimpleNamespace(delete_items=AsyncMock(return_value=True), create_item=AsyncMock(return_value=(True, {})))
    assert await DailyInspirationDefaultsMethods(service).set_defaults_for_date("2026-10-21", "de", reviewed) == 1
    persisted = service.create_item.call_args.args[1]
    assert persisted["wiki_metadata"] == row["wiki_metadata"]
    # Directus text-field serialization must preserve every hashed source field.
    persisted["wiki_metadata"] = json.dumps(persisted["wiki_metadata"], ensure_ascii=True)
    persisted["follow_up_suggestions"] = json.dumps(persisted["follow_up_suggestions"])
    assert is_inspiration_media_coherent(persisted)


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_missing_wiki_source_cannot_be_reviewed_as_generated_copy():
    captured = []
    async def review(candidates, *_args, **_kwargs):
        captured.extend(candidates)
        return candidates
    scope = load_pool_review_helpers(review)
    missing = reviewed_wiki()
    missing.pop("wiki_metadata")
    no_edition = reviewed_wiki()
    no_edition["wiki_metadata"].pop("source_language")
    feature = {"content_type": "feature", "feature_metadata": {"feature_id": "custom-pii-detection", "requires_authentication": False}}
    assert await scope["_review_pool_entries"]([missing, no_edition, feature], None, "test") == [feature]
    assert captured == []
    assert scope["_is_public_default_candidate"](feature)


@pytest.mark.parametrize('builder', [reviewed_japanese, reviewed_wiki])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
def test_current_proof_and_policy_versions_invalidate_previous_reviews(builder):
    from backend.apps.ai.daily_inspiration.decisions import POLICY_VERSION
    from backend.apps.ai.daily_inspiration.media_coherence import REVIEW_VERSION
    assert POLICY_VERSION == REVIEW_VERSION == 'daily-editorial-v10'
    row = builder()
    assert is_inspiration_media_coherent(row)
    row['editorial_review'] = row['editorial_review'].replace('daily-editorial-v10:', 'daily-editorial-v9:')
    assert not is_inspiration_media_coherent(row)
