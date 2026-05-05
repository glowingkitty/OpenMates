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
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, time
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
KANBAN_BOARD_EMBED = "![[Boards/all-todos]]"
KANBAN_BOARD_LINK = "Kanban: [[Boards/all-todos|Open All Todos board]]"
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
    return first in {DAILY_NOTES_DIR, "Templates", "Boards", "Archive", ".obsidian", ".obsidian-auto"}


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
            notes.append(note_info(path, vault, tz))
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
        if path.endswith(".md") and (vault / path).exists()
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

{KANBAN_BOARD_LINK}

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


def ensure_kanban_link(text: str) -> str:
    if KANBAN_BOARD_EMBED in text:
        text = text.replace(KANBAN_BOARD_EMBED, KANBAN_BOARD_LINK)
    if KANBAN_BOARD_LINK in text:
        return text

    title_match = re.search(r"(?m)^# .+\n", text)
    if not title_match:
        return f"{KANBAN_BOARD_LINK}\n\n{text}"

    insert_at = title_match.end()
    return f"{text[:insert_at]}\n{KANBAN_BOARD_LINK}\n{text[insert_at:]}"


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


def _format_count(value: object) -> str:
    return f"{_safe_int(value):,}"


def _format_eur(value: object) -> str:
    return f"EUR {_safe_float(value):,.2f}"


def _sum_trend(trend: list[dict[str, object]], key: str) -> int:
    return sum(_safe_int(day.get(key)) for day in trend)


def _sum_trend_float(trend: list[dict[str, object]], key: str) -> float:
    return sum(_safe_float(day.get(key)) for day in trend)


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


def server_stats_summary_body(stats_payload: dict[str, object] | None, warning: str | None) -> str:
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
    invoices = sections.get("invoices") if isinstance(sections.get("invoices"), dict) else {}
    revenue = sections.get("revenue") if isinstance(sections.get("revenue"), dict) else {}
    user_growth = sections.get("user_growth") if isinstance(sections.get("user_growth"), dict) else {}
    engagement = sections.get("engagement") if isinstance(sections.get("engagement"), dict) else {}
    web_analytics = sections.get("web_analytics") if isinstance(sections.get("web_analytics"), dict) else {}
    newsletter = sections.get("newsletter") if isinstance(sections.get("newsletter"), dict) else {}
    data_health = sections.get("data_health") if isinstance(sections.get("data_health"), dict) else {}

    registered_accounts = _safe_int(user_growth.get("total_users"))
    invoice_buyers = _safe_int(invoices.get("lifetime_unique_buyers"))
    known_paying_users = _safe_int(newsletter.get("total_paying_users"))
    paying_customers = max(invoice_buyers, known_paying_users)
    conversion = f"{paying_customers * 100 / registered_accounts:.1f}%" if registered_accounts else "n/a"
    stripe_all_time = stripe_revenue.get("all_time_eur") if "error" not in stripe_revenue else None
    lifetime_revenue = stripe_all_time if isinstance(stripe_all_time, (int, float)) else lifetime.get("total_eur")
    revenue_source = "Stripe" if isinstance(stripe_all_time, (int, float)) else "tracked stats"
    revenue_trend = revenue.get("trend_14d") if isinstance(revenue.get("trend_14d"), list) else []
    engagement_trend = engagement.get("trend_14d") if isinstance(engagement.get("trend_14d"), list) else []
    days = len(revenue_trend) or len(engagement_trend) or 14

    revenue_row_label = "Revenue" if isinstance(stripe_all_time, (int, float)) else "App-tracked revenue"
    revenue_row_value = (
        f"{_format_eur(lifetime_revenue)} lifetime ({revenue_source}), "
        f"{paying_customers:,} paid users"
    )
    if not isinstance(stripe_all_time, (int, float)):
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
        local_time = datetime.fromisoformat(committed_at).astimezone(tz).strftime("%H:%M")
        commits.append(
            {
                "hash": short_hash,
                "url": f"{GITHUB_REPO_URL}/commit/{full_hash}",
                "time": local_time,
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
        # Use time for sorting (commits don't have full ISO, build a sortable key)
        sort_key = commit.get("time", "00:00")
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

    text = ensure_daily_note(daily_path, date_str)
    text = ensure_kanban_link(text)
    text = ensure_marker(text, "daily-summary", "Daily Summary", "No changed notes detected yet.\n")
    text = ensure_marker(text, "server-stats", "Server Stats", "Server stats not fetched yet.\n")
    text = ensure_marker(text, "changed-notes", "Recent Activity", "- No activity detected yet.\n")
    server_stats_payload, server_stats_warning = load_or_refresh_server_stats(vault, git_repo, now, dry_run)
    text = replace_auto_block(text, "daily-summary", summary_from_manifest(manifest))
    text = replace_auto_block(
        text,
        "server-stats",
        server_stats_summary_body(server_stats_payload, server_stats_warning),
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
