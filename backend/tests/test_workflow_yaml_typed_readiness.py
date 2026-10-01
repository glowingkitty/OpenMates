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
          providers: [luma, eventbrite]
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

    valid = validate_workflow_yaml(source.replace("[luma, eventbrite]", "[Luma, Eventbrite]"))
    assert valid.draft_valid is True
    assert valid.enable_ready is True
    assert valid.diagnostics == []


# contract-test: supporting surface=rest_api assertions=hosting-domains.surface-parity,hosting-domains.request.validated,workflows.control.typed-data,workflows.activation.reachable-side-effect
@pytest.mark.parametrize(("id_literal", "ready"), [("com", True), ("2", True), ("true", False)])
def test_hosting_two_group_ids_checks_and_chat_delivery_are_enable_ready(id_literal: str, ready: bool) -> None:
    result = validate_workflow_yaml(
        """
title: Hosting domain checks
start_when:
  manual: {}
steps:
  - id: domains
    use_app_skill: hosting.search_domains
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
    use_app_skill: hosting.search_domains
    input:
      requests:
        - query: example.com
          availability: available_only
          max_results: 1
  - id: empty
    check:
      left: $nodes.only.output.result_count
      op: eq
      right: 0
  - id: report
    send_chat_message:
      title: Hosting search fixture
      message: "Checked {{steps.domains.result_count}} selected domains."
""".replace("id: com", f"id: {id_literal}")
    )

    assert result.draft_valid is True
    assert result.enable_ready is ready
    if ready:
        assert result.diagnostics == []
    else:
        assert result.diagnostics[0].code == "WORKFLOW_NOT_READY"
        assert "expected integer/string, got boolean" in result.diagnostics[0].message
