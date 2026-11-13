"""Write the prepared graphic as an Ink/Stitch-ready SVG in real millimetres.

The document is ``width x height`` mm with a matching viewBox, so one user unit
is one millimetre for Ink/Stitch. Elements appear in sewing order (Ink/Stitch
sews in document order) and carry the ``inkstitch:`` parameters of the fabric
preset. The same file is delivered as ``prepared_svg``.
"""

from __future__ import annotations

from xml.sax.saxutils import quoteattr

from .geometry import Prepared, Shape2D, multipolygon_rings
from .presets import fill_params, running_params, satin_params

INKSTITCH_NS = "http://inkstitch.org/namespace"
# Palette name as Ink/Stitch reads it from "InkStitch Madeira Polyneon.gpl" (prefix stripped).
THREAD_PALETTE = "Madeira Polyneon"
COLLAPSE_LEN_MM = 3.0
# Without the current document version Ink/Stitch opens a GUI "update this file?" dialog,
# which fails headless (lib/update.py, INKSTITCH_SVG_VERSION at v3.3.0).
INKSTITCH_SVG_VERSION = 4
# Page colour = background of Ink/Stitch's realistic render, so white thread stays visible.
FABRIC_COLOUR = "#f4f1ea"


def _num(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _ring_path(rings: list[list[tuple[float, float]]]) -> str:
    parts = []
    for ring in rings:
        if len(ring) < 3:
            continue
        head, *rest = ring[:-1] if ring[0] == ring[-1] else ring
        parts.append(f"M{_num(head[0])} {_num(head[1])}" + "".join(f"L{_num(x)} {_num(y)}" for x, y in rest) + "Z")
    return "".join(parts)


def _line_path(coords: list[tuple[float, float]]) -> str:
    head, *rest = coords
    closed = len(coords) > 2 and coords[0] == coords[-1]
    body = rest[:-1] if closed else rest
    return (f"M{_num(head[0])} {_num(head[1])}" + "".join(f"L{_num(x)} {_num(y)}" for x, y in body)
            + ("Z" if closed else ""))


def _attrs(params: dict[str, str]) -> str:
    return "".join(f" inkstitch:{key}={quoteattr(value)}" for key, value in params.items())


def _element(number: int, shape: Shape2D, fabric: str) -> str:
    element_id = f"s{number:04d}"
    if shape.kind == "fill":
        path = _ring_path(multipolygon_rings(shape.geom))
        style = f"fill:{shape.colour};fill-rule:evenodd;stroke:none"
        params = fill_params(fabric, shape.angle)
    elif shape.rails is not None:
        # Two rails with equally many points: Ink/Stitch pairs them point by point.
        path = "".join(_line_path(list(rail.coords)) for rail in shape.rails)
        style = f"fill:none;stroke:{shape.colour};stroke-width:0.3;stroke-linejoin:round;stroke-linecap:butt"
        params = satin_params(fabric, shape.width)
    else:
        path = _line_path(list(shape.geom.coords))
        style = (f"fill:none;stroke:{shape.colour};stroke-width:{_num(max(shape.width, 0.1))};"
                 "stroke-linejoin:round;stroke-linecap:" + ("round" if shape.linecap == "round" else "butt"))
        params = satin_params(fabric, shape.width) if shape.kind == "satin" else running_params(shape.width)
    if shape.trim_after:
        params["trim_after"] = "true"
    return f'<path id="{element_id}" d="{path}" style="{style}"{_attrs(params)}/>'


def write_prepared_svg(prepared: Prepared, fabric: str) -> str:
    """Serialise the prepared shapes; returns UTF-8 SVG text."""
    width = prepared.width_mm + 2.0
    height = prepared.height_mm + 2.0
    body = "\n".join(_element(k + 1, shape, fabric) for k, shape in enumerate(prepared.shapes))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkstitch="{INKSTITCH_NS}" '
        'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" '
        f'width="{_num(width)}mm" height="{_num(height)}mm" viewBox="0 0 {_num(width)} {_num(height)}">\n'
        f'<metadata><inkstitch:inkstitch_svg_version>{INKSTITCH_SVG_VERSION}</inkstitch:inkstitch_svg_version>'
        f'<inkstitch:thread-palette>"{THREAD_PALETTE}"</inkstitch:thread-palette>'
        f"<inkstitch:collapse_len_mm>{COLLAPSE_LEN_MM:g}</inkstitch:collapse_len_mm>"
        "<inkstitch:min_stitch_len_mm>0.1</inkstitch:min_stitch_len_mm></metadata>\n"
        f'<sodipodi:namedview id="namedview" pagecolor="{FABRIC_COLOUR}" inkscape:pageopacity="1"/>\n'
        '<g id="embroidery" inkscape:groupmode="layer" inkscape:label="Embroidery">\n'
        f"{body}\n</g>\n</svg>\n"
    )
