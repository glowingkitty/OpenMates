"""Recognise narrow filled bands and describe them as satin columns.

A traced or outlined line (a whisker, a mouth curve, a letter stroke) arrives as
a filled polygon. Sewn as an area fill it gets short rows and many tiny stitches;
a satin column sews one stitch straight across the band and follows its curve.

A piece is a band when its skeleton is one line, it is between
``BAND_MIN_WIDTH_MM`` and ``BAND_MAX_WIDTH_MM`` wide and clearly longer than
wide. A shape whose skeleton forks (a Y, a mouth hanging on a nose) is cut at
each fork into its arms; each arm that is a band becomes a satin column and the
rest stays a fill. Shapes with a hole (a ring around a spot) and wedges that
narrow all the way along stay fills. A band
is returned as its centre line, its typical width and two rails (the two long
sides, both running from the same tip to the other) with equally many points,
which Ink/Stitch sews as a satin column of varying width.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

import shapely
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

BAND_MIN_WIDTH_MM = 1.0
BAND_MAX_WIDTH_MM = 6.0
BAND_MIN_ASPECT = 2.5
SAMPLE_MM = 0.4
RAIL_STEP_MM = 0.6
# Rails start this far from the tips, so they never touch each other.
TIP_INSET_MM = 0.3
# How far a rail end is moved on to reach a square end of the band.
END_REACH_MM = 1.2
# A skeleton twig no longer than this many times the clearance at its fork only reaches into a corner.
SPUR_FACTOR = 2.2
MAX_FORKS = 6
CUT_HALF_WIDTH_MM = 0.01
COVER_MIN = 0.93
COVER_MAX = 1.1
# Pull compensation and thread width hide a rim this wide; a bare place beyond it may be at most this large.
BARE_MARGIN_MM = 0.3
BARE_MAX_MM2 = 0.5
BARE_CORNER_SHARE = 0.1
# What stays a fill reaches this far under the satin columns next to it, so no fabric shows between them.
UNDERLAP_MM = 0.4
# A quarter of the way up the sorted widths a band is still at least this share of its typical width.
EVEN_WIDTH_SHARE = 0.6

Node = tuple[float, float]


@dataclass
class Band:
    """A narrow filled shape described as a satin column."""

    centre: LineString
    width: float
    rails: tuple[LineString, LineString]


def _skeleton(polygon: Polygon) -> dict[Node, dict[Node, float]]:
    """Approximate medial axis: Voronoi edges of the sampled outline that lie inside the shape."""
    sites = MultiPoint(shapely.segmentize(polygon.exterior, SAMPLE_MM).coords[:-1])
    edges = shapely.voronoi_polygons(sites, only_edges=True)
    graph: dict[Node, dict[Node, float]] = {}
    shapely.prepare(polygon)
    for edge in getattr(edges, "geoms", [edges]):
        if edge.is_empty or not polygon.contains(edge):
            continue
        coords = [(round(x, 3), round(y, 3)) for x, y in edge.coords]
        for start, end in zip(coords, coords[1:]):
            if start == end:
                continue
            length = math.dist(start, end)
            graph.setdefault(start, {})[end] = length
            graph.setdefault(end, {})[start] = length
    return graph


def _distances(graph: dict[Node, dict[Node, float]], sources: list[Node]) -> tuple[dict[Node, float], dict[Node, Node]]:
    distance = {node: 0.0 for node in sources}
    previous: dict[Node, Node] = {}
    queue = [(0.0, node) for node in sources]
    heapq.heapify(queue)
    while queue:
        reached, node = heapq.heappop(queue)
        if reached > distance[node]:
            continue
        for neighbour, length in graph[node].items():
            candidate = reached + length
            if candidate < distance.get(neighbour, math.inf):
                distance[neighbour] = candidate
                previous[neighbour] = node
                heapq.heappush(queue, (candidate, neighbour))
    return distance, previous


def _longest_path(graph: dict[Node, dict[Node, float]]) -> list[Node]:
    """Longest shortest path of the largest connected part (the skeleton's main line)."""
    remaining = set(graph)
    best: dict[Node, float] = {}
    while remaining:
        reached, _ = _distances(graph, [next(iter(remaining))])
        if len(reached) > len(best):
            best = reached
        remaining -= set(reached)
    first = max(best, key=best.__getitem__)
    from_first, _ = _distances(graph, [first])
    second = max(from_first, key=from_first.__getitem__)
    _, previous = _distances(graph, [second])
    path = [first]
    while path[-1] != second:
        path.append(previous[path[-1]])
    return path


def _tip(centre: LineString, at_end: bool, ring: LineString, reach: float) -> Point:
    """Where the centre line, continued straight on, leaves the shape."""
    length = centre.length
    back = min(reach, length / 4.0)
    end = centre.interpolate(length if at_end else 0.0)
    inner = centre.interpolate(length - back if at_end else back)
    span = math.dist((inner.x, inner.y), (end.x, end.y)) or 1.0
    ux, uy = (end.x - inner.x) / span, (end.y - inner.y) / span
    ray = LineString([(end.x, end.y), (end.x + ux * 3.0 * reach, end.y + uy * 3.0 * reach)])
    hits = shapely.get_parts(ray.intersection(ring))
    points = [hit for hit in hits if isinstance(hit, Point)]
    if not points:
        return ring.interpolate(ring.project(end))
    return min(points, key=end.distance)


def _edge(ring: LineString, centre: Point, direction: tuple[float, float], reach: float) -> tuple[float, float]:
    """First point of the outline met from ``centre`` in ``direction``."""
    ray = LineString([(centre.x, centre.y), (centre.x + direction[0] * reach, centre.y + direction[1] * reach)])
    hits = [hit for hit in shapely.get_parts(ray.intersection(ring)) if isinstance(hit, Point)]
    if not hits:
        return (centre.x, centre.y)
    nearest = min(hits, key=centre.distance)
    return (nearest.x, nearest.y)


def _rails(polygon: Polygon, whole: LineString) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Both sides of the band where lines square to the centre line leave it, so stitches lie across the band."""
    ring = polygon.exterior
    length = whole.length
    inset = min(TIP_INSET_MM, length / 10.0)
    count = max(6, math.ceil(length / RAIL_STEP_MM) + 1)
    left: list[tuple[float, float]] = []
    right: list[tuple[float, float]] = []
    tangents: list[tuple[float, float]] = []
    for k in range(count):
        at = inset + (length - 2.0 * inset) * k / (count - 1)
        centre = whole.interpolate(at)
        before, after = whole.interpolate(max(0.0, at - 1.0)), whole.interpolate(min(length, at + 1.0))
        span = math.dist((before.x, before.y), (after.x, after.y)) or 1.0
        tx, ty = (after.x - before.x) / span, (after.y - before.y) / span
        one = _edge(ring, centre, (-ty, tx), 2.0 * BAND_MAX_WIDTH_MM)
        other = _edge(ring, centre, (ty, -tx), 2.0 * BAND_MAX_WIDTH_MM)
        # A line that grazes an end of the band meets the outline much nearer on one side: skip it.
        near, far = sorted((math.dist(one, (centre.x, centre.y)), math.dist(other, (centre.x, centre.y))))
        if left and far > 2.0 * near + 0.2:
            continue
        left.append(one)
        right.append(other)
        tangents.append((tx, ty))
    # At a square end the last line stops short of the end: push both rail ends on to the outline.
    for index, sign in ((0, -1.0), (-1, 1.0)):
        direction = (tangents[index][0] * sign, tangents[index][1] * sign)
        left[index] = _pushed(ring, left[index], right[index], direction)
        right[index] = _pushed(ring, right[index], left[index], direction)
    return left, right


def _pushed(
    ring: LineString, point: tuple[float, float], opposite: tuple[float, float], direction: tuple[float, float]
) -> tuple[float, float]:
    """``point`` moved along ``direction`` to the outline when that is at most ``END_REACH_MM`` away."""
    span = math.dist(point, opposite) or 1.0
    inside = (point[0] + (opposite[0] - point[0]) * 0.05 / span, point[1] + (opposite[1] - point[1]) * 0.05 / span)
    ray = LineString([inside, (inside[0] + direction[0] * END_REACH_MM, inside[1] + direction[1] * END_REACH_MM)])
    hits = [hit for hit in shapely.get_parts(ray.intersection(ring)) if isinstance(hit, Point)]
    if not hits:
        return point
    nearest = min(hits, key=Point(inside).distance)
    return (nearest.x, nearest.y)


def _tree(graph: dict[Node, dict[Node, float]]) -> dict[Node, dict[Node, float]]:
    """Shortest-path tree of the skeleton: evenly sampled round outlines give tiny loops, a tree has none."""
    _, previous = _distances(graph, [next(iter(graph))])
    tree: dict[Node, dict[Node, float]] = {node: {} for node in graph}
    for node, parent in previous.items():
        tree[node][parent] = tree[parent][node] = graph[node][parent]
    return tree


def _largest_part(graph: dict[Node, dict[Node, float]]) -> dict[Node, dict[Node, float]]:
    remaining = set(graph)
    best: set[Node] = set()
    while remaining:
        reached, _ = _distances(graph, [next(iter(remaining))])
        if len(reached) > len(best):
            best = set(reached)
        remaining -= set(reached)
    return {node: {other: length for other, length in graph[node].items() if other in best} for node in best}


def _prune(graph: dict[Node, dict[Node, float]], ring: LineString) -> None:
    """Remove twigs that only reach from a fork into a corner of the outline."""
    changed = True
    while changed:
        # All twigs of one round are found before any is removed: taking one of the two twigs
        # at a square end away first would make the other look like part of the main line.
        twigs: list[list[Node]] = []
        for leaf in [node for node, edges in graph.items() if len(edges) == 1]:
            chain, length, previous, node = [leaf], 0.0, None, leaf
            while len(graph[node]) <= 2:
                onward = [other for other in graph[node] if other != previous]
                if not onward:
                    break
                length += graph[node][onward[0]]
                previous, node = node, onward[0]
                chain.append(node)
            if len(graph[node]) >= 3 and length <= SPUR_FACTOR * ring.distance(Point(node)):
                twigs.append(chain[:-1])
        changed = bool(twigs)
        for chain in twigs:
            for twig in chain:
                for other in graph.pop(twig, {}):
                    graph.get(other, {}).pop(twig, None)


def _pruned_skeleton(polygon: Polygon) -> dict[Node, dict[Node, float]]:
    graph = _skeleton(polygon)
    if len(graph) < 3:
        return {}
    graph = _tree(_largest_part(graph))
    _prune(graph, polygon.exterior)
    return graph


def _single_band(polygon: Polygon, graph: dict[Node, dict[Node, float]] | None = None) -> Band | None:
    """Describe a hole-free piece as one satin column, or None when it is not one narrow band."""
    if polygon.is_empty or polygon.interiors or not polygon.is_valid:
        return None
    ring = polygon.exterior
    mean_width = 2.0 * polygon.area / ring.length
    if not BAND_MIN_WIDTH_MM <= mean_width <= BAND_MAX_WIDTH_MM:
        return None
    if ring.length / 2.0 < BAND_MIN_ASPECT * mean_width:
        return None
    graph = _pruned_skeleton(polygon) if graph is None else graph
    if len(graph) < 3 or any(len(edges) > 2 for edges in graph.values()):
        return None
    path = _longest_path(graph)
    centre = LineString(path)
    reach = 2.0 * max(ring.distance(Point(node)) for node in path)
    start, end = _tip(centre, False, ring, reach), _tip(centre, True, ring, reach)
    whole = LineString([(start.x, start.y), *path, (end.x, end.y)]).simplify(0.05)
    left, right = _rails(polygon, whole)
    widths = sorted(math.dist(one, other) for one, other in zip(left, right))
    width = widths[len(widths) // 2]
    if width < BAND_MIN_WIDTH_MM or widths[int(len(widths) * 0.9)] > BAND_MAX_WIDTH_MM:
        return None
    if widths[-1] > 1.5 * BAND_MAX_WIDTH_MM or whole.length < BAND_MIN_ASPECT * width:
        return None
    # A wedge narrows all the way along; a band keeps its width and only narrows at its tips.
    if widths[len(widths) // 4] < EVEN_WIDTH_SHARE * width:
        return None
    # The column must cover the piece: a blob hanging on a line, or a missed part, stays a fill.
    column = shapely.make_valid(Polygon(left + right[::-1]))
    if not COVER_MIN * polygon.area <= column.area <= COVER_MAX * polygon.area:
        return None
    # No part of the piece may stay bare next to the column: the colour under it was cut away.
    bare = polygon.difference(column.buffer(BARE_MARGIN_MM))
    # A corner of a slanted end stays out of the column; it may be a tenth of a width square.
    allowed = max(BARE_MAX_MM2, BARE_CORNER_SHARE * width * width)
    if any(part.area > allowed for part in getattr(bare, "geoms", [bare])):
        return None
    return Band(whole, width, (LineString(left), LineString(right)))


def _fork_cuts(polygon: Polygon, fork: Node) -> list[LineString]:
    """Cuts from a fork of the skeleton to each place where the outline comes closest to it."""
    ring = shapely.segmentize(polygon.exterior, 0.2)
    centre = Point(fork)
    reach = polygon.exterior.distance(centre) * 1.25 + 0.2
    coords = list(ring.coords)[:-1]
    near = [math.dist(fork, coord) <= reach for coord in coords]
    if all(near) or not any(near):
        return []
    start = near.index(False)
    order = list(range(start, len(coords))) + list(range(start))
    groups: list[list[int]] = []
    for position in order:
        if not near[position]:
            continue
        if groups and (groups[-1][-1] + 1) % len(coords) == position:
            groups[-1].append(position)
        else:
            groups.append([position])
    cuts = []
    for group in groups:
        x, y = coords[min(group, key=lambda position: math.dist(fork, coords[position]))]
        span = math.dist(fork, (x, y)) or 1.0
        over = 0.1 / span
        cuts.append(LineString([fork, (x + (x - fork[0]) * over, y + (y - fork[1]) * over)]))
    return cuts if len(cuts) >= 2 else []


def find_bands(polygon: Polygon) -> tuple[list[Band], BaseGeometry] | None:
    """Satin columns found in ``polygon`` and the area left to fill, or None when it has no band."""
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        return None
    if 2.0 * polygon.area / polygon.length > BAND_MAX_WIDTH_MM:
        return None
    if polygon.interiors:
        return None
    graph = _pruned_skeleton(polygon)
    forks = [node for node, edges in graph.items() if len(edges) > 2]
    if not forks:
        band = _single_band(polygon, graph)
        return ([band], Polygon()) if band is not None else None
    if len(forks) > MAX_FORKS:
        return None
    cuts = [cut for fork in forks for cut in _fork_cuts(polygon, fork)]
    if not cuts:
        return None
    pieces = polygon.difference(unary_union(cuts).buffer(CUT_HALF_WIDTH_MM, cap_style="flat"))
    bands: list[Band] = []
    rest: list[BaseGeometry] = []
    for piece in getattr(pieces, "geoms", [pieces]):
        if not isinstance(piece, Polygon) or piece.is_empty:
            continue
        band = _single_band(piece)
        if band is None:
            rest.append(piece.buffer(UNDERLAP_MM))
        else:
            bands.append(band)
    if not bands:
        return None
    # A small fill under each fork closes the place where the column ends meet.
    rest.extend(Point(fork).buffer(polygon.exterior.distance(Point(fork)) * 1.3) for fork in forks)
    return bands, unary_union(rest).intersection(polygon)
