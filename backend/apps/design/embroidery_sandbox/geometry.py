"""Read SVG shapes into millimetre geometry and apply the fixed preparation rules.

Needs the template's svgelements and shapely. Rules run in the order of the
Specification (design-embroidery.prepare.fixed-rules): scale to width, drop a
full-canvas background, cut hidden overlaps, group thread colours, split lines
into satin bands and running stitches. Fabric presets are applied when the
prepared SVG is written (``prepared_svg``).
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree
from svgelements import SVG, Close, Color, Line, Move, Shape, Text

from .bands import find_bands
from .limits import MIN_DETAIL_MM, PipelineError
from .ordering import OrderItem, colour_changes, plan_order
from .presets import SATIN_MIN_WIDTH_MM
from .svg_source import SourceScan, URL_RE

BACKGROUND_COVERAGE = 0.95
OVERLAP_MM = 0.4
MIN_PIECE_AREA_MM2 = 0.4
MIN_PIECE_WIDTH_MM = 0.5
MIN_LINE_LENGTH_MM = 1.0
CURVE_STEP_MM = 0.25
SIMPLIFY_MM = 0.03
MARGIN_MM = 1.0
# A jump to the next shape of the same thread longer than this gets a trim first,
# so no connecting stitch is left lying across the fabric between separate shapes.
TRIM_DISTANCE_MM = 1.0
# A fill whose mean width (2 x area / outline length) is below this is sewn across its length.
NARROW_BAND_MM = 3.0


@dataclass
class Shape2D:
    """One sewable layer of a source element (its fill or its stroke)."""

    index: int
    colour: str
    kind: str  # "fill", "satin" or "running"
    geom: BaseGeometry
    width: float = 0.0
    linecap: str = "butt"
    flattened_paint: bool = False
    angle: float = 0.0
    trim_after: bool = False
    # A band sewn as a satin column of varying width: its two long sides, tip to tip.
    rails: tuple[LineString, LineString] | None = None

    def centre(self) -> tuple[float, float]:
        point = self.geom.representative_point() if self.kind == "fill" else self.geom.centroid
        return (round(point.x, 3), round(point.y, 3))


@dataclass
class Prepared:
    """Result of the fixed rules: shapes in sewing order plus what changed."""

    shapes: list[Shape2D]
    width_mm: float
    height_mm: float
    notes: list[dict[str, str | int | float]] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)
    colour_count: int = 0
    shape_count: int = 0
    # Changes that alter nothing the user sees; reported in the run metrics, not as notes.
    technical: dict[str, int] = field(default_factory=dict)


def _hex(colour: Color | None) -> str | None:
    if colour is None or colour.value is None or colour.alpha == 0:
        return None
    return f"#{colour.red:02x}{colour.green:02x}{colour.blue:02x}"


def _paint(element: Shape, key: str, scan: SourceScan) -> tuple[str | None, bool]:
    raw = str(element.values.get(key, "") or "")
    match = URL_RE.search(raw)
    if match:
        colour = scan.paint_colours.get(match.group(1))
        return colour, colour is not None
    opacity = float(element.values.get(f"{key}-opacity", 1) or 1) * float(element.values.get("opacity", 1) or 1)
    if opacity < 0.05:
        return None, False
    return _hex(element.fill if key == "fill" else element.stroke), False


def _flatten(element: Shape, step: float) -> list[tuple[list[tuple[float, float]], bool]]:
    """Return subpaths as (points, closed) with curves sampled every ``step`` units."""
    subpaths: list[tuple[list[tuple[float, float]], bool]] = []
    points: list[tuple[float, float]] = []
    closed = False
    for segment in element.segments(transformed=True):
        if isinstance(segment, Move):
            if len(points) > 1:
                subpaths.append((points, closed))
            points, closed = [(segment.end.x, segment.end.y)], False
            continue
        if segment.start is not None and not points:
            points = [(segment.start.x, segment.start.y)]
        if isinstance(segment, Close):
            closed = True
            if len(points) > 1:
                subpaths.append((points, True))
            points, closed = [(segment.end.x, segment.end.y)] if segment.end is not None else [], False
            continue
        if isinstance(segment, Line):
            points.append((segment.end.x, segment.end.y))
            continue
        length = segment.length(error=1e-4)
        count = max(2, min(256, math.ceil(length / step)))
        for i in range(1, count + 1):
            point = segment.point(i / count)
            points.append((point.x, point.y))
    if len(points) > 1:
        subpaths.append((points, closed))
    return subpaths


def _rings_to_area(rings: list[list[tuple[float, float]]], evenodd: bool) -> BaseGeometry:
    polygons: list[tuple[Polygon, float]] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        polygon = shapely.make_valid(Polygon(ring))
        area = polygon.area
        if area <= 0:
            continue
        signed = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]))
        polygons.append((polygon, math.copysign(1.0, signed)))
    if not polygons:
        return Polygon()
    if evenodd:
        result: BaseGeometry = Polygon()
        for polygon, _ in polygons:
            result = result.symmetric_difference(polygon)
        return result
    polygons.sort(key=lambda item: -item[0].area)
    result = Polygon()
    placed: list[tuple[Polygon, float]] = []
    for polygon, sign in polygons:
        probe = polygon.representative_point()
        parents = [item for item in placed if item[0].contains(probe)]
        parent = min(parents, key=lambda item: item[0].area) if parents else None
        if parent is not None and parent[1] != sign:
            result = result.difference(polygon)
        else:
            result = result.union(polygon)
        placed.append((polygon, sign))
    return result


def _polygons(geom: BaseGeometry) -> list[Polygon]:
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty else []
    if hasattr(geom, "geoms"):
        return [part for sub in geom.geoms for part in _polygons(sub)]
    return []


def _lines(geom: BaseGeometry) -> list[LineString]:
    if isinstance(geom, LineString):
        return [geom] if not geom.is_empty else []
    if hasattr(geom, "geoms"):
        return [part for sub in geom.geoms for part in _lines(sub)]
    return []


@dataclass
class _Source:
    shapes: list[Shape2D]
    canvas: Polygon
    text_sizes: list[float]
    unit_mm_guess: float


def read_shapes(svg_text: str, scan: SourceScan, width_mm: float) -> _Source:
    """Parse drawable shapes in source units; fills and strokes become separate layers."""
    try:
        document = SVG.parse(io.StringIO(svg_text), reify=True)
    except (ValueError, TypeError, AttributeError, IndexError, KeyError) as exc:
        raise PipelineError("unreadable_svg", f"The SVG could not be parsed ({type(exc).__name__}).") from exc
    canvas_w = float(document.width or 0) or 1.0
    canvas_h = float(document.height or 0) or 1.0
    bbox = document.bbox()
    span = max((bbox[2] - bbox[0]) if bbox else canvas_w, 1e-6)
    unit_mm = width_mm / span
    step = CURVE_STEP_MM / unit_mm
    shapes: list[Shape2D] = []
    text_sizes: list[float] = []
    order = 0
    for element in document.elements():
        values = getattr(element, "values", {}) or {}
        if values.get("display") == "none" or values.get("visibility") in ("hidden", "collapse"):
            continue
        if isinstance(element, Text):
            scale = math.sqrt(abs(element.transform.determinant)) if element.transform else 1.0
            text_sizes.append(float(element.font_size or 16.0) * scale)
            continue
        if not isinstance(element, Shape):
            continue
        subpaths = _flatten(element, step)
        if not subpaths:
            continue
        order += 1
        fill, fill_flat = _paint(element, "fill", scan)
        if fill:
            evenodd = str(values.get("fill-rule", "nonzero")).strip() == "evenodd"
            area = _rings_to_area([points for points, _ in subpaths], evenodd)
            if area.area > 0:
                shapes.append(Shape2D(order * 2, fill, "fill", area, flattened_paint=fill_flat))
        stroke, stroke_flat = _paint(element, "stroke", scan)
        width = float(element.stroke_width or 0)
        if stroke and width > 0:
            lines = [LineString(points + ([points[0]] if closed else [])) for points, closed in subpaths]
            cap = str(values.get("stroke-linecap", "butt")).strip()
            shapes.append(Shape2D(order * 2 + 1, stroke, "stroke", MultiLineString(lines), width=width,
                                  linecap=cap, flattened_paint=stroke_flat))
    return _Source(shapes, Polygon([(0, 0), (canvas_w, 0), (canvas_w, canvas_h), (0, canvas_h)]),
                   text_sizes, unit_mm)


def _drop_background(source: _Source) -> int:
    """Drop bottom-most fills that only cover the whole canvas; return how many."""
    dropped = 0
    canvas_area = source.canvas.area
    while source.shapes:
        bottom = source.shapes[0]
        if bottom.kind != "fill":
            break
        coverage = bottom.geom.intersection(source.canvas).area / canvas_area
        if coverage < BACKGROUND_COVERAGE:
            break
        source.shapes.pop(0)
        dropped += 1
    return dropped


def _scale(source: _Source, width_mm: float) -> tuple[float, float]:
    """Scale all layers so the drawn extent is ``width_mm`` wide; return (w, h) in mm."""
    bounds = []
    for shape in source.shapes:
        x0, y0, x1, y1 = shape.geom.bounds
        pad = shape.width / 2 if shape.kind == "stroke" else 0.0
        bounds.append((x0 - pad, y0 - pad, x1 + pad, y1 + pad))
    x0 = min(b[0] for b in bounds)
    y0 = min(b[1] for b in bounds)
    x1 = max(b[2] for b in bounds)
    y1 = max(b[3] for b in bounds)
    factor = width_mm / max(x1 - x0, 1e-9)
    matrix = [factor, 0, 0, factor, MARGIN_MM - x0 * factor, MARGIN_MM - y0 * factor]
    for shape in source.shapes:
        shape.geom = affinity.affine_transform(shape.geom, matrix).simplify(SIMPLIFY_MM)
        shape.width *= factor
    source.text_sizes = [size * factor for size in source.text_sizes]
    return width_mm, (y1 - y0) * factor


def clean_area(geom: BaseGeometry) -> BaseGeometry:
    """Remove slivers and crumbs that cannot be sewn (opening + minimum area)."""
    if geom.is_empty:
        return geom
    radius = MIN_PIECE_WIDTH_MM / 2
    opened = geom.buffer(-radius, join_style="mitre").buffer(radius, join_style="mitre").intersection(geom)
    parts = [part for part in _polygons(opened) if part.area >= MIN_PIECE_AREA_MM2]
    return unary_union(parts) if parts else Polygon()


def detail_findings(shapes: list[Shape2D], text_sizes: list[float]) -> list[dict[str, str]]:
    """Report fills narrower than 1 mm and live text below 1 mm (after scaling)."""
    small = 0
    for shape in shapes:
        if shape.kind == "fill" and shape.geom.buffer(-MIN_DETAIL_MM / 2).is_empty:
            small += 1
    tiny_text = sum(1 for size in text_sizes if size * 0.7 < MIN_DETAIL_MM)
    if not small and not tiny_text:
        return []
    parts = []
    if small:
        parts.append(f"{small} filled shape(s) narrower than 1 mm")
    if tiny_text:
        parts.append(f"{tiny_text} text line(s) less than 1 mm high")
    return [{"code": "detail_below_1mm", "detail": "At this size the graphic has " + " and ".join(parts) + "."}]


def colour_finding(shapes: list[Shape2D]) -> list[dict[str, str]]:
    colours = sorted({shape.colour for shape in shapes})
    if len(colours) <= 12:
        return []
    return [{"code": "more_than_12_colours",
             "detail": f"The graphic uses {len(colours)} thread colours; 12 or fewer sew well."}]


def load_and_scale(svg_text: str, scan: SourceScan, width_mm: float) -> tuple[_Source, int, float, float]:
    """Rules 1 and 2: read, leave out the background, scale to the requested width."""
    source = read_shapes(svg_text, scan, width_mm)
    if not source.shapes:
        raise PipelineError("nothing_to_sew")
    dropped = _drop_background(source)
    if not source.shapes:
        raise PipelineError("nothing_to_sew", "Nothing to sew after leaving out the background.")
    width, height = _scale(source, width_mm)
    return source, dropped, width, height


def _cut_overlaps(shapes: list[Shape2D]) -> tuple[list[Shape2D], int, int]:
    """Rule 3 and the line split of rule 5, top to bottom.

    Lower fills keep an OVERLAP_MM strip under the edge of the shapes above them,
    so neighbouring colours close without gaps but no area is sewn twice.
    """
    covered: BaseGeometry | None = None
    result: list[Shape2D] = []
    cut = 0
    lost = 0
    for shape in reversed(shapes):
        if shape.kind == "fill":
            visible = shape.geom
            if covered is not None and covered.intersects(shape.geom):
                visible = shape.geom.difference(covered.buffer(-OVERLAP_MM, join_style="mitre"))
                if visible.area < shape.geom.area - 0.01:
                    cut += 1
            cleaned = clean_area(visible)
            if cleaned.is_empty:
                # Something stayed visible but was too small or thin to sew.
                lost += 1 if visible.area >= 0.05 else 0
            else:
                result.append(Shape2D(shape.index, shape.colour, "fill", cleaned,
                                      flattened_paint=shape.flattened_paint))
            covered = shape.geom if covered is None else covered.union(shape.geom)
            continue
        satin = shape.width >= SATIN_MIN_WIDTH_MM
        lines = shape.geom if covered is None else shape.geom.difference(covered)
        pieces = [line for line in _lines(lines) if line.length >= MIN_LINE_LENGTH_MM]
        if covered is not None and lines.length < shape.geom.length - 0.05:
            cut += 1
        for piece in pieces:
            result.append(Shape2D(shape.index, shape.colour, "satin" if satin else "running", piece,
                                  width=shape.width, linecap=shape.linecap,
                                  flattened_paint=shape.flattened_paint))
        if satin:
            cap = {"round": "round", "square": "square"}.get(shape.linecap, "flat")
            band = shape.geom.buffer(shape.width / 2, cap_style=cap)
            covered = band if covered is None else covered.union(band)
    result.reverse()
    return result, cut, lost


def _dependencies(shapes: list[Shape2D]) -> dict[int, set[int]]:
    """``deps[j]`` holds the lower shapes that layer ``j`` still overlaps."""
    tree = STRtree([shape.geom for shape in shapes])
    deps: dict[int, set[int]] = {i: set() for i in range(len(shapes))}
    for j, upper in enumerate(shapes):
        area_upper = upper.geom if upper.kind == "fill" else upper.geom.buffer(max(upper.width, 0.3) / 2)
        for i in tree.query(area_upper):
            i = int(i)
            if i >= j:
                continue
            lower = shapes[i]
            area_lower = lower.geom if lower.kind == "fill" else lower.geom.buffer(max(lower.width, 0.3) / 2)
            if area_upper.intersection(area_lower).area > 0.01:
                deps[j].add(i)
    return deps


def _long_axis_angle(geom: BaseGeometry) -> float:
    """Visual counter-clockwise angle of the shape's long axis, rounded to 15 degrees."""
    rectangle = geom.minimum_rotated_rectangle
    if not isinstance(rectangle, Polygon):
        return 0.0
    coords = list(rectangle.exterior.coords)
    edges = [(coords[k + 1][0] - coords[k][0], coords[k + 1][1] - coords[k][1]) for k in range(2)]
    dx, dy = max(edges, key=lambda edge: math.hypot(*edge))
    angle = math.degrees(math.atan2(-dy, dx))
    angle = (round(angle / 15.0) * 15.0) % 180.0
    return angle - 180.0 if angle > 90.0 else angle


