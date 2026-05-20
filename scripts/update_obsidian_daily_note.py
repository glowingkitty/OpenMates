#!/usr/bin/env python3
"""
Deterministically updates the local Obsidian daily note for the memory vault.

This script is designed for cron: it is idempotent, uses only the Python
standard library, and replaces only AUTO-marked sections in the daily note.
Manual daily-note content outside those markers is preserved. It tracks changed
notes by local filesystem mtime and stores a per-day manifest to avoid duplicate
links across repeated runs.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VAULT = PROJECT_ROOT / "vaults" / "memory"
DEFAULT_GIT_REPO = PROJECT_ROOT
DEFAULT_TIMEZONE = "Europe/Berlin"
GITHUB_REPO_URL = "https://github.com/glowingkitty/OpenMates"
DAILY_NOTES_DIR = "Daily Notes"
STATE_DIR = ".obsidian-auto/daily-note-state"
SERVER_STATS_CACHE_DIR = ".obsidian-auto/server-stats"
SERVER_STATS_CACHE_MAX_AGE_SECONDS = 60 * 60
DAILY_METRICS_ASSET_DIR = "assets/daily-metrics"
SVG_WIDTH = 1200
SVG_HEIGHT = 660
SVG_FONT = "Lexend Deca Variable, Lexend Deca, Inter, Arial, sans-serif"
SVG_COLORS = {
    "background": "#171717",
    "card": "#212121",
    "card_alt": "#252525",
    "grid": "#404040",
    "text": "#ffffff",
    "text_primary": "#e6e6e6",
    "text_secondary": "#cfcfcf",
    "text_tertiary": "#a0a0a0",
    "primary_start": "#4867cd",
    "primary_end": "#5a85eb",
    "button": "#ff553b",
    "button_hover": "#ff6b54",
    "finance_start": "#0a6e04",
    "finance_end": "#2cb81e",
    "health_start": "#fd50a0",
    "health_end": "#f42c2d",
    "travel_start": "#059db3",
    "travel_end": "#13daf5",
    "warning": "#f0a050",
    "neutral": "#555555",
}
LEGACY_BOARD_LINKS = (
    "Kanban: [[Boards/all-todos|Open All Todos board]]",
    "Kanban: [[OpenMates/Tasks/Boards/All Todos|Open All Todos board]]",
    "![[Boards/all-todos]]",
)
GENERATED_TEST_NOTE_PREFIX = "OpenMates/Tests/"
GENERATED_TEST_NOTE_TYPES = {"e2e-test", "test-dashboard"}
MARKER_PATTERN = re.compile(
    r"<!-- AUTO:(?P<name>[a-z0-9-]+):start -->.*?<!-- AUTO:(?P=name):end -->",
    re.DOTALL,
)


@dataclass(frozen=True)
class NoteInfo:
    path: str
    link: str
    title: str
    mtime: str
    note_type: str | None
    project: str | None
    area: str | None
    task_status: str | None
    priority: str | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update today's Obsidian daily note.")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--git-repo", type=Path, default=DEFAULT_GIT_REPO)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--date", help="Override date as YYYY-MM-DD for testing/backfill.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def today_window(tz_name: str, date_override: str | None) -> tuple[str, float, float, ZoneInfo]:
    tz = ZoneInfo(tz_name)
    if date_override:
        day = datetime.strptime(date_override, "%Y-%m-%d").date()
    else:
        day = datetime.now(tz).date()

    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day, time.max, tzinfo=tz)
    return day.isoformat(), start.timestamp(), end.timestamp(), tz


def should_skip(path: Path, vault: Path) -> bool:
    rel_parts = path.relative_to(vault).parts
    if not rel_parts:
        return True
    first = rel_parts[0]
    rel_path = path.relative_to(vault).as_posix()
    return (
        first in {DAILY_NOTES_DIR, "Templates", "Boards", "Archive", ".obsidian", ".obsidian-auto"}
        or rel_path.startswith(GENERATED_TEST_NOTE_PREFIX)
    )


def is_generated_test_note(path: str) -> bool:
    return path.startswith(GENERATED_TEST_NOTE_PREFIX)


def is_generated_test_note_info(note: dict[str, str | None] | NoteInfo) -> bool:
    note_type = note.note_type if isinstance(note, NoteInfo) else note.get("type")
    return note_type in GENERATED_TEST_NOTE_TYPES


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}

    data: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line or line.startswith(" ") or line.startswith("\t") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip().strip('"')
    return data


def obsidian_link(path: Path, vault: Path) -> str:
    rel = path.relative_to(vault).with_suffix("").as_posix()
    return f"[[{rel}]]"


def note_info(path: Path, vault: Path, tz: ZoneInfo) -> NoteInfo:
    text = path.read_text(encoding="utf-8", errors="replace")
    props = parse_frontmatter(text)
    rel = path.relative_to(vault).as_posix()
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz).isoformat(timespec="seconds")
    return NoteInfo(
        path=rel,
        link=obsidian_link(path, vault),
        title=path.stem,
        mtime=mtime,
        note_type=props.get("type") or None,
        project=props.get("project") or None,
        area=props.get("area") or None,
        task_status=props.get("task_status") or props.get("status") or None,
        priority=props.get("priority") or None,
    )


def changed_notes(vault: Path, start_ts: float, end_ts: float, tz: ZoneInfo) -> list[NoteInfo]:
    notes: list[NoteInfo] = []
    for path in vault.rglob("*.md"):
        if should_skip(path, vault):
            continue
        mtime = path.stat().st_mtime
        if start_ts <= mtime <= end_ts:
            info = note_info(path, vault, tz)
            if not is_generated_test_note_info(info):
                notes.append(info)
    return sorted(notes, key=lambda item: item.path.lower())


def load_manifest(path: Path) -> dict[str, dict[str, str | None]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("notes", {})


def save_manifest(path: Path, date_str: str, notes: dict[str, dict[str, str | None]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date": date_str, "notes": dict(sorted(notes.items()))}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def merge_manifest(
    existing: dict[str, dict[str, str | None]],
    current_notes: list[NoteInfo],
    vault: Path,
    now: datetime,
) -> tuple[dict[str, dict[str, str | None]], bool]:
    merged = {
        path: note
        for path, note in existing.items()
        if (
            path.endswith(".md")
            and not is_generated_test_note(path)
            and not is_generated_test_note_info(note)
            and (vault / path).exists()
        )
    }
    changed = len(merged) != len(existing)
    now_text = now.isoformat(timespec="seconds")
    for note in current_notes:
        previous = merged.get(note.path, {})
        if previous.get("mtime") == note.mtime:
            continue

        merged[note.path] = {
            "first_seen": previous.get("first_seen") or now_text,
            "last_seen": now_text,
            "mtime": note.mtime,
            "link": note.link,
            "title": note.title,
            "type": note.note_type,
            "project": note.project,
            "area": note.area,
            "task_status": note.task_status,
            "priority": note.priority,
        }
        changed = True
    return merged, changed


def daily_note_template(date_str: str) -> str:
    return f"""---
type: daily-note
date: {date_str}
task_status: in_progress
tags:
  - daily-note
---

# {date_str}

## Daily Summary

<!-- AUTO:daily-summary:start -->
No changed notes detected yet.
<!-- AUTO:daily-summary:end -->

## Server Stats

<!-- AUTO:server-stats:start -->
Server stats not fetched yet.
<!-- AUTO:server-stats:end -->

## Focus

- 

## Manual Notes

- 

## Recent Activity

<!-- AUTO:changed-notes:start -->
- No activity detected yet.
<!-- AUTO:changed-notes:end -->

## Due Today

```dataview
TABLE priority, due, task_status, area
FROM "" AND -"Templates"
WHERE due = date(this.date) AND task_status != "done"
SORT priority DESC
```

## Decisions

- 

## Questions

- 

## End Of Day Review

