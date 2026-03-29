#!/usr/bin/env python3
"""
Health check module for debug.py — provides system health summaries, entity health
checks, error fingerprint display, and request replay.

Called by debug.py; not meant to be run directly.

Architecture context: See docs/contributing/guides/debugging.md
Tests: None (inspection script, not production code)
"""

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx

# Shared inspection utilities — logging setup
from debug_utils import configure_script_logging

# debug_health is a library, not a CLI script. Use WARNING so it only
# logs when something goes wrong; callers control their own verbosity.
logger = configure_script_logging(
    'debug_health', level=logging.WARNING, fmt='%(message)s',
    extra_suppress=['aiohttp'],
)

# ─── ANSI colours ────────────────────────────────────────────────────────────

RESET  = "\033[0m"
BOLD   = "\033[1m"
RED    = "\033[31m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
CYAN   = "\033[36m"
DIM    = "\033[2m"

def _c(color: str, text: str) -> str:
    return f"{color}{text}{RESET}"

def _ok(text: str) -> str: return _c(GREEN, f"✓ {text}")
def _warn(text: str) -> str: return _c(YELLOW, f"⚠ {text}")
def _err(text: str) -> str: return _c(RED, f"✗ {text}")
def _section(text: str) -> str: return f"\n{BOLD}{CYAN}{'─'*4} {text} {'─'*(48-len(text))}{RESET}"

# ─── Prometheus query helpers ────────────────────────────────────────────────

PROMETHEUS_URL = "http://prometheus:9090"
OPENOBSERVE_URL = "http://openobserve:5080"
OPENOBSERVE_ORG = "default"

# Maximum chars per line in health output
MAX_LINE_LEN = 80


async def _prom_query(query: str) -> Optional[float]:
    """Run an instant PromQL query and return the first numeric result, or None."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query}
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            if not results:
                return None
            return float(results[0]["value"][1])
    except Exception:
        return None


async def _prom_query_series(query: str) -> List[Dict]:
    """Run an instant PromQL query and return all result series."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{PROMETHEUS_URL}/api/v1/query",
                params={"query": query}
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            return data.get("data", {}).get("result", [])
    except Exception:
        return []


async def _openobserve_recent_errors(limit: int = 10, since_minutes: int = 30) -> List[Dict]:
    """
    Fetch recent error-level log entries from OpenObserve across all services.
    Returns list of {ts, service, message} dicts, newest-first.
    Uses OpenObserve SQL search API: POST /api/{org}/{stream}/_search
    """
    try:
        import os
        email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
        password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

        start_us = int((time.time() - since_minutes * 60) * 1_000_000)
        end_us = int(time.time() * 1_000_000)

        # Valid fields: _timestamp, container, level, message, service
        # The 'log' field does not exist in this stream — do NOT reference it.
        sql = (
            f"SELECT _timestamp, container, service, message, level "
            f"FROM \"default\" "
            f"WHERE LOWER(level) IN ('error', 'critical') "
            f"ORDER BY _timestamp DESC LIMIT {limit}"
        )

        # Use /{org}/_search — stream name is specified in the SQL FROM clause.
        # Do NOT use /{org}/default/_search: when ORG="default" that produces
        # /api/default/default/_search which returns 404.
        body = {"query": {"sql": sql, "start_time": start_us, "end_time": end_us}}
        urls_to_try = (
            f"{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/_search",
            f"{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/default/_search",
        )

        resp = None
        async with httpx.AsyncClient(timeout=10.0, auth=(email, password)) as client:
            for url in urls_to_try:
                resp = await client.post(url, json=body)
                if resp.status_code == 200:
                    break
        if resp is None or resp.status_code != 200:
            return []
        data = resp.json()
        results = []
        for hit in data.get("hits", []):
            ts_us = hit.get("_timestamp", 0)
            svc = hit.get("container", hit.get("service", "?"))
            msg = hit.get("message", hit.get("log", ""))[:500]
            results.append({
                "ts": int(ts_us) * 1000,  # convert µs → ns for display consistency
                "service": svc,
                "message": msg,
            })
        return results
    except Exception:
        return []


# ─── Log access health check ─────────────────────────────────────────────────

# Production Admin Debug API — same constant as debug_logs.py
PROD_API_BASE = "https://api.openmates.org/v1/admin/debug"


