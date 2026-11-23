"""Rotation of AI test-user personas over the week (pure, no I/O).

Mon-Fri: 3 personas on dev and 2 on prod per day, disjoint on the same day. Over one week
every persona runs on dev at least once and on prod exactly once. Saturday and Sunday:
nothing, on dev and prod (owner, 21 Nov 2026: scheduled runs Monday to Friday only). The
start offset moves with the ISO week so the daily pairings differ from week to week.
"""

from __future__ import annotations

from datetime import date

DEV_PER_DAY = 3
PROD_PER_DAY = 2
WEEKEND = 5  # date.weekday() of Saturday; Saturday and Sunday never run


def _window(ids: list[str], start: int, size: int) -> list[str]:
    return [ids[(start + i) % len(ids)] for i in range(size)]


def personas_for(day: date, persona_ids: list[str]) -> dict[str, list[str]]:
    """Return {"dev": [...], "prod": [...], "kind": "daily"|"none"} for the date."""
    weekday = day.weekday()
    if weekday >= WEEKEND:
        return {"kind": "none", "dev": [], "prod": []}
    ids = list(persona_ids)
    if len(ids) < DEV_PER_DAY + PROD_PER_DAY:
        raise ValueError("rotation needs at least five personas")
    offset = (day.isocalendar().week * 3) % len(ids)
    prod = _window(ids, PROD_PER_DAY * weekday + offset, PROD_PER_DAY)
    dev = _window(ids, PROD_PER_DAY * weekday + offset + PROD_PER_DAY, DEV_PER_DAY)
    return {"kind": "daily", "dev": dev, "prod": prod}


def areas_for(persona_ids: list[str], personas: list[dict]) -> list[str]:
    """Distinct areas of the given personas, in first-seen order."""
    by_id = {p["id"]: p for p in personas}
    seen: list[str] = []
    for pid in persona_ids:
        for area in by_id.get(pid, {}).get("areas", []):
            if area not in seen:
                seen.append(area)
    return seen
