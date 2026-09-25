# backend/tests/test_workflow_template_expressions.py
#
# Safe Workflow template-expression contracts for typed step outputs and
# deterministic date/time calculations.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from datetime import datetime, timezone

import pytest

from backend.core.api.app.services.workflow_template_expressions import (
    WorkflowTemplateExpressionError,
    resolve_workflow_template,
)


# contract-test: supporting surface=rest_api assertions=workflows.control.typed-data,workflows.message.standard
def test_typed_step_and_trigger_templates_resolve_without_stringifying_exact_values() -> None:
    context = {
        "trigger": {"city": "Berlin"},
        "nodes": {"forecast": {"output": {"rain_probability": 70, "summary": "Rain likely"}}},
    }

    assert resolve_workflow_template("{{ steps.forecast.rain_probability }}", context) == 70
    assert resolve_workflow_template("Weather for {{ trigger.city }}", context) == "Weather for Berlin"


# contract-test: supporting surface=rest_api assertions=workflows.control.typed-data,workflows.message.standard
def test_list_item_fields_are_projected_for_direct_and_template_references() -> None:
    context = {
        "nodes": {
            "events": {
                "output": {
                    "results": [
                        {"title": "AI Meetup", "venue": {"city": "Berlin"}},
                        {"title": "Design Night", "venue": {"city": "Hamburg"}},
                        {"title": "Founders Talk", "venue": {"city": "Munich"}},
                    ]
                }
            }
        }
    }

    assert resolve_workflow_template("$nodes.events.output.results.title", context) == [
        "AI Meetup",
        "Design Night",
        "Founders Talk",
    ]
    assert resolve_workflow_template("{{steps.events.results.title}}", context) == [
        "AI Meetup",
        "Design Night",
        "Founders Talk",
    ]
    assert resolve_workflow_template("{{ steps.events.results.venue.city }}", context) == [
        "Berlin",
        "Hamburg",
        "Munich",
    ]
    assert resolve_workflow_template("$nodes.events.output.results", context) == context["nodes"]["events"]["output"]["results"]


# contract-test: supporting surface=rest_api assertions=workflows.control.typed-data
def test_invalid_list_item_path_preserves_missing_path_semantics_per_item() -> None:
    context = {"nodes": {"events": {"output": {"results": [{"title": "AI Meetup"}, {}]}}}}

    assert resolve_workflow_template("$nodes.events.output.results.missing", context) == [None, None]
    assert resolve_workflow_template("{{steps.events.results.missing}}", context) == [None, None]


# contract-test: supporting surface=rest_api assertions=workflows.control.typed-data
def test_clock_now_and_date_filters_are_deterministic() -> None:
    now = datetime(2026, 7, 13, 7, 30, tzinfo=timezone.utc)

    assert resolve_workflow_template("{{ clock.now }}", {}, now=now) == "2026-07-13T07:30:00Z"
    assert resolve_workflow_template("{{ clock.now | plus_hours: 2 }}", {}, now=now) == "2026-07-13T09:30:00Z"
    assert resolve_workflow_template("{{ clock.now | plus_days: 1 }}", {}, now=now) == "2026-07-14T07:30:00Z"


@pytest.mark.parametrize(
    "expression",
    [
        "{{ __import__('os').system('id') }}",
        "{{ steps.forecast.__class__ }}",
        "{{ clock.now | eval: 1 }}",
    ],
)
# contract-test: supporting surface=rest_api assertions=workflows.control.typed-data
def test_arbitrary_code_attributes_and_unknown_filters_are_rejected(expression: str) -> None:
    with pytest.raises(WorkflowTemplateExpressionError):
        resolve_workflow_template(expression, {"nodes": {"forecast": {"output": {}}}})