- 
"""


def ensure_daily_note(path: Path, date_str: str) -> str:
    if not path.exists() or path.read_text(encoding="utf-8", errors="replace").strip() == "":
        return daily_note_template(date_str)
    return path.read_text(encoding="utf-8", errors="replace")


def remove_legacy_board_links(text: str) -> str:
    for link in LEGACY_BOARD_LINKS:
        text = text.replace(f"\n{link}\n", "\n")
        text = text.replace(f"{link}\n", "")
    return text


def ensure_marker(text: str, name: str, heading: str, default_body: str) -> str:
    if f"<!-- AUTO:{name}:start -->" in text:
        return text
    block = f"\n\n## {heading}\n\n<!-- AUTO:{name}:start -->\n{default_body}\n<!-- AUTO:{name}:end -->\n"
    return text.rstrip() + block + "\n"


def replace_auto_block(text: str, name: str, body: str) -> str:
    replacement = f"<!-- AUTO:{name}:start -->\n{body.rstrip()}\n<!-- AUTO:{name}:end -->"
    pattern = re.compile(
        rf"<!-- AUTO:{re.escape(name)}:start -->.*?<!-- AUTO:{re.escape(name)}:end -->",
        re.DOTALL,
    )
    if pattern.search(text):
        return pattern.sub(replacement, text)
    return text.rstrip() + "\n\n" + replacement + "\n"


def move_section_after_auto_block(text: str, heading: str, name: str, after_name: str) -> str:
    section_pattern = re.compile(
        rf"\n*## {re.escape(heading)}\n\n"
        rf"<!-- AUTO:{re.escape(name)}:start -->.*?<!-- AUTO:{re.escape(name)}:end -->\n*",
        re.DOTALL,
    )
    match = section_pattern.search(text)
    if not match:
        return text

    section = match.group(0).strip()
    without_section = section_pattern.sub("\n\n", text, count=1).strip() + "\n"
    after_marker = f"<!-- AUTO:{after_name}:end -->"
    marker_index = without_section.find(after_marker)
    if marker_index == -1:
        return without_section.rstrip() + "\n\n" + section + "\n"

    insert_at = marker_index + len(after_marker)
    return (
        without_section[:insert_at].rstrip()
        + "\n\n"
        + section
        + "\n\n"
        + without_section[insert_at:].lstrip("\n")
    )


def _safe_int(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_count(value: object) -> str:
    return f"{_safe_int(value):,}"


def _format_eur(value: object) -> str:
    return f"EUR {_safe_float(value):,.2f}"


def _sum_trend(trend: list[dict[str, object]], key: str) -> int:
    return sum(_safe_int(day.get(key)) for day in trend)


def _sum_trend_float(trend: list[dict[str, object]], key: str) -> float:
    return sum(_safe_float(day.get(key)) for day in trend)


def _svg_escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _monthly_revenue(stripe_monthly: list[dict[str, object]], bank_monthly: list[dict[str, object]]) -> list[dict[str, object]]:
    by_month: dict[str, dict[str, object]] = {}
    for month in stripe_monthly:
        if not isinstance(month, dict):
            continue
        label = str(month.get("month") or "?")
        by_month.setdefault(label, {"month": label, "stripe": 0.0, "bank": 0.0, "transactions": 0})
        by_month[label]["stripe"] = _safe_float(month.get("revenue_eur"))
        by_month[label]["transactions"] = _safe_int(month.get("transactions"))
    for month in bank_monthly:
        if not isinstance(month, dict):
            continue
        label = str(month.get("month") or "?")
        by_month.setdefault(label, {"month": label, "stripe": 0.0, "bank": 0.0, "transactions": 0})
        by_month[label]["bank"] = _safe_float(month.get("revenue_eur"))
        by_month[label]["transactions"] = _safe_int(by_month[label].get("transactions")) + _safe_int(month.get("transfers"))
    return [by_month[month] for month in sorted(by_month)][-6:]


def _daily_revenue(stripe_daily: list[dict[str, object]], bank_daily: list[dict[str, object]]) -> list[dict[str, object]]:
    by_day: dict[str, dict[str, object]] = {}
    for day in stripe_daily:
        if not isinstance(day, dict):
            continue
        label = str(day.get("date") or "")
        if not label:
            continue
        by_day.setdefault(label, {"date": label, "stripe": 0.0, "bank": 0.0, "transactions": 0})
        by_day[label]["stripe"] = _safe_float(day.get("revenue_eur"))
        by_day[label]["transactions"] = _safe_int(day.get("transactions"))
    for day in bank_daily:
        if not isinstance(day, dict):
            continue
        label = str(day.get("date") or "")
        if not label:
            continue
        by_day.setdefault(label, {"date": label, "stripe": 0.0, "bank": 0.0, "transactions": 0})
        by_day[label]["bank"] = _safe_float(day.get("revenue_eur"))
        by_day[label]["transactions"] = _safe_int(by_day[label].get("transactions")) + _safe_int(day.get("transactions"))
    return [by_day[day] for day in sorted(by_day)]


def _six_month_month_cutoff(date_str: str) -> str:
    year, month, *_ = [int(part) for part in date_str.split("-")]
    month -= 5
    while month <= 0:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def _last_six_month_labels(date_str: str) -> list[str]:
    year, month, *_ = [int(part) for part in date_str.split("-")]
    labels = []
    for offset in range(5, -1, -1):
        label_year = year
        label_month = month - offset
        while label_month <= 0:
            label_month += 12
            label_year -= 1
        labels.append(f"{label_year:04d}-{label_month:02d}")
    return labels


def _last_day_labels(date_str: str, days: int) -> list[str]:
    end = datetime.strptime(date_str, "%Y-%m-%d").date()
    return [(end - timedelta(days=offset)).isoformat() for offset in range(days - 1, -1, -1)]


def _align_month_items(
    items: list[dict[str, object]],
    labels: list[str],
    value_keys: tuple[str, ...],
) -> list[dict[str, object]]:
    by_month = {str(item.get("month") or ""): item for item in items}
    aligned = []
    for label in labels:
        item = dict(by_month.get(label, {}))
        item["month"] = label
        for key in value_keys:
            item.setdefault(key, None)
        aligned.append(item)
    return aligned


def _filter_month_window(items: list[dict[str, object]], date_str: str, key: str = "month") -> list[dict[str, object]]:
    cutoff = _six_month_month_cutoff(date_str)
    return [item for item in items if str(item.get(key) or "") >= cutoff]


def _monthly_user_history(monthly_trend: list[dict[str, object]], current_paid_users: int) -> list[dict[str, object]]:
    months = [month for month in monthly_trend if isinstance(month, dict)][-6:]
    paid_by_month: list[int] = []
    later_new_paid = 0
    for month in reversed(months):
        paid_by_month.append(max(0, current_paid_users - later_new_paid))
        later_new_paid += _safe_int(month.get("new_paying_users"))
    paid_by_month.reverse()
    return [
        {
            "month": str(month.get("month") or "?"),
            "registered": _safe_int(month.get("total_users")),
            "paid": paid_by_month[index] if index < len(paid_by_month) else current_paid_users,
        }
        for index, month in enumerate(months)
    ]


def _daily_newsletter_history(vault: Path, date_str: str, current_subscribers: int) -> list[dict[str, object]]:
    history: list[dict[str, object]] = []
    daily_dir = vault / DAILY_NOTES_DIR
    if daily_dir.exists():
        for path in sorted(daily_dir.glob("*.md")):
            day = path.stem
            if day > date_str:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            match = re.search(r"\| Newsletter \| ([\d,]+) confirmed subscribers \|", text)
            if match:
                history.append({"date": day, "subscribers": _safe_int(match.group(1).replace(",", ""))})
    if not history or history[-1].get("date") != date_str:
        history.append({"date": date_str, "subscribers": current_subscribers})
    else:
        history[-1]["subscribers"] = current_subscribers
    return history[-180:]


def _monthly_newsletter_history(vault: Path, date_str: str, current_subscribers: int) -> list[dict[str, object]]:
    by_month: dict[str, dict[str, object]] = {}
    for item in _daily_newsletter_history(vault, date_str, current_subscribers):
        day = str(item.get("date") or "")
        month = day[:7]
        if not month:
            continue
        by_month[month] = {"month": month, "subscribers": _safe_int(item.get("subscribers"))}
    return _filter_month_window([by_month[month] for month in sorted(by_month)], date_str)


def _daily_snapshot_deltas(
    history: list[dict[str, object]],
    labels: list[str],
    key: str,
    clamp_negative: bool = False,
) -> dict[str, float | None]:
    by_day = {str(item.get("date") or ""): item for item in history}
    deltas: dict[str, float | None] = {}
    previous_value: float | None = None
    for day in sorted(by_day):
        value = _optional_float(by_day[day].get(key))
        if value is not None and previous_value is not None and day in labels:
            delta = value - previous_value
            deltas[day] = max(0.0, delta) if clamp_negative else delta
        elif day in labels:
            deltas[day] = None
        if value is not None:
            previous_value = value
    for label in labels:
        deltas.setdefault(label, None)
    return deltas


def _sum_optional(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def _line_path(values: list[float], x: float, y: float, width: float, height: float) -> str:
    points = _line_points(values, x, y, width, height)
    if not points:
        return ""
    command = [f"M{points[0][0]:.1f} {points[0][1]:.1f}"]
    command.extend(f"L{px:.1f} {py:.1f}" for px, py in points[1:])
    return " ".join(command)


def _line_points(values: list[float], x: float, y: float, width: float, height: float) -> list[tuple[float, float]]:
    if not values:
        return []
    max_value = max(values) or 1.0
    min_value = min(values)
    if max_value == min_value:
        step = width / max(len(values) - 1, 1)
        return [(x + index * step, y + height / 2) for index, _ in enumerate(values)]
    span = max_value - min_value
    step = width / max(len(values) - 1, 1)
    points: list[tuple[float, float]] = []
    for index, value in enumerate(values):
        px = x + index * step
        py = y + height - ((value - min_value) / span * height)
        points.append((px, py))
    return points


def _line_path_fixed_scale(
    values: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
    min_value: float,
    max_value: float,
) -> str:
    points = _line_points_fixed_scale(values, x, y, width, height, min_value, max_value)
    if not points:
        return ""
    command = [f"M{points[0][0]:.1f} {points[0][1]:.1f}"]
    command.extend(f"L{px:.1f} {py:.1f}" for px, py in points[1:])
    return " ".join(command)


def _line_points_fixed_scale(
    values: list[float],
    x: float,
    y: float,
    width: float,
    height: float,
    min_value: float,
    max_value: float,
) -> list[tuple[float, float]]:
    if not values:
        return []
    span = max(max_value - min_value, 1.0)
    step = width / max(len(values) - 1, 1)
    return [
        (x + index * step, y + height - ((value - min_value) / span * height))
        for index, value in enumerate(values)
    ]


def _line_path_optional(values: list[float | None], x: float, y: float, width: float, height: float) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return ""
    min_value = min(present)
    max_value = max(present) or 1.0
    if max_value == min_value:
        max_value = min_value + 1.0
    span = max_value - min_value
    step = width / max(len(values) - 1, 1)
    commands: list[str] = []
    drawing = False
    for index, value in enumerate(values):
        if value is None:
            drawing = False
            continue
        px = x + index * step
        py = y + height - ((value - min_value) / span * height)
        commands.append(("L" if drawing else "M") + f"{px:.1f} {py:.1f}")
        drawing = True
    return " ".join(commands)


def _line_dots_optional(values: list[float | None], x: float, y: float, width: float, height: float, fill: str) -> str:
    present = [value for value in values if value is not None]
    if not present:
        return ""
    min_value = min(present)
    max_value = max(present) or 1.0
    if max_value == min_value:
        max_value = min_value + 1.0
    span = max_value - min_value
    step = width / max(len(values) - 1, 1)
    dots = []
    for index, value in enumerate(values):
        if value is None:
            continue
        px = x + index * step
        py = y + height - ((value - min_value) / span * height)
        dots.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{fill}" stroke="{SVG_COLORS["card"]}" stroke-width="2"/>')
    return "".join(dots)


def _line_dots_fixed_scale(
    values: list[float | None],
    x: float,
    y: float,
    width: float,
    height: float,
    min_value: float,
    max_value: float,
    fill: str,
) -> str:
    return "".join(
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{fill}" stroke="{SVG_COLORS["card"]}" stroke-width="2"/>'
        for px, py in _line_points_fixed_scale(values, x, y, width, height, min_value, max_value)
    )


def _line_dots(values: list[float], x: float, y: float, width: float, height: float, fill: str) -> str:
    return "".join(
        f'<circle cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{fill}" stroke="{SVG_COLORS["card"]}" stroke-width="2"/>'
        for px, py in _line_points(values, x, y, width, height)
    )


def _all_axis_labels(labels: list[str], x: float, y: float, width: float, font_size: int = 16) -> str:
    if not labels:
        return ""
    colors = SVG_COLORS
    step = width / max(len(labels) - 1, 1)
    return "".join(
        f'<text x="{x + index * step:.1f}" y="{y}" fill="{colors["text_tertiary"]}" font-family="{SVG_FONT}" font-size="{font_size}" font-weight="500" text-anchor="middle">{_svg_escape(label)}</text>'
        for index, label in enumerate(labels)
    )


def _value_row(
    label: str,
    values: list[float],
    x: float,
    y: float,
    width: float,
    color: str,
    formatter: str = "count",
    font_size: int = 16,
) -> str:
    if not values:
        return ""
    step = width / max(len(values) - 1, 1)
    label_text = f'<text x="78" y="{y}" fill="{color}" font-family="{SVG_FONT}" font-size="{font_size}" font-weight="800" text-anchor="start">{_svg_escape(label)}</text>'
    cells = []
    for index, value in enumerate(values):
        if value is None:
            text = "-"
        else:
            text = f"EUR {value:,.0f}" if formatter == "eur" else f"{value:,.0f}"
        cells.append(
            f'<text x="{x + index * step:.1f}" y="{y}" fill="{SVG_COLORS["text_secondary"]}" font-family="{SVG_FONT}" font-size="{font_size}" font-weight="500" text-anchor="middle">{_svg_escape(text)}</text>'
        )
    return label_text + "".join(cells)


def _svg_shell(title: str, subtitle: str, body: str, defs: str = "") -> str:
    colors = SVG_COLORS
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" role="img" aria-labelledby="title desc">
  <title id="title">{_svg_escape(title)}</title>
  <desc id="desc">{_svg_escape(subtitle)}</desc>
  <defs>
    <linearGradient id="om-primary" x1="0" x2="1" y1="0" y2="1"><stop offset="9.04%" stop-color="{colors['primary_start']}"/><stop offset="90.06%" stop-color="{colors['primary_end']}"/></linearGradient>
    <linearGradient id="om-action" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="{colors['button']}"/><stop offset="1" stop-color="{colors['button_hover']}"/></linearGradient>
    <linearGradient id="om-finance" x1="0" x2="1" y1="0" y2="1"><stop offset="9.04%" stop-color="{colors['finance_start']}"/><stop offset="90.06%" stop-color="{colors['finance_end']}"/></linearGradient>
    <linearGradient id="om-health" x1="0" x2="1" y1="0" y2="1"><stop offset="9.04%" stop-color="{colors['health_start']}"/><stop offset="90.06%" stop-color="{colors['health_end']}"/></linearGradient>
    <linearGradient id="om-travel" x1="0" x2="1" y1="0" y2="1"><stop offset="9.04%" stop-color="{colors['travel_start']}"/><stop offset="90.06%" stop-color="{colors['travel_end']}"/></linearGradient>
    <filter id="card-shadow" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="4" stdDeviation="12" flood-color="#000000" flood-opacity="0.22"/></filter>
{defs}
  </defs>
  <rect width="{SVG_WIDTH}" height="{SVG_HEIGHT}" rx="34" fill="{colors['background']}"/>
  <rect x="38" y="34" width="1124" height="592" rx="28" fill="{colors['card']}" filter="url(#card-shadow)"/>
  <rect x="38" y="34" width="1124" height="8" rx="4" fill="url(#om-primary)"/>
  <text x="78" y="92" fill="{colors['text']}" font-family="{SVG_FONT}" font-size="40" font-weight="800">{_svg_escape(title)}</text>
  <text x="78" y="128" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="20" font-weight="500">{_svg_escape(subtitle)}</text>
{body}
</svg>
'''


def _write_svg(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _daily_note_image_embed(vault_relative_path: str) -> str:
    # Daily notes live in DAILY_NOTES_DIR, so standard Markdown image links need
    # one parent hop. Obsidian SVG wikilinks are not rendered reliably in all setups.
    alt = Path(vault_relative_path).stem.replace("-", " ").title()
    return f"![{alt}](../{vault_relative_path})"


def _revenue_svg(
    lifetime_revenue: float,
    monthly_revenue: list[dict[str, object]],
    paid_users: int,
) -> str:
    colors = SVG_COLORS
    chart_x = 230
    chart_y = 176
    chart_w = 850
    chart_h = 250
    totals = []
    for month in monthly_revenue:
        stripe = _optional_float(month.get("stripe"))
        bank = _optional_float(month.get("bank"))
        totals.append(None if stripe is None and bank is None else (stripe or 0.0) + (bank or 0.0))
    max_total = max((total for total in totals if total is not None), default=1.0)
    max_total = max(max_total, 1.0)
    bar_gap = 42
    bar_w = (chart_w - bar_gap * (len(monthly_revenue) - 1)) / max(len(monthly_revenue), 1)
    bars = []
    for index, month in enumerate(monthly_revenue):
        stripe = _optional_float(month.get("stripe"))
        bank = _optional_float(month.get("bank"))
        total = None if stripe is None and bank is None else (stripe or 0.0) + (bank or 0.0)
        x = chart_x + index * (bar_w + bar_gap)
        if total is not None:
            stripe_height = (stripe or 0.0) / max_total * chart_h
            bank_height = (bank or 0.0) / max_total * chart_h
            stripe_y = chart_y + chart_h - stripe_height
            bank_y = stripe_y - bank_height
            label_y = max(chart_y - 10, bank_y - 12)
            bars.append(f'<rect x="{x:.1f}" y="{stripe_y:.1f}" width="{bar_w:.1f}" height="{stripe_height:.1f}" rx="15" fill="url(#om-primary)"/>')
            if bank_height > 0:
                bars.append(f'<rect x="{x:.1f}" y="{bank_y:.1f}" width="{bar_w:.1f}" height="{bank_height:.1f}" rx="15" fill="url(#om-finance)"/>')
            bars.append(f'<text x="{x + bar_w / 2:.1f}" y="{label_y:.1f}" fill="{colors["text_primary"]}" font-family="{SVG_FONT}" font-size="21" font-weight="700" text-anchor="middle">{_svg_escape(f"EUR {total:,.0f}")}</text>')
        bars.append(f'<text x="{x + bar_w / 2:.1f}" y="{chart_y + chart_h + 38}" fill="{colors["text_tertiary"]}" font-family="{SVG_FONT}" font-size="19" font-weight="500" text-anchor="middle">{_svg_escape(month.get("month", "?"))}</text>')
    grid = "".join(
        f'<line x1="{chart_x}" y1="{chart_y + chart_h * i / 4:.1f}" x2="{chart_x + chart_w}" y2="{chart_y + chart_h * i / 4:.1f}" stroke="{colors["grid"]}" stroke-opacity="0.45"/>'
        for i in range(5)
    )
    body = f'''
  <text x="1112" y="92" fill="{colors['text']}" font-family="{SVG_FONT}" font-size="36" font-weight="800" text-anchor="end">{_svg_escape(_format_eur(lifetime_revenue))}</text>
  <text x="1112" y="128" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="19" font-weight="500" text-anchor="end">lifetime · {paid_users:,} paid users</text>
  <g>{grid}{''.join(bars)}</g>
  {_value_row('Total', totals, chart_x, 512, chart_w, colors['text_primary'], 'eur', 18)}
  <circle cx="86" cy="574" r="8" fill="url(#om-primary)"/><text x="106" y="581" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="18">Stripe</text>
  <circle cx="190" cy="574" r="8" fill="url(#om-finance)"/><text x="210" y="581" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="18">Bank transfer</text>
'''
    return _svg_shell("Revenue", "Revenue in the last 6 months, with lifetime total in the header", body)


def _users_svg(user_history: list[dict[str, object]], registered_accounts: int, paying_customers: int) -> str:
    colors = SVG_COLORS
    conversion = paying_customers * 100 / registered_accounts if registered_accounts else 0.0
    chart_x = 230
    chart_w = 850
    panel_h = 88
    registered_values = [_optional_float(month.get("registered")) for month in user_history]
    paid_values = [_optional_float(month.get("paid")) for month in user_history]
    labels = [str(month.get("month") or "?") for month in user_history]

    def panel(y: float, title: str, values: list[float | None], stroke: str, total: int) -> str:
        grid = "".join(
            f'<line x1="{chart_x}" y1="{y + panel_h * i / 3:.1f}" x2="{chart_x + chart_w}" y2="{y + panel_h * i / 3:.1f}" stroke="{colors["grid"]}" stroke-opacity="0.4"/>'
            for i in range(4)
        )
        return f'''
  <text x="{chart_x}" y="{y - 16}" fill="{colors['text_primary']}" font-family="{SVG_FONT}" font-size="21" font-weight="800">{_svg_escape(title)}</text>
  <text x="{chart_x + chart_w}" y="{y - 16}" fill="{colors['text']}" font-family="{SVG_FONT}" font-size="24" font-weight="800" text-anchor="end">{total:,}</text>
  <g>{grid}<path d="{_line_path_optional(values, chart_x, y, chart_w, panel_h)}" fill="none" stroke="{stroke}" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>{_line_dots_optional(values, chart_x, y, chart_w, panel_h, stroke)}</g>
'''

    body = f'''
  <text x="1112" y="92" fill="{colors['text']}" font-family="{SVG_FONT}" font-size="36" font-weight="800" text-anchor="end">{conversion:.1f}%</text>
  <text x="1112" y="128" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="19" font-weight="500" text-anchor="end">paid conversion</text>
  {panel(184, 'Registered accounts over time', registered_values, 'url(#om-primary)', registered_accounts)}
  {panel(316, 'Paid users over time', paid_values, 'url(#om-action)', paying_customers)}
  {_all_axis_labels(labels, chart_x, 458, chart_w, 19)}
  {_value_row('Registered', registered_values, chart_x, 498, chart_w, colors['primary_end'], 'count', 18)}
  {_value_row('Paid', paid_values, chart_x, 536, chart_w, colors['button'], 'count', 18)}
'''
    return _svg_shell("Users", "Registered accounts and paid users in the last 6 months", body)


def _engagement_svg(engagement_trend: list[dict[str, object]], paid_users: int) -> str:
    colors = SVG_COLORS
    engagement_trend = engagement_trend[-7:]
    chart_x = 220
    chart_y = 176
    chart_w = 860
    chart_h = 194
    messages = [_safe_float(day.get("messages")) for day in engagement_trend]
    chats = [_safe_float(day.get("chats")) for day in engagement_trend]
    embeds = [_safe_float(day.get("embeds")) for day in engagement_trend]
    labels = [str(day.get("date") or "?")[5:] for day in engagement_trend]
    totals = {
        "messages": sum(messages),
        "chats": sum(chats),
        "embeds": sum(embeds),
    }
    max_all = max(messages + chats + embeds + [1.0])

    def path(values: list[float]) -> str:
        return _line_path_fixed_scale(values, chart_x, chart_y, chart_w, chart_h, 0, max_all)

    def dots(values: list[float], fill: str) -> str:
        return _line_dots_fixed_scale(values, chart_x, chart_y, chart_w, chart_h, 0, max_all, fill)

    grid = "".join(
        f'<line x1="{chart_x}" y1="{chart_y + chart_h * i / 4:.1f}" x2="{chart_x + chart_w}" y2="{chart_y + chart_h * i / 4:.1f}" stroke="{colors["grid"]}" stroke-opacity="0.45"/>'
        for i in range(5)
    )
    per_paid = totals["messages"] / paid_users if paid_users else 0.0
    body = f'''
  <text x="1112" y="92" fill="{colors['text']}" font-family="{SVG_FONT}" font-size="36" font-weight="800" text-anchor="end">{totals['messages']:,.0f}</text>
  <text x="1112" y="128" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="19" font-weight="500" text-anchor="end">messages · {per_paid:.1f} per paid user</text>
  <g>{grid}
    <path d="{path(embeds)}" fill="none" stroke="url(#om-primary)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="{path(messages)}" fill="none" stroke="url(#om-action)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="{path(chats)}" fill="none" stroke="url(#om-finance)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>
    {dots(embeds, 'url(#om-primary)')}{dots(messages, 'url(#om-action)')}{dots(chats, 'url(#om-finance)')}
  </g>
  {_all_axis_labels(labels, chart_x, 410, chart_w, 19)}
  {_value_row('Messages', messages, chart_x, 448, chart_w, colors['button'], 'count', 18)}
  {_value_row('Chats', chats, chart_x, 486, chart_w, colors['finance_end'], 'count', 18)}
  {_value_row('Embeds', embeds, chart_x, 524, chart_w, colors['primary_end'], 'count', 18)}
  <circle cx="86" cy="574" r="8" fill="url(#om-action)"/><text x="106" y="581" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="18">Messages {totals['messages']:,.0f}</text>
  <circle cx="270" cy="574" r="8" fill="url(#om-finance)"/><text x="290" y="581" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="18">Chats {totals['chats']:,.0f}</text>
  <circle cx="410" cy="574" r="8" fill="url(#om-primary)"/><text x="430" y="581" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="18">Embeds {totals['embeds']:,.0f}</text>
'''
    return _svg_shell("Engagement", "Daily engagement over the last 7 days", body)


def _newsletter_svg(
    monthly_newsletter: list[dict[str, object]],
    confirmed_subscribers: int,
    page_loads: int,
    unique_visits: int,
) -> str:
    colors = SVG_COLORS
    milestone = ((confirmed_subscribers // 50) + 1) * 50 if confirmed_subscribers else 50
    progress = confirmed_subscribers / milestone if milestone else 0.0
    chart_x = 230
    chart_y = 188
    chart_w = 850
    chart_h = 214
    subscribers = [_optional_float(month.get("subscribers")) for month in monthly_newsletter]
    labels = [str(month.get("month") or "?") for month in monthly_newsletter]
    grid = "".join(
        f'<line x1="{chart_x}" y1="{chart_y + chart_h * i / 4:.1f}" x2="{chart_x + chart_w}" y2="{chart_y + chart_h * i / 4:.1f}" stroke="{colors["grid"]}" stroke-opacity="0.45"/>'
        for i in range(5)
    )
    body = f'''
  <text x="1112" y="92" fill="{colors['text']}" font-family="{SVG_FONT}" font-size="36" font-weight="800" text-anchor="end">{confirmed_subscribers:,}</text>
  <text x="1112" y="128" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="19" font-weight="500" text-anchor="end">confirmed subscribers</text>
  <g>{grid}<path d="{_line_path_optional(subscribers, chart_x, chart_y, chart_w, chart_h)}" fill="none" stroke="url(#om-primary)" stroke-width="8" stroke-linecap="round" stroke-linejoin="round"/>{_line_dots_optional(subscribers, chart_x, chart_y, chart_w, chart_h, 'url(#om-primary)')}</g>
  {_all_axis_labels(labels, chart_x, 434, chart_w, 19)}
  {_value_row('Subscribers', subscribers, chart_x, 478, chart_w, colors['primary_end'], 'count', 18)}
  <text x="88" y="538" fill="{colors['text_primary']}" font-family="{SVG_FONT}" font-size="21" font-weight="800">Next milestone</text>
  <rect x="330" y="517" width="520" height="34" rx="17" fill="{colors['card_alt']}"/>
  <rect x="330" y="517" width="{min(520, max(18, 520 * progress)):.1f}" height="34" rx="17" fill="url(#om-primary)"/>
  <text x="900" y="542" fill="{colors['text']}" font-family="{SVG_FONT}" font-size="21" font-weight="800">{confirmed_subscribers:,} / {milestone:,}</text>
  <text x="1112" y="582" fill="{colors['text_tertiary']}" font-family="{SVG_FONT}" font-size="18" text-anchor="end">Web yesterday: {unique_visits:,} unique · {page_loads:,} loads</text>
'''
    return _svg_shell("Newsletter & Web", "Subscriber snapshots from the last 6 months plus web traffic", body)


def _daily_development_svg(metrics: list[dict[str, object]]) -> str:
    colors = SVG_COLORS
    card_w = 315
    card_h = 118
    start_x = 78
    start_y = 168
    gap_x = 48
    gap_y = 28

    def block_color(current: float | None, previous: float | None, lower_is_better: bool) -> str:
        if lower_is_better and current and current > 0:
            return colors["warning"]
        if current is None or previous is None or current == previous:
            return colors["primary_end"]
        if current > previous:
            return colors["warning"] if lower_is_better else colors["finance_end"]
        return colors["finance_end"] if lower_is_better else colors["warning"]

    def format_value(value: float | None, formatter: str) -> str:
        if value is None:
            return "-"
        if formatter == "eur":
            return f"{value:,.0f} EUR"
        return f"{value:,.0f}"

    def format_delta(current: float | None, previous: float | None, formatter: str) -> str:
        if previous is None:
            return "no week-before data"
        if formatter == "eur":
            return f"{previous:,.0f} EUR in week before"
        return f"{previous:,.0f} in week before"

    blocks = []
    for index, metric in enumerate(metrics):
        x = start_x + (index % 3) * (card_w + gap_x)
        y = start_y + (index // 3) * (card_h + gap_y)
        current = _optional_float(metric.get("current"))
        previous = _optional_float(metric.get("previous"))
        if metric.get("default_zero"):
            current = current or 0.0
            previous = previous or 0.0
        formatter = str(metric.get("formatter") or "count")
        lower_is_better = bool(metric.get("lower_is_better"))
        fill = block_color(current, previous, lower_is_better)
        blocks.append(
            f'<rect x="{x}" y="{y}" width="{card_w}" height="{card_h}" rx="24" fill="{fill}" fill-opacity="0.24" stroke="{fill}" stroke-opacity="0.74"/>'
        )
        blocks.append(
            f'<text x="{x + 24}" y="{y + 42}" fill="{fill}" font-family="{SVG_FONT}" font-size="30" font-weight="800">{_svg_escape(format_value(current, formatter))}</text>'
        )
        blocks.append(
            f'<text x="{x + 24}" y="{y + 72}" fill="{colors["text_secondary"]}" font-family="{SVG_FONT}" font-size="18" font-weight="800">{_svg_escape(metric.get("label", "?"))}</text>'
        )
        blocks.append(
            f'<text x="{x + 24}" y="{y + 100}" fill="{colors["text_tertiary"]}" font-family="{SVG_FONT}" font-size="15" font-weight="500">{_svg_escape(format_delta(current, previous, formatter))}</text>'
        )
    body = f'''
  <text x="1112" y="92" fill="{colors['text']}" font-family="{SVG_FONT}" font-size="28" font-weight="800" text-anchor="end">last 7 days</text>
  <text x="1112" y="128" fill="{colors['text_secondary']}" font-family="{SVG_FONT}" font-size="18" font-weight="500" text-anchor="end">green up · blue same · orange down</text>
  {''.join(blocks)}
'''
    return _svg_shell("Daily Development", "Seven-day totals compared with the previous seven days", body)


def generate_daily_metric_svgs(
    vault: Path,
    date_str: str,
    sections: dict[str, object],
    dry_run: bool,
) -> list[str]:
    lifetime = sections.get("lifetime_revenue") if isinstance(sections.get("lifetime_revenue"), dict) else {}
    stripe_revenue = sections.get("stripe_revenue") if isinstance(sections.get("stripe_revenue"), dict) else {}
    bank_transfer_revenue = sections.get("bank_transfer_revenue") if isinstance(sections.get("bank_transfer_revenue"), dict) else {}
    invoices = sections.get("invoices") if isinstance(sections.get("invoices"), dict) else {}
    user_growth = sections.get("user_growth") if isinstance(sections.get("user_growth"), dict) else {}
    engagement = sections.get("engagement") if isinstance(sections.get("engagement"), dict) else {}
    web_analytics = sections.get("web_analytics") if isinstance(sections.get("web_analytics"), dict) else {}
    newsletter = sections.get("newsletter") if isinstance(sections.get("newsletter"), dict) else {}

    registered_accounts = _safe_int(user_growth.get("total_users"))
    invoice_buyers = _safe_int(invoices.get("lifetime_unique_buyers"))
    known_paying_users = _safe_int(newsletter.get("total_paying_users"))
    paying_customers = max(invoice_buyers, known_paying_users)
    stripe_all_time = stripe_revenue.get("all_time_eur") if "error" not in stripe_revenue else None
    bank_all_time = bank_transfer_revenue.get("all_time_eur") if "error" not in bank_transfer_revenue else None
    revenue_parts = [value for value in (stripe_all_time, bank_all_time) if isinstance(value, (int, float))]
    lifetime_revenue = sum(float(value) for value in revenue_parts) if revenue_parts else _safe_float(lifetime.get("total_eur"))
    engagement_trend = engagement.get("trend_14d") if isinstance(engagement.get("trend_14d"), list) else []
    revenue_trend = sections.get("revenue", {}).get("trend_14d") if isinstance(sections.get("revenue"), dict) else []
    if not isinstance(revenue_trend, list):
        revenue_trend = []
    lifetime_monthly_trend = lifetime.get("monthly_trend") if isinstance(lifetime.get("monthly_trend"), list) else []
    stripe_monthly = stripe_revenue.get("monthly") if isinstance(stripe_revenue.get("monthly"), list) else []
    bank_monthly = bank_transfer_revenue.get("monthly") if isinstance(bank_transfer_revenue.get("monthly"), list) else []
    stripe_daily = stripe_revenue.get("daily") if isinstance(stripe_revenue.get("daily"), list) else []
    bank_daily = bank_transfer_revenue.get("daily") if isinstance(bank_transfer_revenue.get("daily"), list) else []
    month_labels = _last_six_month_labels(date_str)
    comparison_day_labels = _last_day_labels(date_str, 14)
    previous_day_labels = comparison_day_labels[:7]
    day_labels = comparison_day_labels[7:]
    monthly_revenue = _align_month_items(
        _filter_month_window(_monthly_revenue(stripe_monthly, bank_monthly), date_str),
        month_labels,
        ("stripe", "bank", "transactions"),
    )
    daily_revenue_by_day = {
        str(day.get("date") or ""): day
        for day in _daily_revenue(stripe_daily, bank_daily)
        if day.get("date")
    }
    user_history = _align_month_items(
        _filter_month_window(_monthly_user_history(lifetime_monthly_trend, paying_customers), date_str),
        month_labels,
        ("registered", "paid"),
    )
    confirmed_subscribers = _safe_int(newsletter.get("confirmed_subscribers"))
    monthly_newsletter = _align_month_items(
        _monthly_newsletter_history(vault, date_str, confirmed_subscribers),
        month_labels,
        ("subscribers",),
    )
    trend_by_day = {
        str(item.get("date") or ""): item
        for item in revenue_trend
        if isinstance(item, dict) and item.get("date")
    }
    engagement_by_day = {
        str(item.get("date") or ""): item
        for item in engagement_trend
        if isinstance(item, dict) and item.get("date")
    }
    newsletter_deltas = _daily_snapshot_deltas(
        _daily_newsletter_history(vault, date_str, confirmed_subscribers),
        comparison_day_labels,
        "subscribers",
        clamp_negative=True,
    )
    def trend_values(source: dict[str, dict[str, object]], key: str) -> list[float | None]:
        return [_optional_float(source.get(label, {}).get(key)) for label in day_labels]

    def previous_trend_values(source: dict[str, dict[str, object]], key: str) -> list[float | None]:
        return [_optional_float(source.get(label, {}).get(key)) for label in previous_day_labels]

    def current_snapshot_total(deltas: dict[str, float | None]) -> float | None:
        return _sum_optional([deltas[label] for label in day_labels])

    def previous_snapshot_total(deltas: dict[str, float | None]) -> float | None:
        return _sum_optional([deltas[label] for label in previous_day_labels])

    def current_trend_total(source: dict[str, dict[str, object]], key: str) -> float | None:
        return _sum_optional(trend_values(source, key))

    def previous_trend_total(source: dict[str, dict[str, object]], key: str) -> float | None:
        return _sum_optional(previous_trend_values(source, key))

    def signup_values(labels: list[str]) -> list[float | None]:
        values = []
        for label in labels:
            item = trend_by_day.get(label, {})
            registrations = _optional_float(item.get("new_registrations"))
            completed = _optional_float(item.get("completed_signups"))
            values.append(None if registrations is None and completed is None else max(0.0, (registrations or 0.0) - (completed or 0.0)))
        return values

    def revenue_values(labels: list[str], key: str) -> list[float | None]:
        if not stripe_daily and not bank_daily:
            return [None for _ in labels]
        values = []
        for label in labels:
            day = daily_revenue_by_day.get(label, {})
            if key == "revenue_eur":
                values.append(_safe_float(day.get("stripe")) + _safe_float(day.get("bank")))
            else:
                values.append(float(_safe_int(day.get(key))))
        return values

    daily_development_metrics = [
        {
            "label": "Revenue",
            "current": _sum_optional(revenue_values(day_labels, "revenue_eur")),
            "previous": _sum_optional(revenue_values(previous_day_labels, "revenue_eur")),
            "formatter": "eur",
        },
        {
            "label": "New signups",
            "current": _sum_optional(signup_values(day_labels)),
            "previous": _sum_optional(signup_values(previous_day_labels)),
        },
        {
            "label": "New purchases",
            "current": _sum_optional(revenue_values(day_labels, "transactions")),
            "previous": _sum_optional(revenue_values(previous_day_labels, "transactions")),
        },
        {
            "label": "New chats",
            "current": current_trend_total(engagement_by_day, "chats"),
            "previous": previous_trend_total(engagement_by_day, "chats"),
        },
        {
            "label": "New messages",
            "current": current_trend_total(engagement_by_day, "messages"),
            "previous": previous_trend_total(engagement_by_day, "messages"),
        },
        {
            "label": "New app skill uses",
            "current": current_trend_total(trend_by_day, "usage_entries_created"),
            "previous": previous_trend_total(trend_by_day, "usage_entries_created"),
        },
        {
            "label": "Used credits",
            "current": current_trend_total(trend_by_day, "credits_used"),
            "previous": previous_trend_total(trend_by_day, "credits_used"),
        },
        {
            "label": "New newsletter subscribers",
            "current": current_snapshot_total(newsletter_deltas),
            "previous": previous_snapshot_total(newsletter_deltas),
        },
        {
            "label": "Deleted accounts",
            "current": current_trend_total(trend_by_day, "deleted_accounts"),
            "previous": previous_trend_total(trend_by_day, "deleted_accounts"),
            "lower_is_better": True,
        },
    ]
    asset_dir = vault / DAILY_METRICS_ASSET_DIR / date_str
    files = {
        "daily-development.svg": _daily_development_svg(daily_development_metrics),
        "revenue.svg": _revenue_svg(lifetime_revenue, monthly_revenue, paying_customers),
        "users.svg": _users_svg(user_history, registered_accounts, paying_customers),
        "engagement.svg": _engagement_svg(engagement_trend, paying_customers),
        "newsletter-web.svg": _newsletter_svg(
            monthly_newsletter,
            confirmed_subscribers,
            _safe_int(web_analytics.get("page_loads")),
            _safe_int(web_analytics.get("unique_visits")),
        ),
    }
    for filename, content in files.items():
        _write_svg(asset_dir / filename, content, dry_run)
    return [f"{DAILY_METRICS_ASSET_DIR}/{date_str}/{filename}" for filename in files]


def _read_server_stats_cache(cache_path: Path) -> dict[str, object] | None:
    if not cache_path.exists():
        return None
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _server_stats_cache_is_fresh(cache_path: Path) -> bool:
    if not cache_path.exists():
        return False
    age_seconds = datetime.now().timestamp() - cache_path.stat().st_mtime
    return age_seconds < SERVER_STATS_CACHE_MAX_AGE_SECONDS


def _fetch_production_server_stats(git_repo: Path) -> dict[str, object]:
    result = subprocess.run(
        [
            "docker",
            "exec",
            "api",
            "python3",
            "/app/backend/scripts/server_stats_query.py",
            "--prod",
            "--json",
        ],
        cwd=git_repo,
        capture_output=True,
        text=True,
        timeout=75,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"server_stats_query.py --prod failed: {stderr[:500]}")
    return json.loads(result.stdout)


def load_or_refresh_server_stats(
    vault: Path,
    git_repo: Path,
    now: datetime,
    dry_run: bool,
) -> tuple[dict[str, object] | None, str | None]:
    cache_path = vault / SERVER_STATS_CACHE_DIR / "production-latest.json"
    cached = _read_server_stats_cache(cache_path)
    if cached and _server_stats_cache_is_fresh(cache_path):
        return cached, None

    try:
        data = _fetch_production_server_stats(git_repo)
    except Exception as exc:
        if cached:
            return cached, f"using stale cached stats because refresh failed: {exc}"
        return None, f"server stats unavailable: {exc}"

    payload = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "data": data,
    }
    if not dry_run:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload, None


def server_stats_summary_body(
    stats_payload: dict[str, object] | None,
    warning: str | None,
    vault: Path,
    date_str: str,
    dry_run: bool,
) -> str:
    if not stats_payload:
        return f"Server stats unavailable. {warning or ''}".strip()

    raw_data = stats_payload.get("data") if isinstance(stats_payload.get("data"), dict) else stats_payload
    if not isinstance(raw_data, dict):
        return "Server stats unavailable: cached payload has unexpected format."

    sections = raw_data.get("sections")
    if not isinstance(sections, dict):
        return "Server stats unavailable: response has no sections."

    report_date = str(raw_data.get("date") or "unknown date")
    fetched_at = str(stats_payload.get("fetched_at") or raw_data.get("generated_at") or "unknown time")
    lifetime = sections.get("lifetime_revenue") if isinstance(sections.get("lifetime_revenue"), dict) else {}
    stripe_revenue = sections.get("stripe_revenue") if isinstance(sections.get("stripe_revenue"), dict) else {}
    bank_transfer_revenue = (
        sections.get("bank_transfer_revenue") if isinstance(sections.get("bank_transfer_revenue"), dict) else {}
    )
    invoices = sections.get("invoices") if isinstance(sections.get("invoices"), dict) else {}
    revenue = sections.get("revenue") if isinstance(sections.get("revenue"), dict) else {}
    user_growth = sections.get("user_growth") if isinstance(sections.get("user_growth"), dict) else {}
    engagement = sections.get("engagement") if isinstance(sections.get("engagement"), dict) else {}
    web_analytics = sections.get("web_analytics") if isinstance(sections.get("web_analytics"), dict) else {}
    newsletter = sections.get("newsletter") if isinstance(sections.get("newsletter"), dict) else {}
    data_health = sections.get("data_health") if isinstance(sections.get("data_health"), dict) else {}
    metric_svgs = generate_daily_metric_svgs(vault, date_str, sections, dry_run)

    registered_accounts = _safe_int(user_growth.get("total_users"))
    invoice_buyers = _safe_int(invoices.get("lifetime_unique_buyers"))
    known_paying_users = _safe_int(newsletter.get("total_paying_users"))
    paying_customers = max(invoice_buyers, known_paying_users)
    conversion = f"{paying_customers * 100 / registered_accounts:.1f}%" if registered_accounts else "n/a"
    stripe_all_time = stripe_revenue.get("all_time_eur") if "error" not in stripe_revenue else None
    bank_transfer_all_time = (
        bank_transfer_revenue.get("all_time_eur") if "error" not in bank_transfer_revenue else None
    )
    revenue_parts = []
    if isinstance(stripe_all_time, (int, float)):
        revenue_parts.append(("Stripe", stripe_all_time))
    if isinstance(bank_transfer_all_time, (int, float)) and bank_transfer_all_time > 0:
        revenue_parts.append(("bank transfers", bank_transfer_all_time))
    lifetime_revenue = sum(amount for _, amount in revenue_parts) if revenue_parts else lifetime.get("total_eur")
    revenue_source = " + ".join(label for label, _ in revenue_parts) if revenue_parts else "tracked stats"
    revenue_source_detail = ", ".join(
        f"{label} {_format_eur(amount)}" for label, amount in revenue_parts
    )
    revenue_trend = revenue.get("trend_14d") if isinstance(revenue.get("trend_14d"), list) else []
    engagement_trend = engagement.get("trend_14d") if isinstance(engagement.get("trend_14d"), list) else []
    days = len(revenue_trend) or len(engagement_trend) or 14

    revenue_row_label = "Revenue" if revenue_parts else "App-tracked revenue"
    revenue_row_value = (
        f"{_format_eur(lifetime_revenue)} lifetime ({revenue_source}), "
        f"{paying_customers:,} paid users"
    )
    if revenue_source_detail:
        revenue_row_value += f"; {revenue_source_detail}"
    if not revenue_parts:
        revenue_row_value += "; not authoritative Stripe lifetime"

    rows = [
        "| Area | Metric |",
        "| --- | --- |",
        f"| {revenue_row_label} | {revenue_row_value} |",
        (
            "| Signup funnel | "
            f"{registered_accounts:,} registered accounts -> {paying_customers:,} paid users "
            f"({conversion} conversion); +{_format_count(user_growth.get('completed_signups'))} paid yesterday |"
        ),
    ]
    if isinstance(stripe_revenue.get("ytd_eur"), (int, float)):
        rows.append(f"| Stripe YTD | {_format_eur(stripe_revenue.get('ytd_eur'))} |")
    if isinstance(bank_transfer_revenue.get("ytd_eur"), (int, float)):
        rows.append(
            "| Bank transfer YTD | "
            f"{_format_eur(bank_transfer_revenue.get('ytd_eur'))}, "
            f"{_format_count(bank_transfer_revenue.get('ytd_transfers'))} completed transfers |"
        )
    rows.extend([
        (
            f"| App-tracked last {days} days | "
            f"{_format_eur(_sum_trend_float(revenue_trend, 'income_eur'))}, "
            f"{_sum_trend(revenue_trend, 'purchases'):,} purchases, "
            f"{_sum_trend(revenue_trend, 'unique_buyers'):,} buyers |"
        ),
        (
            f"| Engagement ({days}d) | "
            f"{_sum_trend(engagement_trend, 'messages'):,} messages, "
            f"{_sum_trend(engagement_trend, 'chats'):,} chats, "
            f"{_sum_trend(engagement_trend, 'embeds'):,} embeds |"
        ),
        (
            "| Web yesterday | "
            f"{_format_count(web_analytics.get('page_loads'))} page loads, "
            f"~{_format_count(web_analytics.get('unique_visits'))} unique visits |"
        ),
        (
            "| Newsletter | "
            f"{_format_count(newsletter.get('confirmed_subscribers'))} confirmed subscribers |"
        ),
        (
            "| Data health | "
            f"daily inspirations today={data_health.get('daily_inspiration_today', '?')}, "
            f"total={data_health.get('daily_inspiration_total', '?')} |"
        ),
    ])

    lines = [f"**Production snapshot:** {report_date}, refreshed {fetched_at}"]
    if warning:
        lines.append(f"Warning: {warning}")
    lines.append("")
    if metric_svgs:
        lines.append("**Metric Graphics**")
        lines.append("")
        for svg_path in metric_svgs:
            lines.append(_daily_note_image_embed(svg_path))
            lines.append("")
    lines.extend(rows)
    stripe_monthly = stripe_revenue.get("monthly") if isinstance(stripe_revenue.get("monthly"), list) else []
    if stripe_monthly:
        lines.append("")
        lines.append("**Stripe Monthly Revenue (last 6 months)**")
        lines.append("")
        lines.append("| Month | Revenue | Transactions |")
        lines.append("| --- | ---: | ---: |")
        for month in stripe_monthly[-6:]:
            if not isinstance(month, dict):
                continue
            lines.append(
                f"| {month.get('month', '?')} | "
                f"{_format_eur(month.get('revenue_eur'))} | "
                f"{_format_count(month.get('transactions'))} |"
            )
    bank_transfer_monthly = (
        bank_transfer_revenue.get("monthly") if isinstance(bank_transfer_revenue.get("monthly"), list) else []
    )
    if bank_transfer_monthly:
        lines.append("")
        lines.append("**Bank Transfer Monthly Revenue (last 6 months)**")
        lines.append("")
        lines.append("| Month | Revenue | Transfers |")
        lines.append("| --- | ---: | ---: |")
        for month in bank_transfer_monthly[-6:]:
            if not isinstance(month, dict):
                continue
            lines.append(
                f"| {month.get('month', '?')} | "
                f"{_format_eur(month.get('revenue_eur'))} | "
                f"{_format_count(month.get('transfers'))} |"
            )
    return "\n".join(lines)


def summary_from_manifest(notes: dict[str, dict[str, str | None]]) -> str:
    if not notes:
        return "No changed notes detected yet."

    areas = Counter(str(v.get("area")) for v in notes.values() if v.get("area"))
    types = Counter(str(v.get("type")) for v in notes.values() if v.get("type"))
    projects = Counter(str(v.get("project")) for v in notes.values() if v.get("project"))

    fragments = [f"{len(notes)} notes changed"]
    if projects:
        fragments.append("projects: " + ", ".join(name for name, _ in projects.most_common(3)))
    if areas:
        fragments.append("areas: " + ", ".join(name for name, _ in areas.most_common(5)))
    if types:
        type_text = ", ".join(f"{count} {name}" for name, count in types.most_common(5))
        fragments.append("types: " + type_text)
    return "Today: " + "; ".join(fragments) + "."


def git_commits(repo: Path, start_ts: float, end_ts: float, tz: ZoneInfo) -> list[dict[str, str]]:
    if not (repo / ".git").exists():
        return []

    result = subprocess.run(
        [
            "git",
            "log",
            f"--since=@{int(start_ts)}",
            f"--until=@{int(end_ts)}",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%h%x1f%cI%x1f%s",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []

    commits = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 3)
        if len(parts) != 4:
            continue
        full_hash, short_hash, committed_at, subject = parts
        local_datetime = datetime.fromisoformat(committed_at).astimezone(tz)
        commits.append(
            {
                "hash": short_hash,
                "url": f"{GITHUB_REPO_URL}/commit/{full_hash}",
                "time": local_datetime.strftime("%H:%M"),
                "sort_key": local_datetime.isoformat(timespec="seconds"),
                "subject": subject,
            }
        )
    return commits


def activity_list_body(notes: dict[str, dict[str, str | None]], commits: list[dict[str, str]]) -> str:
    """Build a single chronological list combining note changes and git commits."""
    entries: list[tuple[str, str]] = []

    for note in notes.values():
        link = note.get("link") or note.get("title") or "Untitled"
        meta = [str(note[k]) for k in ("type", "area", "task_status") if note.get(k)]
        suffix = f" ({', '.join(meta)})" if meta else ""
        mtime = str(note.get("mtime") or "")
        # Extract HH:MM from ISO timestamp
        time_str = mtime[11:16] if len(mtime) >= 16 else ""
        label = f"{time_str} note changed: {link}{suffix}" if time_str else f"note changed: {link}{suffix}"
        entries.append((mtime, label))

    for commit in commits:
        label = f"{commit['time']} commit: [`{commit['hash']}`]({commit['url']}) {commit['subject']}"
        sort_key = commit.get("sort_key", "")
        entries.append((sort_key, label))

    if not entries:
        return "- No activity detected yet."

    # Sort by timestamp descending (most recent first)
    entries.sort(key=lambda e: e[0], reverse=True)
    return "\n".join(f"- {label}" for _, label in entries)


def update_daily_note(
    vault: Path,
    git_repo: Path,
    tz_name: str,
    date_override: str | None,
    dry_run: bool,
) -> dict[str, object]:
    date_str, start_ts, end_ts, tz = today_window(tz_name, date_override)
    now = datetime.now(tz)
    daily_path = vault / DAILY_NOTES_DIR / f"{date_str}.md"
    manifest_path = vault / STATE_DIR / f"{date_str}.json"

    current_notes = changed_notes(vault, start_ts, end_ts, tz)
    commits = git_commits(git_repo, start_ts, end_ts, tz)
    manifest, manifest_changed = merge_manifest(load_manifest(manifest_path), current_notes, vault, now)

    text = remove_legacy_board_links(ensure_daily_note(daily_path, date_str))
    text = ensure_marker(text, "daily-summary", "Daily Summary", "No changed notes detected yet.\n")
    text = ensure_marker(text, "server-stats", "Server Stats", "Server stats not fetched yet.\n")
    text = ensure_marker(text, "changed-notes", "Recent Activity", "- No activity detected yet.\n")
    server_stats_payload, server_stats_warning = load_or_refresh_server_stats(vault, git_repo, now, dry_run)
    text = replace_auto_block(text, "daily-summary", summary_from_manifest(manifest))
    text = replace_auto_block(
        text,
        "server-stats",
        server_stats_summary_body(server_stats_payload, server_stats_warning, vault, date_str, dry_run),
    )
    text = move_section_after_auto_block(text, "Server Stats", "server-stats", "daily-summary")
    text = replace_auto_block(text, "changed-notes", activity_list_body(manifest, commits))
    if "<!-- AUTO:git-commits:start -->" in text:
        text = replace_auto_block(text, "git-commits", "See the activity table above.")

    existing_text = daily_path.read_text(encoding="utf-8", errors="replace") if daily_path.exists() else ""
    daily_note_changed = text != existing_text

    if not dry_run and (manifest_changed or daily_note_changed):
        daily_path.parent.mkdir(parents=True, exist_ok=True)
        if manifest_changed or not manifest_path.exists():
            save_manifest(manifest_path, date_str, manifest)
        if daily_note_changed:
            daily_path.write_text(text, encoding="utf-8")

    return {
        "date": date_str,
        "daily_note": str(daily_path),
        "manifest": str(manifest_path),
        "changed_notes_found": len(current_notes),
        "manifest_notes": len(manifest),
        "git_commits": len(commits),
        "server_stats": "available" if server_stats_payload else "unavailable",
        "server_stats_warning": server_stats_warning,
        "manifest_changed": manifest_changed,
        "daily_note_changed": daily_note_changed,
        "dry_run": dry_run,
    }


def main() -> int:
    args = parse_args()
    vault = args.vault.expanduser().resolve()
    if not vault.exists():
        raise SystemExit(f"Vault not found: {vault}")

    git_repo = args.git_repo.expanduser().resolve()
    result = update_daily_note(vault, git_repo, args.timezone, args.date, args.dry_run)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
