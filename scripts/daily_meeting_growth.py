"""Production marketing and growth numbers for the daily meeting briefing (aggregate counts only).

Source: the read-only admin endpoint ``POST /v1/admin/debug/growth-metrics`` on PRODUCTION, called
through ``backend/scripts/growth_metrics_query.py`` in the api container (admin key from Vault).
Dev data is never used for these numbers.

Left out completely: admins (server side), the server's configured test accounts (server side), and
every account whose email appears in the dev server's ``.env`` (test accounts, the founder's personal
test account, admin notification addresses) or in the private file
``logs/daily-meetings/growth-excluded-emails.txt`` (one email per line: the founder's other accounts).
Only base64 SHA-256 hashes of those emails leave this machine; the reply holds counts only.

Active users exist only for "now" (last session check), so each run keeps an aggregate snapshot in
``logs/daily-meetings/growth-history.json`` and compares with the previous meeting's snapshot.
Docs: docs/contributing/guides/daily-meeting.md
"""

from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

QUERY = ["docker", "exec", "-i", "api", "python", "/app/backend/scripts/growth_metrics_query.py"]
EXCLUDE_FILE = "growth-excluded-emails.txt"
HISTORY_FILE = "growth-history.json"
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HISTORY_DAYS = 60


def email_hash(email: str) -> str:
    """The hash clients store in ``directus_users.hashed_email``."""
    return base64.b64encode(hashlib.sha256(email.strip().lower().encode()).digest()).decode()


def excluded_emails(root: Path, out: Path) -> set[str]:
    """Every email in the dev server's .env plus the private founder-accounts file."""
    emails: set[str] = set()
    env = root / ".env"
    if env.is_file():
        for line in env.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and not name.lstrip().startswith("#"):
                emails |= set(EMAIL.findall(value))
    private = out / EXCLUDE_FILE
    if private.is_file():
        emails |= {match for line in private.read_text().splitlines()
                   if not line.strip().startswith("#") for match in EMAIL.findall(line)}
    return {email.lower() for email in emails}


def fetch(since: datetime, hashes: set[str], target: str = "prod") -> dict:
    request = {"since": since.isoformat(), "exclude_email_hashes": sorted(hashes)}
    run = subprocess.run([*QUERY, f"--{target}"], input=json.dumps(request),
                         capture_output=True, text=True, timeout=150)
    if run.returncode:
        raise RuntimeError((run.stderr or run.stdout).strip()[-300:] or f"exit {run.returncode}")
    reply = json.loads(run.stdout)
    if not isinstance(reply, dict) or not isinstance(reply.get("metrics"), dict):
        raise ValueError("growth-metrics reply has no metrics object")
    return reply["metrics"]


def remember(out: Path, day: str, metrics: dict) -> dict | None:
    """Store today's aggregate snapshot; return the latest one from an earlier day."""
    path = out / HISTORY_FILE
    try:
        history = json.loads(path.read_text()) if path.is_file() else {}
    except ValueError:
        history = {}
    earlier = sorted(d for d in history if d < day)
    previous = {"date": earlier[-1], **history[earlier[-1]]} if earlier else None
    history[day] = {"total_users": metrics.get("total_users"), "paying_users_total": metrics.get("paying_users_total"),
                    "active_users": metrics.get("active_users")}
    keep = sorted(history)[-HISTORY_DAYS:]
    path.write_text(json.dumps({d: history[d] for d in keep}, indent=1))
    path.chmod(0o600)
    return previous


def collect(root: Path, out: Path, since: datetime, day: str, gaps: list[str]) -> dict | None:
    try:
        metrics = fetch(since, {email_hash(e) for e in excluded_emails(root, out)})
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        reason = re.sub(r"\s+", " ", str(error))[:200]
        gaps.append(f"production growth numbers unavailable ({reason})")
        return None
    return {"metrics": metrics, "previous_snapshot": remember(out, day, metrics)}


def _trend(now: int, before: int | None) -> str:
    if before is None:
        return ""
    delta = now - before
    if not before:
        return " (previous period: 0)" if not now else f" (previous period: 0, +{now})"
    return f" (previous period: {before}, {'+' if delta >= 0 else ''}{delta}, {delta * 100 / before:+.0f}%)"


def render(growth: dict | None) -> list[str]:
    out = ["", "## Marketing and growth numbers (production)", ""]
    if not growth:
        return out + ["_Production growth numbers unavailable — see data gaps. Say so in one sentence; "
                      "do not guess numbers._", ""]
    m, prev = growth["metrics"], growth.get("previous_snapshot") or {}
    periods = m.get("periods") or {}
    since, last, week, week_before = (periods.get(k) or {} for k in
                                      ("since_last_meeting", "since_last_meeting_previous",
                                       "last_7_days", "previous_7_days"))
    active, prev_active = m.get("active_users") or {}, prev.get("active_users") or {}
    total_note = (f" (last meeting snapshot {prev['date']}: {prev['total_users']})"
                  if prev.get("total_users") is not None else "")
    out += [f"Aggregate counts from production, since {str(m.get('since', '?'))[:16].replace('T', ' ')} UTC. "
            f"Admin, test and the founder's own accounts are left out ({m.get('excluded_accounts', 0)} accounts); "
            "no personal data.", "",
            f"- **Total users:** {m.get('total_users')}{total_note}; paying users ever: {m.get('paying_users_total')}",
            f"- **New signups since the last meeting:** {since.get('signups_completed', 0)}"
            f"{_trend(since.get('signups_completed', 0), last.get('signups_completed'))}; "
            f"started but not finished: {since.get('signups_started', 0) - since.get('signups_completed', 0)}",
            f"- **New signups, last 7 days:** {week.get('signups_completed', 0)}"
            f"{_trend(week.get('signups_completed', 0), week_before.get('signups_completed'))}",
            f"- **Active users:** {active.get('last_24_hours', 0)} in the last 24 h"
            f"{_trend(active.get('last_24_hours', 0), prev_active.get('last_24_hours'))}; "
            f"{active.get('last_7_days', 0)} in the last 7 days"
            f"{_trend(active.get('last_7_days', 0), prev_active.get('last_7_days'))}"
            + (f" — compared with the snapshot of {prev['date']}" if prev_active else " — no earlier snapshot yet"),
            f"- **New paying users:** {since.get('new_paying_users', 0)} since the last meeting"
            f"{_trend(since.get('new_paying_users', 0), last.get('new_paying_users'))}; "
            f"{week.get('new_paying_users', 0)} in the last 7 days"
            f"{_trend(week.get('new_paying_users', 0), week_before.get('new_paying_users'))}",
            f"- **Credit purchases:** {since.get('credit_purchases', 0)} since the last meeting"
            f"{_trend(since.get('credit_purchases', 0), last.get('credit_purchases'))}; "
            f"{week.get('credit_purchases', 0)} in the last 7 days"
            f"{_trend(week.get('credit_purchases', 0), week_before.get('credit_purchases'))}",
            "", "_Previous period = the equally long period just before. Active users compare with the "
            "last meeting's snapshot. Purchases leave out gift cards, refunds and chargebacks._", ""]
    return out
