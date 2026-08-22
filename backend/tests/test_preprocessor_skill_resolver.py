"""Tests for AI preprocessing skill identifier normalization.

The preprocessing model sometimes emits mixed separator variants for app
skills. These tests keep the resolver aligned with tool dispatch names so
valid skills are not filtered before the main processor can execute them.

Architecture context: docs/architecture/apps/social-media.md
"""

# ruff: noqa: E402

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

import sys
import types

llm_utils_stub = types.ModuleType("backend.apps.ai.utils.llm_utils")
llm_utils_stub.call_preprocessing_llm = None
llm_utils_stub.LLMPreprocessingCallResult = object
sys.modules.setdefault("backend.apps.ai.utils.llm_utils", llm_utils_stub)

from backend.apps.ai.processing.preprocessor import (
    _build_skill_resolver_map,
    _resolve_explicit_skill_mentions_from_latest_user_text,
)


def _user_message(content: str) -> dict[str, str]:
    return {"role": "user", "content": content}


# contract-test: direct surface=gui.web assertions=app-skills.execution.registered-validated
def test_skill_resolver_handles_mixed_app_and_skill_separators() -> None:
    resolver = _build_skill_resolver_map(["social_media-get-posts"])

    assert resolver["social_media-get_posts"] == "social_media-get-posts"
    assert resolver["social-media-get-posts"] == "social_media-get-posts"
    assert resolver["social_media_get_posts"] == "social_media-get-posts"


# contract-test: direct surface=gui.web assertions=app-skills.execution.registered-validated
def test_skill_resolver_preserves_underscored_skill_ids() -> None:
    resolver = _build_skill_resolver_map(["code-search_repos"])

    assert resolver["code-search_repos"] == "code-search_repos"
    assert resolver["code-search-repos"] == "code-search_repos"
    assert resolver["code_search_repos"] == "code-search_repos"


# contract-test: direct surface=gui.web assertions=app-skills.execution.registered-validated
def test_skill_resolver_handles_dot_form_app_skill_names() -> None:
    resolver = _build_skill_resolver_map(["fitness-search_classes"])

    assert resolver["fitness.search_classes"] == "fitness-search_classes"
    assert resolver["fitness.search-classes"] == "fitness-search_classes"


# contract-test: direct surface=gui.web assertions=app-skills.execution.registered-validated
def test_skill_resolver_handles_slash_form_app_skill_names() -> None:
    resolver = _build_skill_resolver_map(["events-search"])

    assert resolver["events/search"] == "events-search"


# contract-test: direct surface=gui.web assertions=app-skills.execution.registered-validated,events-search.surface-parity
def test_explicit_skill_mention_resolves_dot_form_from_latest_user_message() -> None:
    result = _resolve_explicit_skill_mentions_from_latest_user_text(
        [_user_message("Use events.search to make two separate searches for tech events in Berlin.")],
        ["events-search", "web-search"],
    )

    assert result == ["events-search"]


# contract-test: direct surface=gui.web assertions=app-skills.execution.registered-validated
def test_explicit_skill_mention_requires_directive() -> None:
    result = _resolve_explicit_skill_mentions_from_latest_user_text(
        [_user_message("Why did events.search fail yesterday?")],
        ["events-search"],
    )

    assert result == []


# contract-test: direct surface=gui.web assertions=app-skills.execution.registered-validated
def test_explicit_skill_mention_ignores_assistant_history() -> None:
    result = _resolve_explicit_skill_mentions_from_latest_user_text(
        [
            {"role": "assistant", "content": "Use events.search for this."},
            _user_message("What events can I attend in Berlin?"),
        ],
        ["events-search"],
    )

    assert result == []
