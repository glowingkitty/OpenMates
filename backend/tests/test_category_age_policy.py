# backend/tests/test_category_age_policy.py
#
# Unit tests for the Daily Inspiration category-based video age policy.
# Guards OPE-350: filter stale YouTube videos from inspirations while keeping
# evergreen categories (history, cooking, psychology, movies, general knowledge)
# uncapped.
#
# Bug history this test suite guards against:
# - OPE-350 (2026-04-06): an 11-year-old DW video was surfaced for a finance
#   topic. The fix introduced category_age_policy.py with per-bucket caps
#   (strict 3y, medium 5y, loose 10y, evergreen uncapped) and a blanket 10y
#   hard cutoff. These tests lock in the cap table, the parser's fail-open
#   behavior, and the unknown-category fallback.
#
# Run: python -m pytest backend/tests/test_category_age_policy.py -v

from datetime import datetime, timedelta, timezone

import pytest

# The policy module has zero external deps — import it directly so tests run
# even on machines without the full backend stack installed.
try:
    from backend.apps.ai.daily_inspiration.category_age_policy import (
        CATEGORY_MAX_AGE_YEARS,
        DEFAULT_MAX_AGE_YEARS,
        HARD_CUTOFF_YEARS,
        LOOSE_MAX_YEARS,
        MEDIUM_MAX_YEARS,
        STRICT_MAX_YEARS,
        describe_policy_for_prompt,
        get_max_age_years,
        is_within_category_policy,
        is_within_hard_cutoff,
        parse_published_at,
        policy_bucket_for_category,
        video_age_years,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend policy module missing: {_exc}")

# Generator import is optional — pulls in heavy deps (dotenv, httpx, etc.).
# Only the cross-consistency test needs it; other tests continue to run.
try:
    from backend.apps.ai.daily_inspiration.generator import AVAILABLE_CATEGORIES
    _HAS_GENERATOR = True
except ImportError:
    AVAILABLE_CATEGORIES = []
    _HAS_GENERATOR = False


# ──────────────────────────────────────────────────────────────────────────────
# Fixture: fixed "now" for deterministic age calculations
# ──────────────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)


def _iso_years_ago(years: float) -> str:
    """Build an ISO 8601 Z-suffix timestamp N years before NOW."""
    delta = timedelta(days=years * 365.25)
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


# ──────────────────────────────────────────────────────────────────────────────
# parse_published_at
# ──────────────────────────────────────────────────────────────────────────────


class TestParsePublishedAt:
    def test_z_suffix(self):
        parsed = parse_published_at("2024-06-15T10:30:00Z")
        assert parsed is not None
        assert parsed.tzinfo is not None
        assert parsed.year == 2024 and parsed.month == 6 and parsed.day == 15

    def test_explicit_offset(self):
        parsed = parse_published_at("2024-06-15T12:30:00+02:00")
        assert parsed is not None
        # Normalised to UTC
        assert parsed.hour == 10

    def test_naive_assumed_utc(self):
        parsed = parse_published_at("2024-06-15T10:30:00")
        assert parsed is not None
        assert parsed.tzinfo == timezone.utc

    def test_none_returns_none(self):
        assert parse_published_at(None) is None

    def test_empty_string_returns_none(self):
        assert parse_published_at("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_published_at("   ") is None

    def test_garbage_returns_none(self):
        assert parse_published_at("not-a-date") is None

    def test_partial_garbage_returns_none(self):
        assert parse_published_at("2024/06/15") is None

    def test_future_date_parses(self):
        # Future dates parse fine — age calculation clamps them.
        parsed = parse_published_at("2099-01-01T00:00:00Z")
        assert parsed is not None and parsed.year == 2099


# ──────────────────────────────────────────────────────────────────────────────
# video_age_years
# ──────────────────────────────────────────────────────────────────────────────


class TestVideoAgeYears:
    def test_known_age(self):
        age = video_age_years(_iso_years_ago(2.0), now=NOW)
        assert age is not None
        assert 1.99 < age < 2.01

    def test_missing_returns_none(self):
        assert video_age_years(None, now=NOW) is None
        assert video_age_years("", now=NOW) is None
        assert video_age_years("garbage", now=NOW) is None

    def test_future_clamped_to_zero(self):
        age = video_age_years("2099-01-01T00:00:00Z", now=NOW)
        assert age == 0.0

    def test_zero_age(self):
        age = video_age_years("2026-04-06T12:00:00Z", now=NOW)
        assert age is not None and abs(age) < 0.001


# ──────────────────────────────────────────────────────────────────────────────
# Category mapping consistency
# ──────────────────────────────────────────────────────────────────────────────


class TestCategoryMapping:
    @pytest.mark.skipif(not _HAS_GENERATOR, reason="generator module requires backend deps")
    def test_all_generator_categories_mapped(self):
        """The policy table must cover every category the LLM can emit."""
        missing = set(AVAILABLE_CATEGORIES) - set(CATEGORY_MAX_AGE_YEARS.keys())
        extra = set(CATEGORY_MAX_AGE_YEARS.keys()) - set(AVAILABLE_CATEGORIES)
        assert not missing, f"Categories missing from policy table: {missing}"
        assert not extra, f"Policy table has unknown categories: {extra}"

    def test_strict_bucket_members(self):
        strict = {
            c for c, cap in CATEGORY_MAX_AGE_YEARS.items()
            if cap == STRICT_MAX_YEARS
        }
        assert strict == {
            "software_development", "finance", "marketing_sales",
            "business_development", "activism",
        }

    def test_medium_bucket_members(self):
        medium = {
            c for c, cap in CATEGORY_MAX_AGE_YEARS.items()
            if cap == MEDIUM_MAX_YEARS
        }
        assert medium == {
            "science", "medical_health", "electrical_engineering",
            "maker_prototyping",
        }

    def test_loose_bucket_members(self):
        loose = {
            c for c, cap in CATEGORY_MAX_AGE_YEARS.items()
            if cap == LOOSE_MAX_YEARS
        }
        assert loose == {"design"}

    def test_evergreen_bucket_members(self):
        evergreen = {c for c, cap in CATEGORY_MAX_AGE_YEARS.items() if cap is None}
        assert evergreen == {
            "history", "movies_tv", "life_coach_psychology",
            "cooking_food", "general_knowledge",
        }


# ──────────────────────────────────────────────────────────────────────────────
# get_max_age_years
# ──────────────────────────────────────────────────────────────────────────────


class TestGetMaxAgeYears:
    def test_strict(self):
        assert get_max_age_years("finance") == STRICT_MAX_YEARS

    def test_medium(self):
        assert get_max_age_years("science") == MEDIUM_MAX_YEARS

    def test_loose(self):
        assert get_max_age_years("design") == LOOSE_MAX_YEARS

    def test_evergreen_returns_none(self):
        assert get_max_age_years("history") is None
        assert get_max_age_years("cooking_food") is None

    def test_unknown_falls_back_to_loose(self):
        assert get_max_age_years("unrecognized") == DEFAULT_MAX_AGE_YEARS
        assert DEFAULT_MAX_AGE_YEARS == LOOSE_MAX_YEARS

    def test_none_falls_back_to_loose(self):
        assert get_max_age_years(None) == DEFAULT_MAX_AGE_YEARS


# ──────────────────────────────────────────────────────────────────────────────
# is_within_hard_cutoff
# ──────────────────────────────────────────────────────────────────────────────


class TestIsWithinHardCutoff:
    def test_recent_video_passes(self):
        assert is_within_hard_cutoff(_iso_years_ago(2.0), now=NOW) is True

    def test_nine_years_passes(self):
        assert is_within_hard_cutoff(_iso_years_ago(9.0), now=NOW) is True

    def test_eleven_years_fails(self):
        assert is_within_hard_cutoff(_iso_years_ago(11.0), now=NOW) is False

    def test_missing_date_fails_open(self):
        assert is_within_hard_cutoff(None, now=NOW) is True
        assert is_within_hard_cutoff("", now=NOW) is True
        assert is_within_hard_cutoff("garbage", now=NOW) is True

    def test_future_date_passes(self):
        assert is_within_hard_cutoff("2099-01-01T00:00:00Z", now=NOW) is True

    def test_hard_cutoff_constant(self):
        """OPE-350 guard: hard cutoff must be 10 years."""
        assert HARD_CUTOFF_YEARS == 10


# ──────────────────────────────────────────────────────────────────────────────
# is_within_category_policy
# ──────────────────────────────────────────────────────────────────────────────


class TestIsWithinCategoryPolicy:
    def test_strict_within_cap(self):
        assert is_within_category_policy("finance", _iso_years_ago(2.0), now=NOW) is True

    def test_strict_over_cap(self):
        """OPE-350: the exact bug — a 4-year-old finance video must be rejected."""
        assert is_within_category_policy("finance", _iso_years_ago(4.0), now=NOW) is False

    def test_strict_missing_date_fails_open(self):
        assert is_within_category_policy("finance", None, now=NOW) is True

    def test_medium_within_cap(self):
        assert is_within_category_policy("science", _iso_years_ago(4.0), now=NOW) is True

    def test_medium_over_cap(self):
        assert is_within_category_policy("science", _iso_years_ago(6.0), now=NOW) is False

    def test_loose_within_cap(self):
        assert is_within_category_policy("design", _iso_years_ago(9.0), now=NOW) is True

    def test_loose_over_cap(self):
        assert is_within_category_policy("design", _iso_years_ago(11.0), now=NOW) is False

    def test_evergreen_allows_ancient(self):
        assert is_within_category_policy("history", _iso_years_ago(50.0), now=NOW) is True
        assert is_within_category_policy("cooking_food", _iso_years_ago(30.0), now=NOW) is True

    def test_unknown_uses_loose(self):
        assert is_within_category_policy("unrecognized", _iso_years_ago(9.0), now=NOW) is True
        assert is_within_category_policy("unrecognized", _iso_years_ago(11.0), now=NOW) is False

    def test_future_date_passes(self):
        assert is_within_category_policy("finance", "2099-01-01T00:00:00Z", now=NOW) is True


# ──────────────────────────────────────────────────────────────────────────────
# policy_bucket_for_category
# ──────────────────────────────────────────────────────────────────────────────


class TestPolicyBucket:
    def test_strict(self):
        assert policy_bucket_for_category("finance") == "strict"

    def test_medium(self):
        assert policy_bucket_for_category("science") == "medium"

    def test_loose(self):
        assert policy_bucket_for_category("design") == "loose"

    def test_evergreen(self):
        assert policy_bucket_for_category("history") == "evergreen"

    def test_unknown(self):
        assert policy_bucket_for_category("nope") == "unknown"
        assert policy_bucket_for_category(None) == "unknown"


# ──────────────────────────────────────────────────────────────────────────────
# describe_policy_for_prompt
# ──────────────────────────────────────────────────────────────────────────────


class TestDescribePolicyForPrompt:
    def test_non_empty(self):
        text = describe_policy_for_prompt()
        assert isinstance(text, str) and len(text) > 50

    def test_mentions_key_bucket_numbers(self):
        text = describe_policy_for_prompt()
        # The LLM needs to see the numeric caps to reason about them.
        assert "3 years" in text
        assert "5 years" in text
        assert "10 years" in text

    def test_mentions_evergreen_categories(self):
        text = describe_policy_for_prompt()
        assert "history" in text
        assert "cooking" in text
