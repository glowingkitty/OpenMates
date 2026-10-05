"""Metadata shortlists selected in the existing foreground Jev call.

Snapshots carry identity and revision only into reload. Every body is freshly
authorized after the decision; selection conveys no execution permission.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from backend.apps.ai.processing.agentic_context import first_party, fresh_project
from backend.apps.ai.processing.rule_context import (
    MAX_APPLIED_RULE_CHARS, MAX_DISCOVERY_CHARS, MAX_RULE_CANDIDATES,
    authorized_project_memory_documents, eligible_rule_catalog, parse_custom_rule_documents,
)
from backend.shared.python_utils.rule_loader import rules_prompt


async def _rules(request: Any, directus: Any, cache: Any, eligible_app_ids: list[str]) -> list:
    project = await fresh_project(request, directus, cache)
    project_id = project.get("project_id") if project else None
    supplied = await authorized_project_memory_documents(getattr(request, "custom_rule_documents", []),
        project=project, user_id=getattr(request, "user_id", None), directus=directus)
    private = parse_custom_rule_documents(supplied,
        authenticated_first_party=first_party(request), active_project_id=project_id)
    return eligible_rule_catalog(eligible_app_ids=eligible_app_ids, custom_rules=private,
        authenticated_first_party=first_party(request), active_project_id=project_id)


async def discover_rule_metadata(request: Any, directus: Any, cache: Any,
                                 eligible_app_ids: list[str]) -> list[dict]:
    try:
        binding = await fresh_project(request, directus, cache)
        request._preselected_rule_project_activation = (binding or {}).get("activation_id")
        catalog = await _rules(request, directus, cache, eligible_app_ids)
        result = []
        for rule in catalog[:MAX_RULE_CANDIDATES]:
            entry = {key: getattr(rule, key) for key in
                     ("id", "title", "description", "when_to_use", "revision", "source", "app_id", "project_id")}
            if len(json.dumps([*result, entry], ensure_ascii=True)) <= MAX_DISCOVERY_CHARS:
                result.append(entry)
        return result
    except Exception:
        return []


async def reload_preselected_rules(request: Any, directus: Any, cache: Any,
                                    eligible_app_ids: list[str], selected: list[dict]) -> list:
    try:
        binding = await fresh_project(request, directus, cache)
        if (binding or {}).get("activation_id") != getattr(request, "_preselected_rule_project_activation", None):
            return []
        current = {rule.id: rule for rule in await _rules(request, directus, cache, eligible_app_ids)}
        fresh = await fresh_project(request, directus, cache)
        if (fresh or {}).get("activation_id") != getattr(request, "_preselected_rule_project_activation", None):
            return []
        result = []
        seen = set()
        for snapshot in selected[:MAX_RULE_CANDIDATES]:
            rule = current.get(snapshot.get("id"))
            if not rule or rule.id in seen or rule.revision != snapshot.get("revision"):
                continue
            seen.add(rule.id)
            if len(rules_prompt([*result, rule])) <= MAX_APPLIED_RULE_CHARS:
                result.append(rule)
        return result
    except Exception:
        return []


async def _workflow_service(request: Any, cache: Any) -> tuple[Any, str | None] | None:
    if not first_party(request) or cache is None:
        return None
    from backend.core.api.app.services.workflow_service import DirectusWorkflowRepository, WorkflowService
    vault_key_id = await cache.get_user_vault_key_id(request.user_id)
    if not vault_key_id:
        return None
    return WorkflowService(repository=DirectusWorkflowRepository()), vault_key_id


async def discover_workflow_metadata(request: Any, cache: Any) -> list[dict]:
    from backend.apps.workflows.skills.saved_workflow_context import saved_workflow_metadata
    try:
        binding = await _workflow_service(request, cache)
        if not binding:
            return []
        service, vault_key_id = binding
        return await asyncio.to_thread(saved_workflow_metadata, service, request.user_id,
            vault_key_id=vault_key_id, team_id=request.team_id)
    except Exception:
        return []


async def reload_preselected_workflows(request: Any, cache: Any, selected: list[dict]) -> list[dict]:
    from backend.apps.workflows.skills.saved_workflow_context import load_selected_saved_workflows, saved_workflow_metadata
    try:
        binding = await _workflow_service(request, cache)
        if not binding:
            return []
        service, vault_key_id = binding
        fresh = await asyncio.to_thread(saved_workflow_metadata, service, request.user_id,
            vault_key_id=vault_key_id, team_id=request.team_id)
        expected = {row.get("workflow_id"): row.get("current_version_id") for row in selected[:3]}
        retained = [row for row in fresh if row["workflow_id"] in expected
                    and row["current_version_id"] == expected[row["workflow_id"]]]
        return await asyncio.to_thread(load_selected_saved_workflows, service, request.user_id,
            [row["workflow_id"] for row in retained],
            retained, vault_key_id=vault_key_id, team_id=request.team_id)
    except Exception:
        return []
