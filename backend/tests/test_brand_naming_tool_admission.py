# contract-test-file: supporting surface=cli assertions=brand-naming.flow
"""Regression for real finalist requests losing trademark tools in preprocessing."""
import pytest
from pathlib import Path
from types import SimpleNamespace

import yaml

from backend.apps.ai.processing.focus_mode_routing import (
    BRAND_NAMING_RESEARCH_SKILLS,
    brand_naming_research_skill_scope,
)


def scope(skills, *, focus="business-find_brand_name", exact=False, available=None):
    return brand_naming_research_skill_scope(
        active_focus_id=focus, preselected_skills=skills,
        available_skills=set(BRAND_NAMING_RESEARCH_SKILLS) if available is None else available,
        exact_request=exact,
    )


@pytest.mark.parametrize("selected", [{"hosting-search_domains", "web-search"},
                                      {"hosting-search_domains"}, {"business-search_trademarks"}])
# contract-test: supporting surface=cli assertions=brand-naming.flow
def test_finalist_research_offers_all_three_checks(selected):
    assert scope(selected) == set(BRAND_NAMING_RESEARCH_SKILLS)


@pytest.mark.parametrize("focus", [None, "web-research", "business-financial_analysis"])
# contract-test: supporting surface=cli assertions=brand-naming.flow
def test_inactive_or_other_focus_preserves_routing(focus):
    selected = {"hosting-search_domains", "web-search"}
    assert scope(selected, focus=focus) == selected


# contract-test: supporting surface=cli assertions=brand-naming.flow
def test_explicit_skill_selection_stays_exact():
    assert scope({"hosting-search_domains"}, exact=True) == {"hosting-search_domains"}


@pytest.mark.parametrize("selected", [None, set(), {"math-calculate"}])
# contract-test: supporting surface=cli assertions=brand-naming.flow
def test_intake_and_unrelated_requests_do_not_gain_research_tools(selected):
    assert scope(selected) == selected


# contract-test: supporting surface=cli assertions=brand-naming.flow
def test_missing_provider_skill_stays_excluded_and_input_is_not_mutated():
    selected = {"hosting-search_domains"}
    assert scope(selected, available={"hosting-search_domains", "web-search"}) == {
        "hosting-search_domains", "web-search",
    }
    assert selected == {"hosting-search_domains"}


# contract-test: supporting surface=cli assertions=brand-naming.flow
def test_admitted_skill_reaches_real_tool_generator_and_preserves_mate_scope():
    from backend.apps.ai.processing.tool_generator import generate_tools_from_apps
    from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition

    apps = {}
    for app_id, skill_id in [("business", "search_trademarks"),
                             ("hosting", "search_domains"), ("web", "search")]:
        data = yaml.safe_load((Path(__file__).parents[1] / "apps" / app_id / "app.yml").read_text())
        definition = next(item for item in data["skills"] if item["id"] == skill_id)
        apps[app_id] = SimpleNamespace(skills=[AppSkillDefinition.model_validate(definition)])

    admitted = scope({"hosting-search_domains", "web-search"})
    tools = generate_tools_from_apps(apps, preselected_skills=admitted)
    assert {tool["function"]["name"] for tool in tools} == set(BRAND_NAMING_RESEARCH_SKILLS)
    restricted = generate_tools_from_apps(apps, assigned_app_ids=["hosting", "web"],
                                         preselected_skills=admitted)
    assert {tool["function"]["name"] for tool in restricted} == {"hosting-search_domains", "web-search"}
