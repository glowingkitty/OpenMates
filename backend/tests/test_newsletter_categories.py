"""Newsletter category migration contract tests.

These tests protect the consent boundary for newsletter delivery categories:
settings surfaces expose canonical categories, legacy stored preferences are
honored as aliases, and unknown categories fail closed instead of broadening
eligibility.
"""

from __future__ import annotations

from backend.core.api.app.utils.newsletter_utils import (
    DEFAULT_NEWSLETTER_CATEGORIES,
    NEWSLETTER_CATEGORIES,
    apply_newsletter_category_update,
    is_subscriber_allowed_for_category,
    normalize_newsletter_categories,
)


# contract-test: direct surface=rest_api assertions=newsletter.categories.default-and-migration
def test_missing_preferences_default_canonical_events_and_software_updates_on() -> None:
    assert NEWSLETTER_CATEGORIES == ("openmates_events", "software_updates")
    assert DEFAULT_NEWSLETTER_CATEGORIES == {
        "openmates_events": True,
        "software_updates": True,
    }
    assert normalize_newsletter_categories(None) == DEFAULT_NEWSLETTER_CATEGORIES


# contract-test: direct surface=rest_api assertions=newsletter.categories.default-and-migration
def test_legacy_updates_opt_out_maps_both_canonical_categories_off() -> None:
    normalized = normalize_newsletter_categories({"updates_and_announcements": False})

    assert normalized == {
        "openmates_events": False,
        "software_updates": False,
    }


# contract-test: direct surface=rest_api assertions=newsletter.categories.default-and-migration
def test_explicit_canonical_values_win_over_legacy_aliases() -> None:
    normalized = normalize_newsletter_categories(
        {
            "updates_and_announcements": False,
            "openmates_events": True,
            "software_updates": False,
        }
    )

    assert normalized == {
        "openmates_events": True,
        "software_updates": False,
    }


# contract-test: direct surface=rest_api assertions=newsletter.categories.default-and-migration
def test_delivery_allows_canonical_and_legacy_aliases_but_unknown_fails_closed() -> None:
    categories = {"openmates_events": True, "software_updates": False, "daily_inspirations": True}

    assert is_subscriber_allowed_for_category(categories, "openmates_events") is True
    assert is_subscriber_allowed_for_category(categories, "software_updates") is False
    assert is_subscriber_allowed_for_category(categories, "updates_and_announcements") is False
    assert is_subscriber_allowed_for_category(categories, "tips_and_tricks") is False
    assert is_subscriber_allowed_for_category(categories, "daily_inspirations") is True
    assert is_subscriber_allowed_for_category(categories, "unknown") is False


# contract-test: direct surface=rest_api assertions=newsletter.categories.default-and-migration
def test_partial_updates_change_only_supplied_canonical_keys() -> None:
    updated = apply_newsletter_category_update(
        {"openmates_events": True, "software_updates": True},
        {"software_updates": False, "updates_and_announcements": False, "unknown": True},
    )

    assert updated == {
        "openmates_events": True,
        "software_updates": False,
    }
