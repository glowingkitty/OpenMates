# backend/apps/ai/utils/mindmap_fences.py
#
# Helpers for OpenMates Mind Maps fenced JSON blocks.
#
# The generation contract is intentionally strict at the creation/import
# boundary: only explicit OpenMates mind map JSON becomes a Mind Maps embed.
# The renderer can still show partially valid maps, but backend creation never
# invents labels, IDs, or relationships.

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional


MINDMAP_FENCE_LANGUAGES = {"openmates_mindmap", "ommindmap"}
SUPPORTED_SCHEMA_VERSION = 1
INVALID_CONTENT_LABEL = "Invalid content"


@dataclass(frozen=True)
class MindMapNormalizationResult:
    status: str
    model: dict[str, Any] | None
    source_json: str
    title: str
    node_count: int
    edge_count: int
    warnings: list[dict[str, str]]
    parse_error: str | None = None


def is_mindmap_fence(language: Optional[str]) -> bool:
    return (language or "").strip().lower() in MINDMAP_FENCE_LANGUAGES


def normalize_mindmap_source(source: str) -> MindMapNormalizationResult:
    try:
        raw = json.loads(source)
    except json.JSONDecodeError as exc:
        return MindMapNormalizationResult(
            status="invalid_source",
            model=None,
            source_json=source,
            title="Invalid mind map JSON",
            node_count=0,
            edge_count=0,
            warnings=[],
            parse_error=f"Invalid mind map JSON: {exc.msg}",
        )

    if not isinstance(raw, dict):
        return _invalid_structure(source, "root_not_object")
    if raw.get("openmatesType") != "mindmap":
        return _invalid_structure(source, "missing_openmates_type")
    if raw.get("schemaVersion") != SUPPORTED_SCHEMA_VERSION:
        return _invalid_structure(source, "unsupported_schema")

    warnings: list[dict[str, str]] = []
    title = _string_value(raw.get("title")) or "Mind Map"
    root_id = _string_value(raw.get("rootId")) or ""
    nodes = raw.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return _invalid_structure(source, "missing_nodes", title)

    normalized_nodes: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            warnings.append({"code": "invalid_node", "path": f"nodes[{index}]"})
            continue
        node_id = _string_value(node.get("id"))
        if not node_id:
            warnings.append({"code": "missing_node_id", "path": f"nodes[{index}]"})
            continue
        if node_id in seen_node_ids:
            warnings.append({"code": "duplicate_node_id", "path": f"nodes[{index}]"})
            continue
        seen_node_ids.add(node_id)

        label = _string_value(node.get("label"))
        if not label:
            label = INVALID_CONTENT_LABEL
            warnings.append({"code": "missing_label", "path": f"nodes[{index}].label"})

        normalized_node: dict[str, Any] = {"id": node_id, "label": label}
        for key in ("description", "color", "icon"):
            value = _string_value(node.get(key))
            if value:
                normalized_node[key] = value
        children = node.get("children")
        if isinstance(children, list):
            normalized_children = [child for child in children if isinstance(child, str) and child]
            missing_children = [child for child in normalized_children if child not in seen_node_ids]
            if missing_children:
                # A child can legally appear later in the node list, so validate after the full set is known.
                normalized_node["children"] = normalized_children
            elif normalized_children:
                normalized_node["children"] = normalized_children
        normalized_nodes.append(normalized_node)

    if not normalized_nodes:
        return _invalid_structure(source, "missing_valid_nodes", title)

    known_ids = {node["id"] for node in normalized_nodes}
    if root_id not in known_ids:
        warnings.append({"code": "missing_root", "path": "rootId"})
        root_id = normalized_nodes[0]["id"] if normalized_nodes else ""

    for node in normalized_nodes:
        children = node.get("children")
        if not isinstance(children, list):
            continue
        valid_children = [child for child in children if child in known_ids]
        if len(valid_children) != len(children):
            warnings.append({"code": "missing_child", "path": f"nodes.{node['id']}.children"})
        if valid_children:
            node["children"] = valid_children
        else:
            node.pop("children", None)

    normalized_edges = _normalize_edges(raw.get("edges"), known_ids, warnings)
    model = {
        "openmatesType": "mindmap",
        "schemaVersion": SUPPORTED_SCHEMA_VERSION,
        "title": title,
        "rootId": root_id,
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "view": _normalize_view(raw.get("view")),
    }
    source_json = json.dumps(model, ensure_ascii=False, indent=2)
    return MindMapNormalizationResult(
        status="partial" if warnings else "valid",
        model=model,
        source_json=source_json,
        title=title,
        node_count=len(normalized_nodes),
        edge_count=len(normalized_edges),
        warnings=warnings,
    )


def _invalid_structure(source: str, code: str, title: str = "Invalid mind map JSON") -> MindMapNormalizationResult:
    return MindMapNormalizationResult(
        status="invalid_source",
        model=None,
        source_json=source,
        title=title,
        node_count=0,
        edge_count=0,
        warnings=[{"code": code, "path": "$"}],
        parse_error=title,
    )


def _normalize_edges(value: Any, known_ids: set[str], warnings: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    edges: list[dict[str, str]] = []
    for index, edge in enumerate(value):
        if not isinstance(edge, dict):
            warnings.append({"code": "invalid_edge", "path": f"edges[{index}]"})
            continue
        source = _string_value(edge.get("source"))
        target = _string_value(edge.get("target"))
        if source not in known_ids:
            warnings.append({"code": "missing_edge_source", "path": f"edges[{index}].source"})
            continue
        if target not in known_ids:
            warnings.append({"code": "missing_edge_target", "path": f"edges[{index}].target"})
            continue
        normalized = {"source": source, "target": target}
        edge_type = _string_value(edge.get("type"))
        if edge_type:
            normalized["type"] = edge_type
        label = _string_value(edge.get("label"))
        if label:
            normalized["label"] = label
        edges.append(normalized)
    return edges


def _normalize_view(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"layout": "radial-tree", "collapsedNodeIds": []}
    layout = _string_value(value.get("layout")) or "radial-tree"
    collapsed = value.get("collapsedNodeIds")
    collapsed_ids = [item for item in collapsed if isinstance(item, str)] if isinstance(collapsed, list) else []
    return {"layout": layout, "collapsedNodeIds": collapsed_ids}


def _string_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
