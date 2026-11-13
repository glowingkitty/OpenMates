"""Sewing order: group shapes of one thread colour while respecting the stacking.

Standard library only. After hidden overlaps are cut away, a shape only has to be
sewn after the lower shapes it still touches (the small overlap strip under its
edge, or the fill a line lies on). Within those constraints a deterministic
greedy order sews every available shape of the current colour before changing
thread, prefers colours that can sew fills now (lines and outlines come last)
and, inside a colour, walks to the nearest shape to keep jumps short.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

KIND_RANK = {"fill": 0, "satin": 1, "running": 2}


@dataclass(frozen=True)
class OrderItem:
    """One sewable shape: its z index (unique id), thread colour, kind and centre."""

    index: int
    colour: str
    kind: str
    centre: tuple[float, float]


def colour_changes(colours: list[str]) -> int:
    """Number of thread changes when sewing the colours in this sequence."""
    return sum(1 for previous, current in zip(colours, colours[1:]) if previous != current)


def _closure(colour: str, available_done: set[int], items: dict[int, OrderItem],
             deps: dict[int, set[int]], remaining: set[int]) -> int:
    """How many shapes of one colour could be sewn in a row starting now."""
    done = set(available_done)
    count = 0
    progressed = True
    while progressed:
        progressed = False
        for index in sorted(remaining - done):
            if items[index].colour == colour and deps.get(index, set()) <= done:
                done.add(index)
                count += 1
                progressed = True
    return count


def plan_order(items: list[OrderItem], deps: dict[int, set[int]], start_colour: str | None = None) -> list[int]:
    """Return item indexes in sewing order. ``deps[i]`` must be sewn before ``i``.

    ``start_colour`` is the thread sewn just before these items (a sew-on
    border), so available items of that colour come first.
    """
    by_index = {item.index: item for item in items}
    remaining = set(by_index)
    unknown = {dep for wanted in deps.values() for dep in wanted} - remaining
    if unknown:
        raise ValueError(f"dependencies reference unknown shapes {sorted(unknown)}")
    done: set[int] = set()
    order: list[int] = []
    current_colour: str | None = start_colour
    position: tuple[float, float] | None = None
    while remaining:
        available = [index for index in remaining if deps.get(index, set()) <= done]
        if not available:
            raise ValueError("the stacking constraints contain a cycle")
        same = [index for index in available if by_index[index].colour == current_colour]
        if not same:
            colours = sorted({by_index[index].colour for index in available})

            def colour_key(colour: str) -> tuple[int, int, int, int]:
                members = [index for index in available if by_index[index].colour == colour]
                best_kind = min(KIND_RANK[by_index[index].kind] for index in members)
                run = _closure(colour, done, by_index, deps, remaining)
                left = sum(1 for index in remaining if by_index[index].colour == colour)
                # Prefer a colour that can be finished now: starting one that is
                # still needed later costs an extra thread change.
                return best_kind, 0 if run == left else 1, -run, min(members)

            current_colour = min(colours, key=colour_key)
            same = [index for index in available if by_index[index].colour == current_colour]

        def item_key(index: int) -> tuple[int, float, int]:
            item = by_index[index]
            distance = 0.0 if position is None else math.dist(position, item.centre)
            return KIND_RANK[item.kind], round(distance, 3), index

        chosen = min(same, key=item_key)
        order.append(chosen)
        done.add(chosen)
        remaining.discard(chosen)
        position = by_index[chosen].centre
    return order
