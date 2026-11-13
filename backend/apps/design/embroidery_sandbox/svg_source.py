"""Structural scan of the source SVG with the standard library only.

Finds what the fixed rules cannot sew (gradients, filters, live text, embedded
pixel images) and resolves gradient and pattern paint servers to one flat colour
so the geometry stage can still sew such a shape and name the change in the notes.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .limits import PipelineError, check_source_size

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
PAINT_SERVER_TAGS = {"linearGradient", "radialGradient", "pattern", "meshgradient"}
URL_RE = re.compile(r"url\(\s*['\"]?#([^)'\"\s]+)['\"]?\s*\)")
HEX_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
RGB_RE = re.compile(r"^rgb\(\s*(\d+)%?\s*,\s*(\d+)%?\s*,\s*(\d+)%?\s*\)$")
NAMED_COLOURS = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000",
    "blue": "#0000ff", "yellow": "#ffff00", "gray": "#808080", "grey": "#808080",
    "orange": "#ffa500", "purple": "#800080", "navy": "#000080", "teal": "#008080",
}


@dataclass
class SourceScan:
    """What the standard-library pass found in the source SVG."""

    paint_colours: dict[str, str] = field(default_factory=dict)
    uses_paint_server: bool = False
    uses_filter: bool = False
    text_snippets: list[str] = field(default_factory=list)
    image_count: int = 0


def local_name(tag: str) -> str:
    """Strip an XML namespace from a tag name."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def style_map(element: ET.Element) -> dict[str, str]:
    """Merge presentation attributes with the inline style (style wins)."""
    values = {key: value for key, value in element.attrib.items() if "}" not in key}
    for declaration in element.attrib.get("style", "").split(";"):
        if ":" in declaration:
            key, value = declaration.split(":", 1)
            values[key.strip()] = value.strip()
    return values


def normalise_colour(value: str | None) -> str | None:
    """Return a #rrggbb colour for hex, rgb() and a few named colours, else None."""
    if not value:
        return None
    text = value.strip().lower()
    if text in NAMED_COLOURS:
        return NAMED_COLOURS[text]
    match = HEX_RE.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(ch * 2 for ch in digits)
        return "#" + digits
    match = RGB_RE.match(text)
    if match:
        channels = [max(0, min(255, int(part))) for part in match.groups()]
        if "%" in text:
            channels = [round(c * 2.55) for c in channels]
        return "#" + "".join(f"{c:02x}" for c in channels)
    return None


def average_colour(colours: list[str]) -> str:
    """Average #rrggbb colours channel by channel (rounded)."""
    channels = [[int(colour[i:i + 2], 16) for i in (1, 3, 5)] for colour in colours]
    mean = [round(sum(row[i] for row in channels) / len(channels)) for i in range(3)]
    return "#" + "".join(f"{c:02x}" for c in mean)


def _stop_colours(server: ET.Element) -> list[str]:
    colours: list[str] = []
    for stop in server.iter():
        if local_name(stop.tag) != "stop":
            continue
        colour = normalise_colour(style_map(stop).get("stop-color", "#000000"))
        if colour:
            colours.append(colour)
    return colours


def _paint_colours(root: ET.Element) -> dict[str, str]:
    """Map every paint server id to one flat colour (average of its stops)."""
    servers = {
        element.attrib["id"]: element
        for element in root.iter()
        if local_name(element.tag) in PAINT_SERVER_TAGS and "id" in element.attrib
    }
    resolved: dict[str, str] = {}
    for server_id, server in servers.items():
        current, seen = server, set()
        colours = _stop_colours(current)
        while not colours and current is not None and server_id not in seen:
            seen.add(server_id)
            href = current.attrib.get("href") or current.attrib.get(XLINK_HREF) or ""
            current = servers.get(href.lstrip("#"))
            colours = _stop_colours(current) if current is not None else []
        if colours:
            resolved[server_id] = average_colour(colours)
        else:
            # A pattern without stops: sew it in the first solid fill it contains.
            fills = [normalise_colour(style_map(child).get("fill")) for child in server.iter()]
            solid = [fill for fill in fills if fill]
            resolved[server_id] = solid[0] if solid else "#808080"
    return resolved


def parse_root(svg_text: str) -> ET.Element:
    """Parse the source after the size check; raise unreadable_svg on bad input."""
    check_source_size(svg_text)
    if "<!ENTITY" in svg_text:
        raise PipelineError("unreadable_svg", "The graphic declares XML entities, which are not allowed.")
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise PipelineError("unreadable_svg", f"The graphic is not valid SVG ({exc}).") from exc
    if local_name(root.tag) != "svg":
        raise PipelineError("unreadable_svg", "The graphic does not start with an <svg> element.")
    return root


def scan_source(svg_text: str) -> SourceScan:
    """Scan the source for features the fixed rules cannot sew as drawn."""
    root = parse_root(svg_text)
    scan = SourceScan(paint_colours=_paint_colours(root))
    in_defs: set[int] = set()
    for element in root.iter():
        if local_name(element.tag) in {"defs", "clipPath", "mask", "symbol", "marker"}:
            in_defs.update(id(child) for child in element.iter() if child is not element)
    for element in root.iter():
        name = local_name(element.tag)
        if id(element) in in_defs:
            continue
        styles = style_map(element)
        for key in ("fill", "stroke"):
            match = URL_RE.search(styles.get(key, ""))
            if match and match.group(1) in scan.paint_colours:
                scan.uses_paint_server = True
        if URL_RE.search(styles.get("filter", "")) or URL_RE.search(styles.get("mask", "")):
            scan.uses_filter = True
        if name == "text":
            text = " ".join("".join(element.itertext()).split())
            if text:
                scan.text_snippets.append(text[:80])
        elif name == "image":
            scan.image_count += 1
    return scan


def findings_from_scan(scan: SourceScan) -> list[dict[str, str]]:
    """Rework findings that the structural scan alone can decide."""
    findings: list[dict[str, str]] = []
    if scan.uses_paint_server or scan.uses_filter:
        parts = []
        if scan.uses_paint_server:
            parts.append("a gradient or pattern fill")
        if scan.uses_filter:
            parts.append("a filter or mask effect")
        findings.append({"code": "gradient_or_filter", "detail": "The graphic uses " + " and ".join(parts) + "."})
    if scan.text_snippets:
        quoted = "; ".join(f'"{snippet}"' for snippet in scan.text_snippets[:3])
        findings.append({"code": "live_text", "detail": f"Live text is not drawn as shapes: {quoted}."})
    if scan.image_count:
        findings.append({
            "code": "embedded_pixel_image",
            "detail": f"The graphic embeds {scan.image_count} pixel image(s), which cannot be sewn.",
        })
    return findings
