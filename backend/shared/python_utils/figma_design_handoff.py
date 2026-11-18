# backend/shared/python_utils/figma_design_handoff.py
#
# Turns Figma API node trees into compact design data and a code handoff.
# Vector geometry is dropped; design tokens use only values present in the file
# (styles, variables); anything that cannot be mapped is listed in notes.
#
# Spec: specifications/features/app-skills/design-figma/specification.yml

from __future__ import annotations

import re
from typing import Any

IMAGE_URL_EXPIRY_DAYS = 30
DEFAULT_MAX_NODES = 800
_SCREEN_TYPES = frozenset({"FRAME", "COMPONENT", "COMPONENT_SET", "SECTION"})
_LAYOUT_KEYS = (
    "layoutMode", "itemSpacing", "paddingLeft", "paddingRight", "paddingTop", "paddingBottom",
    "primaryAxisAlignItems", "counterAxisAlignItems",
)
_TEXT_KEYS = (
    "fontFamily", "fontWeight", "fontSize", "lineHeightPx", "letterSpacing", "textAlignHorizontal",
)
_SPACING_HINTS = ("spacing", "space", "gap", "padding", "margin", "radius", "radii", "rounded", "corner")


def to_hex(color: dict[str, Any]) -> str:
    channels = [max(0, min(255, round(float(color.get(key, 0)) * 255))) for key in ("r", "g", "b")]
    return "#" + "".join(f"{value:02x}" for value in channels)


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else round(float(value), 3)


def _paint(paint: dict[str, Any]) -> dict[str, Any] | None:
    if paint.get("visible") is False:
        return None
    kind = paint.get("type", "")
    opacity = paint.get("opacity", 1)
    if kind == "SOLID":
        color = paint.get("color", {})
        return {"type": "solid", "color": to_hex(color), "opacity": _number(opacity * color.get("a", 1))}
    if kind.startswith("GRADIENT"):
        stops = [to_hex(stop.get("color", {})) for stop in paint.get("gradientStops", [])]
        return {"type": kind.lower(), "stops": stops, "opacity": _number(opacity)}
    if kind == "IMAGE":
        return {"type": "image", "scale_mode": paint.get("scaleMode")}
    return {"type": kind.lower()}


def _paints(items: Any) -> list[dict[str, Any]]:
    return [p for p in (_paint(item) for item in items or [] if isinstance(item, dict)) if p]


def _effects(items: Any) -> list[dict[str, Any]]:
    result = []
    for effect in items or []:
        if not isinstance(effect, dict) or effect.get("visible") is False:
            continue
        item: dict[str, Any] = {"type": str(effect.get("type", "")).lower()}
        if "color" in effect:
            item["color"] = to_hex(effect["color"])
            item["opacity"] = _number(effect["color"].get("a", 1))
        offset = effect.get("offset") or {}
        for source, target in (("radius", "blur"), ("spread", "spread")):
            if source in effect:
                item[target] = _number(effect[source])
        if offset:
            item["x"], item["y"] = _number(offset.get("x", 0)), _number(offset.get("y", 0))
        result.append(item)
    return result


def _simplify_one(node: dict[str, Any], parent_id: str | None) -> dict[str, Any]:
    box = node.get("absoluteBoundingBox") or {}
    item: dict[str, Any] = {
        "id": node.get("id"), "name": node.get("name"), "type": node.get("type"),
        "parent_id": parent_id,
        "width": box.get("width"), "height": box.get("height"), "x": box.get("x"), "y": box.get("y"),
    }
    layout = {key: node[key] for key in _LAYOUT_KEYS if key in node}
    if layout:
        item["layout"] = layout
    fills, strokes = _paints(node.get("fills")), _paints(node.get("strokes"))
    if fills:
        item["fills"] = fills
    if strokes:
        item["strokes"] = strokes
        if "strokeWeight" in node:
            item["stroke_weight"] = node["strokeWeight"]
    radius = node.get("cornerRadius", node.get("rectangleCornerRadii"))
    if radius is not None:
        item["corner_radius"] = radius
    effects = _effects(node.get("effects"))
    if effects:
        item["effects"] = effects
    if node.get("type") == "TEXT":
        style = node.get("style") or {}
        text = {"characters": node.get("characters", "")}
        text.update({key: style[key] for key in _TEXT_KEYS if key in style})
        if "textAlignHorizontal" in text:
            text["textAlign"] = text.pop("textAlignHorizontal")
        item["text"] = text
    if node.get("componentId"):
        item["component_id"] = node["componentId"]
    if node.get("styles"):
        item["styles"] = dict(node["styles"])
    return item


def simplify_nodes(
    document: dict[str, Any] | list[dict[str, Any]], max_nodes: int = DEFAULT_MAX_NODES,
) -> tuple[list[dict[str, Any]], bool]:
    """Flatten a node tree (or trees) into compact records; returns (nodes, truncated)."""

    roots = document if isinstance(document, list) else [document]
    flat: list[dict[str, Any]] = []
    truncated = False
    stack: list[tuple[dict[str, Any], str | None]] = [(root, None) for root in reversed(roots) if root]
    while stack:
        node, parent_id = stack.pop()
        if len(flat) >= max_nodes:
            truncated = True
            break
        flat.append(_simplify_one(node, parent_id))
        children = node.get("children") or []
        stack.extend((child, node.get("id")) for child in reversed(children) if isinstance(child, dict))
    return flat, truncated


