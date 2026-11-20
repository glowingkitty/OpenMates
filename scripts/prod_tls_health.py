"""Hourly production TLS certificate health check (TASK-5089).

Runs with the hourly prod smoke (scripts/prod_smoke_cron.py free-hourly) and
answers one question: does every public production host serve a valid
certificate that is not about to expire? For each host it connects to every
IPv4 address the name resolves to (Vercel edges can serve different
certificates) and verifies chain and hostname with the system trust store.

A host fails when the handshake does not verify (expired, wrong name, unknown
issuer), when it is unreachable, or when the certificate has fewer than
MIN_DAYS_LEFT days left. Vercel and Let's Encrypt renew about 30 days before
expiry, so a certificate inside that window means renewal is stuck; that is how
www.openmates.org served a certificate that expired in Feb 2026 for months.

Failures go to DISCORD_WEBHOOK_PROD_SMOKE when the state changes and every six
hours while it stays failing; a recovery is posted once.

Usage: python3 scripts/prod_tls_health.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import discord_summary  # noqa: E402 (repo path bootstrap)

HOSTS = ("openmates.org", "www.openmates.org", "app.openmates.org", "api.openmates.org")
MIN_DAYS_LEFT = 21
STATE_FILE = Path(__file__).resolve().parent.parent / "test-results" / "hourly-prod" / "tls-health-state.json"
REPEAT_ALERT_SECONDS = 6 * 3600
TIMEOUT = 15
USER_AGENT = "OpenMates-TLS-Health/1.0"

Resolve = Callable[[str], list[str]]
FetchCert = Callable[[str, str], dict[str, Any]]


def resolve_ipv4(host: str) -> list[str]:
    """All IPv4 addresses of ``host``, sorted, without duplicates."""
    infos = socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def fetch_cert(host: str, address: str) -> dict[str, Any]:
    """Verified TLS handshake with ``address`` using SNI ``host``; returns the peer certificate."""
    context = ssl.create_default_context()
    with socket.create_connection((address, 443), timeout=TIMEOUT) as sock:
        with context.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert()


def check_address(host: str, address: str, now: datetime, fetch: FetchCert = fetch_cert) -> dict[str, Any]:
    try:
        cert = fetch(host, address)
    except ssl.SSLCertVerificationError as exc:
        return {"ok": False, "address": address, "reason": f"{host} ({address}): certificate invalid: {exc.verify_message}."}
    except (ssl.SSLError, OSError) as exc:
        return {"ok": False, "address": address, "reason": f"{host} ({address}): TLS handshake failed ({type(exc).__name__})."}
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), tz=timezone.utc)
    days_left = (expires - now).total_seconds() / 86400
    result: dict[str, Any] = {"ok": days_left >= MIN_DAYS_LEFT, "address": address,
                              "not_after": expires.isoformat(), "days_left": round(days_left, 1)}
    if not result["ok"]:
        result["reason"] = (
            f"{host} ({address}): certificate expires {expires:%Y-%m-%d} ({days_left:.0f} days left); "
            "automatic renewal looks stuck."
        )
    return result


def check_host(host: str, now: datetime, resolve: Resolve = resolve_ipv4, fetch: FetchCert = fetch_cert) -> dict[str, Any]:
    try:
        addresses = resolve(host)
    except OSError as exc:
        return {"ok": False, "reason": f"{host}: DNS lookup failed ({type(exc).__name__})."}
    if not addresses:
        return {"ok": False, "reason": f"{host}: no IPv4 address."}
    results = [check_address(host, address, now, fetch) for address in addresses]
    reasons = [r["reason"] for r in results if not r["ok"]]
    host_result: dict[str, Any] = {"ok": not reasons, "addresses": results}
    if reasons:
        host_result["reason"] = " ".join(reasons)
    return host_result


def evaluate(now: datetime, resolve: Resolve = resolve_ipv4, fetch: FetchCert = fetch_cert) -> dict[str, Any]:
    checks = {host: check_host(host, now, resolve, fetch) for host in HOSTS}
    return {"ok": all(c["ok"] for c in checks.values()), "checked_at": now.isoformat(), "checks": checks}


def alert_decision(result: dict[str, Any], state: dict[str, Any], now_ts: float) -> str | None:
    """Return 'failure', 'recovery' or None (nothing to post)."""
    was_ok = state.get("ok", True)
    if result["ok"]:
        return "recovery" if not was_ok else None
    if was_ok or now_ts - float(state.get("last_alert_ts", 0)) >= REPEAT_ALERT_SECONDS:
        return "failure"
    return None


def format_message(result: dict[str, Any], kind: str) -> str:
    """One short line for the lock screen; the full reasons stay in the printed check result."""
    if kind == "recovery":
        return discord_summary.alert("✅", "Prod TLS recovered: all certificates are valid again.")
    reasons = [c["reason"] for c in result["checks"].values() if not c["ok"] and c.get("reason")]
    more = f" (+{len(reasons) - 1} more)" if len(reasons) > 1 else ""
    text = f"Prod TLS failing: {reasons[0]}{more}" if reasons else "Prod TLS check failing."
    return discord_summary.alert("🚨", text)


def post_discord(webhook_url: str, content: str, opener: Callable[..., Any] = urllib.request.urlopen) -> bool:
    request = urllib.request.Request(
        webhook_url,
        data=json.dumps({"content": content}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with opener(request, timeout=TIMEOUT) as response:
            response.read()
        return True
    except (urllib.error.URLError, OSError) as exc:
        print(f"[tls-health] Discord post failed: {type(exc).__name__}", file=sys.stderr)
        return False


def _load_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        print("[tls-health] state file unreadable; starting fresh", file=sys.stderr)
        return {}


def run(*, dry_run: bool = False, state_path: Path = STATE_FILE) -> int:
    result = evaluate(datetime.now(timezone.utc))
    state = _load_state(state_path)
    kind = alert_decision(result, state, time.time())
    print("[tls-health] " + json.dumps(result, sort_keys=True))
    new_state = {"ok": result["ok"], "last_alert_ts": state.get("last_alert_ts", 0), "checked_at": result["checked_at"]}
    if kind:
        message = format_message(result, kind)
        webhook = os.environ.get("DISCORD_WEBHOOK_PROD_SMOKE", "")
        if dry_run:
            print(f"[tls-health] dry run, would post {kind}:\n{message}")
        elif not webhook:
            print("[tls-health] DISCORD_WEBHOOK_PROD_SMOKE not set; cannot alert", file=sys.stderr)
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
