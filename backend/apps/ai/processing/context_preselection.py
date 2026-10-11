"""Metadata shortlists selected in the existing foreground Jev call.

Snapshots carry identity and revision only into reload. Every body is freshly
authorized after the decision; selection conveys no execution permission.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from backend.apps.ai.processing.agentic_context import first_party, fresh_project
from backend.apps.ai.processing.rule_context import (
    MAX_APPLIED_RULE_CHARS, MAX_DISCOVERY_CHARS, MAX_RULE_CANDIDATES,
    authorized_project_memory_documents, eligible_rule_catalog, parse_custom_rule_documents,
)
from backend.shared.python_utils.rule_loader import rules_prompt

WORKFLOW_METADATA_TTL_SECONDS = 30


def _workflow_metadata_cache_key(user_id: str, team_id: str | None, vault_key_id: str) -> str:
    scope = json.dumps([user_id, team_id, vault_key_id], separators=(",", ":"))
    return "workflow:discovery:v1:" + hashlib.sha256(scope.encode()).hexdigest()


def _workflow_metadata_epoch_key(user_id: str, team_id: str | None) -> str:
    from backend.core.api.app.services.workflow_service import _hash_owner_id, _hash_team_id
    return "workflow:discovery:epoch:" + (_hash_team_id(team_id) if team_id else _hash_owner_id(user_id))


async def _versioned_workflow_metadata_key(cache: Any, user_id: str, team_id: str | None,
                                           vault_key_id: str) -> str:
    epoch = await cache.get(_workflow_metadata_epoch_key(user_id, team_id))
    return f"{_workflow_metadata_cache_key(user_id, team_id, vault_key_id)}:{epoch or 0}"


async def _cached_workflow_metadata(cache: Any, key: str, vault_key_id: str) -> list[dict] | None:
    from backend.core.api.app.utils.encryption import EncryptionService
    sealed = await cache.get(key)
    if not isinstance(sealed, dict) or not isinstance(sealed.get("ciphertext"), str):
        return None
    plaintext = await EncryptionService().decrypt_with_user_key(sealed["ciphertext"], vault_key_id)
    if not plaintext:
        return None
    rows = json.loads(plaintext)
    return rows if isinstance(rows, list) else None


async def _save_workflow_metadata(cache: Any, key: str, vault_key_id: str, rows: list[dict]) -> None:
    from backend.core.api.app.utils.encryption import EncryptionService
    ciphertext, _ = await EncryptionService().encrypt_with_user_key(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=True), vault_key_id)
    await cache.set(key, {"ciphertext": ciphertext}, ttl=WORKFLOW_METADATA_TTL_SECONDS)


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
        # Newly authorized Project guides must not be displaced by the bounded
        # public app catalogue. Stable sorting preserves order within each scope.
        for rule in sorted(catalog, key=lambda item: item.source != "project"):
            if len(result) >= MAX_RULE_CANDIDATES:
                break
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


async def _close_workflow_service(service: Any) -> None:
    client = getattr(getattr(service, "repository", None), "_client", None)
    if client is not None:
        try:
            await asyncio.to_thread(client.close)
        except Exception:
            pass


async def _authorize_workflow_team(request: Any, cache: Any) -> None:
    team_id = getattr(request, "team_id", None)
    if not team_id:
        return
    from backend.core.api.app.services.directus import DirectusService
    directus = DirectusService(cache_service=cache)
    try:
        await directus.team.require_team_role(
            team_id, request.user_id, {"owner", "admin", "member", "viewer"})
    finally:
        await directus.close()


async def discover_workflow_metadata(request: Any, cache: Any) -> list[dict]:
    from backend.apps.workflows.skills.saved_workflow_context import saved_workflow_metadata
    service = None
    try:
        if not first_party(request):
            return []
        await _authorize_workflow_team(request, cache)
        binding = await _workflow_service(request, cache)
        if not binding:
            return []
        service, vault_key_id = binding
        key = None
        try:
            key = await _versioned_workflow_metadata_key(cache, request.user_id, request.team_id, vault_key_id)
            cached = await _cached_workflow_metadata(cache, key, vault_key_id)
            if cached is not None:
                return cached
        except Exception:
            pass  # A missing or unreadable cache always falls back to Directus.
        rows = await asyncio.to_thread(saved_workflow_metadata, service, request.user_id,
            vault_key_id=vault_key_id, team_id=request.team_id)
        if key is not None:
            try:
                await _save_workflow_metadata(cache, key, vault_key_id, rows)
            except Exception:
                pass
        return rows
    except Exception:
        return []
    finally:
        if service is not None:
            await _close_workflow_service(service)


async def reload_preselected_workflows(request: Any, cache: Any, selected: list[dict]) -> list[dict]:
    from backend.apps.workflows.skills.saved_workflow_context import load_selected_saved_workflows
    service = None
    try:
        if not first_party(request):
            return []
        await _authorize_workflow_team(request, cache)
        binding = await _workflow_service(request, cache)
        if not binding:
            return []
        service, vault_key_id = binding
        def fresh_selected() -> list[dict]:
            retained = []
            for row in selected[:3]:
                if not isinstance(row, dict) or not isinstance(row.get("workflow_id"), str):
                    continue
                record = service.repository.get_workflow(row["workflow_id"], request.user_id,
                                                         team_id=request.team_id)
                if (record and record.get("lifecycle", "persisted") == "persisted"
                        and record.get("current_version_id") == row.get("current_version_id")):
                    retained.append(row)
            return retained
        retained = await asyncio.to_thread(fresh_selected)
        if not retained:
            return []
        return await asyncio.to_thread(load_selected_saved_workflows, service, request.user_id,
            [row["workflow_id"] for row in retained], retained,
            vault_key_id=vault_key_id, team_id=request.team_id)
    except Exception:
        return []
    finally:
        if service is not None:
            await _close_workflow_service(service)
