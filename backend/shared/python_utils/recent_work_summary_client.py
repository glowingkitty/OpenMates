"""Transient internal HTTP IPC; never falls back to Redis/durable chat decryption."""

from __future__ import annotations

import os
import time

import httpx

from backend.shared.python_utils.recent_work_summary_cache import RecentChatSummary, SummarySource, PRIVATE_CONTEXT_FIELDS


def authoritative_context_turn_id(request: object) -> str:
    """Use only a successful API-memory restoration, never client turn metadata."""
    return getattr(request, "_authoritative_context_turn_id", None) or request.message_id


def bind_restored_context_turn(request: object, restored: dict) -> None:
    """Runtime-only authority: this marker is emitted solely by the IPC opener."""
    setattr(request, "_authoritative_context_turn_id", restored.get("_authoritative_context_turn_id"))


async def mint_response_summary_completion(request: object, task_id: str,
                                          *, client: RecentWorkSummaryClient | None = None) -> None:
    """Bind memory-only postprocessing authority before final delivery clears a turn."""
    if any(getattr(request, flag, False) for flag in ("is_external", "is_incognito", "is_anonymous")):
        return
    revision = f"{task_id}:{getattr(request, 'assistant_response_source_revision', 1)}"
    ticket = await (client or RecentWorkSummaryClient()).mint_completion(
        owner_id=request.user_id, chat_id=request.chat_id, task_id=task_id, revision=revision,
        turn_id=authoritative_context_turn_id(request),
    )
    # Private, non-model fields stay out of model_dump/Celery result serialization.
    if ticket:
        setattr(request, "_recent_summary_completion_ticket", ticket)
        setattr(request, "_recent_summary_revision", revision)


async def write_response_summary_completion(request: object, task_id: str, summary: str | None,
                                           *, client: RecentWorkSummaryClient | None = None) -> bool:
    """Write only a newly generated final summary, preserving its completion anchor."""
    ticket = getattr(request, "_recent_summary_completion_ticket", None)
    revision = getattr(request, "_recent_summary_revision", None)
    if not ticket or not revision or not isinstance(summary, str) or not summary.strip():
        return False
    project = getattr(request, "active_project_focus", None) or {}
    return await (client or RecentWorkSummaryClient()).write(
        owner_id=request.user_id, chat_id=request.chat_id, task_id=task_id,
        revision=revision, text=summary,
        project_id=project.get("project_id") or project.get("id"), completion_ticket=ticket,
    )


class RecentWorkSummaryClient:
    """Worker-facing runtime IPC. Errors are optional cache misses without logging."""

    def __init__(self, *, base_url: str | None = None, token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._base_url = (base_url or os.getenv("INTERNAL_API_BASE_URL", "http://api:8000")).rstrip("/")
        self._token = token or os.getenv("INTERNAL_API_SHARED_TOKEN", "")
        self._transport = transport

    async def _post(self, path: str, payload: dict) -> dict | None:
        if not self._token:
            return None

        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=5.0, trust_env=False) as client:
                response = await client.post(
                    f"{self._base_url}/internal/recent-work/{path}", json=payload,
                    headers={"X-Internal-Service-Token": self._token},
                )
                if response.status_code != 200:
                    return None
                result = response.json()
                return result if isinstance(result, dict) else None
        except Exception:
            return None

    async def seal_context(self, *, owner_id: str, chat_id: str, turn_id: str,
                           request_id: str, fields: dict) -> str | None:
        result = await self._post("context/seal", {
            "owner_id": owner_id, "current_chat_id": chat_id, "task_id": request_id,
            "turn_id": turn_id, "request_id": request_id, "fields": fields,
        })
        reference = result.get("reference") if result else None
        return reference if isinstance(reference, str) else None

    async def open_context(self, *, owner_id: str, chat_id: str, turn_id: str,
                           request_id: str, reference: str) -> dict | None:
        result = await self._post("context/open", {
            "owner_id": owner_id, "current_chat_id": chat_id, "task_id": request_id,
            "turn_id": turn_id, "request_id": request_id, "reference": reference,
        })
        fields = result.get("fields") if result else None
        return fields if isinstance(fields, dict) and not set(fields) - PRIVATE_CONTEXT_FIELDS else None

    async def mark_active(self, *, owner_id: str, chat_id: str, task_id: str, turn_id: str,
                          summary: str | None = None, summary_version: int | None = None, active_goal: str | None = None) -> bool:
        result = await self._post("active", {"owner_id": owner_id, "current_chat_id": chat_id,
            "task_id": task_id, "turn_id": turn_id, "summary": summary, "summary_version": summary_version, "active_goal": active_goal})
        return bool(result and result.get("stored") is True)

    async def write(
        self, *, owner_id: str, chat_id: str, task_id: str, revision: str,
        text: str, project_id: str | None = None, active: bool = False,
        assistant_completed_at: float | None = None,
        completion_ticket: str | None = None,
    ) -> bool:
        result = await self._post("write", {
            "owner_id": owner_id, "current_chat_id": chat_id, "task_id": task_id,
            "revision": revision, "text": text[:4_000], "project_id": project_id,
            "active": active, "assistant_completed_at": assistant_completed_at,
            "completion_ticket": completion_ticket,
        })
        return bool(result and result.get("stored") is True)

    async def mint_completion(self, *, owner_id: str, chat_id: str, task_id: str,
                              revision: str, turn_id: str) -> str | None:
        result = await self._post("completion", {
            "owner_id": owner_id, "current_chat_id": chat_id, "task_id": task_id,
            "revision": revision, "turn_id": turn_id,
        })
        ticket = result.get("ticket") if result else None
        return ticket if isinstance(ticket, str) else None

    async def read(
        self, *, owner_id: str, current_chat_id: str, task_id: str,
        authorized_chat_ids: list[str], current_project_id: str | None = None,
    ) -> list[RecentChatSummary]:
        result = await self._post("read", {
            "owner_id": owner_id, "current_chat_id": current_chat_id, "task_id": task_id,
            "authorized_chat_ids": authorized_chat_ids[:128], "current_project_id": current_project_id,
        })
        if not result or not isinstance(result.get("summaries"), list):
            return []
        summaries = []
        try:
            for item in result["summaries"][:24]:
                source = SummarySource(**item["source"])
                if source.owner_id != owner_id or source.chat_id not in authorized_chat_ids or source.expires_at <= time.time():
                    continue
                if isinstance(item["text"], str):
                    summaries.append(RecentChatSummary(source, item["text"][:4_000]))
        except (KeyError, TypeError, ValueError):
            return []
        return summaries


