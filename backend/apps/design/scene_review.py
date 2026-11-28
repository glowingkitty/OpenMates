"""Render a bounded preview of an editable Design for visual review."""

from __future__ import annotations

from math import ceil, sqrt
from typing import Iterable
from xml.etree.ElementTree import Element, SubElement, tostring

from backend.apps.design.scene import DesignScene, ImageLayer, PathLayer, ShapeLayer, TextLayer

FONT_FAMILIES = {"Sans": "Arial", "Serif": "Georgia", "Mono": "monospace"}
PREVIEW_TILE = 384


def _element(parent: Element, tag: str, **attrs: str | float) -> Element:
    return SubElement(parent, tag, {key.replace("_", "-"): str(value) for key, value in attrs.items()})


def _text_lines(layer: TextLayer) -> tuple[list[str], bool]:
    import cairocffi as cairo

    context = cairo.Context(cairo.ImageSurface(cairo.FORMAT_A8, 1, 1))
    context.select_font_face(
        FONT_FAMILIES[layer.font], cairo.FONT_SLANT_NORMAL,
        cairo.FONT_WEIGHT_BOLD if layer.weight >= 600 else cairo.FONT_WEIGHT_NORMAL,
    )
    context.set_font_size(layer.font_size)
    lines = []
    for paragraph in layer.text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if line and context.text_extents(candidate)[4] > layer.width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    descent = layer.font_size * 0.12
    baseline = layer.font_size * (1 + (len(lines) - 1) * 1.13)
    overflow = baseline + descent > layer.height or any(context.text_extents(line)[4] > layer.width for line in lines)
    return lines, overflow


def _text_parent(parent: Element, layer: TextLayer, clip_id: str, lines: Iterable[str]) -> None:
    clip = _element(parent, "clipPath", id=clip_id)
    _element(clip, "rect", width=layer.width, height=layer.height)
    text = _element(
        parent, "text", x=0, y=layer.font_size, fill=layer.color, font_family=FONT_FAMILIES[layer.font],
        font_size=layer.font_size, font_weight=layer.weight, clip_path=f"url(#{clip_id})",
    )
    for index, line in enumerate(lines):
        _element(text, "tspan", x=0, y=layer.font_size * (1 + index * 1.13)).text = line


def review_preview(scene: DesignScene) -> tuple[str, tuple[str, ...]]:
    """Build safe SVG from typed values and report text that cannot fit its box."""
    columns = ceil(sqrt(len(scene.pages)))
    rows = ceil(len(scene.pages) / columns)
    svg = Element("svg", {
        "xmlns": "http://www.w3.org/2000/svg",
        "viewBox": f"0 0 {columns * PREVIEW_TILE} {rows * PREVIEW_TILE}",
    })
    clips = []
    for index, page in enumerate(scene.pages):
        tile = _element(
            svg, "svg", x=(index % columns) * PREVIEW_TILE, y=(index // columns) * PREVIEW_TILE,
            width=PREVIEW_TILE, height=PREVIEW_TILE, viewBox=f"0 0 {page.width} {page.height}", overflow="hidden",
        )
        _element(tile, "rect", width=page.width, height=page.height, fill=page.background)
        for layer_index, layer in enumerate(page.layers):
            if layer.hidden:
                continue
            transform = f"translate({layer.x} {layer.y}) rotate({layer.rotation} {layer.width / 2} {layer.height / 2})"
            node = _element(tile, "g", transform=transform)
            if isinstance(layer, TextLayer):
                lines, clipped = _text_lines(layer)
                if clipped:
                    clips.append(f"{page.id}/{layer.id}")
                _text_parent(node, layer, f"clip-{index}-{layer_index}", lines)
            elif isinstance(layer, PathLayer):
                _element(node, "path", d=layer.path, fill=layer.color,
                         transform=f"scale({layer.width / layer.view_width} {layer.height / layer.view_height})")
            elif isinstance(layer, ImageLayer):
                # Source photos stay on the client. Review the occupied image box without reading a URL.
                _element(node, "rect", width=layer.width, height=layer.height, fill="#d6d3cc")
            elif isinstance(layer, ShapeLayer) and layer.shape == "ellipse":
                _element(node, "ellipse", cx=layer.width / 2, cy=layer.height / 2,
                         rx=layer.width / 2, ry=layer.height / 2, fill=layer.color)
            elif isinstance(layer, ShapeLayer):
                radius = min(layer.radius or 0, layer.width / 2, layer.height / 2)
                _element(node, "rect", width=layer.width, height=layer.height, rx=radius, fill=layer.color)
    return tostring(svg, encoding="unicode"), tuple(clips)


def missing_copy(scene: DesignScene, required_copy: Iterable[str]) -> tuple[str, ...]:
    """Check literal words in visible layers independently of the raster evaluator."""
    def normalized(value: str) -> str:
        return " ".join(value.casefold().split())

    visible = [
        normalized(layer.text)
        for page in scene.pages
        for layer in page.layers
        if isinstance(layer, TextLayer) and not layer.hidden
    ]
    return tuple(text for text in required_copy if not any(normalized(text) in layer for layer in visible))
