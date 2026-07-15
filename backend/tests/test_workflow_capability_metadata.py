# backend/tests/test_workflow_capability_metadata.py
#
# Contract tests for metadata-derived Workflow app-skill capability discovery.
# The registry must not maintain a central allowlist: registered app metadata
# controls eligibility, while absent or invalid Workflow classification fails
# closed with a stable reason.
#
# Spec: docs/specs/workflows-cli-runtime/spec.yml

from types import SimpleNamespace

from backend.core.api.app.services.workflow_capability_registry import (
    WORKFLOW_CLASSIFICATION_REQUIRED,
    WORKFLOW_TEST_EXAMPLE_REQUIRED,
    WorkflowCapabilityRegistry,
)


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


def test_unclassified_registered_skills_fail_closed_with_an_explicit_reason() -> None:
    registry = WorkflowCapabilityRegistry(
        FakeSkillRegistry({"web": SimpleNamespace(skills=[_skill("search", None)])})
    )

    capability = registry.get_capability("web.search")

    assert capability.enabled is False
    assert capability.reason == WORKFLOW_CLASSIFICATION_REQUIRED


def test_test_allowed_capability_requires_a_schema_valid_example_input() -> None:
    registry = WorkflowCapabilityRegistry(
        FakeSkillRegistry(
            {"news": SimpleNamespace(skills=[_skill("search", _workflow(example={"query": 3}))])}
        )
    )

    capability = registry.get_capability("news.search")

    assert capability.enabled is False
    assert capability.reason == WORKFLOW_TEST_EXAMPLE_REQUIRED
