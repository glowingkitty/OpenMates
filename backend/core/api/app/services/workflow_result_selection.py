"""Reserve identifiable Workflow results per chat destination before Ask AI."""

from __future__ import annotations

from copy import deepcopy
import json
import re
import time
import uuid
from typing import Any, Callable

from starlette.concurrency import run_in_threadpool

from backend.core.api.app.services.workflow_delivery_history import (
    WorkflowDeliveryHistory, canonical_result_identity, keyed_fingerprint,
)
from backend.core.api.app.services.workflow_template_expressions import resolve_workflow_template
from backend.core.api.app.services.workflow_ai_service import _bounded_value


_REFERENCE = re.compile(r"\{\{\s*((?:steps|\$nodes)\.[A-Za-z0-9_-]+\.[A-Za-z0-9_.-]+)\s*\}\}")
_AI_RESULT_FIELDS = (
    "id", "source_id", "provider", "title", "name", "date_start", "date_end",
    "start_time", "end_time", "venue", "location", "address", "city",
    "lat", "lon", "url", "link", "description", "summary",
)
_EMBED_LINK = re.compile(r"\[([^\]]*)\]\(embed:([^\s)]+)\)")
_RESULTS_VIEW = re.compile(r"```(?:embeds_results_view|embeds_map_view)\s*\n(.*?)\n?```", re.DOTALL | re.IGNORECASE)
_PERSISTABLE_RESULT_EMBED_TYPES = {"events": "event", "news": "website", "home": "listing", "hosting": "hosting_domain"}


def persistable_result_embed_type(app_id: Any) -> str | None:
    """Only these source results can satisfy a reserved permanent chat embed."""
    return _PERSISTABLE_RESULT_EMBED_TYPES.get(app_id) if isinstance(app_id, str) else None


def sanitize_workflow_ai_answer(answer: str, allowed_refs: set[str]) -> str:
    """Keep authored prose while removing references that the selection cannot persist."""
    def clean_link(match: re.Match[str]) -> str:
        return match.group(0) if match.group(2) in allowed_refs else match.group(1)

    answer = _EMBED_LINK.sub(clean_link, answer)

    def clean_view(match: re.Match[str]) -> str:
        title = "Results"
        refs: list[str] = []
        for line in match.group(1).splitlines():
            key, sep, value = line.partition(":")
            if not sep:
                continue
            if key.strip() == "title":
                title = value.strip()[:100] or title
            elif key.strip() in {"embeds", "highlight"}:
                refs.extend(ref for ref in (part.strip() for part in value.split(",")) if ref in allowed_refs and ref not in refs)
        if not refs:
            return ""
        return "```embeds_results_view\ntitle: " + title + "\nembeds: " + ", ".join(refs) + "\n```"

    return _RESULTS_VIEW.sub(clean_view, answer).strip()


def _node_and_fields(reference: str) -> tuple[str, list[str]] | None:
    parts = reference.split(".")
    if parts[0] == "steps" and len(parts) >= 3:
        return parts[1], parts[2:]
    if parts[0] == "$nodes" and len(parts) >= 4 and parts[2] == "output":
        return parts[1], parts[3:]
    return None


def selected_context(context: dict[str, Any], selected_lists: dict[str, list[dict[str, Any]]], answer: str | None = None, ask_node_id: str | None = None) -> dict[str, Any]:
    projected = deepcopy(context)
    for reference, items in selected_lists.items():
        target = _node_and_fields(reference)
        if target is None:
            continue
        node_id, fields = target
        holder = (projected.get("nodes", {}).get(node_id) or {}).get("output")
        for field in fields[:-1]:
            holder = holder.get(field) if isinstance(holder, dict) else None
        if isinstance(holder, dict):
            holder[fields[-1]] = deepcopy(items)
    if answer is not None and ask_node_id:
        output = (projected.get("nodes", {}).get(ask_node_id) or {}).get("output")
        if isinstance(output, dict):
            output["answer"] = answer
    return projected


