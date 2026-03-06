#!/usr/bin/env python3
"""
Health check module for debug.py — provides system health summaries, entity health
checks, error fingerprint display, and request replay.

Called by debug.py; not meant to be run directly.

Architecture context: See docs/claude/debugging.md
Tests: None (inspection script, not production code)
"""

import hashlib
import json
import logging
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

import httpx

# Add backend path
sys.path.insert(0, '/app/backend')
sys.path.insert(0, '/app')

# Suppress noisy library logs
logging.basicConfig(level=logging.WARNING, format='%(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('backend').setLevel(logging.WARNING)
logging.getLogger('aiohttp').setLevel(logging.WARNING)

logger = logging.getLogger('debug_health')
logger.setLevel(logging.WARNING)  # Only raise if something goes wrong

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
LOKI_URL = "http://loki:3100"

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


async def _loki_recent_errors(limit: int = 10, since_minutes: int = 30) -> List[Dict]:
    """
    Fetch recent error-level log entries from Loki across all services.
    Returns list of {ts, service, message} dicts, newest-first.
    """
    try:
        now_ns = int(time.time() * 1e9)
        start_ns = int((time.time() - since_minutes * 60) * 1e9)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params={
                    "query": '{job=~".+"} | json | level =~ "ERROR|error|CRITICAL|critical"',
                    "start": str(start_ns),
                    "end": str(now_ns),
                    "limit": limit,
                    "direction": "backward",
                }
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for stream in data.get("data", {}).get("result", []):
                svc = stream.get("stream", {}).get("container_name", stream.get("stream", {}).get("job", "?"))
                for ts_str, line in stream.get("values", []):
                    try:
                        entry = json.loads(line)
                        msg = entry.get("message", line[:120])
                    except Exception:
                        msg = line[:120]
                    results.append({
                        "ts": int(ts_str),
                        "service": svc,
                        "message": msg,
                    })
            # Sort newest first and limit
            results.sort(key=lambda x: x["ts"], reverse=True)
            return results[:limit]
    except Exception:
        return []


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

async def run_health_check(verbose: bool = False) -> None:
    """
    Run a comprehensive system health check:
    - Prometheus target status (api, prometheus self)
    - API error rate and latency from Prometheus
    - Celery queue depths from Redis
    - Recent error logs from Loki
    - Celery task failure count (if metrics available)
    """
    print(_section("OpenMates System Health"))
    print(_c(DIM, f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"))

    issues_found = 0

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

    # ── 4. Recent errors from Loki ─────────────────────────────────────────
    since_min = 60 if not verbose else 30
    limit = 5 if not verbose else 10
    recent_errors = await _loki_recent_errors(limit=limit, since_minutes=since_min)
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
            parts = member.split("|", 4)
            exc_type = parts[1] if len(parts) > 1 else "?"
            file_part = parts[2] if len(parts) > 2 else "?"
            func = parts[3] if len(parts) > 3 else "?"
            line = parts[4] if len(parts) > 4 else "?"
            count = int(score)
            color = RED if count > 100 else (YELLOW if count > 10 else RESET)
            print(f"{indent}{_c(color, str(count).rjust(5))}x  {exc_type}  {file_part}:{func}:{line}")

        await cache.close()
    except Exception as exc:
        print(f"{indent}{_c(DIM, f'Error fingerprints unavailable: {exc}')}")


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
            parts = member.split("|", 4)
            exc_type = (parts[1] if len(parts) > 1 else "?")[:28]
            file_part = (parts[2] if len(parts) > 2 else "?")[-25:]
            func = (parts[3] if len(parts) > 3 else "?")[:20]
            line = parts[4] if len(parts) > 4 else "?"
            count = int(score)
            color = RED if count > 100 else (YELLOW if count > 10 else RESET)
            location = f"{file_part}:{func}:{line}"[:45]
            print(f"  {_c(color, str(count).rjust(6))}  {exc_type:<30}  {location}")

        print()
        # Also sample recent occurrences from Loki for each fingerprint
        print(_c(DIM, "  Tip: Run `debug.py logs <email>` to trace errors to specific users."))
        await cache.close()
    except Exception as exc:
        print(_err(f"  Failed to fetch error fingerprints: {exc}"))

    print()


# ─── Request replay ───────────────────────────────────────────────────────────

async def replay_request(request_id: str) -> None:
    """
    Reconstruct the full timeline of a request by querying Loki for all
    log entries with the given request_id across all services.
    """
    print(_section(f"Request Replay: {request_id}"))

    try:
        since_min = 1440  # 24h — request_id logs may be from yesterday
        now_ns = int(time.time() * 1e9)
        start_ns = int((time.time() - since_min * 60) * 1e9)

        # LogQL: match request_id in JSON logs
        loki_query = '{job=~".+"} | json | request_id=`' + request_id + '`'

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{LOKI_URL}/loki/api/v1/query_range",
                params={
                    "query": loki_query,
                    "start": str(start_ns),
                    "end": str(now_ns),
                    "limit": 500,
                    "direction": "forward",
                }
            )

        if resp.status_code != 200:
            print(_err(f"  Loki returned {resp.status_code}: {resp.text[:200]}"))
            return

        data = resp.json()
        all_events = []
        for stream in data.get("data", {}).get("result", []):
            svc = stream.get("stream", {}).get("container_name",
                  stream.get("stream", {}).get("job", "?"))
            for ts_str, line in stream.get("values", []):
                try:
                    entry = json.loads(line)
                    level = entry.get("level", entry.get("levelname", "info")).upper()
                    msg = entry.get("message", line[:160])
                except Exception:
                    level = "INFO"
                    msg = line[:160]
                all_events.append({
                    "ts": int(ts_str),
                    "service": svc,
                    "level": level,
                    "message": msg,
                })

        if not all_events:
            print(_warn(f"  No log entries found for request_id={request_id}"))
            print(_c(DIM, "  Note: Only requests with request_id propagation are traceable."))
            print(_c(DIM, "  Loki retention is 7 days."))
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
