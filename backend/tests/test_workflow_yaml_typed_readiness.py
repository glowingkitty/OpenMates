"""CLI YAML readiness shares the execution model's typed app contract."""

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
