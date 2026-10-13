# contract-test-file: supporting surface=cli assertions=trademarks.parity,trademarks.coverage,trademarks.evidence
"""Protect the trademark values advertised to downstream Workflow nodes."""
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from backend.apps.business.skills.search_trademarks import TrademarkSearchResponse
from backend.core.api.app.services.workflow_app_skill_adapter import _normalize_skill_output


@pytest.mark.parametrize("state", ["partial", "zero", "unsupported"])
# contract-test: supporting surface=cli assertions=trademarks.parity,trademarks.coverage,trademarks.evidence
def test_declared_trademark_workflow_fields_remain_typed_and_preserve_coverage(state):
    matches = [{"query": "ADIDAS", "mark": "ADIDAS", "region": "US",
                "application_number": "72318279", "nice_classes": [25],
                "source_url": "https://tsdr.uspto.gov/#caseNumber=72318279"}] if state == "partial" else []
    coverage = ([{"query": "ADIDAS", "region": "US", "status": "searched",
                  "returned_count": len(matches), "total_matches": len(matches),
                  "checked_at": "2026-10-13T00:00:00Z"}] if state != "unsupported" else [])
    if state != "zero":
        coverage.append({"query": "ADIDAS", "region": "DE", "status": "unsupported",
                         "source_url": "https://register.dpma.de/DPMAregister/marke/uebersicht"})
    raw = TrademarkSearchResponse(
        success=state != "unsupported", status="error" if state == "unsupported" else "finished",
        query="ADIDAS", regions=[row["region"] for row in coverage], nice_classes=[25],
        match="exact", matches=matches, result_count=len(matches), coverage=coverage,
        partial=state != "zero", error="No requested region could be searched" if state == "unsupported" else None,
    ).model_dump()
    original = deepcopy(raw)
    output = _normalize_skill_output("business", "search_trademarks", {}, raw)
    metadata = yaml.safe_load((Path(__file__).parents[1] / "apps/business/app.yml").read_text())
    skill = next(item for item in metadata["skills"] if item["id"] == "search_trademarks")
    Draft202012Validator(skill["workflow"]["output_schema"]).validate(output)
    for field in ("result_count", "matches", "coverage", "regions", "nice_classes",
                  "status_filter", "match", "partial", "limitation"):
        assert output[field] == raw[field]
    assert output["raw"] == original
    assert raw == original
    assert "results" not in output, "Whole-response trademark evidence must not become per-record results"
    assert "legal availability" in output["limitation"]
    if state == "unsupported":
        assert output["error"] and output["raw"]["success"] is False
        assert output["coverage"][0]["status"] == "unsupported"
    elif state == "zero":
        assert output["result_count"] == 0 and output["raw"]["success"] is True
        assert "error" not in output and output["coverage"][0]["status"] == "searched"
