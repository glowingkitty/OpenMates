"""Daily security monitoring digest and watcher liveness (health.no-silent-failure).

The digest confirms the watcher ran (runs N/24), lists per-source coverage,
host report freshness, suppressed counts by reason, verdict counts and the
unresolved incidents carried forward, so absence of alerts is never the only
evidence of safety. It is a deterministic email sent once per UTC day through
the security-reporting delivery ledger.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from security_monitoring import notify
from security_monitoring.config import Settings
from security_monitoring.state import Store, utc

from security_report_delivery import (  # noqa: E402 - notify put the scripts dir on sys.path
    SendResult,
    container_email_sender,
    deliver_notification,
    stable_notification_id,
)


def digest_data(store: Store, now: datetime, *, stale_roles: list[str] | None = None) -> dict[str, Any]:
    end = now.astimezone(timezone.utc)
    start = end - timedelta(hours=24)
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
    unresolved = store.unresolved_incidents()
    return {
        "window_start": utc(start),
        "window_end": utc(end),
        "runs_total": len(runs),
        "runs_complete": sum(1 for run in runs if run["outcome"] == "complete"),
        "runs_incomplete": sum(1 for run in runs if run["outcome"] != "complete"),
        "coverage": dict(sorted(coverage.items())),
        "stale_hosts": sorted(stale_roles if stale_roles is not None else latest_summary.get("stale_hosts", [])),
        "inventory_complete": latest_summary.get("inventory_complete"),
        "suppressed": store.suppressed_counts_since(start),
        "verdicts": store.verdict_counts_since(start),
        "open_incidents": [
            {"incident_id": item["incident_id"], "kind": item["kind"], "severity": item["severity"],
             "state": item["state"], "opened_at": item["opened_at"],
             "subject": ", ".join(item["details"].get("advisory_ids", [])[:3]) or item["details"].get("signal") or item["details"].get("signal_kind") or ""}
            for item in unresolved
        ],
        "last_run_started": utc(last) if (last := store.last_run_started()) else None,
    }


def render_digest(data: dict[str, Any]) -> notify.Rendered:
    lines: list[tuple[str, str]] = [
        ("Window", f"{data['window_start']} to {data['window_end']}"),
        ("Watcher runs", f"{data['runs_total']}/24 ({data['runs_complete']} complete, {data['runs_incomplete']} incomplete)"),
        ("Last run started", notify.bounded(data.get("last_run_started") or "never", 40)),
        ("Inventory complete", "yes" if data.get("inventory_complete") else "no"),
        ("Stale host reports", ", ".join(data["stale_hosts"]) or "none"),
    ]
    for name, entry in data["coverage"].items():
        if entry["unsupported"] and not entry["ok"] and not entry["failed"]:
            lines.append((f"Coverage gap {notify.bounded(name, 60)}", "source unsupported (standing gap, not alerted hourly)"))
            continue
        lines.append((f"Source {notify.bounded(name, 60)}", f"{entry['ok']} ok, {entry['failed']} failed, {entry['items']} items"))
    suppressed = ", ".join(f"{notify.bounded(reason, 80)}: {count}" for reason, count in sorted(data["suppressed"].items()))
    lines.append(("Suppressed", suppressed or "none"))
    verdicts = ", ".join(f"{outcome}: {count}" for outcome, count in sorted(data["verdicts"].items()))
    lines.append(("Verdicts (24h)", verdicts or "none"))
    for item in data["open_incidents"][:40]:
        lines.append((f"Open {item['kind']}", notify.bounded(
            f"{item['incident_id']} [{item['severity']}, {item['state']}] {item['subject']} since {item['opened_at']}", 300)))
    if not data["open_incidents"]:
        lines.append(("Open incidents", "none"))
    checklist = ()
    if data["runs_total"] < 20:
        checklist = ("Investigate missing watcher runs (fewer than 20 of 24 hourly runs)",)
    return notify.Rendered("[Security] Daily security monitoring digest", tuple(lines), checklist)


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
    result.update({"digest": outcome.state, "notification_id": notification_id})
    return result
