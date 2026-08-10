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


def test_typed_step_and_trigger_templates_resolve_without_stringifying_exact_values() -> None:
    context = {
        "trigger": {"city": "Berlin"},
        "nodes": {"forecast": {"output": {"rain_probability": 70, "summary": "Rain likely"}}},
    }

    assert resolve_workflow_template("{{ steps.forecast.rain_probability }}", context) == 70
    assert resolve_workflow_template("Weather for {{ trigger.city }}", context) == "Weather for Berlin"


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
def test_arbitrary_code_attributes_and_unknown_filters_are_rejected(expression: str) -> None:
    with pytest.raises(WorkflowTemplateExpressionError):
        resolve_workflow_template(expression, {"nodes": {"forecast": {"output": {}}}})
