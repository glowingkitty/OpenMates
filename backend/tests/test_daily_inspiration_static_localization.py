"""Static public card translations must ship complete, offline and honestly tagged."""
import json
from pathlib import Path

import pytest
import yaml

from backend.apps.ai.daily_inspiration.feature_suggestions import (
    FEATURE_TIPS,
    build_feature_inspirations,
)
from backend.apps.ai.daily_inspiration.static_localization import STATIC_LOCALIZATIONS
from backend.apps.ai.daily_inspiration.wiki_suggestions import WIKI_TIPS, build_wiki_inspirations

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {"title", "description", "phrase", "assistant_response"}


# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_generated_copy_covers_every_supported_ui_language_and_static_card():
    registry = json.loads((ROOT / "frontend/packages/ui/src/i18n/languages.json").read_text())
    assert set(STATIC_LOCALIZATIONS) == {entry["code"] for entry in registry["languages"]}
    english = STATIC_LOCALIZATIONS["en"]
    assert len(english) == len(FEATURE_TIPS) + len(WIKI_TIPS)
    for locale, cards in STATIC_LOCALIZATIONS.items():
        assert cards.keys() == english.keys()
        for key, copy in cards.items():
            assert copy.keys() == FIELDS
            assert all(isinstance(value, str) and value.strip() for value in copy.values())
            if locale != "en":
                # Proper names can match, but no card may silently retain English body copy.
                for field in ("description", "phrase", "assistant_response"):
                    assert copy[field] != english[key][field], (locale, key, field)


@pytest.mark.parametrize("locale", STATIC_LOCALIZATIONS)
# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_all_locales_reach_every_visible_field_without_changing_identity(locale):
    features = build_feature_inspirations(count=99, language=locale)
    english_features = build_feature_inspirations(count=99, language="en")
    wikis = build_wiki_inspirations(count=99, language=locale)
    english_wikis = build_wiki_inspirations(count=99, language="en")
    for item, baseline in zip(features, english_features, strict=True):
        assert item.language == locale
        assert item.title == item.feature.title
        assert item.feature.feature_id == baseline.feature.feature_id
        assert item.feature.icon == baseline.feature.icon
        assert item.feature.settings_path == baseline.feature.settings_path
        assert item.feature.requires_authentication == baseline.feature.requires_authentication
        if item.direct_video:
            assert item.direct_video.title == item.title
            assert item.direct_video.mp4_url == baseline.direct_video.mp4_url
            assert item.direct_video.thumbnail_url == baseline.direct_video.thumbnail_url
            assert item.direct_video.teaser_url == baseline.direct_video.teaser_url
        if locale != "en":
            assert item.phrase != baseline.phrase
            assert item.assistant_response != baseline.assistant_response
            assert item.feature.description != baseline.feature.description
    for item, baseline in zip(wikis, english_wikis, strict=True):
        assert item.language == locale
        assert item.title == item.wiki.title
        assert item.assistant_response == item.wiki.extract
        assert item.wiki.source_language == "en"
        assert item.wiki.wiki_title == baseline.wiki.wiki_title
        assert item.category == baseline.category
        if locale != "en":
            assert item.phrase != baseline.phrase
            assert item.wiki.description != baseline.wiki.description
            assert item.assistant_response != baseline.assistant_response


@pytest.mark.parametrize("requested,expected", [
    ("pt-BR", "pt"), ("ZH_hant_TW", "zh"), (" FR-ca ", "fr"),
    ("he-IL", "he"), ("unsupported", "en"), ("", "en"),
])
# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_region_variants_and_unsupported_languages_are_truthfully_tagged(requested, expected):
    for build in (build_feature_inspirations, build_wiki_inspirations):
        actual = build(language=requested)
        baseline = build(language=expected)
        assert [(item.language, item.title, item.phrase) for item in actual] == [
            (item.language, item.title, item.phrase) for item in baseline
        ]


# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_guest_localized_features_keep_authentication_filter():
    cards = build_feature_inspirations(count=99, language="ar", include_authenticated_only=False)
    assert cards
    assert all(card.language == "ar" and not card.feature.requires_authentication for card in cards)
    assert {card.feature.feature_id for card in cards}.isdisjoint({"export-data", "incognito-mode"})


# contract-test: supporting surface=rest_api assertions=language-preferences.content-language,daily-inspiration.public-defaults
def test_generated_backend_copy_matches_shared_yaml_source():
    source = yaml.safe_load((ROOT / "frontend/packages/ui/src/i18n/sources/daily_inspiration_fallback.yml").read_text())
    for locale, cards in STATIC_LOCALIZATIONS.items():
        for card, copy in cards.items():
            assert copy == {field: source[f"{card}.{field}"][locale] for field in FIELDS}
