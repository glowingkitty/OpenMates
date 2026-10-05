"""Bounded owner-authorized saved Workflow discovery, without execution grants."""
from __future__ import annotations

from typing import Any

from backend.core.api.app.services.workflow_models import WorkflowLifecycle

MAX_WORKFLOW_CANDIDATES = 20
MAX_SELECTED_WORKFLOWS = 3
SAVED_WORKFLOW_INSTRUCTION = (
    "Saved workflows are validated deterministic graphs. Select only supplied existing workflow IDs. "
    "Selection never runs, edits, enables or rewrites a workflow. To execute a relevant saved graph, "
    "use workflows.run with explicit typed input and the initiating source_chat_id. Per-run "
    "message_destination_overrides may target the current chat or authorized subchats; discovery "
    "does not require a new regular chat. Preserve configured Checks, branches and Unsure outcomes."
)


def saved_workflow_metadata(
    workflow_service: Any, user_id: str, *, vault_key_id: str | None = None,
    team_id: str | None = None, authorized_workflow_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Only titles/summaries enter shortlisting; never decrypt graphs for ranking.

    Project IDs, when supplied, must come from authorized Project item resolution,
    not the model. Disabled definitions remain discoverable for useful edits.
    """
    if not user_id:
        return []
    allowed = set(authorized_workflow_ids) if authorized_workflow_ids is not None else None
    summaries = workflow_service.list_workflows(user_id, vault_key_id, team_id=team_id)
    return [{
        "workflow_id": item.id, "title": item.title[:200],
        "description": (item.description or "")[:1000],
        "enabled": item.enabled, "status": item.status.value,
        "current_version_id": item.current_version_id,
    } for item in summaries if item.lifecycle == WorkflowLifecycle.PERSISTED
        and (allowed is None or item.id in allowed)][:MAX_WORKFLOW_CANDIDATES]


def load_selected_saved_workflows(
    workflow_service: Any, user_id: str, selected_ids: list[str],
    candidates: list[dict[str, Any]], *, vault_key_id: str | None = None,
    team_id: str | None = None,
) -> list[dict[str, Any]]:
    """Reauthorize shortlisted IDs and reject stale versions before graph loading."""
    allowed = {item["workflow_id"]: item for item in candidates[:MAX_WORKFLOW_CANDIDATES]}
    result = []
    for workflow_id in dict.fromkeys(selected_ids[:MAX_SELECTED_WORKFLOWS]):
        if workflow_id not in allowed:
            continue
        try:
            detail = workflow_service.get_workflow(workflow_id, user_id, vault_key_id, team_id=team_id)
        except (LookupError, PermissionError):
            continue
        if detail.lifecycle != WorkflowLifecycle.PERSISTED or detail.current_version_id != allowed[workflow_id]["current_version_id"]:
            continue
        graph = _safe_graph(detail.graph.model_dump(mode="json", by_alias=True))
        result.append({**allowed[workflow_id], "graph": graph,
                       "binding_requirements": detail.binding_requirements,
                       "invocation_tool": "workflows.run"})
    return result


def _safe_graph(value: Any) -> Any:
    if isinstance(value, dict):
        forbidden = {"token", "secret", "credential", "credentials", "password", "apikey", "privatekey", "vaultkey", "masterkey", "encryptionkey", "authorization", "vault", "grant", "grantid", "accountid", "connectionid", "connectedaccountid"}
        return {key: _safe_graph(child) for key, child in value.items()
                if not any("".join(c for c in key.lower() if c.isalnum()).endswith(suffix)
                           for suffix in forbidden)}
    if isinstance(value, list):
        return [_safe_graph(child) for child in value]
    return value