def prepare_ask_preview(
    prompt: str, context: dict[str, Any],
    embed_type_for_skill: Callable[[str, str], str | None],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Project referenced test results into bounded cards without reserving delivery."""
    ai_lists: dict[str, list[dict[str, Any]]] = {}
    embeds: list[dict[str, Any]] = []
    remaining_chars = 128_000
    run_id = context.get("workflow", {}).get("run_id", "")
    ask_node_id = context.get("workflow", {}).get("node_id", "")
    for reference in dict.fromkeys(match.group(1) for match in _REFERENCE.finditer(prompt)):
        path = _node_and_fields(reference)
        if path is None:
            continue
        source = context.get("nodes", {}).get(path[0]) or {}
        app_id, skill_id = source.get("app_id"), source.get("skill_id")
        if not isinstance(app_id, str) or not isinstance(skill_id, str):
            continue
        content_type = embed_type_for_skill(app_id, skill_id)
        if not content_type:
            continue
        value = resolve_workflow_template(reference if reference.startswith("$nodes.") else "{{" + reference + "}}", context)
        if not isinstance(value, list):
            continue
        ai_lists[reference] = []
        for index, item in enumerate(value[:20]):
            if not isinstance(item, dict):
                continue
            content = _bounded_value(item, depth=0)
            size = len(json.dumps(content, ensure_ascii=False))
            if size > remaining_chars:
                break
            remaining_chars -= size
            embed_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:workflow-preview:{run_id}:{ask_node_id}:{reference}:{index}"))
            # IDs precede result data so prompt bounding cannot remove their mapping.
            ai_lists[reference].append({"embed_ref": embed_id, **{key: child for key, child in content.items() if key != "embed_ref"}})
            embeds.append({"embed_id": embed_id, "content_type": content_type, "app_id": app_id, "skill_id": skill_id, "content": content})
    return selected_context(context, ai_lists), embeds


async def prepare_ask_destinations(
    *, workflow_service: Any, workflow_id: str, run_id: str, ask_node_id: str,
    prompt: str, context: dict[str, Any], user_id: str,
    send_nodes: list[Any],
) -> dict[str, dict[str, Any]]:
    """Return selected items and stable refs for each downstream Send node.

    The same delivery ID and destination hash are used by Send and ACK, so a
    retry sees its own reservation while later runs cannot reselect it.
    """
    references = [match.group(1) for match in _REFERENCE.finditer(prompt)]
    lists: dict[str, tuple[str, str, list[dict[str, Any]]]] = {}
    for reference in references:
        path = _node_and_fields(reference)
        if path is None:
            continue
        node_id, _ = path
        source = context.get("nodes", {}).get(node_id) or {}
        value = resolve_workflow_template(reference if reference.startswith("$nodes.") else "{{" + reference + "}}", context)
        if isinstance(value, list) and isinstance(source, dict) and persistable_result_embed_type(source.get("app_id")):
            lists[reference] = (str(source["app_id"]), str(source.get("skill_id") or ""),
                                [item for item in value if isinstance(item, dict)])
    if not lists or not send_nodes:
        return {}
    history = WorkflowDeliveryHistory(workflow_service)
    key = await run_in_threadpool(history.key, workflow_id, user_id)
    prepared: dict[str, dict[str, Any]] = {}
    for send in send_nodes:
        delivery_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"openmates:workflow:{run_id}:{send.id}:delivery"))
        destination = keyed_fingerprint(
            key, f"destination:v1:{send.id}:" + (f"chat:{send.config['chat_id']}" if send.config.get("chat_id") else "new-chat"),
        )
        candidates: list[dict[str, Any]] = []
        indexed: list[tuple[str, str, dict[str, Any], str]] = []
        for reference, (app_id, _, items) in lists.items():
            for item in items:
                try:
                    fingerprint = keyed_fingerprint(key, canonical_result_identity(item))
                except ValueError:
                    continue
                candidates.append({"index": len(candidates), "fingerprint": fingerprint, "only_new": True})
                indexed.append((reference, app_id, item, fingerprint))
        if not candidates:
            continue
        selected_indexes = await run_in_threadpool(
            history.reserve, user_id=user_id, workflow_id=workflow_id, run_id=run_id,
            node_id=send.id, delivery_id=delivery_id, destination_hash=destination,
            candidates=candidates, expires_at=int(time.time()) + min(int(send.config.get("expires_in_seconds") or 7 * 86400), 7 * 86400),
        )
        selected = set(selected_indexes)
        selected_lists: dict[str, list[dict[str, Any]]] = {reference: [] for reference in lists}
        ai_lists: dict[str, list[dict[str, Any]]] = {reference: [] for reference in lists}
        embeds: list[dict[str, Any]] = []
        for index, (reference, app_id, item, fingerprint) in enumerate(indexed):
            if index not in selected:
                continue
            embed_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{delivery_id}:embed:{fingerprint}"))
            ai_item = {"embed_ref": embed_id, **{field: item[field] for field in _AI_RESULT_FIELDS if field in item}}
            selected_lists[reference].append(item)
            ai_lists[reference].append(ai_item)
            content_type = persistable_result_embed_type(app_id)
            embeds.append({"embed_id": embed_id, "content_type": content_type, "content": item})
        prepared[send.id] = {
            "delivery_id": delivery_id,
            "selected_lists": selected_lists,
            "ai_lists": ai_lists,
            "embeds": embeds,
            "skip": not selected,
            "ask_node_id": ask_node_id,
        }
    return prepared