def _assign_angles(shapes: list[Shape2D]) -> None:
    """Fill rows follow the long axis; touching fills of other colours differ by >= 30 degrees.

    A narrow band (a drawn line given as an outline) is sewn across instead, like a satin
    column: rows along a thin band leave a ragged edge.
    """
    fills = [shape for shape in shapes if shape.kind == "fill"]
    for k, shape in enumerate(fills):
        angle = _long_axis_angle(shape.geom)
        if 2.0 * shape.geom.area / max(shape.geom.length, 1e-9) < NARROW_BAND_MM:
            angle += 90.0
        neighbours = [other.angle for other in fills[:k]
                      if other.colour != shape.colour and other.geom.distance(shape.geom) < 0.5]
        # Closest to the long axis first: +0, +45, -45, +90 degrees.
        candidates = [((angle + offset + 90.0) % 180.0) - 90.0 for offset in (0.0, 45.0, -45.0, 90.0)]
        shape.angle = next(
            (candidate for candidate in candidates
             if all(abs(((candidate - other) + 90.0) % 180.0 - 90.0) >= 30.0 for other in neighbours)),
            candidates[0],
        )


def _merge_blocks(shapes: list[Shape2D]) -> list[Shape2D]:
    """Union touching fills of the same colour block into one element (one seamless fill)."""
    merged: list[Shape2D] = []
    for shape in shapes:
        target = None
        if shape.kind == "fill":
            for k in range(len(merged) - 1, -1, -1):
                candidate = merged[k]
                if candidate.colour != shape.colour:
                    break
                if candidate.kind == "fill" and candidate.geom.intersection(shape.geom).area > 0.01:
                    target = k
                    break
        if target is None:
            merged.append(shape)
            continue
        candidate = merged[target]
        merged[target] = Shape2D(candidate.index, candidate.colour, "fill",
                                 clean_area(candidate.geom.union(shape.geom)),
                                 flattened_paint=candidate.flattened_paint or shape.flattened_paint)
    return merged


