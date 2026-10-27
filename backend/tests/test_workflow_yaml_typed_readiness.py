"""CLI YAML readiness shares the execution model's typed app contract."""

import pytest

from backend.core.api.app.services.workflow_yaml_compiler import validate_workflow_yaml


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract,workflows.control.typed-data,workflows.activation.reachable-side-effect
def test_invalid_event_provider_enum_is_editable_but_not_ready():
    source = """
title: Upcoming events
start_when:
  manual: {}
steps:
  - id: events
    use_app_skill: events.search
    input:
      requests:
        - query: AI
          location: Berlin
          providers: [PRETALX]
          conference: 39C3
  - id: report
    send_chat_message:
      title: Upcoming events
      message: "Upcoming events: {{steps.events.results}}"
      blocks:
        - id: events
          source: $nodes.events.output.results
"""
    invalid = validate_workflow_yaml(source)
    assert invalid.draft_valid is True
    assert invalid.graph is not None
    assert invalid.enable_ready is False
    assert invalid.diagnostics[0].code == "WORKFLOW_NOT_READY"
    assert "providers" in invalid.diagnostics[0].message
    assert "allowed value" in invalid.diagnostics[0].message

    valid = validate_workflow_yaml(source.replace("[PRETALX]", "[pretalx]"))
    assert valid.draft_valid is True
    assert valid.enable_ready is True
    assert valid.diagnostics == []


# contract-test: supporting surface=rest_api assertions=workflows.control.typed-data,workflows.activation.reachable-side-effect
@pytest.mark.parametrize(("id_literal", "ready"), [("com", True), ("2", True), ("true", False)])
def test_isolated_group_ids_checks_and_chat_delivery_are_enable_ready(id_literal: str, ready: bool, monkeypatch) -> None:
    from backend.core.api.app.services import workflow_capability_registry
    registry = _AvailableGroupedLookup()
    # The YAML entrypoint and final graph preflight each resolve a registry.
    # Bind both to this isolated fixture without changing runtime classifications.
    monkeypatch.setattr(workflow_capability_registry, "WorkflowCapabilityRegistry", lambda: registry)
    result = validate_workflow_yaml(
        """
title: Synthetic grouped lookup
start_when:
  manual: {}
steps:
  - id: domains
    use_app_skill: example.lookup
    input:
      requests:
        - id: com
          query: example.com
          max_results: 1
        - id: net
          query: example.net
          max_results: 1
  - id: count
    check:
      left: $nodes.domains.output.result_count
      op: eq
      right: 2
  - id: only
    use_app_skill: example.lookup
    input:
      requests:
        - query: example.com
          sort: relevance
          max_results: 1
  - id: empty
    check:
      left: $nodes.only.output.result_count
      op: eq
      right: 0
  - id: report
    send_chat_message:
      title: Synthetic grouped results
      message: "Checked {{steps.domains.result_count}} selected domains."
""".replace("id: com", f"id: {id_literal}"),
        capability_registry=registry,
    )

    assert result.draft_valid is True
    assert result.enable_ready is ready, result.diagnostics
    if ready:
        assert result.diagnostics == []
    else:
        assert result.diagnostics[0].code == "WORKFLOW_NOT_READY"
        assert "expected integer/string, got boolean" in result.diagnostics[0].message


class _AvailableGroupedLookup:
    """An isolated typed capability, without claiming a live provider exists."""

    def get_capability(self, identifier):
        from backend.core.api.app.services.workflow_models import WorkflowCapability
        assert identifier == "example.lookup"
        return WorkflowCapability(type="app_skill", id=identifier, title="Synthetic grouped lookup", metadata={
            "input_schema": {"type": "object", "required": ["requests"], "properties": {
                "requests": {"type": "array", "items": {"type": "object", "required": ["query"],
                    "properties": {"id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                        "query": {"type": "string"}, "max_results": {"type": "integer"},
                        "sort": {"type": "string", "enum": ["relevance"]}}}},
            }},
            "output_schema": {"type": "object", "properties": {"result_count": {"type": "integer"},
                "results": {"type": "array", "items": {"type": "object"}}}},
        })


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_source_free_hosting_workflow_is_editable_and_unavailable():
    result = validate_workflow_yaml("""
title: Unavailable domain lookup
start_when:
  manual: {}
steps:
  - id: domains
    use_app_skill: hosting.search_domains
    input:
      requests:
        - id: first
          query: example.com
  - id: report
    send_chat_message:
      title: Domain lookup
      message: "Results: {{steps.domains.results}}"
""")
    assert result.draft_valid is True
    assert result.enable_ready is False
    assert result.diagnostics[0].code == "WORKFLOW_CAPABILITY_UNAVAILABLE"
    assert "hosting.search_domains" in result.diagnostics[0].message