async def seal_private_context_payload(payload: dict, *, request_id: str,
                                       client: RecentWorkSummaryClient | None = None, ensure_turn_binding: bool = False) -> dict:
    """Remove private bodies before any durable queue/cache boundary; fail closed."""
    result = dict(payload)
    fields = {key: result.pop(key) for key in PRIVATE_CONTEXT_FIELDS if result.get(key)}
    for key in PRIVATE_CONTEXT_FIELDS:
        result.pop(key, None)
    if not fields and not ensure_turn_binding:
        return result
    reference = await (client or RecentWorkSummaryClient()).seal_context(
        owner_id=result.get("user_id", ""), chat_id=result.get("chat_id", ""),
        turn_id=result.get("message_id", ""), request_id=request_id, fields=fields,
    )
    if not reference:
        raise RuntimeError("Transient private context handoff unavailable")
    result["agentic_context_ref"] = reference
    result["agentic_context_request_id"] = request_id
    result["agentic_context_turn_id"] = result.get("message_id")
    return result


async def restore_private_context_payload(payload: dict,
                                          *, client: RecentWorkSummaryClient | None = None) -> dict:
    """Optional memory-only read; a miss never recovers old documents from storage."""
    result = {key: value for key, value in payload.items()
              if key not in PRIVATE_CONTEXT_FIELDS and key != "_authoritative_context_turn_id"}
    reference = result.get("agentic_context_ref")
    if not reference:
        return result
    fields = await (client or RecentWorkSummaryClient()).open_context(
        owner_id=result.get("user_id", ""), chat_id=result.get("chat_id", ""),
        turn_id=result.get("agentic_context_turn_id") or result.get("message_id", ""), request_id=result.get("agentic_context_request_id", ""),
        reference=reference,
    )
    if fields is not None:
        result.update(fields)
        result["_authoritative_context_turn_id"] = result.get("agentic_context_turn_id") or result.get("message_id")
    return result


async def mark_response_summary_active(request: object, task_id: str,
                                       *, client: RecentWorkSummaryClient | None = None) -> bool:
    if any(getattr(request, flag, False) for flag in ("is_external", "is_incognito", "is_anonymous")):
        return False
    return await (client or RecentWorkSummaryClient()).mark_active(
        owner_id=request.user_id, chat_id=request.chat_id, task_id=task_id, turn_id=authoritative_context_turn_id(request),
        summary=getattr(request, "current_chat_summary", None),
        summary_version=getattr(request, "current_chat_summary_v", None),
        active_goal=(getattr(request, "current_user_content", None) or "")[:4000] or None)
