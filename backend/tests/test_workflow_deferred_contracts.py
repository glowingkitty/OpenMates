# backend/tests/test_workflow_deferred_contracts.py
#
# Deferred Workflow app-skill contract tests.
# These tests protect connected-account, client-side encrypted data, and
# file/embed-input skills from becoming executable Workflow actions before their
# separate permission, encryption, and input-binding specs exist.
#
# Spec: docs/specs/workflow-app-skill-expansion/spec.yml

from backend.core.api.app.services.workflow_capability_registry import (
    WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
    WORKFLOW_CONNECTED_ACCOUNT_REQUIRED,
    WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED,
    WorkflowCapabilityRegistry,
)
from backend.core.api.app.services.workflow_yaml_compiler import validate_workflow_yaml


DEFERRED_REASON_BY_SKILL = {
    "calendar.get-events": WORKFLOW_CONNECTED_ACCOUNT_REQUIRED,
    "calendar.create-event": WORKFLOW_CONNECTED_ACCOUNT_REQUIRED,
    "calendar.update-event": WORKFLOW_CONNECTED_ACCOUNT_REQUIRED,
    "calendar.delete-event": WORKFLOW_CONNECTED_ACCOUNT_REQUIRED,
    "mail.search": WORKFLOW_CONNECTED_ACCOUNT_REQUIRED,
    "tasks.create": WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
    "tasks.search": WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
    "reminder.set-reminder": WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
    "reminder.list-reminders": WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
    "reminder.cancel-reminder": WORKFLOW_CLIENT_ENCRYPTED_DATA_REQUIRED,
    "audio.transcribe": WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED,
    "pdf.read": WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED,
    "pdf.search": WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED,
    "pdf.view": WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED,
    "images.vectorize": WORKFLOW_FILE_OR_EMBED_INPUT_REQUIRED,
}


def test_deferred_skills_are_disabled_with_stable_reasons() -> None:
    registry = WorkflowCapabilityRegistry()
    by_id = {capability.id: capability for capability in registry.list_capabilities()}

    for capability_id, reason in DEFERRED_REASON_BY_SKILL.items():
        assert by_id[capability_id].enabled is False
        assert by_id[capability_id].reason == reason


def test_yaml_validation_blocks_deferred_skills_before_execution() -> None:
    registry = WorkflowCapabilityRegistry()

    for capability_id, reason in DEFERRED_REASON_BY_SKILL.items():
        result = validate_workflow_yaml(_workflow_yaml_for(capability_id), capability_registry=registry)

        assert result.draft_valid is True
        assert result.enable_ready is False
        assert len(result.diagnostics) == 1
        diagnostic = result.diagnostics[0]
        assert diagnostic.code == "WORKFLOW_CAPABILITY_UNAVAILABLE"
        assert reason in diagnostic.message
        assert diagnostic.help_command == f"openmates workflows help-app {capability_id}"


def _workflow_yaml_for(capability_id: str) -> str:
    return f"""
title: Deferred skill test
start_when:
  manual: {{}}
steps:
  - id: deferred
    use_app_skill: {capability_id}
    input: {{}}
"""
