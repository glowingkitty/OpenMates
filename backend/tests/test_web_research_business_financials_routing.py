"""Web Research routing contract for Business company financials.

This protects the spec gate that allows Web Research to mention the Business
company-financials skill only after the real public example chat is approved.
It is deterministic metadata coverage: no LLM call is needed to prove that the
focus-mode routing prompt exposes the right positive and negative boundaries.
"""

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
BUSINESS_APP = REPO_ROOT / "backend/apps/business/app.yml"
WEB_APP = REPO_ROOT / "backend/apps/web/app.yml"


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _skill(config: dict, skill_id: str) -> dict:
    return next(skill for skill in config["skills"] if skill["id"] == skill_id)


def _focus(config: dict, focus_id: str) -> dict:
    return next(focus for focus in config["focuses"] if focus["id"] == focus_id)


def test_web_research_mentions_company_financials_only_after_business_skill_exists() -> None:
    business = _load_yaml(BUSINESS_APP)
    web = _load_yaml(WEB_APP)
    company_financials = _skill(business, "company_financials")
    research_hint = _focus(web, "research")["preprocessor_hint"].lower()

    assert company_financials["workflow"]["available"] is True
    assert company_financials["providers"] == [{"name": "SEC EDGAR", "no_api_key": True}]
    assert "business.company_financials" in research_hint
    assert "sec edgar" in research_hint


def test_web_research_routes_explicit_public_company_financials_to_business_skill() -> None:
    web = _load_yaml(WEB_APP)
    research_hint = _focus(web, "research")["preprocessor_hint"].lower()

    positive_terms = [
        "explicit public compan",
        "ticker",
        "cik",
        "revenue",
        "net income",
        "cash flow",
        "balance sheet",
        "filing",
    ]
    for term in positive_terms:
        assert term in research_hint


def test_web_research_excludes_discovery_private_company_and_investment_advice() -> None:
    web = _load_yaml(WEB_APP)
    research_hint = _focus(web, "research")["preprocessor_hint"].lower()

    negative_terms = [
        "private compan",
        "company discovery",
        "category discovery",
        "investment advice",
        "stock-price forecast",
        "buy/sell",
    ]
    for term in negative_terms:
        assert term in research_hint
