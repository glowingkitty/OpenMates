"""Regression coverage for German public defaults and static personalized tips."""

import ast
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from backend.apps.ai.daily_inspiration.feature_suggestions import (
    GUEST_ONBOARDING_FEATURE_IDS,
    build_feature_inspirations,
    feature_requires_authentication,
)
from backend.apps.ai.daily_inspiration.wiki_suggestions import build_wiki_inspirations
from backend.apps.ai.daily_inspiration.media_coherence import editorial_review_digest, is_inspiration_media_coherent


ROOT = Path(__file__).resolve().parents[2]


def _load_route():
    """Load real route logic without requiring the Docker-only service graph.

    Imports/decorators configure FastAPI/Redis, while the actual endpoint and
    all its helpers execute unchanged with service doubles below.
    """
    source = ROOT / "backend/core/api/app/routes/default_inspirations.py"
    tree = ast.parse(source.read_text())
    nodes = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            node.decorator_list = []
            nodes.append(node)
        elif isinstance(node, ast.Assign) and all(
            isinstance(target, ast.Name) and target.id.startswith("_")
            for target in node.targets
        ):
            nodes.append(node)
    namespace = {
        "__annotations__": {},
        "Dict": Dict,
        "List": List,
        "Any": Any,
        "Request": Any,
        "DirectusService": Any,
        "CacheService": Any,
        "Depends": lambda dependency: None,
        "json": json,
        "random": random,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "logger": logging.getLogger(__name__),
        "AVAILABLE_CATEGORIES": {"science", "history", "openmates_official"},
        "GUEST_ONBOARDING_FEATURE_IDS": GUEST_ONBOARDING_FEATURE_IDS,
        "feature_requires_authentication": feature_requires_authentication,
        "build_feature_inspirations": build_feature_inspirations,
        "build_wiki_inspirations": build_wiki_inspirations,
        "is_inspiration_media_coherent": is_inspiration_media_coherent,
    }
    exec(
        compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace
    )
    return namespace["get_default_inspirations"]


# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_german_static_personalized_features_translate_all_display_text():
    german = build_feature_inspirations(20, language="de-DE")
    english = build_feature_inspirations(20)
    assert len(german) == len(english) == 9
    for localized, original in zip(german, english):
        assert localized.language == "de"
        assert localized.phrase != original.phrase
        assert localized.title != original.title
        assert localized.assistant_response != original.assistant_response
        assert localized.feature.description != original.feature.description
        assert localized.feature.settings_path == original.feature.settings_path
        if localized.direct_video:
            assert localized.direct_video.title == localized.title
            assert localized.direct_video.mp4_url == original.direct_video.mp4_url


# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_german_static_wiki_copy_and_extract_are_localized():
    for german, english in zip(
        build_wiki_inspirations(10, language="de"),
        build_wiki_inspirations(10),
    ):
        assert german.language == "de"
        assert german.phrase != english.phrase
        assert german.assistant_response != english.assistant_response
        assert german.wiki.description != english.wiki.description
        assert german.wiki.extract == german.assistant_response
        assert german.wiki.wiki_title == english.wiki.wiki_title


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
async def test_german_defaults_remove_english_fill_even_when_stamped_german():
    english = {
        "pool_entry_id": "english-video",
        "language": "de",
        "phrase": "English contamination",
        "content_type": "video",
    }
    german = {
        "pool_entry_id": "german-wiki",
        "language": "de",
        "phrase": "Wie entsteht das Leuchten?",
        "title": "Leuchtende Tiere",
        "content_type": "wiki",
        "category": "science",
    }
    german["wiki_metadata"] = {"wiki_title": "Biolumineszenz", "source_language": "de",
        "title": "Biolumineszenz", "description": "Natürliches Leuchten",
        "extract": "Tiere erzeugen durch chemische Reaktionen Licht."}
    german["editorial_review"] = editorial_review_digest(german)
    directus = SimpleNamespace(
        inspiration_defaults=SimpleNamespace(
            get_defaults_for_date=AsyncMock(return_value=[english, german])
        ),
        inspiration_pool=SimpleNamespace(
            get_pool_entries_by_language=AsyncMock(return_value=[{"id": "german-wiki"}])
        ),
    )
    redis = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())

    class Cache:
        @property
        async def client(self):
            return redis

    response = await _load_route()(None, "de", directus, Cache())
    items = response["inspirations"]
    assert len(items) == 10
    assert all(item["language"] == "de" for item in items)
    assert not any(item["phrase"] == english["phrase"] for item in items)
    assert any(item["phrase"] == german["phrase"] for item in items)
    assert redis.set.call_args.args[0] == "public:default_inspirations:v15:de"


