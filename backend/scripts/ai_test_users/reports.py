"""Pick, de-duplicate and describe the findings an AI test user files as issue reports."""

from __future__ import annotations

import re
from typing import Any

SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
SIMILARITY = 0.6


def words(title: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9äöüß]{3,}", title.lower())}


def similar(a: str, b: str) -> bool:
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return False
    overlap = len(wa & wb)
    return overlap / len(wa | wb) >= SIMILARITY or overlap / min(len(wa), len(wb)) >= 0.8


def rank(finding: dict[str, Any]) -> tuple[int, float]:
    return SEVERITY_RANK.get(str(finding.get("severity")), 3), -(finding.get("jev_score") or 0.0)


def select_reports(findings: list[dict[str, Any]], skip_titles: list[str], max_reports: int) -> list[list[dict[str, Any]]]:
    """Kept findings grouped by duplicate title; the first finding of a group is its lead.

    Groups whose lead title resembles one of `skip_titles` (already reported) are dropped.
    """
    kept = sorted((f for f in findings if f.get("kept") and f.get("title")), key=rank)
    groups: list[list[dict[str, Any]]] = []
    for finding in kept:
        for group in groups:
            if similar(group[0]["title"], finding["title"]):
                group.append(finding)
                break
        else:
            groups.append([finding])
    groups = [g for g in groups if not any(similar(g[0]["title"], s) for s in skip_titles)]
    return groups[: max(0, max_reports)]


def screenshot_steps(lead_step: int | None, available: list[int], limit: int) -> list[int]:
    """The finding's own step first, then the nearest neighbouring steps, returned in step order."""
    if lead_step is None or lead_step not in available:
        return sorted(available[-limit:]) if available and limit else []
    chosen = [lead_step]
    for distance in range(1, len(available) + 1):
        for step in (lead_step - distance, lead_step + distance):
            if step in available and len(chosen) < limit:
                chosen.append(step)
    return sorted(chosen[:limit])


def report_text(group: list[dict[str, Any]], persona: dict[str, Any], target: str) -> tuple[str, str]:
    lead = group[0]
    parts = [str(lead["title"]).strip()]
    for finding in group:
        lines = [f"Step {finding.get('step')}: {finding.get('evidence', '')}".strip()]
        if finding.get("expected"):
            lines.append(f"Expected: {finding['expected']}")
        parts.append("\n".join(lines))
    parts.append(
        f"Surface: {lead.get('surface', '-')}, severity {lead.get('severity', '-')}, "
        f"Jev score {lead.get('jev_score')}. Found by the automated AI test user "
        f"'{persona.get('name', persona.get('id'))}' on {persona.get('device_label', 'unknown device')} ({target})."
    )
    return str(lead["title"]).strip(), "\n\n".join(parts)
