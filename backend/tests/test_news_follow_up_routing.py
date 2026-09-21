"""Regression coverage for same-topic news follow-up routing."""

import ast
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

import pytest

from backend.apps.ai.processing.search_skill_reliability import expand_companion_skills


def _load_routing_functions():
    """Load pure routing logic without stubbing shared provider modules.

    Importing the full preprocessor requires worker services. Compile the actual
    function and constant definitions so these unit tests remain isolated from
    other tests' provider mocks and never replace entries in sys.modules.
    """
    source = Path(__file__).resolve().parents[1] / "apps/ai/processing/preprocessor.py"
    names = {
        "_news_follow_up_repeats_prior_topic", "_normalize_topic_area",
        "_normalize_task_area", "_resolve_category_from_topic_area",
        "USER_ROLE", "TOPIC_CONTINUITY_STOP_WORDS", "ONBOARDING_SUPPORT_CATEGORY",
        "SOFTWARE_DEVELOPMENT_CATEGORY", "SAME_TOPIC_SHIFT_VALUES",
        "FOLLOW_UP_CONTINUITY_TOPIC_AREAS", "TOPIC_AREA_DESCRIPTIONS",
        "TOPIC_AREA_TO_MATE_CATEGORY",
    }
    nodes = []
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.FunctionDef):
            defined = {node.name}
        elif isinstance(node, ast.Assign):
            defined = {target.id for target in node.targets if isinstance(target, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined = {node.target.id}
        else:
            continue
        if defined & names:
            nodes.append(node)
    namespace = {"re": re, "Any": Any, "Dict": Dict, "List": List, "Optional": Optional}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


_routing = _load_routing_functions()
_news_follow_up_repeats_prior_topic = _routing["_news_follow_up_repeats_prior_topic"]
_resolve_category_from_topic_area = _routing["_resolve_category_from_topic_area"]


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


# contract-test: supporting surface=gui.web assertions=web-search.surface-parity
@pytest.mark.parametrize("topic_area", [None, "news-search", "unknown_topic"])
@pytest.mark.parametrize("topic_shift", ["same_topic", "unclear", "noticeable_shift"])
def test_invalid_topic_keeps_last_valid_mate(topic_area, topic_shift):
    assert _resolve_category_from_topic_area(
        raw_topic_area=topic_area, raw_topic_shift=topic_shift,
        previous_category="software_development",
        available_category_ids={"software_development", "cooking_food"},
    ) == "software_development"


# contract-test: supporting surface=gui.web assertions=web-search.surface-parity
@pytest.mark.parametrize("previous,shift", [
    ("not_a_mate", "same_topic"), ("software_development", "noticeable_shift"),
])
def test_valid_new_topic_can_select_different_mate(previous, shift):
    assert _resolve_category_from_topic_area(
        raw_topic_area="cooking_food", raw_topic_shift=shift,
        previous_category=previous,
        available_category_ids={"software_development", "cooking_food"},
    ) == "cooking_food"
