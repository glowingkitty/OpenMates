"""Daily security monitoring digest and watcher liveness (health.no-silent-failure).

The digest (owner decision 21 Nov) starts with "New": incidents opened or fixed
since the previous digest. Then "Still open": every unresolved incident, one
line each, so nothing is forgotten but nothing is repeated in full. A short
footer confirms the watcher ran, coverage gaps and host report freshness, so
absence of alerts is never the only evidence of safety. It is a deterministic email sent once per UTC day through
the security-reporting delivery ledger.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from security_monitoring import notify
from security_monitoring.config import Settings
from security_monitoring.state import Store, parse_utc, utc

from security_report_delivery import (  # noqa: E402 - notify put the scripts dir on sys.path
    SendResult,
    container_email_sender,
    deliver_notification,
    stable_notification_id,
)


DIGEST_CURSOR_KEY = "digest:last_window_end"
SEVERITY_ORDER = ("urgent", "critical", "high", "affected_fix_soon", "medium", "affected_low", "low")
SEVERITY_LABEL = {"urgent": "urgent", "affected_fix_soon": "fix soon", "affected_low": "low"}


def _subject(item: dict[str, Any]) -> str:
    details = item.get("details") or {}
    ids = ", ".join(str(value) for value in (details.get("advisory_ids") or [])[:3])
    assets = details.get("assets") or []
    names = ", ".join(sorted({str(asset.get("name")) for asset in assets if asset.get("name")})[:3])
    signal = details.get("signal") or details.get("signal_kind") or ""
    parts = [part for part in (ids, names, signal, details.get("summary") if not ids else "") if part]
    return " | ".join(str(part) for part in parts)[:240]


def _summarize(item: dict[str, Any]) -> dict[str, Any]:
    details = item.get("details") or {}
    fix = details.get("automatic_actions") or {}
    assets = sorted({str(asset.get("name")) for asset in (details.get("assets") or []) if asset.get("name")})
    return {
        "incident_id": item["incident_id"], "kind": item["kind"], "severity": item["severity"], "state": item["state"],
        "opened_at": item["opened_at"], "resolved_at": item.get("resolved_at"), "subject": _subject(item),
        "fix": fix.get("summary") or "", "commit": fix.get("commit") or "",
        "advisory_ids": [str(value) for value in (details.get("advisory_ids") or [])],
        "asset_key": ", ".join(assets[:3]) if item["kind"] == "advisory" else "",
    }


GROUP_MIN = 3


def _grouped_open_lines(items: list[dict[str, Any]]) -> list[str]:
    """One line per open item; several advisories on the same package collapse into one line."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        if item["asset_key"]:
            groups[(item["severity"], item["asset_key"])].append(item)
    lines: list[str] = []
    done: set[tuple[str, str]] = set()
    for item in items:
        key = (item["severity"], item["asset_key"])
        members = groups.get(key, []) if item["asset_key"] else []
        if len(members) >= GROUP_MIN:
            if key in done:
                continue
            done.add(key)
            ids = [advisory for member in members for advisory in member["advisory_ids"][:1]]
            severity = SEVERITY_LABEL.get(item["severity"], item["severity"])
            since = min(member["opened_at"] for member in members)[:10]
            lines.append(notify.bounded(f"[{severity}] {item['asset_key']}: {len(members)} advisories ({', '.join(ids[:6])}"
                                        f"{', ...' if len(ids) > 6 else ''}) since {since}", 300))
            continue
        lines.append(_line(item) + f" since {item['opened_at'][:10]}")
    return lines


def _severity_rank(severity: str) -> int:
    return SEVERITY_ORDER.index(severity) if severity in SEVERITY_ORDER else len(SEVERITY_ORDER)


def digest_window_start(store: Store, end: datetime) -> datetime:
    """New = since the previous digest; first digest (or a gap over 7 days) covers the last 24 hours."""
    previous = store.get_meta(DIGEST_CURSOR_KEY)
    if previous:
        start = parse_utc(previous)
        if timedelta(0) < end - start <= timedelta(days=7):
            return start
    return end - timedelta(hours=24)


