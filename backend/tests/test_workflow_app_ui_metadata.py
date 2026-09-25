from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry,
    _FilesystemWorkflowMetadataRegistry,
)
from backend.core.api.app.services.workflow_app_skill_adapter import (
    WORKFLOW_PASSTHROUGH_FIELDS,
    WORKFLOW_RESULT_LIST_SKILLS,
)


def _property_paths(schema: object, prefix: str = ""):
    if not isinstance(schema, dict):
        return
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return

    for name, field in properties.items():
        path = f"{prefix}.{name}" if prefix else name
        yield path, field
        yield from _property_paths(field, path)
        if isinstance(field, dict):
            yield from _property_paths(field.get("items"), f"{path}[]")


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_workflow_available_skills_explicitly_classify_all_ui_fields() -> None:
    missing: list[str] = []
    invalid: list[str] = []
    relevance_not_basic: list[str] = []

    capabilities = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).list_capabilities()
    enabled = [capability for capability in capabilities if capability.enabled]
    assert len(enabled) == 40
    fallback_result_capabilities = {
        capability.id
        for capability in enabled
        if capability.metadata["workflow_source"] == "workflow_capabilities.yml"
        and "results" in capability.metadata["output_schema"].get("properties", {})
    }
    normalized_result_capabilities = {
        f"{app_id}.{skill_id}" for app_id, skill_id in WORKFLOW_RESULT_LIST_SKILLS
    }
    assert fallback_result_capabilities <= normalized_result_capabilities
    assert {"business.company_financials", "web.search"} <= normalized_result_capabilities

    for capability in enabled:
        schemas = {
            "input": capability.metadata.get("input_schema"),
            "output": capability.metadata.get("output_schema"),
        }
        for side, schema in schemas.items():
            for field_path, field in _property_paths(schema):
                basic = (field.get("x-ui") or {}).get("basic") if isinstance(field, dict) else None
                reference = f"{capability.id} {side}.{field_path}"
                if basic is None:
                    missing.append(reference)
                elif not isinstance(basic, bool):
                    invalid.append(reference)
                if side == "input" and field_path.endswith("relevance_criteria") and basic is not True:
                    relevance_not_basic.append(reference)

    assert not missing, "Missing explicit x-ui.basic metadata:\n" + "\n".join(missing)
    assert not invalid, "x-ui.basic must be a boolean:\n" + "\n".join(invalid)
    assert not relevance_not_basic, "Natural-language relevance criteria must be basic:\n" + "\n".join(relevance_not_basic)


def _normalized_output_fields(capability_id: str) -> set[str]:
    app_id, skill_id = capability_id.split(".", 1)
    common = {"app_id", "skill_id", "raw", "error"}
    if capability_id == "ai.ask":
        return common | {"answer", "summary"}
    if capability_id == "weather.forecast":
        return common | {
            "summary", "location", "provider", "days_requested", "start_date", "end_date",
            "rain_probability", "max_temperature_c", "humidity_avg_pct", "forecast_day",
            "forecast_days", "results", "result_count", "hourly", "rain_periods",
            "rain_expected", "rain_summary",
        }
    if capability_id in {"news.search", "events.search", "home.search"}:
        alias = {"news.search": "articles", "events.search": "events", "home.search": "listings"}[capability_id]
        return common | {"summary", "queries", "results", alias, "result_count", "provider", "warnings", "partial"}

    fields = common | {"summary", "result_count", "provider", "artifact_ids", "task_ids"}
    if (app_id, skill_id) in WORKFLOW_RESULT_LIST_SKILLS:
        fields.add("results")
    fields.update(WORKFLOW_PASSTHROUGH_FIELDS.get((app_id, skill_id), ()))
    return fields


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_all_enabled_output_schema_fields_are_emitted_by_the_normalizer_contract() -> None:
    capabilities = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).list_capabilities()
    mismatches: list[str] = []
    for capability in capabilities:
        if not capability.enabled:
            continue
        declared = set(capability.metadata["output_schema"].get("properties", {}))
        missing = declared - _normalized_output_fields(capability.id)
        if missing:
            mismatches.append(f"{capability.id}: {', '.join(sorted(missing))}")

    assert not mismatches, "Output schema fields missing from normalizer contract:\n" + "\n".join(mismatches)


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_event_search_keeps_date_range_and_event_type_advanced() -> None:
    capability = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).get_capability(
        "events.search"
    )
    assert capability.metadata["cost"]["per_unit"]["credits"] == 30
    fields = capability.metadata["input_schema"]["properties"]["requests"]["items"]["properties"]
    for name in ("query", "location", "relevance_criteria"):
        assert fields[name]["x-ui"]["basic"] is True
    for name in ("start_date", "end_date", "event_type"):
        assert fields[name]["x-ui"]["basic"] is False


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_travel_connection_output_schema_matches_normalized_result_contract() -> None:
    capability = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).get_capability(
        "travel.search_connections"
    )
    output_properties = capability.metadata["output_schema"]["properties"]
    result_properties = output_properties["results"]["items"]["properties"]

    assert output_properties["results"]["x-ui"]["basic"] is True
    assert {
        name for name, field in result_properties.items() if field["x-ui"]["basic"] is True
    } == {
        "origin",
        "destination",
        "departure",
        "arrival",
        "duration",
        "total_price",
        "currency",
        "transport_method",
        "booking_url",
    }
    assert {
        name for name, field in result_properties.items() if field["x-ui"]["basic"] is False
    } == {
        "source_provider",
        "provider",
        "trip_type",
        "stops",
        "carriers",
        "booking_provider",
        "bookable_seats",
        "last_ticketing_date",
        "co2_kg",
    }


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_fallback_result_lists_are_typed_only_for_stable_result_contracts() -> None:
    capabilities = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).list_capabilities()
    fallback_results = {
        capability.id: capability.metadata["output_schema"]["properties"]["results"]["items"]
        for capability in capabilities
        if capability.enabled
        and capability.metadata["workflow_source"] == "workflow_capabilities.yml"
        and "results" in capability.metadata["output_schema"].get("properties", {})
    }
    typed = {capability_id for capability_id, items in fallback_results.items() if items.get("properties")}
    generic = set(fallback_results) - typed

    assert typed == {
        "code.search_repos",
        "design.search_icons",
        "electronics.search_components",
        "fitness.search_classes",
        "fitness.search_locations",
        "health.search_appointments",
        "images.search",
        "maps.search",
        "models3d.search",
        "nutrition.search_recipes",
        "shopping.search_products",
        "social_media.get-posts",
        "social_media.search",
        "travel.search_connections",
        "travel.search_stays",
        "videos.search",
    }
    assert generic == {
        "code.get_docs",
        "openmates.get-docs",
        "travel.get_flight",
        "videos.get_transcript",
        "weather.rain_radar",
        "web.read",
    }
