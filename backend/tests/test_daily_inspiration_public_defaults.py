# backend/tests/test_daily_inspiration_public_defaults.py
# Regression tests for public Daily Inspiration defaults.
#
# Public defaults are shown to signed-out visitors, so they must not include
# settings deep links that only work after authentication. Static Wikipedia
# fallbacks also need to avoid redirect-only titles that surprise users.

from backend.apps.ai.daily_inspiration.feature_suggestions import (
    build_feature_inspirations,
    feature_requires_authentication,
)
from backend.apps.ai.daily_inspiration.wiki_suggestions import build_wiki_inspirations


def test_public_feature_inspirations_exclude_authenticated_only_tips() -> None:
    inspirations = build_feature_inspirations(
        count=10,
        include_authenticated_only=False,
    )

    feature_ids = [inspiration.feature.feature_id for inspiration in inspirations if inspiration.feature]

    assert "export-data" not in feature_ids
    assert "custom-pii-detection" in feature_ids
    assert "incognito-mode" not in feature_ids
    assert "privacy-dashboard" in feature_ids
    assert all(
        inspiration.feature and inspiration.feature.requires_authentication is False
        for inspiration in inspirations
    )


def test_unknown_legacy_feature_ids_default_to_authenticated_only() -> None:
    assert feature_requires_authentication("unknown-legacy-feature") is True


def test_static_wiki_fallbacks_do_not_include_redirect_only_murmuration() -> None:
    inspirations = build_wiki_inspirations(count=10)
    wiki_titles = [inspiration.wiki.wiki_title for inspiration in inspirations if inspiration.wiki]

    assert "Murmuration" not in wiki_titles
    assert "Collective_animal_behavior" in wiki_titles
