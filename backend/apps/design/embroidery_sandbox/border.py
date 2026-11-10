"""Sew-on border: one filled band around the whole prepared design (shapely).

Assertion design-embroidery.prepare.sew-on-border. All values are millimetres at
the sewn size, after the fixed rules have ordered the design's shapes:

1. The silhouette is the union of everything that is sewn: fills, satin bands
   (with their caps) and running lines widened to RUNNING_HALF_WIDTH_MM.
2. The outline is the silhouette grown outward by ``border_mm`` with round
   joins. Growing by ``b`` closes every gap or opening of the design narrower
   than ``2 b`` (it equals a morphological closing followed by the growth), while
   a wider opening keeps a hole that is ``2 b`` narrower. Holes and notches the
   growth leaves narrower than MIN_OPENING_MM are closed too, so no unsewable
   slit of fabric remains.
3. The border is the outline minus the design's interior, where the interior is
   the silhouette shrunk by BORDER_OVERLAP_MM. So the border covers the band,
   the filled gaps and a strip under the design's edge (the design overlaps it
   and no fabric shows between them), but is never sewn under the whole design.
4. Everything is moved so the outline starts at the page margin; the border is
   sewn first and the page grows by the border on every side.
"""

from __future__ import annotations

from dataclasses import replace

from shapely import affinity
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .geometry import MARGIN_MM, Prepared, Shape2D, clean_area, finish_order
from .limits import PipelineError
from .ordering import colour_changes

# Width of the strip under the design's edge that the border keeps (the design overlaps it).
BORDER_OVERLAP_MM = 0.45
# A running line counts as this wide (each side) when the silhouette is built.
RUNNING_HALF_WIDTH_MM = 0.3
# Holes and notches the grown outline leaves narrower than this are filled.
MIN_OPENING_MM = 1.0
# Shape2D.index of the border (source shapes count from 2).
BORDER_INDEX = -1


def _sewn_area(shape: Shape2D) -> BaseGeometry:
    if shape.kind == "fill":
        return shape.geom
    if shape.kind == "satin":
        cap = {"round": "round", "square": "square"}.get(shape.linecap, "flat")
        return shape.geom.buffer(shape.width / 2, cap_style=cap)
    return shape.geom.buffer(max(shape.width / 2, RUNNING_HALF_WIDTH_MM))


def design_silhouette(shapes: list[Shape2D]) -> BaseGeometry:
    """Union of everything sewn, as an area."""
    return unary_union([_sewn_area(shape) for shape in shapes])


def border_outline(silhouette: BaseGeometry, border_mm: float) -> BaseGeometry:
    """Silhouette grown by ``border_mm`` (round), with slits narrower than MIN_OPENING_MM closed."""
    grown = silhouette.buffer(border_mm, join_style="round")
    radius = MIN_OPENING_MM / 2
    return grown.buffer(radius, join_style="round").buffer(-radius, join_style="round").union(grown)


def border_area(silhouette: BaseGeometry, border_mm: float) -> BaseGeometry:
    """The band, the filled gaps and the overlap strip under the design's edge."""
    interior = silhouette.buffer(-BORDER_OVERLAP_MM, join_style="mitre")
    return clean_area(border_outline(silhouette, border_mm).difference(interior))


def border_note(border_mm: float) -> dict[str, str | float]:
    """Plain-language note; ``mm`` is the width the translations insert."""
    return {"code": "border_added", "mm": border_mm, "text": f"Border of {border_mm:g} mm added for sewing on"}


def apply_border(prepared: Prepared, border_mm: float, colour: str) -> Prepared:
    """Return the prepared design with the border sewn first, moved to the margin, on a grown page."""
    silhouette = design_silhouette(prepared.shapes)
    outline = border_outline(silhouette, border_mm)
    border = border_area(silhouette, border_mm)
    if border.is_empty:
        raise PipelineError("sandbox_failed", "The sew-on border could not be built for this design.")
    x0, y0, x1, y1 = outline.bounds
    dx, dy = MARGIN_MM - x0, MARGIN_MM - y0
    moved = [replace(shape, geom=affinity.translate(shape.geom, dx, dy)) for shape in prepared.shapes]
    shapes = [Shape2D(BORDER_INDEX, colour, "fill", affinity.translate(border, dx, dy)), *moved]
    finish_order(shapes)
    technical = {**prepared.technical, "border_area_mm2": int(border.area),
                 "thread_changes_grouped": colour_changes([shape.colour for shape in shapes])}
    return replace(prepared, shapes=shapes, width_mm=x1 - x0, height_mm=y1 - y0,
                   notes=[*prepared.notes, border_note(border_mm)], technical=technical)
