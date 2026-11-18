#!/usr/bin/env python3
"""Hourly production transactional email health check (TASK-427).

Runs with the hourly prod smoke (scripts/prod_smoke_cron.py free-hourly) and
answers one question: can production send user emails right now? Three checks:

1. Production's own Brevo health check, read from the public status endpoint.
   It calls GET /v3/account from the prod server with the prod Vault key, so
   it also catches a revoked key or Brevo's authorised-IP block on prod.
2. The Brevo account itself (GET /v3/account over IPv4): reachable, active and
   with send credits left.
3. Production send error rate in the last two hours, from Brevo's own events
   tagged ``environment:production``: provider ``error`` and ``blocked``
   events against requests. Hard bounces are recipient problems and excluded.

Failures go to DISCORD_WEBHOOK_PROD_SMOKE when the state changes and every six
hours while it stays failing; a recovery is posted once. No key, recipient
address or message content is printed or posted.

Usage: python3 scripts/prod_email_health.py [--dry-run] [--json]
Architecture: docs/architecture/infrastructure/transactional-email-monitoring.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.brevo_ipv4 import urlopen as brevo_urlopen  # noqa: E402 (repo path bootstrap)

PROD_STATUS_URL = "https://api.openmates.org/v1/status"
BREVO_ACCOUNT_URL = "https://api.brevo.com/v3/account"
BREVO_EVENTS_URL = "https://api.brevo.com/v3/smtp/statistics/events"
STATE_FILE = Path(__file__).resolve().parent.parent / "test-results" / "hourly-prod" / "email-health-state.json"
ERROR_WINDOW = timedelta(hours=2)
MIN_SEND_CREDITS = 200
MIN_FAILED_EVENTS = 3
MAX_FAILURE_RATIO = 0.25
REPEAT_ALERT_SECONDS = 6 * 3600
PROVIDER_FAILURE_EVENTS = {"error", "blocked"}
HTTP_TIMEOUT = 20
USER_AGENT = "OpenMates-Email-Health/1.0"

Fetch = Callable[[urllib.request.Request], Any]


def _fetch_json(request: urllib.request.Request, opener: Callable[..., Any]) -> tuple[int, Any]:
    try:
        with opener(request, timeout=HTTP_TIMEOUT) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            body = json.load(exc)
        except (ValueError, OSError):
            body = {}
        return exc.code, body


def check_prod_status(opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    """Production's own Brevo check, as published on the status endpoint."""
    request = urllib.request.Request(PROD_STATUS_URL, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        code, body = _fetch_json(request, opener)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "reason": f"Prod status page unreachable ({type(exc).__name__})."}
    if code != 200:
        return {"ok": False, "reason": f"Prod status page returned HTTP {code}."}
    for group in body.get("groups", []):
        for service in group.get("services", []):
            if service.get("id") == "brevo":
                status = service.get("status")
                if status == "operational":
                    return {"ok": True, "status": status}
                return {"ok": False, "status": status, "reason": f"Prod's own Brevo check reports '{status}'."}
    return {"ok": False, "reason": "Prod status page has no Brevo entry."}


def check_account(api_key: str, opener: Callable[..., Any] = brevo_urlopen) -> dict[str, Any]:
    """Brevo account reachable with the key, and send credits left."""
    if not api_key:
        return {"ok": False, "reason": "BREVO_API_KEY is not set on the dev host."}
    request = urllib.request.Request(BREVO_ACCOUNT_URL, headers={"api-key": api_key, "Accept": "application/json"})
    try:
        code, body = _fetch_json(request, opener)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "reason": f"Brevo API unreachable ({type(exc).__name__})."}
    if code != 200:
        message = str(body.get("message") or "")[:200]
        return {"ok": False, "http_status": code, "reason": f"Brevo account check HTTP {code}: {message}".strip()}
    credits = [
        plan.get("credits") for plan in body.get("plan", [])
        if plan.get("creditsType") == "sendLimit" and isinstance(plan.get("credits"), (int, float))
    ]
    if credits and max(credits) < MIN_SEND_CREDITS:
        return {"ok": False, "credits": max(credits), "reason": f"Only {max(credits)} Brevo send credits left."}
    return {"ok": True, "credits": max(credits) if credits else None}


def _is_production(event: dict[str, Any]) -> bool:
    tags = event.get("tags") or ([event["tag"]] if event.get("tag") else [])
    return any("environment:production" in str(tag) for tag in tags)