def _split_parts(shapes: list[Shape2D]) -> list[Shape2D]:
    """Sew the separate parts of one fill as elements of their own, nearest part first.

    Parts of one element are joined by a sewn connecting stitch; separate elements can be trimmed.
    """
    split: list[Shape2D] = []
    for shape in shapes:
        parts = _polygons(shape.geom) if shape.kind == "fill" else []
        if len(parts) < 2:
            split.append(shape)
            continue
        last = split[-1].geom if split else None
        while parts:
            part = min(parts, key=lambda candidate: last.distance(candidate) if last is not None else 0.0)
            parts.remove(part)
            split.append(Shape2D(shape.index, shape.colour, "fill", part, flattened_paint=shape.flattened_paint))
            last = part
    return split


def _bands_to_satin(shapes: list[Shape2D]) -> list[Shape2D]:
    """Sew narrow filled bands (lines given as outlines) as satin columns across the band."""
    result: list[Shape2D] = []
    for shape in shapes:
        parts = _polygons(shape.geom) if shape.kind == "fill" else []
        found = find_bands(parts[0]) if len(parts) == 1 else None
        if found is None:
            result.append(shape)
            continue
        bands, rest = found
        rest = clean_area(rest)
        for part in _polygons(rest):
            result.append(Shape2D(shape.index, shape.colour, "fill", part, flattened_paint=shape.flattened_paint))
        for band in bands:
            result.append(Shape2D(shape.index, shape.colour, "satin", band.centre, width=band.width,
                                  linecap="round", flattened_paint=shape.flattened_paint, rails=band.rails))
    return result


