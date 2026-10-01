# backend/tests/test_workflow_capability_metadata.py
#
# Contract tests for metadata-derived Workflow app-skill capability discovery.
# The registry must not maintain a central allowlist: registered app metadata
# controls eligibility, while absent or invalid Workflow classification fails
# closed with a stable reason.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from types import SimpleNamespace
import os

import pytest

from backend.core.api.app.services import workflow_capability_registry as capability_module

from backend.core.api.app.services.workflow_capability_registry import (
    WORKFLOW_CLASSIFICATION_REQUIRED,
    WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
    WORKFLOW_CONNECTED_ACCOUNT_REQUIRED,
    WORKFLOW_RUNTIME_UNSUPPORTED,
    WORKFLOW_TEST_EXAMPLE_REQUIRED,
    WorkflowCapabilityRegistry,
    _FilesystemWorkflowMetadataRegistry,
    _matches_schema,
)
from scripts.audit_workflow_capabilities import audit_workflow_capabilities


class FakeSkillRegistry:
    def __init__(self, metadata: dict[str, SimpleNamespace]) -> None:
        self.metadata = metadata

    def all_metadata(self) -> dict[str, SimpleNamespace]:
        return self.metadata

    def get_metadata(self, app_id: str) -> SimpleNamespace | None:
        return self.metadata.get(app_id)

    def is_skill_available(self, app_id: str, skill_id: str) -> bool:
        return any(
            skill.id == skill_id
            for skill in self.metadata.get(app_id, SimpleNamespace(skills=[])).skills
        )


def _skill(skill_id: str, workflow: dict | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=skill_id,
        class_path="backend.apps.example.Skill",
        internal=False,
        pricing=SimpleNamespace(model_dump=lambda mode: {"fixed": 1}),
        tool_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        workflow=workflow,
    )


def _workflow(*, example: dict | None = None) -> dict:
    return {
        "available": True,
        "execution_mode": "sync",
        "effect": "read",
        "unattended": True,
        "test_allowed": True,
        "test_example_input": example or {"query": "OpenMates"},
        "output_schema": {"type": "object", "properties": {"summary": {"type": "string"}}},
        "approval": "never",
        "binding_requirements": ["none"],
    }


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_capabilities_are_discovered_from_registered_metadata_not_a_skill_allowlist() -> None:
    metadata = {
        "library": SimpleNamespace(skills=[_skill("lookup", _workflow())]),
        "web": SimpleNamespace(skills=[_skill("search", _workflow())]),
        "weather": SimpleNamespace(skills=[_skill("forecast", _workflow())]),
        "news": SimpleNamespace(skills=[_skill("search", _workflow())]),
        "events": SimpleNamespace(skills=[_skill("search", _workflow())]),
        "ai": SimpleNamespace(skills=[_skill("ask", _workflow())]),
    }

    capabilities = WorkflowCapabilityRegistry(FakeSkillRegistry(metadata)).list_capabilities()

    by_id = {capability.id: capability for capability in capabilities}
    assert set(by_id) == {
        "ai.ask",
        "events.search",
        "library.lookup",
        "news.search",
        "weather.forecast",
        "web.search",
    }
    assert by_id["library.lookup"].enabled is True
    assert by_id["library.lookup"].metadata["input_schema"]["required"] == ["query"]
    assert by_id["library.lookup"].metadata["output_schema"]["type"] == "object"
    assert by_id["library.lookup"].metadata["cost"] == {"fixed": 1}
    assert by_id["library.lookup"].metadata["workflow"]["effect"] == "read"


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_unclassified_registered_skills_fail_closed_with_an_explicit_reason() -> None:
    registry = WorkflowCapabilityRegistry(
        FakeSkillRegistry({"web": SimpleNamespace(skills=[_skill("search", None)])})
    )

    capability = registry.get_capability("web.search")

    assert capability.enabled is False
    assert capability.reason == WORKFLOW_CLASSIFICATION_REQUIRED


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
@pytest.mark.parametrize("unsafe_policy", [
    {"execution_mode": "async_job"}, {"execution_mode": "sandbox"},
    {"approval": "always"}, {"unattended": False},
])
def test_incomplete_job_or_approval_lifecycle_cannot_enable_a_workflow_skill(unsafe_policy: dict) -> None:
    policy = {**_workflow(), **unsafe_policy}
    registry = WorkflowCapabilityRegistry(FakeSkillRegistry({
        "example": SimpleNamespace(skills=[_skill("unsafe", policy)])
    }))
    capability = registry.get_capability("example.unsafe")
    assert capability.enabled is False
    assert capability.reason == WORKFLOW_RUNTIME_UNSUPPORTED
    assert capability.metadata["workflow"] == policy


@pytest.mark.parametrize("capability_id", ["social_media.search", "social_media.get-posts"])
# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_queued_social_media_skills_are_classified_as_jobs_and_unavailable(capability_id: str) -> None:
    capability = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).get_capability(capability_id)
    assert capability.metadata["workflow"]["execution_mode"] == "async_job"
    assert capability.enabled is False
    assert capability.reason == WORKFLOW_RUNTIME_UNSUPPORTED


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_test_allowed_capability_requires_a_schema_valid_example_input() -> None:
    registry = WorkflowCapabilityRegistry(
        FakeSkillRegistry(
            {"news": SimpleNamespace(skills=[_skill("search", _workflow(example={"query": 3}))])}
        )
    )

    capability = registry.get_capability("news.search")

    assert capability.enabled is False
    assert capability.reason == WORKFLOW_TEST_EXAMPLE_REQUIRED


