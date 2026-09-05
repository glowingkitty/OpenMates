# backend/tests/test_external_result_sanitizer.py
#
# Unit tests for the external result sanitizer — field-level prompt injection
# scanning of external API results before they enter the AI context window.
#
# Tests cover: path key extraction, field sanitization decisions (skip lists,
# URL detection, min-char thresholds, long-text hints), recursive field collection,
# and path-based value setting on nested structures.
#
# Architecture: docs/architecture/prompt-injection.md
# Run: python -m pytest backend/tests/test_external_result_sanitizer.py -v

import pytest

try:
    from backend.apps.ai.processing.external_result_sanitizer import (
        _key_name_for_path,
        _should_sanitize_field,
        _collect_string_fields,
        _collect_string_fields_with_overrides,
        _set_path_value,
        SKIP_FIELD_NAMES,
        LONG_TEXT_HINTS,
    )
except ImportError as _exc:
    pytestmark = pytest.mark.skip(reason=f"Backend dependencies not installed: {_exc}")


# ===========================================================================
# _key_name_for_path
# ===========================================================================

class TestKeyNameForPath:
    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_simple_key(self):
        assert _key_name_for_path("description") == "description"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_dotted_path(self):
        assert _key_name_for_path("data.items.description") == "description"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_single_dot(self):
        assert _key_name_for_path("data.url") == "url"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_empty_string(self):
        assert _key_name_for_path("") == ""

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_returns_lowercase(self):
        assert _key_name_for_path("data.Description") == "description"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_array_indexed_path(self):
        # _key_name_for_path uses rsplit on ".", so "items[0].description" → "description"
        assert _key_name_for_path("data.items[0].description") == "description"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_array_string_path_strips_the_index_suffix(self):
        assert _key_name_for_path("results[0].extra_snippets[1]") == "extra_snippets"


# ===========================================================================
# _should_sanitize_field
# ===========================================================================

class TestShouldSanitizeField:
    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_skip_url_fields(self):
        """Fields in SKIP_FIELD_NAMES should never be sanitized."""
        for field in ["url", "image_url", "thumbnail", "favicon", "hash", "id", "s3_key",
                       "place_id", "phone_number", "datetime"]:
            assert _should_sanitize_field(field, "x" * 200, min_chars=120) is False

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_skip_url_values(self):
        """String values that look like URLs should be skipped."""
        assert _should_sanitize_field("content", "https://example.com/page", min_chars=10) is False
        assert _should_sanitize_field("content", "http://example.com/page", min_chars=10) is False

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_empty_or_whitespace_skipped(self):
        assert _should_sanitize_field("description", "", min_chars=10) is False
        assert _should_sanitize_field("description", "   ", min_chars=10) is False

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_long_text_sanitized(self):
        """Text >= min_chars should be sanitized."""
        text = "a" * 120
        assert _should_sanitize_field("some_field", text, min_chars=120) is True

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_short_text_not_sanitized(self):
        """Text < min_chars should NOT be sanitized (unless in LONG_TEXT_HINTS)."""
        text = "a" * 50
        assert _should_sanitize_field("some_unknown_field", text, min_chars=120) is False

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_long_text_hints_lower_threshold(self):
        """Fields in LONG_TEXT_HINTS are sanitized at 40 chars even if below min_chars."""
        for field in ["description", "summary", "content", "body", "transcript"]:
            text = "a" * 40
            assert _should_sanitize_field(field, text, min_chars=120) is True, \
                f"Expected sanitization for LONG_TEXT_HINT field: {field}"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_long_text_hints_below_40_not_sanitized(self):
        """Even LONG_TEXT_HINTS fields need at least 40 chars."""
        assert _should_sanitize_field("description", "a" * 39, min_chars=120) is False

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_dotted_path_extracts_key(self):
        """Should extract the final key from dotted paths."""
        assert _should_sanitize_field("data.items[0].description", "a" * 50, min_chars=120) is True

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_skip_field_in_dotted_path(self):
        """Should skip even when skip-field is part of a dotted path."""
        assert _should_sanitize_field("data.items[0].url", "a" * 200, min_chars=120) is False


# ===========================================================================
# _collect_string_fields
# ===========================================================================