def digest_data(store: Store, now: datetime, *, stale_roles: list[str] | None = None) -> dict[str, Any]:
    end = now.astimezone(timezone.utc)
    start = digest_window_start(store, end)
    runs = store.runs_between(start, end)
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "failed": 0, "unsupported": 0, "items": 0})
    for run in runs:
        for status in run["source_statuses"]:
            entry = coverage[str(status.get("name"))]
            if not status.get("supported", True):
                entry["unsupported"] += 1
            else:
                entry["ok" if status.get("ok") else "failed"] += 1
            entry["items"] += int(status.get("item_count") or 0)
    latest_summary = runs[-1]["summary"] if runs else {}
    unresolved = sorted(store.unresolved_incidents(), key=lambda item: (_severity_rank(item["severity"]), item["opened_at"]))
    new = [_summarize(item) for item in store.incidents_opened_between(start, end)]
    new_ids = {item["incident_id"] for item in new}
    return {
        "window_start": utc(start),
        "window_end": utc(end),
        "runs_total": len(runs),
        "runs_expected": max(1, round((end - start).total_seconds() / 3600)),
        "runs_complete": sum(1 for run in runs if run["outcome"] == "complete"),
        "runs_incomplete": sum(1 for run in runs if run["outcome"] != "complete"),
        "coverage": dict(sorted(coverage.items())),
        "stale_hosts": sorted(stale_roles if stale_roles is not None else latest_summary.get("stale_hosts", [])),
        "inventory_complete": latest_summary.get("inventory_complete"),
        "suppressed": store.suppressed_counts_since(start),
        "verdicts": store.verdict_counts_since(start),
        "new_incidents": new,
        "fixed_incidents": [_summarize(item) for item in store.incidents_resolved_between(start, end)
                            if item["incident_id"] not in new_ids],
        "open_incidents": [{**_summarize(item), "is_new": item["incident_id"] in new_ids} for item in unresolved],
        "last_run_started": utc(last) if (last := store.last_run_started()) else None,
        "fix_plan": _fix_plan(store),
        "images": _image_report(store),
    }


def _image_report(store: Store) -> dict[str, Any]:
    from security_monitoring import image_report  # noqa: PLC0415 - optional daily report

    return dict(image_report.last_report(store) or {})


def _fix_plan(store: Store) -> dict[str, Any]:
    from security_monitoring import fix_batch  # noqa: PLC0415 - fix_batch imports dispatch-side modules

    return dict(fix_batch.last_plan(store) or {})


def _line(item: dict[str, Any]) -> str:
    severity = SEVERITY_LABEL.get(item["severity"], item["severity"])
    text = f"[{severity}] {item['subject'] or item['kind']}"
    if item.get("commit"):
        text += f" (fix on dev: {item['commit'][:12]})"
    return notify.bounded(text, 300)


