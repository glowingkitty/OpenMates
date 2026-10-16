from backend.apps.ai.utils.app_skill_result_groups import is_request_group_failure, maps_result_parent_metadata


# contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering,maps-search.provider.budget-and-cache
def test_quota_result_keeps_parent_error_and_request_provider():
    group = {"results": [], "provider": "Geoapify", "status": "quota_exhausted", "error": "Daily allowance exhausted"}
    assert not is_request_group_failure("maps", "search", group)
    assert maps_result_parent_metadata(group) == {
        "provider": "Geoapify", "error": "Daily allowance exhausted", "search_status": "quota_exhausted",
    }


# contract-test: supporting surface=gui.web assertions=maps-search.gui.place-rendering
def test_validation_failure_retains_error_flow_and_success_keeps_warnings():
    assert is_request_group_failure("maps", "search", {"results": [], "status": "invalid_request", "error": "Invalid area"})
    assert not is_request_group_failure("maps", "search", {"results": []})
    group = {"results": [], "provider": "Geoapify", "warnings": ["No verified matches"], "filter_summary": {"status": "no_verified_results"}}
    metadata = maps_result_parent_metadata(group)
    assert metadata["warnings"] == group["warnings"] and metadata["filter_summary"] == group["filter_summary"]
    assert "results" not in metadata


# contract-test: supporting surface=rest_api assertions=maps-search.compatibility.regular-search
def test_other_skills_keep_their_existing_failure_semantics():
    assert is_request_group_failure("web", "search", {"results": [], "error": "Provider failed"})
    assert not is_request_group_failure("web", "search", {"results": []})
    assert not is_request_group_failure("hosting", "search_domains", {"results": [], "error": "Quota reached"})
