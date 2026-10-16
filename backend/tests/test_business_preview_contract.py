"""The existing financials preview is self-contained through its skill builder."""
from backend.apps.business.skills.company_financials import CompanyFinancialsSkill


# contract-test: supporting surface=gui.web assertions=app-skills.surface.semantic-parity
def test_company_financials_preview_preserves_queries_and_source():
    metadata = CompanyFinancialsSkill.resolve_preview_metadata({"companies": [{"query": "CALM"}, {"query": "MU"}]})
    assert metadata == {"provider": "SEC EDGAR", "providers": ["SEC EDGAR"], "query": "CALM, MU"}