# contract-test: supporting surface=rest_api assertions=hosting-domains.surface-parity,hosting-domains.request.validated
def test_hosting_capability_has_typed_workflow_contract_and_google_safe_ids() -> None:
    capability = WorkflowCapabilityRegistry(_FilesystemWorkflowMetadataRegistry()).get_capability(
        "hosting.search_domains"
    )
    assert capability.enabled is True
    assert capability.metadata["cost"] == {"fixed": 1}
    workflow = capability.metadata["workflow"]
    assert {key: workflow[key] for key in (
        "execution_mode", "effect", "unattended", "approval", "binding_requirements", "test_allowed",
    )} == {
        "execution_mode": "sync", "effect": "read", "unattended": True,
        "approval": "never", "binding_requirements": ["none"], "test_allowed": True,
    }
    assert workflow["test_example_input"] == {"requests": [{"query": "example.com", "max_results": 1}]}
    fields = capability.metadata["input_schema"]["properties"]["requests"]["items"]["properties"]
    assert "anyOf" in fields["id"] and "oneOf" not in fields["id"]
    assert all(_matches_schema(value, fields["id"]) for value in ("com", 2))
    assert not any(_matches_schema(value, fields["id"]) for value in (True, [], None))
    assert fields["availability"]["default"] == "prefer_available"
    assert fields["max_results"]["maximum"] == 20
    output = capability.metadata["output_schema"]["properties"]
    assert output["results"]["type"] == "array"
    assert output["raw"]["properties"]["results"]["items"]["properties"]["checked_results"]["type"] == "array"


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_runtime_date_example_is_resolved_for_validation_and_preserved_in_metadata() -> None:
    today = {"$date": "today", "format": "date"}
    weather_skill = _skill(
        "forecast",
        _workflow(
            example={"location": "Berlin", "start_date": today, "end_date": today}
        ),
    )
    weather_skill.tool_schema = {
        "type": "object",
        "properties": {
            "location": {"type": "string"},
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
        },
        "required": ["location"],
    }
    registry = WorkflowCapabilityRegistry(
        FakeSkillRegistry({"weather": SimpleNamespace(skills=[weather_skill])})
    )

    capability = registry.get_capability("weather.forecast")

    assert capability.enabled is True
    assert capability.metadata["workflow"]["test_example_input"]["start_date"] == today
    assert capability.metadata["workflow"]["test_example_input"]["end_date"] == today

    weather_skill.workflow["test_example_input"]["start_date"] = {
        "$date": "unsupported_date",
        "format": "date",
    }
    invalid_capability = registry.get_capability("weather.forecast")
    assert invalid_capability.enabled is False
    assert invalid_capability.reason == WORKFLOW_TEST_EXAMPLE_REQUIRED


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_unavailable_capability_accepts_stable_deferred_reason() -> None:
    registry = WorkflowCapabilityRegistry(
        FakeSkillRegistry(
            {
                "tasks": SimpleNamespace(
                    skills=[
                        _skill(
                            "search",
                            {
                                "available": False,
                                "unavailable_reason": WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
                            },
                        )
                    ]
                )
            }
        )
    )

    capability = registry.get_capability("tasks.search")

    assert capability.enabled is False
    assert capability.reason == WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_repository_public_skills_have_workflow_classification() -> None:
    issues = audit_workflow_capabilities()

    assert [issue.as_dict() for issue in issues] == []


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_repository_expanded_capabilities_and_deferred_reasons_are_discoverable() -> None:
    registry = WorkflowCapabilityRegistry()

    by_id = {capability.id: capability for capability in registry.list_capabilities()}

    assert by_id["math.calculate"].enabled is True
    assert by_id["math.calculate"].metadata["workflow"]["effect"] == "compute"
    assert by_id["web.read"].enabled is True
    assert by_id["web.read"].metadata["workflow_source"] == "workflow_capabilities.yml"
    assert by_id["tasks.search"].enabled is False
    assert by_id["tasks.search"].reason == WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED
    assert by_id["calendar.get-events"].enabled is False
    assert by_id["calendar.get-events"].reason == WORKFLOW_CONNECTED_ACCOUNT_REQUIRED
    assert by_id["code.run"].enabled is False
    assert by_id["code.run"].reason == WORKFLOW_RUNTIME_UNSUPPORTED


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_filesystem_metadata_cache_reuses_snapshot_and_invalidates_on_source_change(tmp_path) -> None:
    app_file = tmp_path / "example" / "app.yml"
    app_file.parent.mkdir()
    app_file.write_text("id: example\nskills: []\n", encoding="utf-8")
    first = _FilesystemWorkflowMetadataRegistry(tmp_path)
    second = _FilesystemWorkflowMetadataRegistry(tmp_path)
    assert first.all_metadata() is second.all_metadata()

    app_file.write_text("id: example\nskills:\n  - id: new\n    class_path: example.New\n", encoding="utf-8")
    os.utime(app_file, None)
    updated = _FilesystemWorkflowMetadataRegistry(tmp_path)
    assert updated.all_metadata() is not first.all_metadata()
    assert updated.is_skill_available("example", "new")


# contract-test: supporting surface=rest_api assertions=workflows.actions.skill-contract
def test_classification_cache_invalidates_on_source_change(tmp_path, monkeypatch) -> None:
    source = tmp_path / "workflow_capabilities.yml"
    monkeypatch.setattr(capability_module, "WORKFLOW_CLASSIFICATION_FILE", source)
    source.write_text("capabilities:\n  example.one:\n    available: false\n", encoding="utf-8")
    first = capability_module._load_workflow_classifications()
    assert capability_module._load_workflow_classifications() is first
    source.write_text("capabilities:\n  example.two:\n    available: false\n", encoding="utf-8")
    os.utime(source, None)
    assert "example.two" in capability_module._load_workflow_classifications()