def summarize_events(events: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    """Count production requests and provider failures inside ERROR_WINDOW."""
    since = now - ERROR_WINDOW
    requests = failed = 0
    for event in events:
        if not _is_production(event):
            continue
        try:
            when = datetime.fromisoformat(str(event.get("date", "")))
        except ValueError:
            continue
        if when < since:
            continue
        if event.get("event") == "requests":
            requests += 1
        elif event.get("event") in PROVIDER_FAILURE_EVENTS:
            failed += 1
    ratio = failed / max(requests, 1)
    ok = not (failed >= MIN_FAILED_EVENTS and ratio >= MAX_FAILURE_RATIO)
    result: dict[str, Any] = {"ok": ok, "requests": requests, "failed": failed}
    if not ok:
        result["reason"] = (
            f"{failed} of {requests} production emails were refused by Brevo (error/blocked) in the last "
            f"{int(ERROR_WINDOW.total_seconds() // 3600)} hours."
        )
    return result


def check_error_rate(api_key: str, now: datetime, opener: Callable[..., Any] = brevo_urlopen) -> dict[str, Any]:
    if not api_key:
        return {"ok": False, "reason": "BREVO_API_KEY is not set on the dev host."}
    query = urllib.parse.urlencode({"days": 1, "limit": 2500, "sort": "desc"})
    request = urllib.request.Request(f"{BREVO_EVENTS_URL}?{query}", headers={"api-key": api_key, "Accept": "application/json"})
    try:
        code, body = _fetch_json(request, opener)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "reason": f"Brevo events unreachable ({type(exc).__name__})."}
    if code != 200:
        return {"ok": False, "http_status": code, "reason": f"Brevo events HTTP {code}."}
    return summarize_events(body.get("events") or [], now)


def evaluate(api_key: str, now: datetime) -> dict[str, Any]:
    checks = {
        "prod_status": check_prod_status(),
        "brevo_account": check_account(api_key),
        "prod_error_rate": check_error_rate(api_key, now),
    }
    return {"ok": all(check["ok"] for check in checks.values()), "checked_at": now.isoformat(), "checks": checks}


def alert_decision(result: dict[str, Any], state: dict[str, Any], now_ts: float) -> str | None:
    """Return 'failure', 'recovery' or None (nothing to post)."""
    was_ok = state.get("ok", True)
    if result["ok"]:
        return "recovery" if not was_ok else None
    if was_ok or now_ts - float(state.get("last_alert_ts", 0)) >= REPEAT_ALERT_SECONDS:
        return "failure"
    return None


def format_message(result: dict[str, Any], kind: str) -> str:
    if kind == "recovery":
        return "✅ **Prod email recovered**: transactional email sending works again (Brevo)."
    reasons = [check["reason"] for check in result["checks"].values() if not check["ok"] and check.get("reason")]
    lines = ["🚨 **Prod email check FAILED**: users may not be receiving emails (login codes, receipts, recovery)."]
    lines += [f"- {reason}" for reason in reasons]
    lines.append("Runbook: docs/architecture/infrastructure/transactional-email-monitoring.md")
    return "\n".join(lines)


def post_discord(webhook_url: str, content: str, opener: Callable[..., Any] = urllib.request.urlopen) -> bool:
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"content": content[:1900]}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with opener(request, timeout=HTTP_TIMEOUT) as response:
            response.read()
        return True
    except (urllib.error.URLError, OSError) as exc:
        print(f"[email-health] Discord post failed: {type(exc).__name__}", file=sys.stderr)
        return False


def _load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        print("[email-health] state file unreadable; starting fresh", file=sys.stderr)
        return {}


def run(*, dry_run: bool = False, state_path: Path = STATE_FILE) -> int:
    now = datetime.now(timezone.utc)
    result = evaluate(os.environ.get("BREVO_API_KEY", ""), now)
    state = _load_state(state_path)
    kind = alert_decision(result, state, time.time())
    print("[email-health] " + json.dumps(result, sort_keys=True))
    new_state = {"ok": result["ok"], "last_alert_ts": state.get("last_alert_ts", 0), "checked_at": result["checked_at"]}
    if kind:
        message = format_message(result, kind)
        webhook = os.environ.get("DISCORD_WEBHOOK_PROD_SMOKE", "")
        if dry_run:
            print(f"[email-health] dry run, would post {kind}:\n{message}")
        elif not webhook:
            print("[email-health] DISCORD_WEBHOOK_PROD_SMOKE not set; cannot alert", file=sys.stderr)
        elif post_discord(webhook, message):
            new_state["last_alert_ts"] = time.time()
        else:
            new_state["ok"] = state.get("ok", True)  # retry the alert next hour
    if not dry_run:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(new_state) + "\n")
    return 0 if result["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="check and print, but neither post nor save state")
    args = parser.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
