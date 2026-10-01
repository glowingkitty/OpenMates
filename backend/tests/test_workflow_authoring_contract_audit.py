"""Offline audit regressions; never invoke providers or persist workflows."""
# contract-test-file: infrastructure

from types import SimpleNamespace

import pytest

from backend.core.api.app.services.workflow_capability_registry import (
    WorkflowCapabilityRegistry, _FilesystemWorkflowMetadataRegistry,
)
from backend.scripts.audit_workflow_authoring_contracts import audit_authoring_contracts


def test_all_enabled_skills_have_compilable_examples_and_output_references():
    registry = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry())
    enabled = [capability for capability in registry.list_capabilities() if capability.enabled]

    result = audit_authoring_contracts(registry)

    assert result["issues"] == []
    assert result["checked_ids"] == [capability.id for capability in enabled]
    assert result["checked_output_references"] == sum(
        len(capability.metadata["output_schema"]["properties"]) for capability in enabled
    )
    assert result["checked_input_rejections"] == len(enabled)
    assert result["checked_unknown_output_rejections"] == len(enabled)


@pytest.mark.parametrize("invalid_part", ["example", "schema"])
def test_audit_reports_invalid_contract_without_leaking_example_values(invalid_part):
    capability = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).get_capability(
        "weather.forecast"
    ).model_copy(deep=True)
    if invalid_part == "example":
        capability.metadata["workflow"]["test_example_input"] = {"location": ["private input"]}
    else:
        capability.metadata["output_schema"] = {"type": "invalid-private-schema"}
    registry = SimpleNamespace(list_capabilities=lambda: [capability])

    result = audit_authoring_contracts(registry)

    assert result["issues"] == [{
        "capability_id": "weather.forecast", "code": "INVALID_CONTRACT_OR_EXAMPLE", "field": None,
    }]
    assert "private" not in str(result)