async def check_log_access() -> Tuple[bool, bool]:
    """
    Verify that Claude can actually read logs before starting any debug task.

    Checks:
      1. Local OpenObserve (dev) — POST a minimal SQL query and expect HTTP 200.
      2. Production server — GET the Admin Debug API /ping endpoint with the
         Vault-sourced API key and expect HTTP 200.

    Returns:
        (local_ok, prod_ok) — True means the source is reachable and authenticated.

    Prints a clear summary so the caller can decide whether to stop.
    Failures are shown as ✗ with actionable hints; do NOT silently swallow them.
    """
    import os

    print(_section("Log Access Check"))

    # ── 1. Local OpenObserve ──────────────────────────────────────────────────
    local_ok = False
    email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
    password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

    if not email or not password:
        print(_err("  Local OpenObserve — credentials not set"))
        print(_c(DIM, "    Set OPENOBSERVE_ROOT_EMAIL and OPENOBSERVE_ROOT_PASSWORD env vars."))
    else:
        # Minimal SQL that returns quickly and proves the stream exists
        probe_sql = 'SELECT _timestamp FROM "default" ORDER BY _timestamp DESC LIMIT 1'
        now_us = int(time.time() * 1_000_000)
        start_us = now_us - 5 * 60 * 1_000_000  # 5-minute window
        body = {"query": {"sql": probe_sql, "start_time": start_us, "end_time": now_us}}
        urls = (
            f"{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/_search",
            f"{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/default/_search",
        )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                for url in urls:
                    resp = await client.post(
                        url, json=body,
                        auth=(email, password),
                    )
                    if resp.status_code == 200:
                        local_ok = True
                        break
                    if resp.status_code == 404:
                        continue
                    print(_err(f"  Local OpenObserve — HTTP {resp.status_code}"))
                    print(_c(DIM, f"    URL: {url}"))
                    break
        except Exception as exc:
            print(_err(f"  Local OpenObserve — cannot connect: {exc}"))
            print(_c(DIM, f"    Expected at {OPENOBSERVE_URL}. Is the openobserve container running?"))
            print(_c(DIM, "    Run: docker compose ps openobserve"))

    if local_ok:
        print(_ok("  Local OpenObserve — reachable and authenticated"))

    # ── 2. Production server (Admin Debug API) ────────────────────────────────
    prod_ok = False
    try:
        from debug_utils import get_api_key_from_vault  # local import to avoid circular deps
        api_key = await get_api_key_from_vault()
    except SystemExit:
        # get_api_key_from_vault() calls sys.exit(1) if the key is missing
        print(_err("  Production logs — Admin API key not found in Vault"))
        print(_c(DIM, "    See: SECRET__ADMIN__DEBUG_CLI__API_KEY setup in debugging-ref.md"))
        api_key = None
    except Exception as exc:
        print(_err(f"  Production logs — Vault unreachable: {exc}"))
        print(_c(DIM, "    Is the vault container running? Check: docker compose ps vault"))
        api_key = None

    if api_key:
        # /allowed-services is a cheap, auth-required endpoint — ideal as a connectivity probe
        probe_url = f"{PROD_API_BASE}/allowed-services"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    probe_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if resp.status_code == 200:
                prod_ok = True
                print(_ok("  Production logs   — Admin API reachable and authenticated"))
            elif resp.status_code in (401, 403):
                # Try to detect the specific "device not approved" case from the response body
                try:
                    body = resp.json()
                    detail = body.get("detail", "")
                except Exception:
                    detail = resp.text[:200]
                if "device" in detail.lower() and ("approved" in detail.lower() or "confirm" in detail.lower()):
                    print(_err(f"  Production logs — API key device not approved (HTTP {resp.status_code})"))
                    print(_c(DIM, "    The API key is valid but this device hasn't been confirmed yet."))
                    print(_c(DIM, "    Fix: log in to production → Settings → Developers → Devices → approve the pending device."))
                else:
                    print(_err(f"  Production logs — API key rejected (HTTP {resp.status_code})"))
                    print(_c(DIM, "    Regenerate the key: admin user → API Keys → create new, update SECRET__ADMIN__DEBUG_CLI__API_KEY"))
            else:
                print(_err(f"  Production logs — unexpected HTTP {resp.status_code} from {probe_url}"))
        except Exception as exc:
            print(_err(f"  Production logs — cannot reach {probe_url}: {exc}"))
            print(_c(DIM, "    Check that the production API is up and DNS resolves from inside Docker."))

    print()
    return local_ok, prod_ok


async def run_log_access_check() -> None:
    """
    Standalone entrypoint for `debug.py health --log-access` (or just `debug.py health`).

    Runs check_log_access() and exits non-zero if either source is inaccessible,
    printing a clear stop message so Claude knows to halt the task and ask the user.
    """
    import sys
    local_ok, prod_ok = await check_log_access()

    if local_ok and prod_ok:
        print(_ok("  Log sources healthy — safe to proceed with debugging."))
        print()
        return

    # One or both sources are down — print a prominent stop banner
    print(_c(RED + BOLD, "  ══ STOP — log access issues detected ══"))
    if not local_ok:
        print(_c(RED, "    ✗ Local OpenObserve is not accessible."))
        print(_c(DIM, "      Dev-server logs and OpenObserve presets will not work."))
    if not prod_ok:
        print(_c(RED, "    ✗ Production Admin API is not accessible."))
        print(_c(DIM, "      Production log queries (--production / run_prod_mode) will fail."))
    print()
    print("  Please resolve the issues above and re-run `debug.py health` before proceeding.")
    print()
    sys.exit(1)


# ─── Redis queue depth helper ─────────────────────────────────────────────────

async def _get_celery_queue_depths() -> Dict[str, int]:
    """
    Query Redis to get Celery queue depths.
    Returns {queue_name: message_count}.
    """
    try:
        from backend.core.api.app.services.cache import CacheService
        cache = CacheService()
        redis = await cache.client

        # Standard Celery queue names
        queue_names = [
            'email', 'user_init', 'persistence', 'health_check',
            'server_stats', 'demo', 'e2e_tests', 'reminder',
            'app_ai', 'app_web', 'app_images', 'app_pdf',
            'usage', 'leaderboard', 'app_events', 'app_music',
            'app_mail', 'app_math', 'app_shopping',
        ]
        depths = {}
        for q in queue_names:
            try:
                length = await redis.llen(q)
                if length > 0:
                    depths[q] = length
            except Exception:
                pass
        await cache.close()
        return depths
    except Exception:
        return {}


# ─── Main health check ────────────────────────────────────────────────────────