def list_frames(document: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pages with their top-level frames, components and sections."""

    roots = document if isinstance(document, list) else [document]
    frames: list[dict[str, Any]] = []
    for root in roots:
        pages = root.get("children") or [] if root.get("type") == "DOCUMENT" else [root]
        for page in pages:
            candidates = page.get("children") or [] if page.get("type") == "CANVAS" else [page]
            for child in candidates:
                if child.get("type") in _SCREEN_TYPES:
                    box = child.get("absoluteBoundingBox") or {}
                    frames.append({
                        "id": child.get("id"), "name": child.get("name"), "type": child.get("type"),
                        "page": page.get("name") if page.get("type") == "CANVAS" else None,
                        "width": box.get("width"), "height": box.get("height"),
                    })
    return frames


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "token"


def _variable_value(variable: dict[str, Any], collections: dict[str, Any]) -> Any:
    collection = collections.get(variable.get("variableCollectionId")) or {}
    values = variable.get("valuesByMode") or {}
    return values.get(collection.get("defaultModeId"), next(iter(values.values()), None))


def _text_tokens(slug: str, node: dict[str, Any]) -> list[str]:
    text = node.get("text") or {}
    lines = []
    if "fontFamily" in text:
        lines.append(f"  --{slug}-font-family: \"{text['fontFamily']}\";")
    if "fontSize" in text:
        lines.append(f"  --{slug}-font-size: {_number(text['fontSize'])}px;")
    if "fontWeight" in text:
        lines.append(f"  --{slug}-font-weight: {_number(text['fontWeight'])};")
    if "lineHeightPx" in text:
        lines.append(f"  --{slug}-line-height: {_number(text['lineHeightPx'])}px;")
    return lines


def build_code_handoff(
    file: dict[str, Any], nodes: list[dict[str, Any]], components: dict[str, Any] | None,
    styles: dict[str, Any] | None, variables: dict[str, Any] | None,
    images: dict[str, str | None] | None, frames: list[dict[str, Any]] | None = None,
    image_format: str = "png",
) -> dict[str, Any]:
    """Build tokens, screens, components and assets using only values in the file."""

    components, styles, images = components or {}, styles or {}, images or {}
    notes: list[str] = []
    css: dict[str, str] = {}
    text_lines: list[str] = []
    used: set[str] = set()
    for node in nodes:
        for kind, style_id in (node.get("styles") or {}).items():
            style = styles.get(style_id)
            if not style or style_id in used:
                continue
            slug = slugify(style.get("name", ""))
            if kind == "fill" and (node.get("fills") or [{}])[0].get("type") == "solid":
                used.add(style_id)
                fill = node["fills"][0]
                css[slug] = fill["color"] if fill["opacity"] == 1 else f"{fill['color']}{round(fill['opacity'] * 255):02x}"
            elif kind == "text" and node.get("text"):
                used.add(style_id)
                text_lines.extend(_text_tokens(slug, node))
    for style_id, style in styles.items():
        if style_id not in used:
            notes.append(f"Style '{style.get('name', style_id)}' ({style.get('styleType')}) has no resolved value and was not mapped.")
    meta = (variables or {}).get("meta", variables or {})
    collections = meta.get("variableCollections") or {}
    for variable in (meta.get("variables") or {}).values():
        value, slug = _variable_value(variable, collections), slugify(variable.get("name", ""))
        kind = variable.get("resolvedType")
        if isinstance(value, dict) and value.get("type") == "VARIABLE_ALIAS":
            notes.append(f"Variable '{variable.get('name')}' is an alias and was not mapped.")
        elif kind == "COLOR" and isinstance(value, dict):
            css.setdefault(slug, to_hex(value))
        elif kind == "FLOAT" and isinstance(value, (int, float)) and any(h in slug for h in _SPACING_HINTS):
            css.setdefault(slug, f"{_number(value)}px")
        else:
            notes.append(f"Variable '{variable.get('name')}' ({kind}) was not mapped to a token.")
    lines = [f"  --{slug}: {value};" for slug, value in css.items()] + text_lines
    tokens_css = ":root {\n" + "\n".join(lines) + "\n}" if lines else ""
    screens = [
        {"node_id": f["id"], "name": f["name"], "width": f.get("width"), "height": f.get("height"),
         "image_url": images.get(f["id"])}
        for f in (frames or []) if f.get("id")
    ]
    assets = [
        {"node_id": node_id, "url": url, "format": image_format, "expires_in_days": IMAGE_URL_EXPIRY_DAYS}
        for node_id, url in images.items() if url
    ]
    if assets:
        notes.append(f"Image URLs expire after {IMAGE_URL_EXPIRY_DAYS} days; copy the assets into the project now.")
    if not tokens_css:
        notes.append("No tokens could be derived; read values from the nodes and do not invent any.")
    return {
        "tokens_css": tokens_css, "screens": screens,
        "components": [
            {"id": cid, "key": c.get("key"), "name": c.get("name"), "description": c.get("description", "")}
            for cid, c in components.items()
        ],
        "assets": assets, "notes": notes,
    }
