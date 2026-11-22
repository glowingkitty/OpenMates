"""Satin rings: a closed band along an outline, sewn as one satin column (shapely).

Assertion design-embroidery.prepare.sew-on-border. A sew-on border is sewn like
the edge of a patch: one dense satin column runs once around each outline ring
of the bordered design, every stitch square to the edge, so the edge is stable
for cutting out. Values are millimetres at the sewn size.

For an outer ring the column lies inside it, for a hole ring (a wide opening the
border runs around) outside it, ``width`` wide. Its two rails are the ring and
the ring moved ``width`` into the band (``inner``). The rails are sampled in
pairs: every ``STEP_MM`` along the ring, paired with the nearest point of
``inner``, so each stitch is square to the edge. Where the ring bends outward
(a round corner) several ring points share one inner point and the stitches fan
around it; where it bends inward the inner rail is longer and extra pairs are
inserted along it, so no stitch cuts across the band. Inner positions only move
forward, so stitches never cross. Ink/Stitch sews between the pairs and turns
the stitches gradually from one pair to the next, so only the pairs where the
stitch direction turns (``KEEP_TURN_DEG``) or at least every ``KEEP_EVERY_MM``
are kept; on a straight stretch that also keeps the rails straight.

A ring is not sewn as a satin ring, and its band stays part of the filled
border, when its inner rail would fall apart (the design has a neck there that
is narrower than the column), when what it encloses is narrower than
``MIN_INSIDE_MM`` (a speck whose column would end in a point), or, for an
opening, when its column would leave the outline or overlap another column.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import LinearRing, LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.ops import substring

STEP_MM = 0.4
# Consecutive inner rail points are at least this far apart, so no rail section has zero length.
MIN_INNER_STEP_MM = 0.02
# Pair thinning: keep a pair when the stitch turned this much since the last kept one, or after this distance.
KEEP_TURN_DEG = 4.0
KEEP_EVERY_MM = 4.0
# A ring is sewn as satin only when what it encloses is at least this wide.
MIN_INSIDE_MM = 0.6
# Columns may touch, but may not overlap by more than this area.
MAX_OVERLAP_MM2 = 0.5


@dataclass
class SatinRing:
    """One closed satin column: its centre line and its two closed rails, paired point by point."""

    centre: LineString
    rails: tuple[LineString, LineString]
    band: BaseGeometry


def _forward(positions: list[float], length: float) -> list[float]:
    """Unwrap cyclic positions on a ring of ``length`` so they only move forward and close after one turn."""
    steps = []
    for current, following in zip(positions, positions[1:] + positions[:1]):
        step = (following - current) % length
        # A small backward move (a stitch about to cross its neighbour) is held instead.
        steps.append(0.0 if step > length / 2 else step)
    total = sum(steps)
    if total <= 0:
        return []
    scale = length / total
    unwrapped, at = [], positions[0]
    for step in steps:
        unwrapped.append(at)
        at += step * scale
    return unwrapped


def _inner_positions(ring_line: LineString, inner_line: LineString, count: int) -> list[float]:
    length = ring_line.length
    return _forward([inner_line.project(ring_line.interpolate(length * k / count)) for k in range(count)],
                    inner_line.length)


def _from(line: LineString, at: float) -> LineString:
    """The same closed line, starting ``at`` along it."""
    if at <= 0:
        return line
    head, tail = substring(line, at, line.length), substring(line, 0, at)
    return LineString([*head.coords, *list(tail.coords)[1:]])


def _paired_rails(ring: LinearRing, inner: LinearRing) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    ring_line, inner_line = LineString(ring.coords), LineString(inner.coords)
    length, inner_length = ring_line.length, inner_line.length
    count = max(12, math.ceil(length / STEP_MM))
    inner_at = _inner_positions(ring_line, inner_line, count)
    if len(inner_at) != count:
        return [], []
    # Start where the column runs straight (the largest inner step), never inside a fan
    # around a corner, so the closing stitch meets the first one cleanly.
    steps = [inner_at[k] - inner_at[k - 1] for k in range(1, count)]
    start = max(range(len(steps)), key=lambda k: (round(steps[k], 6), -k)) + 1
    ring_line = _from(ring_line, length * start / count)
    inner_line = _from(inner_line, inner_at[start] % inner_length)
    outer_at = [length * k / count for k in range(count)]
    inner_at = _inner_positions(ring_line, inner_line, count)
    if len(inner_at) != count:
        return [], []
    outer: list[tuple[float, float]] = []
    inner_points: list[tuple[float, float]] = []
    last = None
    for k in range(count):
        o0, o1 = outer_at[k], outer_at[k + 1] if k + 1 < count else length
        i0 = inner_at[k]
        i1 = inner_at[k + 1] if k + 1 < count else inner_at[0] + inner_length
        # The inner rail runs on further than the ring here (an inward bend): add pairs along it.
        pieces = max(1, math.ceil((i1 - i0) / STEP_MM))
        for piece in range(pieces):
            share = piece / pieces
            at = i0 + (i1 - i0) * share
            if last is not None and at - last < MIN_INNER_STEP_MM:
                at = last + MIN_INNER_STEP_MM
            last = at
            point = ring_line.interpolate(o0 + (o1 - o0) * share)
            outer.append((point.x, point.y))
            inner_point = inner_line.interpolate(at % inner_length)
            inner_points.append((inner_point.x, inner_point.y))
    outer.append(outer[0])
    inner_points.append(inner_points[0])
    return outer, inner_points


def _turn(a: tuple[float, float], b: tuple[float, float]) -> float:
    angle = abs(math.degrees(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0]))) % 360.0
    return min(angle, 360.0 - angle)


def _thinned(outer: list[tuple[float, float]], inner: list[tuple[float, float]]) -> tuple[list, list]:
    """Drop pairs Ink/Stitch would reproduce anyway; both rails keep equally many points and stay closed."""
    keep = [0]
    run = 0.0
    for k in range(1, len(outer) - 1):
        last = keep[-1]
        run += math.dist(outer[k], outer[k - 1])
        stitch = (inner[k][0] - outer[k][0], inner[k][1] - outer[k][1])
        kept = (inner[last][0] - outer[last][0], inner[last][1] - outer[last][1])
        following = (inner[k + 1][0] - outer[k + 1][0], inner[k + 1][1] - outer[k + 1][1])
        if run >= KEEP_EVERY_MM or _turn(kept, stitch) >= KEEP_TURN_DEG or _turn(stitch, following) >= KEEP_TURN_DEG:
            keep.append(k)
            run = 0.0
    keep.append(len(outer) - 1)
    return [outer[k] for k in keep], [inner[k] for k in keep]


def _ring(ring: LinearRing, inner: LinearRing, band: BaseGeometry) -> SatinRing | None:
    outer, inner_points = _paired_rails(ring, inner)
    outer, inner_points = _thinned(outer, inner_points)
    if len(outer) < 13:
        return None
    centre = LineString([((ox + ix) / 2, (oy + iy) / 2) for (ox, oy), (ix, iy) in zip(outer, inner_points)])
    return SatinRing(centre, (LineString(outer), LineString(inner_points)), band)


def satin_rings(outline: BaseGeometry, width: float) -> list[SatinRing]:
    """One satin ring per outline ring that can carry a column ``width`` wide."""
    rings: list[SatinRing] = []
    for part in getattr(outline, "geoms", [outline]):
        if not isinstance(part, Polygon) or part.is_empty:
            continue
        part = orient(part)
        outer = Polygon(part.exterior)
        inside = outer.buffer(-width, join_style="round")
        if (isinstance(inside, Polygon) and not inside.interiors
                and not inside.buffer(-MIN_INSIDE_MM / 2).is_empty):
            ring = _ring(part.exterior, orient(inside).exterior, outer.difference(inside))
            if ring is not None:
                rings.append(ring)
        for hole in part.interiors:
            opening = Polygon(hole)
            grown = opening.buffer(width, join_style="round")
            if not grown.within(outer):
                continue
            band = grown.difference(opening)
            if any(band.intersection(other.band).area > MAX_OVERLAP_MM2 for other in rings):
                continue
            # A hole ring runs the other way round; its inner rail must run the same way.
            hole_ring = LinearRing(list(hole.coords)[::-1]) if not hole.is_ccw else hole
            inner = orient(grown).exterior
            ring = _ring(LinearRing(hole_ring.coords), inner, band)
            if ring is not None:
                rings.append(ring)
    return rings
