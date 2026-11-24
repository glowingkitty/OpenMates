#!/usr/bin/env python3
"""Cron entry for the GitHub-hosted production smoke suites.

`python3 scripts/run_tests.py ...` always forwards to the isolated CI
dispatcher (scripts/ci_entrypoint.py), which has no production modes, so the
`--prod-*` flags never reached run_tests.main() and the prod smoke crons sat on
HOLD while production AI chats were down (TASK-832, Nov 13-14 2026).

These modes never touch the shared dev stack: run_tests.main() dispatches
.github/workflows/prod-smoke.yml on GitHub, waits for it, parses its artifacts
and sends the alerts. This script imports run_tests (the forwarder only runs
when run_tests.py is the main program) and calls main() with one prod flag.
free-hourly first runs scripts/prod_email_health.py (prod transactional email) and
scripts/prod_tls_health.py (prod certificate validity and expiry).

Usage: python3 scripts/prod_smoke_cron.py {free-hourly|paid-chat|app-skill} [--dry-run] [--force]
Architecture: docs/architecture/test-orchestration.md
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

SUITE_FLAGS = {
    "free-hourly": "--prod-free-hourly",
    "paid-chat": "--prod-paid-chat",
    "app-skill": "--prod-app-skill",
}


def run_tests_argv(suite: str, dry_run: bool, force: bool) -> list[str]:
    """Build the argv run_tests.main() sees for one production suite."""
    argv = ["run_tests.py", SUITE_FLAGS[suite]]
    if dry_run:
        argv.append("--dry-run")
    if force:
        argv.append("--force")
    return argv


def run_monitor(root: Path) -> int:
    """Run inexpensive production checks and recheck only active smoke incidents."""
    import prod_email_health
    import prod_tls_health
    from scripts import production_uptime
    from scripts.production_uptime import Observation

    if not production_uptime.enabled():
        return 0
    store = production_uptime.store_for(root)
    webhook = os.environ.get("DISCORD_WEBHOOK_PROD_SMOKE", "")

    def post(message: str) -> bool:
        return bool(webhook) and prod_email_health.post_discord(webhook, message)

    now = datetime.now(timezone.utc)
    prod_email_health.monitor(store, now, post, api_key=os.environ.get("BREVO_API_KEY", ""))
    result = prod_tls_health.evaluate(now)
    for host, check in result["checks"].items():
        addresses = check.get("addresses") or []
        invalid = not addresses or any("not_after" not in address for address in addresses)
        health = "up" if check["ok"] else "down" if invalid else "up"
        items = [Observation(f"Production TLS ({host})", "TLS handshake", now.timestamp(), health,
                             check.get("reason", "") if invalid else "")]
        if not invalid and not check["ok"]:
            items.append(Observation(f"Production TLS ({host})", "certificate renewal", now.timestamp(),
                                     "checker", check.get("reason", "")))
        store.record(items, time.time(), post)
    print("[tls-health] " + str(result))

    active = store.active_services()
    suites_by_service = {
        "free-hourly": {"reachability", "guest-chat", "guest-web-send"},
        "paid-chat": {"paid-chat"},
        "app-skill": {"app-skill-web-search"},
    }
    suites = [suite for suite, keys in suites_by_service.items()
              if active.intersection(production_uptime.SERVICES[key] for key in keys)]
    with ThreadPoolExecutor(max_workers=len(SUITE_FLAGS)) as pool:
        codes = list(pool.map(lambda suite: subprocess.run(
            [sys.executable, __file__, suite, "--force"], check=False).returncode, suites))
    return next((code for code in codes if code), 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("suite", choices=[*sorted(SUITE_FLAGS), "monitor"])
    parser.add_argument("--dry-run", action="store_true", help="resolve the run without dispatching it")
    parser.add_argument("--force", action="store_true", help="run even if the dedup window says skip")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from scripts import production_uptime

    if args.suite == "monitor":
        return 0 if args.dry_run else run_monitor(root)
    email_rc = tls_rc = 0
    if args.suite == "free-hourly" and not production_uptime.enabled():
        # Transactional email health rides with the hourly smoke (TASK-427):
        # its own Discord alert, independent of the GitHub-hosted browser run.
        import prod_email_health

        email_rc = prod_email_health.run(dry_run=args.dry_run)
        # TLS certificate validity/expiry for the public prod hosts (TASK-5089).
        import prod_tls_health

        tls_rc = prod_tls_health.run(dry_run=args.dry_run)
    import run_tests

    sys.argv = run_tests_argv(args.suite, args.dry_run, args.force)
    smoke_rc = run_tests.main()
    return smoke_rc or email_rc or tls_rc


if __name__ == "__main__":
    raise SystemExit(main())
