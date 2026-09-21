"""Regression coverage for same-topic news follow-up routing."""

# ruff: noqa: E402

import sys
import types

from backend.tests.runtime_import_stubs import install_code_route_import_stubs

install_code_route_import_stubs()

llm_utils_stub = types.ModuleType("backend.apps.ai.utils.llm_utils")
llm_utils_stub.call_preprocessing_llm = None
llm_utils_stub.LLMPreprocessingCallResult = object
sys.modules.setdefault("backend.apps.ai.utils.llm_utils", llm_utils_stub)

from backend.apps.ai.processing.preprocessor import _news_follow_up_repeats_prior_topic
from backend.apps.ai.processing.search_skill_reliability import (
    expand_companion_skills,
    require_first_explicit_skill_call,
)


def _message(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


# contract-test: supporting surface=gui.web assertions=web-search.surface-parity
def test_detects_repeated_named_topic_across_news_follow_up() -> None:
    assert _news_follow_up_repeats_prior_topic([
        _message("user", "latest anthropic and openai news?"),
        _message("assistant", "Recent AI news"),
        _message("user", "Search for recent articles about OpenAI safety incidents"),
    ]) is True


# contract-test: supporting surface=gui.web assertions=web-search.surface-parity
def test_does_not_treat_generic_search_words_as_topic_continuity() -> None:
    assert _news_follow_up_repeats_prior_topic([
        _message("user", "Search recent articles about OpenAI safety"),
        _message("assistant", "Recent AI news"),
        _message("user", "Search recent articles about cooking recipes"),
    ]) is False


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,web-search.surface-parity
def test_explicit_news_search_does_not_add_companion_skills() -> None:
    expanded = expand_companion_skills(
        {"news-search"},
        exact_request=True,
    )

    assert expanded == {"news-search"}


# contract-test: supporting surface=gui.web assertions=app-skills.execution.registered-validated,web-search.surface-parity
def test_explicit_news_search_requires_the_first_tool_call() -> None:
    assert require_first_explicit_skill_call(
        "auto",
        user_requested_skills_only=True,
        preselected_skills={"news-search"},
        total_skill_calls=0,
    ) == "required"

    assert require_first_explicit_skill_call(
        "auto",
        user_requested_skills_only=True,
        preselected_skills={"news-search"},
        total_skill_calls=1,
    ) == "auto"