async def run_health_check(verbose: bool = False, skip_log_access: bool = False) -> None:
    """
    Run a comprehensive system health check:
    - Log access (OpenObserve local + production Admin API) — mandatory first step
    - Prometheus target status (api, prometheus self)
    - API error rate and latency from Prometheus
    - Celery queue depths from Redis
    - Recent error logs from OpenObserve
    - Celery task failure count (if metrics available)

    Args:
        verbose: Show extended metrics (request breakdown, celery failures, error fingerprints).
        skip_log_access: Skip log access check (for callers that already ran it).
    """
    print(_section("OpenMates System Health"))
    print(_c(DIM, f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"))

    issues_found = 0

    # ── 0. Log access — verify we can actually read logs before proceeding ────
    if not skip_log_access:
        local_ok, prod_ok = await check_log_access()
        if not local_ok or not prod_ok:
            import sys
            print(_c(RED + BOLD, "  STOP — cannot access one or more log sources (see above)."))
            print("  Resolve the issues and re-run `debug.py health` before debugging.")
            print()
            sys.exit(1)

    # ── 1. Prometheus targets ──────────────────────────────────────────────
    print(_c(BOLD, "  Prometheus Targets"))
    targets_up = await _prom_query_series("up")
    if not targets_up:
        print(_warn("  Cannot reach Prometheus at " + PROMETHEUS_URL))
        issues_found += 1
    else:
        for t in targets_up:
            job = t.get("metric", {}).get("job", "?")
            val = float(t["value"][1])
            if val == 1.0:
                print(f"  {_ok(job)}")
            else:
                print(f"  {_err(job + ' — DOWN')}")
                issues_found += 1

    # ── 2. API error rate ──────────────────────────────────────────────────
    print()
    print(_c(BOLD, "  API Metrics (last 5 min)"))

    # Error rate: percentage of 5xx responses
    error_rate = await _prom_query(
        'sum(rate(api_requests_total{status_code=~"5.."}[5m])) / '
        'sum(rate(api_requests_total[5m]))'
    )
    if error_rate is None:
        total_reqs = await _prom_query('sum(rate(api_requests_total[5m]))')
        if total_reqs is None or total_reqs == 0:
            print(_c(DIM, "  No request data (quiet server or Prometheus not collecting)"))
        else:
            print(_ok(f"  Error rate: 0% ({total_reqs:.1f} req/s)"))
    elif error_rate > 0.10:
        print(_err(f"  Error rate: {error_rate*100:.1f}%"))
        issues_found += 1
    elif error_rate > 0.02:
        print(_warn(f"  Error rate: {error_rate*100:.1f}%"))
        issues_found += 1
    else:
        print(_ok(f"  Error rate: {error_rate*100:.2f}%"))

    # P95 latency
    p95 = await _prom_query(
        'histogram_quantile(0.95, sum(rate(api_request_duration_seconds_bucket[5m])) by (le))'
    )
    import math
    if p95 is not None and not math.isnan(p95):
        if p95 > 5.0:
            print(_err(f"  P95 latency: {p95:.2f}s"))
            issues_found += 1
        elif p95 > 2.0:
            print(_warn(f"  P95 latency: {p95:.2f}s"))
        else:
            print(_ok(f"  P95 latency: {p95:.3f}s"))

    if verbose:
        # Request rate breakdown
        req_series = await _prom_query_series(
            'sum by (status_code) (rate(api_requests_total[5m]))'
        )
        if req_series:
            print()
            print(_c(DIM, "  Request rate by status code (req/s, 5 min avg):"))
            for s in sorted(req_series, key=lambda x: x["metric"].get("status_code", "")):
                sc = s["metric"].get("status_code", "?")
                rate = float(s["value"][1])
                if rate > 0.001:
                    color = RED if str(sc).startswith("5") else (YELLOW if str(sc).startswith("4") else RESET)
                    print(f"    {_c(color, str(sc))}: {rate:.3f} req/s")

        # Celery task metrics
        celery_failures = await _prom_query('sum(rate(celery_task_failures_total[5m]))')
        if celery_failures is not None:
            if celery_failures > 0.1:
                print(_err(f"  Celery failures: {celery_failures:.2f}/s"))
                issues_found += 1
            elif celery_failures > 0.01:
                print(_warn(f"  Celery failures: {celery_failures:.3f}/s"))
            else:
                print(_ok(f"  Celery failures: {celery_failures:.4f}/s"))

    # ── 3. Queue depths ────────────────────────────────────────────────────
    print()
    print(_c(BOLD, "  Celery Queues"))
    depths = await _get_celery_queue_depths()
    if not depths:
        print(_ok("  All queues empty"))
    else:
        for q, n in sorted(depths.items(), key=lambda x: -x[1]):
            if n > 50:
                print(_err(f"  {q}: {n} pending"))
                issues_found += 1
            elif n > 10:
                print(_warn(f"  {q}: {n} pending"))
            else:
                print(_c(DIM, f"  {q}: {n} pending"))

    # ── 4. Recent errors from OpenObserve ──────────────────────────────────
    since_min = 60 if not verbose else 30
    limit = 5 if not verbose else 10
    recent_errors = await _openobserve_recent_errors(limit=limit, since_minutes=since_min)
    print()
    if recent_errors:
        print(_c(BOLD, f"  Recent Errors (last {since_min} min, newest first)"))
        issues_found += len(recent_errors)
        for entry in recent_errors:
            ts_s = datetime.fromtimestamp(entry['ts'] / 1e9).strftime('%H:%M:%S')
            svc = entry['service'][:16]
            msg = entry['message'][:MAX_LINE_LEN - 30]
            print(f"  {_c(DIM, ts_s)} {_c(YELLOW, svc):<18} {msg}")
    else:
        print(_ok(f"  No errors in the last {since_min} min"))

    # ── 5. Error fingerprints (brief) ─────────────────────────────────────
    if verbose:
        print()
        print(_c(BOLD, "  Top Error Fingerprints (7d)"))
        await _print_error_fingerprints(top=5, indent="  ")

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    if issues_found == 0:
        print(_ok("  All systems healthy"))
    elif issues_found <= 3:
        print(_warn(f"  {issues_found} issue(s) found — review above"))
    else:
        print(_err(f"  {issues_found} issues found — action needed"))
    print()


async def run_health_check_compact() -> str:
    """Return a one-liner health summary for non-debug session modes.

    Checks Prometheus API error rate, P95 latency, queue depths,
    AND OpenObserve application error count (last 30 min).

    Returns a short string like:
      "OK (0% API errors, P95 42ms, queues clear)"
    or:
      "WARN — 12 app errors (30m), API error rate 5.1%"
    """
    import math
    parts = []
    warnings = []

    # 1. Prometheus: HTTP 5xx error rate (last 5 min)
    error_rate = await _prom_query(
        'sum(rate(api_requests_total{status_code=~"5.."}[5m])) / '
        'sum(rate(api_requests_total[5m]))'
    )
    if error_rate is None:
        total_reqs = await _prom_query('sum(rate(api_requests_total[5m]))')
        if total_reqs is None or total_reqs == 0:
            parts.append("no request data")
        else:
            parts.append("0% API errors")
    elif error_rate > 0.02:
        warnings.append(f"API 5xx rate {error_rate*100:.1f}%")
    else:
        parts.append(f"{error_rate*100:.1f}% API errors")

    # 2. P95 latency
    p95 = await _prom_query(
        'histogram_quantile(0.95, sum(rate(api_request_duration_seconds_bucket[5m])) by (le))'
    )
    if p95 is not None and not math.isnan(p95):
        if p95 > 2.0:
            warnings.append(f"P95 {p95:.1f}s")
        elif p95 < 1.0:
            parts.append(f"P95 {p95*1000:.0f}ms")
        else:
            parts.append(f"P95 {p95:.2f}s")

    # 3. Queue depths
    depths = await _get_celery_queue_depths()
    total_pending = sum(depths.values()) if depths else 0
    if total_pending > 50:
        warnings.append(f"queue backlog: {total_pending} tasks")
    elif total_pending > 0:
        parts.append(f"queues: {total_pending} pending")
    else:
        parts.append("queues clear")

    # 4. OpenObserve: application-level errors (last 30 min)
    # This catches errors that don't produce 5xx (task failures, embed errors, etc.)
    app_errors = await _openobserve_recent_errors(limit=50, since_minutes=30)
    if app_errors:
        count = len(app_errors)
        if count >= 50:
            warnings.append("50+ app errors (30m)")
        elif count >= 10:
            warnings.append(f"{count} app errors (30m)")
        elif count >= 3:
            parts.append(f"{count} app errors (30m)")
        else:
            parts.append(f"{count} app error{'s' if count != 1 else ''} (30m)")
    else:
        parts.append("0 app errors (30m)")

    if warnings:
        # Include parts as additional context after warnings
        extra = f" | {', '.join(parts)}" if parts else ""
        return f"WARN — {', '.join(warnings)}{extra}"
    return f"OK ({', '.join(parts)})"


async def _fetch_prod_error_data(top: int = 5) -> dict:
    """Fetch prod error data via the Admin Debug API.

    Returns a dict with:
        api_reachable: bool   — Admin API key worked and HTTP 200 received
        logs_working:  bool   — prod OpenObserve returned at least one log line
        fingerprints:  list   — top error fingerprints (may be empty list)
        error:         str    — human-readable failure reason, or ""
    """
    result = {"api_reachable": False, "logs_working": False, "fingerprints": [], "error": ""}
    try:
        from debug_utils import get_api_key_from_vault, PROD_API_URL
        try:
            api_key = await get_api_key_from_vault()
        except SystemExit:
            result["error"] = "Admin API key not found in Vault"
            return result

        headers = {"Authorization": f"Bearer {api_key}"}

        async with httpx.AsyncClient(timeout=12.0) as client:
            # 1. Probe log access: fetch 5 lines from 'api' service, last 60 min
            logs_resp = await client.get(
                f"{PROD_API_URL}/logs",
                headers=headers,
                params={"services": "api", "since_minutes": 60, "lines": 5},
            )
            if logs_resp.status_code != 200:
                result["error"] = f"Admin API /logs returned HTTP {logs_resp.status_code}"
                return result

            result["api_reachable"] = True
            raw_logs = logs_resp.json().get("logs", "")
            # Any non-header, non-empty line means OpenObserve is returning data
            data_lines = [
                line for line in raw_logs.splitlines()
                if line.strip()
                and not line.startswith("===")
                and not line.startswith("---")
                and "no log entries found" not in line
            ]
            result["logs_working"] = bool(data_lines)

            # 2. Fetch error fingerprints
            errors_resp = await client.get(
                f"{PROD_API_URL}/errors",
                headers=headers,
                params={"top": top},
            )
            if errors_resp.status_code == 200:
                for entry in errors_resp.json().get("top_errors", []):
                    canonical = entry.get("canonical_key", "")
                    parts = canonical.split(":", 3)
                    result["fingerprints"].append({
                        "exc_type": (parts[0] if parts else "?")[:30],
                        "file_part": (parts[1] if len(parts) > 1 else "?").rsplit("/", 1)[-1],
                        "func": (parts[2] if len(parts) > 2 else "?")[:25],
                        "line_num": parts[3] if len(parts) > 3 else "?",
                        "count": entry.get("count", 0),
                    })

        return result
    except Exception as exc:
        result["error"] = str(exc)[:120]
        return result


async def get_error_overview_compact(top: int = 5, since_minutes: int = 30) -> str:
    """Return a compact overview of recent errors for session context.

    Shows errors for both dev (local OpenObserve + Redis) and production
    (Admin Debug API). Explicitly flags if prod log access is broken.

    Output format (healthy):
      [dev]  Errors: 5 (last 30m) — api(3), worker(1), web(1)
      [prod] Logs: OK | Top recurring (7d): none
    Output format (prod OpenObserve disconnected):
      [prod] Logs: DISCONNECTED — prod OpenObserve not returning data
    """
    lines = []

    # ── Dev: recent error count by service from local OpenObserve ────────────
    recent_errors = await _openobserve_recent_errors(limit=50, since_minutes=since_minutes)
    if recent_errors:
        svc_counts: dict[str, int] = {}
        for err in recent_errors:
            svc = err["service"].split("-")[0] if err["service"] != "?" else "unknown"
            svc = svc.replace("/", "").strip()[:12]
            svc_counts[svc] = svc_counts.get(svc, 0) + 1
        total = len(recent_errors)
        breakdown = ", ".join(f"{s}({c})" for s, c in sorted(svc_counts.items(), key=lambda x: -x[1]))
        lines.append(f"  [dev]  Errors: {total} (last {since_minutes}m) — {breakdown}")
    else:
        lines.append(f"  [dev]  Errors: 0 (last {since_minutes}m)")

    # Dev: top error fingerprints from local Redis
    try:
        from backend.core.api.app.services.cache import CacheService
        cache = CacheService()
        redis = await cache.client
        results = await redis.zrevrange(REDIS_ERROR_FINGERPRINTS_KEY, 0, top - 1, withscores=True)
        await cache.close()

        if results:
            lines.append("  [dev]  Top recurring (7d):")
            for i, (member, score) in enumerate(results, 1):
                # Member format: "<fingerprint>|<exc_type>:<filename>:<funcname>:<lineno>"
                # Split on the single pipe first, then parse the colon-delimited canonical key.
                raw = member if isinstance(member, str) else member.decode()
                _fp, _, canonical = raw.partition("|")
                c_parts = canonical.split(":", 3)
                exc_type = (c_parts[0] if c_parts else "?")[:30]
                file_part = (c_parts[1] if len(c_parts) > 1 else "?").rsplit("/", 1)[-1]
                func = (c_parts[2] if len(c_parts) > 2 else "?")[:25]
                line_num = c_parts[3] if len(c_parts) > 3 else "?"
                count = int(score)
                lines.append(f"           {i}. [{count}x] {exc_type} in {file_part}:{func}:{line_num}")
    except Exception:
        pass  # Fingerprints unavailable — not critical

    # ── Prod: log access probe + error fingerprints ───────────────────────────
    prod = await _fetch_prod_error_data(top=top)

    if not prod["api_reachable"]:
        reason = prod["error"] or "could not reach Admin Debug API"
        lines.append(f"  [prod] UNREACHABLE — {reason}")
    elif not prod["logs_working"]:
        lines.append("  [prod] Logs: DISCONNECTED — prod OpenObserve not returning data")
        lines.append("           (fingerprints below may be stale/empty)")
        if prod["fingerprints"]:
            lines.append("  [prod] Top recurring (7d):")
            for i, e in enumerate(prod["fingerprints"], 1):
                lines.append(f"           {i}. [{e['count']}x] {e['exc_type']} in {e['file_part']}:{e['func']}:{e['line_num']}")
        else:
            lines.append("  [prod] Top recurring (7d): none recorded")
    else:
        lines.append("  [prod] Logs: OK")
        if prod["fingerprints"]:
            lines.append("  [prod] Top recurring (7d):")
            for i, e in enumerate(prod["fingerprints"], 1):
                lines.append(f"           {i}. [{e['count']}x] {e['exc_type']} in {e['file_part']}:{e['func']}:{e['line_num']}")
        else:
            lines.append("  [prod] Top recurring (7d): none")

    lines.append("  → Details: debug.py logs --o2 --preset web-app-health")
    return "\n".join(lines)


# ─── Entity health checks ─────────────────────────────────────────────────────

async def check_chat_health(
    chat_id: str,
    production: bool = False,
    dev: bool = False,
) -> None:
    """Fetch chat from Directus/API and show a quick health summary."""
    print(_section(f"Chat Health: {chat_id[:8]}…"))

    if production:
        await _remote_entity_health("chat", chat_id, dev=dev)
        return

    try:
        from backend.core.api.app.services.directus.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        secrets = SecretsManager()
        await secrets.initialize()
        directus = DirectusService(secrets_manager=secrets)
        cache = CacheService()

        issues = []

        # Fetch chat
        chat = await directus.get_item("chats", chat_id, fields=["*"])
        if not chat:
            print(_err(f"  Chat not found in Directus: {chat_id}"))
            return

        created = chat.get('date_created', 'N/A')
        updated = chat.get('date_updated', 'N/A')
        print(f"  Owner:   {chat.get('user_created', '?')}")
        print(f"  Created: {created}")
        print(f"  Updated: {updated}")
        print(f"  Type:    {chat.get('chat_type', '?')}")

        # Messages
        msgs = await directus.get_items("chat_messages", filters={"chat": {"_eq": chat_id}}, fields=["id", "role", "messages_v"])
        msg_count = len(msgs) if msgs else 0
        stored_v = chat.get('messages_v', 0)
        print(f"\n  Messages: {msg_count} (messages_v={stored_v})")
        if msg_count != stored_v:
            issues.append(f"messages_v mismatch: stored={stored_v}, actual={msg_count}")

        # Embeds
        embeds = await directus.get_items("embeds", filters={"chat": {"_eq": chat_id}}, fields=["id", "status", "app_id", "skill_id"])
        embed_count = len(embeds) if embeds else 0
        error_embeds = [e for e in (embeds or []) if e.get("status") == "error"]
        print(f"  Embeds:   {embed_count} ({len(error_embeds)} in error state)")
        if error_embeds:
            issues.append(f"{len(error_embeds)} embed(s) in error state")

        # Embed keys
        embed_keys = await directus.get_items("embed_keys", filters={"chat": {"_eq": chat_id}}, fields=["id", "key_type"])
        key_count = len(embed_keys) if embed_keys else 0
        if embed_count > 0 and key_count == 0:
            issues.append("No embed keys found for a chat with embeds")
        print(f"  Keys:     {key_count}")

        # Cache
        try:
            redis = await cache.client
            cached = await redis.exists(f"chat:{chat_id}")
            print(f"  Cached:   {'yes' if cached else 'no'}")
        except Exception:
            pass

        await directus.close()
        await cache.close()
        await secrets.aclose()

        print()
        if issues:
            for issue in issues:
                print(_warn(f"  {issue}"))
            print()
            print(_warn(f"  {len(issues)} issue(s) found — run with -v for full inspection"))
        else:
            print(_ok("  Chat looks healthy"))
        print()

    except Exception as exc:
        print(_err(f"  Health check failed: {exc}"))
        print()


async def check_embed_health(
    embed_id: str,
    production: bool = False,
    dev: bool = False,
) -> None:
    """Fetch embed from Directus/API and show a quick health summary."""
    print(_section(f"Embed Health: {embed_id[:8]}…"))

    if production:
        await _remote_entity_health("embed", embed_id, dev=dev)
        return

    try:
        from backend.core.api.app.services.directus.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        secrets = SecretsManager()
        await secrets.initialize()
        directus = DirectusService(secrets_manager=secrets)
        cache = CacheService()

        issues = []

        embed = await directus.get_item("embeds", embed_id, fields=["*"])
        if not embed:
            print(_err(f"  Embed not found in Directus: {embed_id}"))
            return

        status = embed.get("status", "?")
        app_id = embed.get("app_id", "?")
        skill_id = embed.get("skill_id", "?")
        print(f"  Status:  {status}")
        print(f"  App:     {app_id} / {skill_id}")
        print(f"  Chat:    {embed.get('chat', '?')}")
        print(f"  Parent:  {embed.get('parent_embed', 'none')}")

        if status == "error":
            issues.append("Embed is in error state")

        # Check content
        has_content = bool(
            embed.get("encrypted_content") or embed.get("content") or embed.get("data")
        )
        if status == "finished" and not has_content:
            issues.append("Finished embed has no content payload")
        print(f"\n  Content: {'present' if has_content else 'MISSING'}")

        # Embed keys
        embed_keys = await directus.get_items("embed_keys", filters={"embed": {"_eq": embed_id}}, fields=["id", "key_type"])
        key_count = len(embed_keys) if embed_keys else 0
        print(f"  Keys:    {key_count}")
        if has_content and key_count == 0:
            issues.append("Embed has content but no encryption keys")

        # Children
        children = await directus.get_items("embeds", filters={"parent_embed": {"_eq": embed_id}}, fields=["id", "status"])
        child_count = len(children) if children else 0
        error_children = [c for c in (children or []) if c.get("status") == "error"]
        if child_count > 0:
            print(f"  Children:{child_count} ({len(error_children)} in error state)")
            if error_children:
                issues.append(f"{len(error_children)} child embed(s) in error state")

        await directus.close()
        await cache.close()
        await secrets.aclose()

        print()
        if issues:
            for issue in issues:
                print(_warn(f"  {issue}"))
            print()
            print(_warn(f"  {len(issues)} issue(s) — run with -v for full inspection"))
        else:
            print(_ok("  Embed looks healthy"))
        print()

    except Exception as exc:
        print(_err(f"  Health check failed: {exc}"))
        print()


async def check_user_health(email: str) -> None:
    """Fetch user from Directus and show a quick health summary."""
    print(_section(f"User Health: {email[:3]}***"))

    try:
        from backend.core.api.app.services.directus.directus import DirectusService
        from backend.core.api.app.services.cache import CacheService
        from backend.core.api.app.utils.secrets_manager import SecretsManager

        secrets = SecretsManager()
        await secrets.initialize()
        directus = DirectusService(secrets_manager=secrets)
        cache = CacheService()

        issues = []

        # Hash email to find user
        email_hash = hashlib.sha256(email.lower().strip().encode()).hexdigest()
        users = await directus.get_items(
            "directus_users",
            filters={"email_hash": {"_eq": email_hash}},
            fields=["id", "status", "date_created", "last_access", "provider"]
        )
        if not users:
            print(_err(f"  User not found for email: {email[:3]}***"))
            return

        user = users[0]
        user_id = user.get("id")
        print(f"  ID:       {user_id}")
        print(f"  Status:   {user.get('status', '?')}")
        print(f"  Created:  {user.get('date_created', 'N/A')}")
        print(f"  Last:     {user.get('last_access', 'N/A')}")

        if user.get("status") != "active":
            issues.append(f"User status is '{user.get('status')}' (not active)")

        # Item counts
        chats = await directus.get_items("chats", filters={"user_created": {"_eq": user_id}}, fields=["id"])
        embeds = await directus.get_items("embeds", filters={"user_created": {"_eq": user_id}}, fields=["id", "status"])
        error_embeds = [e for e in (embeds or []) if e.get("status") == "error"]
        print(f"\n  Chats:   {len(chats) if chats else 0}")
        print(f"  Embeds:  {len(embeds) if embeds else 0} ({len(error_embeds)} in error)")

        if len(error_embeds) > 5:
            issues.append(f"{len(error_embeds)} embeds in error state")

        # Cache primed?
        try:
            redis = await cache.client
            primed = await redis.exists(f"user_primed:{user_id}")
            print(f"  Primed:  {'yes' if primed else 'no'}")
        except Exception:
            pass

        await directus.close()
        await cache.close()
        await secrets.aclose()

        print()
        if issues:
            for issue in issues:
                print(_warn(f"  {issue}"))
            print()
            print(_warn(f"  {len(issues)} issue(s) — run with -v for full inspection"))
        else:
            print(_ok("  User looks healthy"))
        print()

    except Exception as exc:
        print(_err(f"  Health check failed: {exc}"))
        print()


# ─── Remote entity health via Admin Debug API ─────────────────────────────────

async def _remote_entity_health(entity_type: str, entity_id: str, dev: bool = False) -> None:
    """Fetch a quick health summary for an entity via the Admin Debug API."""
    try:
        from backend.core.api.app.utils.secrets_manager import SecretsManager
        secrets = SecretsManager()
        await secrets.initialize()
        try:
            api_key = await secrets.get_secret("kv/data/providers/admin", "debug_cli__api_key")
        finally:
            await secrets.aclose()

        base_url = "https://api.dev.openmates.org/v1/admin/debug" if dev else "https://api.openmates.org/v1/admin/debug"
        url = f"{base_url}/{entity_type}/{entity_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            if resp.status_code == 200:
                data = resp.json()
                # Show basic fields
                for k, v in list(data.items())[:12]:
                    print(f"  {k}: {str(v)[:80]}")
                print()
                print(_ok(f"  Fetched from {'dev' if dev else 'production'} API"))
            else:
                print(_err(f"  API returned {resp.status_code}: {resp.text[:200]}"))
    except Exception as exc:
        print(_err(f"  Remote health check failed: {exc}"))
    print()


# ─── Error fingerprints ───────────────────────────────────────────────────────

REDIS_ERROR_FINGERPRINTS_KEY = "debug:error_fingerprints"


async def _print_error_fingerprints(top: int = 10, indent: str = "") -> None:
    """Display top error fingerprints from Redis sorted set."""
    try:
        from backend.core.api.app.services.cache import CacheService
        cache = CacheService()
        redis = await cache.client

        # Each member is "fingerprint|exception_type|file|func|line"
        # Score is occurrence count
        results = await redis.zrevrange(REDIS_ERROR_FINGERPRINTS_KEY, 0, top - 1, withscores=True)
        if not results:
            print(f"{indent}{_c(DIM, 'No error fingerprints recorded')}")
            await cache.close()
            return

        for member, score in results:
            # Member format: "<fingerprint>|<exc_type>:<filename>:<funcname>:<lineno>"
            raw = member if isinstance(member, str) else member.decode()
            _fp, _, canonical = raw.partition("|")
            c_parts = canonical.split(":", 3)
            exc_type = c_parts[0] if c_parts else "?"
            file_part = c_parts[1] if len(c_parts) > 1 else "?"
            func = c_parts[2] if len(c_parts) > 2 else "?"
            line = c_parts[3] if len(c_parts) > 3 else "?"
            count = int(score)
            color = RED if count > 100 else (YELLOW if count > 10 else RESET)
            print(f"{indent}{_c(color, str(count).rjust(5))}x  {exc_type}  {file_part}:{func}:{line}")

        await cache.close()
    except Exception as exc:
        print(f"{indent}{_c(DIM, f'Error fingerprints unavailable: {exc}')}")


async def show_error_diff_since_deploy(top: int = 10) -> None:
    """Compare error fingerprints from before vs after the last sessions.py deploy.

    Reads the last_deploy_sha from .claude/sessions.json to find the deploy
    timestamp, then queries OpenObserve for errors in two windows:
      - BEFORE: errors that existed before the deploy timestamp (pre-existing)
      - AFTER: errors that appeared after the deploy (potentially introduced)

    Design intent: helps identify regressions without manual time-window guessing.
    """
    import json
    import os as _os
    import subprocess

    # ── Find last deploy SHA and timestamp ─────────────────────────────────
    sessions_file = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        "..", "..", ".claude", "sessions.json"
    )
    last_sha = ""
    deploy_ts = None
    if _os.path.exists(sessions_file):
        try:
            with open(sessions_file) as f:
                sessions_data = json.load(f)
            last_sha = sessions_data.get("last_deploy_sha", "")
        except Exception:
            pass

    if last_sha:
        project_root = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..")
        result = subprocess.run(
            ["git", "show", "-s", "--format=%ci", last_sha],
            capture_output=True, text=True, timeout=10, cwd=project_root,
        )
        if result.returncode == 0 and result.stdout.strip():
            from datetime import datetime
            try:
                # Git outputs: "2026-03-18 14:30:00 +0000"
                ts_str = result.stdout.strip().split("\n")[0]
                deploy_ts = datetime.fromisoformat(ts_str.replace(" +0000", "+00:00"))
            except Exception:
                pass

    if not deploy_ts:
        print("No previous deploy found in .claude/sessions.json.")
        print("Run sessions.py deploy first, then use --diff to compare.")
        print()
        print("Falling back to standard error fingerprints:")
        await show_error_fingerprints(top=top)
        return

    # ── Query errors before and after deploy ──────────────────────────────
    from datetime import timezone
    now = datetime.now(timezone.utc)
    deploy_minutes_ago = int((now - deploy_ts).total_seconds() / 60)

    # Errors in window: [deploy_ts - 30min, deploy_ts] = "before"
    before_window = 30  # minutes before deploy to sample
    print(_section(f"Error Diff Since Deploy ({last_sha[:9]}, {deploy_minutes_ago}m ago)"))

    before_errors = await _openobserve_recent_errors(
        limit=100, since_minutes=deploy_minutes_ago + before_window
    )
    after_errors = await _openobserve_recent_errors(
        limit=100, since_minutes=deploy_minutes_ago
    )

    def _fingerprint_error(err: dict) -> str:
        msg = (err.get("message", "") or "")[:80]
        svc = err.get("service", "?")
        return f"{svc}:{msg}"

    before_fps = {_fingerprint_error(e) for e in before_errors}
    after_fps = {_fingerprint_error(e) for e in after_errors}

    new_fps = after_fps - before_fps
    existing_fps = after_fps & before_fps

    if new_fps:
        print(f"  NEW since deploy ({len(new_fps)} error pattern(s)):")
        for fp in sorted(new_fps)[:top]:
            print(f"    ✗ {fp}")
    else:
        print("  NEW since deploy: none")

    print()
    if existing_fps:
        print(f"  PRE-EXISTING (also in before-window, {len(existing_fps)} pattern(s)):")
        for fp in sorted(existing_fps)[:top]:
            print(f"    ~ {fp}")
    else:
        print("  PRE-EXISTING: none found in before-window")

    print()
    print(f"  Window: before={before_window}m pre-deploy, after={deploy_minutes_ago}m post-deploy")
    print("  Full errors: debug.py errors --compact | debug.py errors --top 20")


async def show_error_fingerprints(top: int = 10) -> None:
    """Main entrypoint for `debug.py errors` subcommand."""
    print(_section("Error Fingerprints (7d rolling)"))

    try:
        from backend.core.api.app.services.cache import CacheService
        cache = CacheService()
        redis = await cache.client

        results = await redis.zrevrange(REDIS_ERROR_FINGERPRINTS_KEY, 0, top - 1, withscores=True)
        if not results:
            print(_c(DIM, "  No error fingerprints recorded yet."))
            print(_c(DIM, "  Fingerprints are collected from 500-level API errors once the"))
            print(_c(DIM, "  error fingerprinting middleware is active."))
            await cache.close()
            print()
            return

        print(f"  {'Count':>6}  {'Exception':<30}  {'Location'}")
        print(f"  {'─'*6}  {'─'*30}  {'─'*40}")

        for member, score in results:
            # Member format: "<fingerprint>|<exc_type>:<filename>:<funcname>:<lineno>"
            raw = member if isinstance(member, str) else member.decode()
            _fp, _, canonical = raw.partition("|")
            c_parts = canonical.split(":", 3)
            exc_type = (c_parts[0] if c_parts else "?")[:28]
            file_part = (c_parts[1] if len(c_parts) > 1 else "?")[-25:]
            func = (c_parts[2] if len(c_parts) > 2 else "?")[:20]
            line = c_parts[3] if len(c_parts) > 3 else "?"
            count = int(score)
            color = RED if count > 100 else (YELLOW if count > 10 else RESET)
            location = f"{file_part}:{func}:{line}"[:45]
            print(f"  {_c(color, str(count).rjust(6))}  {exc_type:<30}  {location}")

        print()
        # Also sample recent occurrences from OpenObserve for each fingerprint
        print(_c(DIM, "  Tip: Run `debug.py logs <email>` to trace errors to specific users."))
        await cache.close()
    except Exception as exc:
        print(_err(f"  Failed to fetch error fingerprints: {exc}"))

    print()


# ─── Request replay ───────────────────────────────────────────────────────────

async def replay_request(request_id: str) -> None:
    """
    Reconstruct the full timeline of a request by querying OpenObserve for all
    log entries with the given request_id across all services.
    """
    print(_section(f"Request Replay: {request_id}"))

    try:
        import os
        email = os.getenv("OPENOBSERVE_ROOT_EMAIL", "")
        password = os.getenv("OPENOBSERVE_ROOT_PASSWORD", "")

        since_min = 1440  # 24h — request_id logs may be from yesterday
        start_us = int((time.time() - since_min * 60) * 1_000_000)
        end_us = int(time.time() * 1_000_000)

        # OpenObserve SQL: search for request_id in JSON log body.
        # Log stream fields: _timestamp, container, service, message, level
        # (no "log" field — logs are stored in "message").
        sql = (
            f"SELECT _timestamp, container, service, message, level "
            f"FROM \"default\" "
            f"WHERE message LIKE '%{request_id}%' "
            f"ORDER BY _timestamp ASC LIMIT 500"
        )

        # Use /{org}/_search — stream is in the SQL FROM clause.
        # Only the first URL works; the second doubles "default" when org=default.
        urls_to_try = (
            f"{OPENOBSERVE_URL}/api/{OPENOBSERVE_ORG}/_search",
        )
        body = {"query": {"sql": sql, "start_time": start_us, "end_time": end_us}}

        resp = None
        async with httpx.AsyncClient(timeout=30.0, auth=(email, password)) as client:
            for url in urls_to_try:
                resp = await client.post(url, json=body)
                if resp.status_code == 200:
                    break

        if resp is None or resp.status_code != 200:
            print(_err(f"  OpenObserve returned {resp.status_code if resp else 'no response'}: {resp.text[:200] if resp else ''}"))
            return

        data = resp.json()
        all_events = []
        for hit in data.get("hits", []):
            ts_us = hit.get("_timestamp", 0)
            svc = hit.get("container", hit.get("service", "?"))
            log_line = hit.get("message", "")
            try:
                entry = json.loads(log_line)
                level = entry.get("level", entry.get("levelname", "info")).upper()
                msg = entry.get("message", log_line[:160])
            except Exception:
                level = hit.get("level", "INFO").upper()
                msg = log_line[:160]
            all_events.append({
                "ts": int(ts_us) * 1000,  # µs → ns for display consistency
                "service": svc,
                "level": level,
                "message": msg,
            })

        if not all_events:
            print(_warn(f"  No log entries found for request_id={request_id}"))
            print(_c(DIM, "  Note: Only requests with request_id propagation are traceable."))
            print(_c(DIM, "  OpenObserve retention: 14 days for operational logs (ZO_COMPACT_DATA_RETENTION_DAYS)."))
            print(_c(DIM, "  Compliance streams: audit-compliance=2yr, financial-compliance=10yr (stream-level overrides)."))
            print()
            return

        all_events.sort(key=lambda x: x["ts"])

        if len(all_events) == 1:
            base_ts = all_events[0]["ts"]
        else:
            base_ts = all_events[0]["ts"]

        print(f"  Found {len(all_events)} log entries across services:\n")

        services_seen = set()
        for ev in all_events:
            services_seen.add(ev["service"])
            offset_ms = (ev["ts"] - base_ts) // 1_000_000
            ts_str = datetime.fromtimestamp(ev["ts"] / 1e9).strftime('%H:%M:%S.%f')[:-3]
            level = ev["level"]
            if level in ("ERROR", "CRITICAL"):
                level_str = _c(RED, f"{level:<8}")
            elif level == "WARNING":
                level_str = _c(YELLOW, f"{level:<8}")
            else:
                level_str = _c(DIM, f"{level:<8}")
            svc = ev["service"][:16]
            offset_str = _c(DIM, f"+{offset_ms:>6}ms")
            msg = ev["message"][:MAX_LINE_LEN - 50]
            print(f"  {ts_str}  {offset_str}  {level_str}  {svc:<18}  {msg}")

        print()
        print(_c(DIM, f"  Services: {', '.join(sorted(services_seen))}"))
        print(_c(DIM, f"  Duration: {(all_events[-1]['ts'] - base_ts) // 1_000_000}ms total"))
        print()

    except Exception as exc:
        print(_err(f"  Replay failed: {exc}"))
        print()


# ═════════════════════════════════════════════════════════════════════════════
#  CLI entry point — called by debug.py via _delegate()
# ═════════════════════════════════════════════════════════════════════════════

async def _async_main():
    """Parse subcommand (health/replay/errors) and dispatch."""
    import argparse

    parser = argparse.ArgumentParser(description="Health, replay, and errors")
    sub = parser.add_subparsers(dest="command")

    health_p = sub.add_parser("health", help="System health check (includes log access verification)")
    health_p.add_argument("-v", "--verbose", action="store_true")
    health_p.add_argument(
        "--compact", action="store_true",
        help="Return a one-liner pass/fail summary (for session start in non-debug modes).",
    )
    health_p.add_argument(
        "--log-access", action="store_true",
        help="Run ONLY the log access check (OpenObserve + production API). Exit 1 if any source is down.",
    )
    health_p.add_argument(
        "--skip-log-access", action="store_true",
        help="Skip the log access check (useful when called from another health workflow).",
    )

    replay_p = sub.add_parser("replay", help="Replay request trace from OpenObserve")
    replay_p.add_argument("request_id", help="Request ID")

    errors_p = sub.add_parser("errors", help="Top error fingerprints")
    errors_p.add_argument("--top", type=int, default=10)
    errors_p.add_argument(
        "--compact", action="store_true",
        help="Return a compact overview of recent errors for session context "
        "(combines fingerprints + recent error counts).",
    )
    errors_p.add_argument(
        "--since", type=int, default=30,
        help="Look back N minutes for recent errors (default: 30). Used with --compact.",
    )
    errors_p.add_argument(
        "--diff",
        action="store_true",
        help="Compare error fingerprints from before vs after the last deployed commit. "
        "Shows which errors are NEW since last deploy vs which are pre-existing.",
    )
    errors_p.add_argument(
        "--since-deploy",
        action="store_true",
        dest="since_deploy",
        help="Alias for --diff. Show new errors introduced since last sessions.py deploy.",
    )

    args = parser.parse_args()

    if args.command == "health":
        if args.log_access:
            await run_log_access_check()
        elif args.compact:
            summary = await run_health_check_compact()
            print(f"Health: {summary}")
        else:
            await run_health_check(verbose=args.verbose, skip_log_access=args.skip_log_access)
    elif args.command == "replay":
        await replay_request(request_id=args.request_id)
    elif args.command == "errors":
        use_diff = getattr(args, 'diff', False) or getattr(args, 'since_deploy', False)
        if use_diff:
            await show_error_diff_since_deploy(top=args.top)
        elif args.compact:
            overview = await get_error_overview_compact(top=args.top, since_minutes=args.since)
            print(overview)
        else:
            await show_error_fingerprints(top=args.top)
    else:
        await run_health_check(verbose=False)


async def main():
    await _async_main()
