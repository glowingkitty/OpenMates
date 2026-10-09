"""Internal-only runtime IPC for API-owned memory-only summary ciphertexts.

Not a public/developer API and never added to Caddy's public allowlist. The
existing internal service credential, live chat ownership and current AI task
binding are mandatory. No paid inference runs here. Request/response contents
must never be attached to logs, traces, jobs, storage or snapshots.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, replace

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.core.api.app.utils.internal_auth import VerifiedInternalRequest
from backend.shared.python_utils.recent_work_summary_cache import (
    recent_work_summary_cache, transient_context_handoff_store,
)

router = APIRouter(prefix="/internal/recent-work", tags=["Internal Services"],
                   dependencies=[VerifiedInternalRequest], include_in_schema=False)


class _TurnBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: str = Field(min_length=1, max_length=100)
    current_chat_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)


class _SummaryWrite(_TurnBinding):
    project_id: str | None = Field(default=None, max_length=100)
    revision: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=4_000, repr=False)
    active: bool = False
    assistant_completed_at: float | None = None
    completion_ticket: str | None = Field(default=None, max_length=100, repr=False)


class _SummaryActive(_TurnBinding):
    turn_id: str = Field(min_length=1, max_length=100)
    summary: str | None = Field(default=None, max_length=4000, repr=False)
    summary_version: int | None = Field(default=None, ge=0)
    active_goal: str | None = Field(default=None, max_length=4000, repr=False)


class _CompletionMint(_TurnBinding):
    turn_id: str = Field(min_length=1, max_length=100)
    revision: str = Field(min_length=1, max_length=100)


class _SummaryRead(_TurnBinding):
    authorized_chat_ids: list[str] = Field(default_factory=list, max_length=128)
    current_project_id: str | None = Field(default=None, max_length=100)


async def _parse(request: Request, model: type[BaseModel], *, max_bytes: int = 64_000) -> BaseModel:
    # Ordinary FastAPI 422 responses echo invalid input, potentially including a
    # summary. Keep all validation errors content-free, including middleware logs.
    try:
        body = await request.body()
        if len(body) > max_bytes:
            raise ValueError("oversized")
        return model.model_validate_json(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid recent-work request") from None


async def _live_owned_chat_ids(directus, owner_id: str, chat_ids: list[str]) -> set[str]:
    if not chat_ids:
        return set()
    rows = await directus.get_items("chats", params={
        "filter[id][_in]": ",".join(chat_ids),
        "filter[hashed_user_id][_eq]": hashlib.sha256(owner_id.encode()).hexdigest(),
        "fields": "id,hashed_team_id", "limit": len(chat_ids),
    }, no_cache=True, admin_required=True)
    team_hashes = {row.get("hashed_team_id") for row in rows or [] if row.get("hashed_team_id")}
    active_teams = set()
    if team_hashes:
        memberships = await directus.get_items("team_memberships", params={
            "filter[hashed_user_id][_eq]": hashlib.sha256(owner_id.encode()).hexdigest(),
            "filter[hashed_team_id][_in]": ",".join(team_hashes),
            "filter[status][_eq]": "active", "fields": "hashed_team_id", "limit": len(team_hashes),
        }, no_cache=True, admin_required=True)
        active_teams = {row["hashed_team_id"] for row in memberships or [] if row.get("hashed_team_id")}
    return {str(row["id"]) for row in rows or [] if row.get("id")
            and (not row.get("hashed_team_id") or row["hashed_team_id"] in active_teams)}


async def _services_and_authority(request: Request, binding: _TurnBinding, *, completion_permit=None):
    state = request.app.state
    cache = getattr(state, "cache_service", None)
    directus = getattr(state, "directus_service", None)
    encryption = getattr(state, "encryption_service", None)
    if not all((cache, directus, encryption)):
        raise HTTPException(status_code=503, detail="Recent-work runtime unavailable")
    try:
        owned = await _live_owned_chat_ids(directus, binding.owner_id, [binding.current_chat_id])
        current = await cache.get_active_ai_task(binding.current_chat_id)
        vault_key_id = await cache.get_user_vault_key_id(binding.owner_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Recent-work authority unavailable") from None
    if (binding.current_chat_id not in owned or not vault_key_id
            or completion_permit is None and current != binding.task_id):
        raise HTTPException(status_code=403, detail="Recent-work turn authority denied")
    return cache, directus, encryption, vault_key_id


class _ContextBinding(_TurnBinding):
    turn_id: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=100)


class _ContextSeal(_ContextBinding):
    fields: dict = Field(repr=False)


class _ContextOpen(_ContextBinding):
    reference: str = Field(min_length=1, max_length=100, repr=False)


async def _context_authority(request: Request, payload: _ContextBinding):
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    state = request.app.state
    cache, directus, encryption = state.cache_service, state.directus_service, state.encryption_service
    try:
        owned = await _live_owned_chat_ids(directus, payload.owner_id, [payload.current_chat_id])
        latest = await cache.get(async_skill_latest_user_turn_key(payload.owner_id, payload.current_chat_id))
        vault_key_id = await cache.get_user_vault_key_id(payload.owner_id)
    except Exception:
        raise HTTPException(status_code=503, detail="Transient context authority unavailable") from None
    if payload.current_chat_id not in owned or latest != payload.turn_id or not vault_key_id:
        raise HTTPException(status_code=403, detail="Transient context authority denied")
    return cache, directus, encryption, vault_key_id


async def _validate_context_projects(payload, fields, directus, cache):
    """A handoff cannot outlive live Project access or its authorized base Focus."""
    from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService
    service = ProjectWriteAuthorizationService(directus, cache)
    project_fields = ("project_focus_catalog", "project_focus_documents", "project_context_documents")
    ids = {row.get("project_id") for key, values in fields.items()
           if key != "async_tool_history" and isinstance(values, list)
           for row in values if isinstance(row, dict) and row.get("project_id")}
    private_completion = fields.get("async_tool_completion")
    if private_completion is not None and (
        not isinstance(private_completion, dict)
        or not isinstance(private_completion.get("project_id"), str)
        or not private_completion["project_id"]
    ):
        raise HTTPException(status_code=403, detail="Private tool result Project binding required")
    if private_completion:
        ids.add(private_completion["project_id"])
    private_history = fields.get("async_tool_history")
    if private_history is not None:
        if (not isinstance(private_history, list)
                or any(not isinstance(entry, dict)
                       or not isinstance(entry.get("project_id"), str)
                       or not entry["project_id"] for entry in private_history)):
            raise HTTPException(status_code=403, detail="Private tool history Project binding required")
        for entry in private_history:
            ids.add(entry["project_id"])
    if not ids and not any(fields.get(key) for key in project_fields):
        return
    try:
        binding = await service.get_active_focus(user_id=payload.owner_id, chat_id=payload.current_chat_id)
        if (isinstance(private_completion, dict) and private_completion.get("project_id")
                and (not binding or binding.get("project_id") != private_completion["project_id"])):
            raise ValueError("Private tool result Project focus changed")
        if isinstance(private_history, list) and any(
            isinstance(entry, dict) and entry.get("project_id") != (binding or {}).get("project_id")
            for entry in private_history
        ):
            raise ValueError("Private tool history Project focus changed")
        if any(fields.get(key) for key in project_fields) and not binding:
            raise ValueError("Missing current Project")
        if binding:
            ids.add(binding["project_id"])
        if len(ids) > 20:
            raise ValueError("Project bound exceeded")
        for project_id in ids:
            await service._require_project_access(payload.owner_id, project_id,
                (binding or {}).get("team_id"), write=False)
        return (binding["project_id"], binding.get("activation_id", "")) if binding else None
    except Exception:
        raise HTTPException(status_code=403, detail="Transient context Project authority denied") from None


@router.post("/context/seal")
async def seal_context(request: Request) -> JSONResponse:
    payload = await _parse(request, _ContextSeal, max_bytes=256_000)
    _cache, _directus, encryption, key = await _context_authority(request, payload)
    try:
        project_binding = await _validate_context_projects(payload, payload.fields, _directus, _cache)
        reference = await transient_context_handoff_store.seal(
            owner_id=payload.owner_id, chat_id=payload.current_chat_id, turn_id=payload.turn_id,
            request_id=payload.request_id, fields=payload.fields, encryption=encryption, vault_key_id=key,
            project_binding=project_binding,
        )
        await _context_authority(request, payload)
    except HTTPException:
        transient_context_handoff_store.revoke(owner_id=payload.owner_id, chat_id=payload.current_chat_id)
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Transient context sealing unavailable") from None
    return JSONResponse({"reference": reference}, headers={"Cache-Control": "no-store"})


@router.post("/context/open")
async def open_context(request: Request) -> JSONResponse:
    payload = await _parse(request, _ContextOpen)
    _cache, _directus, encryption, key = await _context_authority(request, payload)
    try:
        fields = await transient_context_handoff_store.open(payload.reference,
            owner_id=payload.owner_id, chat_id=payload.current_chat_id, turn_id=payload.turn_id,
            request_id=payload.request_id, encryption=encryption, vault_key_id=key,
        )
        await _context_authority(request, payload)
        if fields:
            binding = await _validate_context_projects(payload, fields, _directus, _cache)
            if binding != transient_context_handoff_store.project_binding(payload.reference):
                raise HTTPException(status_code=403, detail="Transient Project activation changed")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Transient context loading unavailable") from None
    return JSONResponse({"fields": fields}, headers={"Cache-Control": "no-store"})


@router.post("/active")
async def mark_active_summary(request: Request) -> JSONResponse:
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    payload = await _parse(request, _SummaryActive)
    cache, directus, encryption, key = await _services_and_authority(request, payload)
    if await cache.get(async_skill_latest_user_turn_key(payload.owner_id, payload.current_chat_id)) != payload.turn_id:
        raise HTTPException(status_code=403, detail="Active summary turn authority denied")
    stored = recent_work_summary_cache.mark_active(owner_id=payload.owner_id, chat_id=payload.current_chat_id,
                                                  vault_key_id=key, task_id=payload.task_id)
    if not stored and ((payload.summary and payload.summary_version is not None) or payload.active_goal):
        from backend.core.api.app.services.project_write_authorization_service import ProjectWriteAuthorizationService
        binding = await ProjectWriteAuthorizationService(directus, cache).get_active_focus(
            user_id=payload.owner_id, chat_id=payload.current_chat_id)
        stored = await recent_work_summary_cache.put(owner_id=payload.owner_id, chat_id=payload.current_chat_id,
            project_id=(binding or {}).get("project_id"),
            revision=(f"{payload.task_id}:client-summary:{payload.summary_version}" if payload.summary and payload.summary_version is not None
                      else f"{payload.task_id}:active-goal:{payload.turn_id}"),
            text=(payload.summary if payload.summary and payload.summary_version is not None
                  else "Current active user request (no assistant completion): " + payload.active_goal),
            vault_key_id=key, encryption=encryption, authorized=True, active=True,
            assistant_completed_at=None, active_task_id=payload.task_id,
            source_kind=("authorized_client_chat_summary" if payload.summary and payload.summary_version is not None
                         else "authorized_active_request_goal"))
    # Revocation or a queued/new user turn during Vault I/O cannot retain an old active copy.
    if (await cache.get_active_ai_task(payload.current_chat_id) != payload.task_id
            or await cache.get(async_skill_latest_user_turn_key(payload.owner_id, payload.current_chat_id)) != payload.turn_id
            or payload.current_chat_id not in await _live_owned_chat_ids(directus, payload.owner_id, [payload.current_chat_id])):
        recent_work_summary_cache.revoke_chat(owner_id=payload.owner_id, chat_id=payload.current_chat_id)
        stored = False
    return JSONResponse({"stored": stored}, headers={"Cache-Control": "no-store"})


@router.post("/completion")
async def mint_completion(request: Request) -> JSONResponse:
    payload = await _parse(request, _CompletionMint)
    cache, *_ = await _services_and_authority(request, payload)
    from backend.apps.ai.tasks.async_skill_continuation import async_skill_latest_user_turn_key
    if await cache.get(async_skill_latest_user_turn_key(payload.owner_id, payload.current_chat_id)) != payload.turn_id:
        return JSONResponse({"ticket": None}, headers={"Cache-Control": "no-store"})
    ticket = recent_work_summary_cache.mint_completion_permit(
        owner_id=payload.owner_id, chat_id=payload.current_chat_id,
        task_id=payload.task_id, revision=payload.revision, turn_id=payload.turn_id,
    )
    return JSONResponse({"ticket": ticket}, headers={"Cache-Control": "no-store"})


@router.post("/write")
async def write_summary(request: Request) -> JSONResponse:
    payload = await _parse(request, _SummaryWrite)
    permit = recent_work_summary_cache.completion_permit(
        payload.completion_ticket, owner_id=payload.owner_id, chat_id=payload.current_chat_id,
        task_id=payload.task_id, revision=payload.revision,
    ) if payload.completion_ticket else None
    if payload.completion_ticket and permit is None:
        return JSONResponse({"stored": False}, headers={"Cache-Control": "no-store"})
    cache, directus, encryption, vault_key_id = await _services_and_authority(request, payload, completion_permit=permit)
    try:
        stored = await recent_work_summary_cache.put(
            owner_id=payload.owner_id, chat_id=payload.current_chat_id,
            project_id=payload.project_id, revision=payload.revision, text=payload.text,
            vault_key_id=vault_key_id, encryption=encryption, authorized=True,
            active=False if permit else payload.active,
            assistant_completed_at=permit.assistant_completed_at if permit else payload.assistant_completed_at,
            source_updated_at=permit.assistant_completed_at if permit else None,
        )
        # Turn takeover during Vault I/O invalidates the write as well as reads.
        still_owned = await _live_owned_chat_ids(directus, payload.owner_id, [payload.current_chat_id])
        still_permitted = recent_work_summary_cache.completion_permit(
            payload.completion_ticket, owner_id=payload.owner_id, chat_id=payload.current_chat_id,
            task_id=payload.task_id, revision=payload.revision,
        ) is permit if permit else await cache.get_active_ai_task(payload.current_chat_id) == payload.task_id
        if not still_permitted or payload.current_chat_id not in still_owned:
            recent_work_summary_cache.discard_revision(owner_id=payload.owner_id, chat_id=payload.current_chat_id,
                                                       revision=payload.revision)
            stored = False
        if permit:
            recent_work_summary_cache.consume_completion_permit(payload.completion_ticket)
    except Exception:
        raise HTTPException(status_code=503, detail="Recent-work write unavailable") from None
    return JSONResponse({"stored": stored}, headers={"Cache-Control": "no-store"})


@router.post("/read")
async def read_summaries(request: Request) -> JSONResponse:
    payload = await _parse(request, _SummaryRead)
    cache, directus, encryption, vault_key_id = await _services_and_authority(request, payload)
    try:
        sources = recent_work_summary_cache.candidates(
            owner_id=payload.owner_id, authorized_chat_ids=payload.authorized_chat_ids,
        )
        sources = [source for source in sources if source.chat_id != payload.current_chat_id]
        sources.sort(key=lambda source: (
            source.project_id != payload.current_project_id if payload.current_project_id else True,
            -source.source_updated_at,
        ))
        sources = sources[:24]
        owned = await _live_owned_chat_ids(directus, payload.owner_id, [source.chat_id for source in sources])
        live_tasks = await cache.get_active_ai_tasks([source.chat_id for source in sources if source.chat_id in owned])
        summaries = []
        for source in sources:
            if source.chat_id not in owned:
                recent_work_summary_cache.revoke_chat(owner_id=payload.owner_id, chat_id=source.chat_id)
                continue
            active = source.active and source.chat_id in live_tasks and (source.active_task_id is None or live_tasks[source.chat_id] == source.active_task_id)
            recent_completion = (source.assistant_completed_at is not None
                                 and 0 <= time.time() - source.assistant_completed_at < 30 * 60)
            if not active and not recent_completion:
                continue
            summary = await recent_work_summary_cache.get(
                owner_id=payload.owner_id, chat_id=source.chat_id, authorized_chat_ids=owned,
                vault_key_id=vault_key_id, encryption=encryption,
            )
            if summary is not None:
                summaries.append({"source": asdict(replace(summary.source, active=active)), "text": summary.text})
        still_owned = await _live_owned_chat_ids(
            directus, payload.owner_id, [payload.current_chat_id] + [item["source"]["chat_id"] for item in summaries],
        )
        for item in summaries:
            if item["source"]["chat_id"] not in still_owned:
                recent_work_summary_cache.revoke_chat(owner_id=payload.owner_id, chat_id=item["source"]["chat_id"])
        summaries = [item for item in summaries if item["source"]["chat_id"] in still_owned]
        if (await cache.get_active_ai_task(payload.current_chat_id) != payload.task_id
                or payload.current_chat_id not in still_owned):
            raise HTTPException(status_code=403, detail="Recent-work turn authority denied")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=503, detail="Recent-work read unavailable") from None
    return JSONResponse({"summaries": summaries}, headers={"Cache-Control": "no-store"})
