"""Public status data for status.openmates.org.

Turns check results and alert state into the one JSON document the static page
renders: overall status, per-component status with 90 daily uptime bars, the
external providers overview and incident history. Only catalog names, statuses,
times and percentages are published, never hostnames, errors or check keys.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Literal, Mapping

from .alerts import CheckResult, OpenAlert
from .catalog import COMPONENTS, PROVIDERS, Component

Status = Literal["operational", "degraded", "outage", "unknown"]
HISTORY_DAYS = 90
MAX_INCIDENTS = 50
DAY_S = 86_400


def day_of(timestamp: float) -> str:
    """UTC calendar day (YYYY-MM-DD) of a Unix timestamp."""
    return time.strftime("%Y-%m-%d", time.gmtime(timestamp))


@dataclass
class DailyCounts:
    """Checks run and checks passed for one check on one UTC day."""

    total: int = 0
    ok: int = 0


@dataclass
class History:
    """Per check and day result counts, plus the newest counted timestamp."""

    days: dict[str, dict[str, DailyCounts]] = field(default_factory=dict)
    last_counted: dict[str, float] = field(default_factory=dict)

    def add(self, key: str, results: Iterable[CheckResult]) -> None:
        """Count results newer than the last counted one (Gatus returns overlaps)."""
        newest = self.last_counted.get(key, 0.0)
        for result in sorted(results, key=lambda r: r.timestamp):
            if result.timestamp <= newest:
                continue
            counts = self.days.setdefault(key, {}).setdefault(day_of(result.timestamp), DailyCounts())
            counts.total += 1
            counts.ok += int(result.success)
            newest = result.timestamp
        self.last_counted[key] = newest

    def prune(self, now: float) -> None:
        """Keep only the last HISTORY_DAYS days."""
        oldest = day_of(now - (HISTORY_DAYS - 1) * DAY_S)
        for per_day in self.days.values():
            for day in [d for d in per_day if d < oldest]:
                del per_day[day]

    def to_json(self) -> dict:
        return {"days": {k: {d: [c.total, c.ok] for d, c in v.items()} for k, v in self.days.items()},
                "last_counted": self.last_counted}

    @classmethod
    def from_json(cls, data: Mapping) -> "History":
        days = {k: {d: DailyCounts(int(c[0]), int(c[1])) for d, c in v.items()}
                for k, v in data.get("days", {}).items()}
        return cls(days=days, last_counted={k: float(v) for k, v in data.get("last_counted", {}).items()})


@dataclass
class Incident:
    """One public incident, opened by a confirmed outage of a component."""

    id: str
    component: str
    title: str
    started_at: float
    resolved_at: float | None = None

    def to_json(self) -> dict:
        return {"id": self.id, "component": self.component, "title": self.title,
                "started_at": self.started_at, "resolved_at": self.resolved_at}

    @classmethod
    def from_json(cls, data: Mapping) -> "Incident":
        resolved = data.get("resolved_at")
        return cls(str(data["id"]), str(data["component"]), str(data["title"]),
                   float(data["started_at"]), None if resolved is None else float(resolved))


def check_status(key: str, latest: Mapping[str, CheckResult], alerts: Mapping[str, OpenAlert]) -> Status:
    """Status of one check: outage only when confirmed, unknown without data."""
    if key in alerts:
        return "outage"
    result = latest.get(key)
    if result is None:
        return "unknown"
    return "operational"


def component_status(component: Component, latest: Mapping[str, CheckResult],
                     alerts: Mapping[str, OpenAlert]) -> Status:
    """All checks down → outage; some down → degraded; no data at all → unknown."""
    statuses = [check_status(c.key, latest, alerts) for c in component.checks]
    if all(s == "unknown" for s in statuses):
        return "unknown"
    known = [s for s in statuses if s != "unknown"]
    if all(s == "outage" for s in known):
        return "outage"
    if any(s == "outage" for s in known):
        return "degraded"
    return "operational"


def update_incidents(incidents: list[Incident], alerts: Mapping[str, OpenAlert], now: float) -> list[Incident]:
    """Open one incident per affected component; resolve it when its checks recover."""
    open_by_component = {i.component: i for i in incidents if i.resolved_at is None}
    for component in COMPONENTS:
        down = [alerts[c.key] for c in component.checks if c.key in alerts]
        current = open_by_component.get(component.id)
        if down and current is None:
            started = min(a.down_since for a in down)
            incidents.append(Incident(f"{component.id}-{int(started)}", component.id,
                                      f"{component.name} disruption", started))
        elif not down and current is not None:
            current.resolved_at = now
    incidents.sort(key=lambda i: i.started_at, reverse=True)
    return incidents[:MAX_INCIDENTS]


def _uptime_bars(keys: Iterable[str], history: History, now: float) -> list[dict]:
    keys = list(keys)
    bars = []
    for offset in range(HISTORY_DAYS - 1, -1, -1):
        day = day_of(now - offset * DAY_S)
        total = sum(history.days.get(k, {}).get(day, DailyCounts()).total for k in keys)
        ok = sum(history.days.get(k, {}).get(day, DailyCounts()).ok for k in keys)
        bars.append({"day": day, "uptime": None if total == 0 else round(100.0 * ok / total, 3)})
    return bars


def _uptime_percent(bars: list[dict]) -> float | None:
    values = [b["uptime"] for b in bars if b["uptime"] is not None]
    return None if not values else round(sum(values) / len(values), 3)


def build(latest: Mapping[str, CheckResult], alerts: Mapping[str, OpenAlert], history: History,
          incidents: list[Incident], now: float) -> dict:
    """The public JSON document served at /data/status.json."""
    components = []
    for component in COMPONENTS:
        bars = _uptime_bars((c.key for c in component.checks), history, now)
        components.append({"id": component.id, "name": component.name, "description": component.description,
                           "status": component_status(component, latest, alerts),
                           "uptime_percent": _uptime_percent(bars), "days": bars})
    providers = [{"id": p.id, "name": p.name, "category": p.category, "status_page": p.status_page,
                  "status": check_status(p.check.key, latest, alerts)} for p in PROVIDERS]
    statuses = {c["status"] for c in components}
    overall: Status = "outage" if "outage" in statuses else "degraded" if "degraded" in statuses else (
        "unknown" if "unknown" in statuses else "operational")
    names = {c.id: c.name for c in COMPONENTS}
    return {
        "generated_at": now,
        "overall": overall,
        "components": components,
        "providers": providers,
        "incidents": [dict(i.to_json(), component_name=names.get(i.component, i.component)) for i in incidents],
    }