@pytest.mark.asyncio
# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
async def test_german_cache_miss_without_defaults_returns_ten_localized_items():
    directus = SimpleNamespace(
        inspiration_defaults=SimpleNamespace(
            get_defaults_for_date=AsyncMock(return_value=[])
        ),
    )

    class Cache:
        @property
        async def client(self):
            return None

    response = await _load_route()(None, "de", directus, Cache())
    items = response["inspirations"]
    assert len(items) == 10
    assert all(item["language"] == "de" for item in items)
    assert all(item["content_type"] in {"wiki", "feature"} for item in items)
    assert all(
        not item.get("feature", {}).get("requires_authentication", False)
        for item in items
        if item.get("feature")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "de", "zh", "es", "fr", "pt", "ru", "ja", "ko", "it", "tr", "vi", "id", "pl", "nl", "ar", "hi", "th", "cs", "sv"])
# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
async def test_every_public_locale_recovers_ten_localized_cards(language):
    directus = SimpleNamespace(inspiration_defaults=SimpleNamespace(get_defaults_for_date=AsyncMock(return_value=[])))
    class Cache:
        @property
        async def client(self):
            return None
    cards = (await _load_route()(None, language, directus, Cache()))["inspirations"]
    assert len(cards) == 10
    assert all(card["language"] == language for card in cards)
    if language != "en":
        english_phrases = {card.phrase for card in build_wiki_inspirations(10)}
        english_phrases.update(card.phrase for card in build_feature_inspirations(20))
        assert not english_phrases.intersection(card["phrase"] for card in cards)


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize("legacy", ["missing_proof", "old_proof", "changed_source", "missing_source"])
# contract-test: supporting surface=rest_api assertions=daily-inspiration.public-defaults
async def test_legacy_dynamic_wiki_defaults_are_withheld_and_static_ten_recover(language, legacy):
    row = {"pool_entry_id": "legacy-wiki", "language": language, "content_type": "wiki",
           "phrase": "LEGACY_UNREVIEWED_COPY", "title": "Legacy generated title",
           "assistant_response": "Legacy generated intro", "follow_up_suggestions": [],
           "wiki_metadata": {"wiki_title": "Cloud", "source_language": "en", "title": "Cloud",
                             "description": "Atmospheric droplets", "extract": "Clouds contain droplets."}}
    if legacy != "missing_proof":
        row["editorial_review"] = editorial_review_digest(row)
    if legacy == "old_proof":
        row["editorial_review"] = row["editorial_review"].replace("daily-editorial-v6:", "daily-editorial-v5:")
    elif legacy == "changed_source":
        row["wiki_metadata"]["extract"] = "A changed source passage."
    elif legacy == "missing_source":
        row.pop("wiki_metadata")
    directus = SimpleNamespace(
        inspiration_defaults=SimpleNamespace(get_defaults_for_date=AsyncMock(return_value=[row])),
        inspiration_pool=SimpleNamespace(get_pool_entries_by_language=AsyncMock(return_value=[{"id": "legacy-wiki"}]))
    )
    class Cache:
        @property
        async def client(self):
            return None
    response = await _load_route()(None, language, directus, Cache())
    cards = response["inspirations"]
    assert len(cards) == 10
    assert not any(card["phrase"] == row["phrase"] for card in cards)
    assert all(card["content_type"] in {"wiki", "feature"} for card in cards)
    assert all(card["language"] == language for card in cards)