def render_digest(data: dict[str, Any]) -> notify.Rendered:
    """Daily email: "New" first, then "Still open" one line each, then a short health footer."""
    lines: list[tuple[str, str]] = []
    new = data["new_incidents"]
    fixed = data["fixed_incidents"]
    still_open = [item for item in data["open_incidents"] if not item.get("is_new")]
    lines.append(("NEW since last email", f"{len(new)} new, {len(fixed)} fixed"))
    for item in new:
        lines.append(("New", _line(item) + f" since {item['opened_at']}"))
    for item in fixed:
        lines.append(("Fixed", _line(item)))
    if not new and not fixed:
        lines.append(("New", "nothing new"))
    groups: dict[str, int] = defaultdict(int)
    for item in still_open:
        groups[SEVERITY_LABEL.get(item["severity"], item["severity"])] += 1
    lines.append(("STILL OPEN", f"{len(still_open)} ({', '.join(f'{k} {v}' for k, v in groups.items()) or 'none'})"))
    for text in _grouped_open_lines(still_open):
        lines.append(("Open", text))
    plan = data.get("fix_plan") or {}
    if plan.get("decisions") or plan.get("waiting"):
        lines.append(("NEEDS A DECISION", f"{len(plan.get('decisions', []))} (the daily fix lane does not change these on its own)"))
        for text in plan.get("decisions", [])[:40]:
            lines.append(("Decide", notify.bounded(text, 300)))
        for text in plan.get("waiting", [])[:40]:
            lines.append(("Waiting", notify.bounded(text, 300)))
    images = data.get("images") or {}
    if images:
        lines.append(("RUNNING IMAGES", f"{images.get('images', 0)} scanned at {notify.bounded(str(images.get('at', '?')), 40)}; "
                                         f"{images.get('kev_findings', 0)} actively exploited; {len(images.get('incomplete', []))} not checked"))
        for text in images.get("lines", [])[:40]:
            lines.append(("Image", notify.bounded(text, 300)))
        for text in images.get("incomplete", [])[:20]:
            lines.append(("Not checked", notify.bounded(text, 300)))
        for text in images.get("runtimes", [])[:40]:
            lines.append(("Runtimes", notify.bounded(text, 300)))
    gaps = sorted(name for name, entry in data["coverage"].items() if entry["unsupported"] and not entry["ok"] and not entry["failed"])
    failed = sorted(name for name, entry in data["coverage"].items() if entry["failed"])
    lines += [
        ("Watcher runs", f"{data['runs_total']}/{data['runs_expected']} ({data['runs_complete']} complete, {data['runs_incomplete']} incomplete); last {notify.bounded(data.get('last_run_started') or 'never', 40)}"),
        ("Window", f"{data['window_start']} to {data['window_end']}"),
        ("Inventory complete", "yes" if data.get("inventory_complete") else "no"),
        ("Stale host reports", ", ".join(data["stale_hosts"]) or "none"),
        ("Sources failed", notify.bounded(", ".join(failed) or "none", 300)),
        ("Standing coverage gaps", notify.bounded(", ".join(gaps) or "none", 400)),
        ("Suppressed", notify.bounded(", ".join(f"{reason}: {count}" for reason, count in sorted(data["suppressed"].items())) or "none", 300)),
        ("Verdicts", ", ".join(f"{outcome}: {count}" for outcome, count in sorted(data["verdicts"].items())) or "none"),
    ]
    checklist: tuple[str, ...] = ()
    if data["runs_total"] < max(1, data["runs_expected"] * 5 // 6):
        checklist = ("Investigate missing watcher runs (fewer than 5/6 of the expected hourly runs)",)
    title = f"[Security] Daily: {len(new)} new, {len(fixed)} fixed, {len(still_open) + len([i for i in data['open_incidents'] if i.get('is_new')])} open"
    return notify.Rendered(title, tuple(lines), checklist)

def watcher_is_stale(store: Store, now: datetime, hours: int) -> bool:
    last = store.last_run_started()
    return last is None or now - last > timedelta(hours=hours)


def run_digest(settings: Settings, store: Store, notifier: notify.Notifier, *, now: datetime | None = None,
               sender: Callable[[dict[str, str]], SendResult] | None = None) -> dict[str, Any]:
    """Check watcher liveness, then deliver the once-per-day digest email."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    result: dict[str, Any] = {}
    if watcher_is_stale(store, current, settings.watcher_stale_hours):
        incident_id, created = store.open_incident(
            "health", "health:watcher_stopped", "high",
            {"signal": "watcher_not_running", "summary": f"No hourly security watcher run in the last {settings.watcher_stale_hours} hours.",
             "checklist": ["Check the dev-host crontab block 'OpenMates security monitoring' and logs/security-monitoring/"]},
            current,
        )
        incident = store.incident(incident_id)
        result["watcher_alert"] = notifier.notify(incident or {}, current) if created else "already_open"
    else:
        store.resolve_incident_key("health:watcher_stopped", current)
    data = digest_data(store, current)
    rendered = render_digest(data)
    notification_id = stable_notification_id("security-monitoring-digest", "dev", current.date().isoformat())
    if settings.dry_run:
        result.update({"digest": "dry_run", "notification_id": notification_id, "preview": rendered.email_payload()["text"]})
        return result
    outcome = deliver_notification(ledger_path=settings.delivery_ledger, notification_id=notification_id,
                                   payload=rendered.email_payload(), recipient=notify.EMAIL_DESTINATION,
                                   sender=sender or container_email_sender())
    if outcome.state in {"accepted", "queued"}:
        store.set_meta(DIGEST_CURSOR_KEY, data["window_end"])
    result.update({"digest": outcome.state, "notification_id": notification_id})
    return result