class TestCollectStringFields:
    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_simple_dict(self):
        payload = {"description": "A long description " + "x" * 120}
        collected = []
        _collect_string_fields(payload, "", min_chars=120, collected=collected)
        assert len(collected) == 1
        assert collected[0][0] == "description"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_nested_dict(self):
        payload = {"data": {"items": {"description": "x" * 130}}}
        collected = []
        _collect_string_fields(payload, "", min_chars=120, collected=collected)
        assert len(collected) == 1
        assert collected[0][0] == "data.items.description"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_list_items(self):
        payload = [{"description": "x" * 130}, {"description": "y" * 130}]
        collected = []
        _collect_string_fields(payload, "", min_chars=120, collected=collected)
        assert len(collected) == 2
        assert "[0].description" in collected[0][0]
        assert "[1].description" in collected[1][0]

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_collects_each_short_extra_snippet(self):
        payload = {"extra_snippets": ["x" * 40, "y" * 40]}
        collected = []
        _collect_string_fields(payload, "", min_chars=120, collected=collected)
        assert collected == [("extra_snippets[0]", "x" * 40), ("extra_snippets[1]", "y" * 40)]

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_skips_url_fields(self):
        payload = {"url": "https://example.com", "description": "x" * 130}
        collected = []
        _collect_string_fields(payload, "", min_chars=120, collected=collected)
        assert len(collected) == 1
        assert collected[0][0] == "description"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_skips_short_text(self):
        payload = {"name": "short", "description": "x" * 130}
        collected = []
        _collect_string_fields(payload, "", min_chars=120, collected=collected)
        assert len(collected) == 1
        assert collected[0][0] == "description"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_empty_dict(self):
        collected = []
        _collect_string_fields({}, "", min_chars=120, collected=collected)
        assert collected == []

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_empty_list(self):
        collected = []
        _collect_string_fields([], "", min_chars=120, collected=collected)
        assert collected == []

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_non_dict_non_list_non_string(self):
        """Numbers, booleans, None should be silently skipped."""
        collected = []
        _collect_string_fields(42, "", min_chars=120, collected=collected)
        _collect_string_fields(None, "", min_chars=120, collected=collected)
        _collect_string_fields(True, "", min_chars=120, collected=collected)
        assert collected == []

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_deeply_nested(self):
        payload = {"a": {"b": {"c": {"content": "x" * 130}}}}
        collected = []
        _collect_string_fields(payload, "", min_chars=120, collected=collected)
        assert len(collected) == 1
        assert collected[0][0] == "a.b.c.content"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_overrides_collect_short_social_post_and_comment_bodies(self):
        payload = {
            "title": "Short title",
            "author": "safe_username",
            "comments": [{"body": "short but hostile", "author": "commenter"}],
        }
        collected = []
        _collect_string_fields_with_overrides(
            payload,
            "",
            min_chars=120,
            collected=collected,
            always_sanitize_field_names={"title", "body"},
        )

        assert collected == [("title", "Short title"), ("comments[0].body", "short but hostile")]

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_overrides_skip_audio_metadata_but_collect_transcript(self):
        payload = {
            "results": [
                {
                    "type": "transcription_result",
                    "s3_key": "user/hash/20260720_155114_original.bin",
                    "model": "voxtral-mini-2602",
                    "transcript": "short user speech",
                }
            ]
        }
        collected = []
        _collect_string_fields_with_overrides(
            payload,
            "",
            min_chars=120,
            collected=collected,
            always_sanitize_field_names={"transcript"},
        )

        assert collected == [("results[0].transcript", "short user speech")]


# ===========================================================================
# _set_path_value
# ===========================================================================

class TestSetPathValue:
    # contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
    def test_simple_key(self):
        obj = {"description": "old"}
        _set_path_value(obj, "description", "new")
        assert obj["description"] == "new"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
    def test_dotted_path(self):
        obj = {"data": {"description": "old"}}
        _set_path_value(obj, "data.description", "new")
        assert obj["data"]["description"] == "new"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
    def test_array_index(self):
        obj = {"items": ["a", "b", "c"]}
        _set_path_value(obj, "items[1]", "new")
        assert obj["items"][1] == "new"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
    def test_mixed_dict_and_array(self):
        obj = {"data": {"items": [{"name": "old"}, {"name": "old2"}]}}
        _set_path_value(obj, "data.items[0].name", "new")
        assert obj["data"]["items"][0]["name"] == "new"
        assert obj["data"]["items"][1]["name"] == "old2"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.batch-equivalent
    def test_deeply_nested_mixed(self):
        obj = {"a": [{"b": {"c": [{"d": "old"}]}}]}
        _set_path_value(obj, "a[0].b.c[0].d", "new")
        assert obj["a"][0]["b"]["c"][0]["d"] == "new"


# ===========================================================================
# Constants validation
# ===========================================================================

class TestConstants:
    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_skip_field_names_are_lowercase(self):
        for field in SKIP_FIELD_NAMES:
            assert field == field.lower(), f"SKIP_FIELD_NAMES entry '{field}' is not lowercase"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_long_text_hints_are_lowercase(self):
        for field in LONG_TEXT_HINTS:
            assert field == field.lower(), f"LONG_TEXT_HINTS entry '{field}' is not lowercase"

    # contract-test: supporting surface=rest_api assertions=app-skills.output.external-semantic
    def test_no_overlap(self):
        """Skip fields and long text hints should not overlap."""
        overlap = SKIP_FIELD_NAMES & LONG_TEXT_HINTS
        assert overlap == set(), f"Overlap between SKIP_FIELD_NAMES and LONG_TEXT_HINTS: {overlap}"