def finish_order(ordered: list[Shape2D]) -> None:
    """Fill angles and trims for shapes in their final sewing order."""
    _assign_angles(ordered)
    for shape, following in zip(ordered, ordered[1:]):
        shape.trim_after = (shape.colour == following.colour
                            and shape.geom.distance(following.geom) > TRIM_DISTANCE_MM)


def prepare(svg_text: str, scan: SourceScan, width_mm: float, start_colour: str | None = None) -> Prepared:
    """Apply the fixed rules and return the shapes in sewing order with notes.

    ``start_colour`` is the thread already in the machine (a sew-on border's), so
    shapes of that colour that can be sewn at once come first.
    """
    source, dropped, width, height = load_and_scale(svg_text, scan, width_mm)
    notes: list[dict[str, str | int]] = []
    technical: dict[str, int] = {}
    if dropped:
        notes.append({"code": "background_removed", "text": "Background left out"})
    findings = detail_findings(source.shapes, source.text_sizes) + colour_finding(source.shapes)
    source_colours = len({shape.colour for shape in source.shapes})
    source_count = len(source.shapes)
    shapes, cut, lost = _cut_overlaps(source.shapes)
    if not shapes:
        raise PipelineError("nothing_to_sew", "Nothing to sew after leaving out the background."
                            if dropped else "Nothing to sew in this graphic.")
    technical["overlaps_cut"] = cut
    if lost:
        notes.append({"code": "tiny_details_removed", "count": lost,
                      "text": f"{lost} detail(s) too small to sew left out"})
    naive_changes = colour_changes([shape.colour for shape in shapes])
    deps = _dependencies(shapes)
    items = [OrderItem(k, shape.colour, shape.kind, shape.centre()) for k, shape in enumerate(shapes)]
    ordered = [shapes[k] for k in plan_order(items, deps, start_colour=start_colour)]
    ordered = _bands_to_satin(_split_parts(_merge_blocks(ordered)))
    finish_order(ordered)
    grouped_changes = colour_changes([shape.colour for shape in ordered])
    technical["thread_changes_naive"] = naive_changes
    technical["thread_changes_grouped"] = grouped_changes
    technical["satin_shapes"] = sum(1 for shape in ordered if shape.kind == "satin")
    technical["bands_as_satin"] = sum(1 for shape in ordered if shape.rails is not None)
    running = [shape for shape in ordered if shape.kind == "running"]
    if running:
        notes.append({"code": "lines_running", "text": "Lines thinner than 1 mm sewn as running stitch"})
    if any(shape.flattened_paint for shape in ordered):
        notes.append({"code": "gradient_flattened", "text": "Gradient sewn in one flat colour"})
    return Prepared(ordered, width, height, notes, findings, source_colours, source_count, technical)


def check(svg_text: str, scan: SourceScan, width_mm: float) -> tuple[list[dict[str, str]], int, int]:
    """Fixed check only: geometry findings plus colour and shape counts, no conversion."""
    source, _, _, _ = load_and_scale(svg_text, scan, width_mm)
    findings = detail_findings(source.shapes, source.text_sizes) + colour_finding(source.shapes)
    return findings, len({shape.colour for shape in source.shapes}), len(source.shapes)


def multipolygon_rings(geom: BaseGeometry) -> list[list[tuple[float, float]]]:
    """Exterior and interior rings of every polygon part, for path output."""
    rings: list[list[tuple[float, float]]] = []
    polygons = _polygons(geom) if not isinstance(geom, MultiPolygon) else list(geom.geoms)
    for polygon in polygons:
        rings.append(list(polygon.exterior.coords))
        rings.extend(list(interior.coords) for interior in polygon.interiors)
    return rings
