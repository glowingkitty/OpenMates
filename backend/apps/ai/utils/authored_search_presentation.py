"""Fold authorized authored duplicates into the search results they reuse."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any

from backend.apps.ai.utils.embeds_map_view import (
    _MAP_VIEW_FENCE_RE,
    extract_results_view_source_refs,
    map_view_source_bindings_from_tool_calls,
)
from backend.shared.python_utils.finalization_embed_graph import FinalizationEmbedGraph

_AUTHORED_REF = re.compile(r"```json[ \t]*\n(?P<body>\s*\{[^{}]*\}\s*)\n?```")


def _ids(value: Any) -> set[str]:
    return {item for item in value if isinstance(item, str) and item} if isinstance(value, list) else set()


async def fold_reused_search_cards(
    content: str,
    tool_calls: Iterable[Mapping[str, Any]],
    graph: FinalizationEmbedGraph,
) -> str:
    """Keep one displayed group while preserving unrelated authored cards."""
    if '"authored_results"' not in content:
        return content
    calls = [call for call in tool_calls if isinstance(call, dict)]
    child_ids = set().union(*(_ids(call.get("result_child_ids")) for call in calls))
    if not child_ids:
        return content

    references = {}
    for match in _AUTHORED_REF.finditer(content):
        try:
            body = json.loads(match.group("body"))
        except json.JSONDecodeError:
            continue
        if body.get("type") == "authored_results" and isinstance(body.get("embed_id"), str):
            references[match.span()] = body["embed_id"]
    carriers = await asyncio.gather(*(graph.get(embed_id) for embed_id in references.values()))

    source_bindings = map_view_source_bindings_from_tool_calls(calls)
    view = next((match for match in _MAP_VIEW_FENCE_RE.finditer(content)
                 if set(extract_results_view_source_refs(match.group(0))) & source_bindings.keys()), None)
    displayed_children = set().union(*(
        _ids(call.get("result_child_ids")) for call in calls
        if view is not None and set(call.get("source_ref_bindings") or {}) & set(
            extract_results_view_source_refs(view.group(0))
        )
    ))
    remove = []
    extra_refs = []
    for span, node in zip(references, carriers):
        if node is None or node.decoded.get("type") != "authored_results":
            continue
        body = node.decoded
        ordered = (body.get("view") or {}).get("embeds") or body.get("member_ids")
        members = _ids(ordered)
        if not members or not members & child_ids:
            continue
        if members <= child_ids and (view is None or members <= displayed_children):
            remove.append(span)
        elif view is not None and members & displayed_children:
            # References are existing members sealed by the carrier and already
            # readable through the normal encrypted chat. Keep their display order.
            extra_refs.extend(member for member in ordered if member not in displayed_children)
            remove.append(span)

    edits = [(start, end, "") for start, end in remove]
    if view is not None and extra_refs:
        block = view.group(0)
        line = re.search(r"^embeds:[ \t]*(.*)$", block, flags=re.MULTILINE)
        existing = line.group(1).split(",") if line else []
        refs = ", ".join(dict.fromkeys([*(ref.strip() for ref in existing if ref.strip()), *extra_refs]))
        replacement = (block[:line.start()] + "embeds: " + refs + block[line.end():]
                       if line else block[:-3] + "embeds: " + refs + "\n```")
        edits.append((*view.span(), replacement))
    for start, end, replacement in sorted(edits, reverse=True):
        content = content[:start] + replacement + content[end:]
    return content
