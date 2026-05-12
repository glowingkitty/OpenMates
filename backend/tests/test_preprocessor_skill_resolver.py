"""Tests for AI preprocessing skill identifier normalization.

The preprocessing model sometimes emits mixed separator variants for app
skills. These tests keep the resolver aligned with tool dispatch names so
valid skills are not filtered before the main processor can execute them.

Architecture context: docs/architecture/apps/social-media.md
"""

from backend.apps.ai.processing.preprocessor import _build_skill_resolver_map


def test_skill_resolver_handles_mixed_app_and_skill_separators() -> None:
    resolver = _build_skill_resolver_map(["social_media-get-posts"])

    assert resolver["social_media-get_posts"] == "social_media-get-posts"
    assert resolver["social-media-get-posts"] == "social_media-get-posts"
    assert resolver["social_media_get_posts"] == "social_media-get-posts"


def test_skill_resolver_preserves_underscored_skill_ids() -> None:
    resolver = _build_skill_resolver_map(["code-search_repos"])

    assert resolver["code-search_repos"] == "code-search_repos"
    assert resolver["code-search-repos"] == "code-search_repos"
    assert resolver["code_search_repos"] == "code-search_repos"
