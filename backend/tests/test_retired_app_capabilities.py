"""Retired execution stays out of discovery while saved schemas remain usable."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml

from backend.core.api.app.routes import apps, apps_api
from backend.core.api.app.services.feature_availability_service import (
    FeatureAvailabilityService,
    collect_feature_definitions_from_app_config,
)
from backend.core.api.app.services.skill_registry import filter_app_components_by_availability
from backend.shared.python_schemas.app_metadata_schemas import AppSkillDefinition

APPS_ROOT = Path(__file__).resolve().parents[1] / "apps"


def app_source(app_id):
    return yaml.safe_load((APPS_ROOT / app_id / "app.yml").read_text())


# contract-test: supporting surface=rest_api assertions=workspace-shell.nav.released-surfaces-visible,app-skills.history.renderable
@pytest.mark.parametrize("app_id,skill_id", [("events", "search"), ("travel", "get_flight")])
def test_retired_execution_is_filtered_but_saved_content_contracts_remain(app_id, skill_id):
    source = app_source(app_id)
    availability = FeatureAvailabilityService(
        definitions=collect_feature_definitions_from_app_config(app_id, source), config={},
    )
    assert availability.is_enabled(f"skill:{app_id}:{skill_id}") is False
    filtered = filter_app_components_by_availability(app_id, source, availability)
    assert skill_id not in {skill["id"] for skill in filtered["skills"]}
    assert filtered["embed_types"] == source["embed_types"]
    assert filtered["settings_and_memories"] == source.get("settings_and_memories", [])
    # Keep the implementation schema for saved results and compatibility callers;
    # runtime registration, rather than deleting historical contracts, gates execution.
    assert next(skill for skill in source["skills"] if skill["id"] == skill_id)["tool_schema"]


# contract-test: supporting surface=rest_api assertions=workspace-shell.nav.released-surfaces-visible,app-skills.history.renderable
def test_removed_health_focuses_cannot_be_rediscovered_from_authored_sources():
    source = app_source("health")
    retired = {"prepare_doctor_report", "health_insights", "prepare_doctor_appointment"}
    assert not retired.intersection(focus["id"] for focus in source.get("focuses", []))
    for directory in ("prepare-doctor-report", "health-insights", "prepare-doctor-appointment"):
        assert not (APPS_ROOT / "health" / "focus_modes" / directory).exists()
    # Retirement must not erase the schemas needed to retain private saved data.
    assert {item["id"] for item in source["settings_and_memories"]} >= {
        "appointments", "medical_history", "symptoms_log", "sleep_diary",
    }
    assert {item["id"] for item in source["embed_types"]} >= {"search_appointments", "create_report"}


# contract-test: supporting surface=rest_api assertions=app-skills.providers.permitted-only
@pytest.mark.asyncio
@pytest.mark.parametrize("module", [apps, apps_api])
async def test_official_ccc_transcripts_remain_available_without_credentials(module):
    source = app_source("videos")
    skill = AppSkillDefinition.model_validate(next(s for s in source["skills"] if s["id"] == "get_transcript"))
    secrets = SimpleNamespace(get_secret=AsyncMock(side_effect=AssertionError("Public captions need no secret")))
    assert skill.providers[0].name == "media.ccc.de"
    assert skill.providers[0].no_api_key is True
    assert await module.is_skill_available(skill, "videos", secrets) is True
    secrets.get_secret.assert_not_called()


# contract-test: supporting surface=rest_api assertions=workspace-shell.nav.released-surfaces-visible
@pytest.mark.parametrize("capability_id", ["events.search", "travel.get_flight"])
def test_filesystem_workflow_discovery_does_not_reenable_paused_skills(capability_id):
    from backend.core.api.app.services.workflow_capability_registry import (
        WORKFLOW_SKILL_NOT_REGISTERED,
        WorkflowCapabilityRegistry,
        _FilesystemWorkflowMetadataRegistry,
    )

    metadata = _FilesystemWorkflowMetadataRegistry(apps_root=APPS_ROOT)
    app_id, skill_id = capability_id.split(".")
    assert metadata.is_skill_available(app_id, skill_id) is False
    capability = WorkflowCapabilityRegistry(skill_registry=metadata).get_capability(capability_id)
    assert capability.enabled is False
    assert capability.reason == WORKFLOW_SKILL_NOT_REGISTERED
