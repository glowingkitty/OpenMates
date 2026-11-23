#!/usr/bin/env python3
"""Install and audit the host-side OpenMates test schedule.

The checked-in block is the source of truth for dev, production, and nightly
test cadence. It calls the engineering-only test wrapper and never modifies
self-hosted product images or the public OpenMates CLI.
"""

# contract-test-file: tooling

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Iterable
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BEGIN = "# BEGIN OpenMates managed test schedule"
END = "# END OpenMates managed test schedule"
LEGACY_COMMAND_MARKERS = (
    "scripts/run-tests-daily.sh --detach",
    "scripts/daily_ci_notification.py --send",
    "scripts/run_tests.py --hourly-dev",
    "scripts/run_tests.py --hourly-prod",
    "scripts/tests.py run --daily",
    "scripts/tests.py run --hourly-dev",
    "scripts/tests.py run --hourly-prod",
    "scripts/tests.py run --prod-free-hourly",
    "scripts/tests.py run --prod-paid-chat",
    "scripts/tests.py run --prod-app-skill",
    "scripts/run_tests.py --prod-free-hourly",
    "scripts/run_tests.py --prod-paid-chat",
    "scripts/run_tests.py --prod-app-skill",
)


# Europe/Berlin is UTC+1 (CET) or UTC+2 (CEST).
BERLIN_UTC_OFFSETS = (1, 2)
# Berlin hours each production suite runs at. run_tests.py gates on the same
# hours (PROD_FREE_HOURLY_START_HOUR..END_HOUR, PROD_PAID_CHAT_HOURS, PROD_APP_SKILL_HOURS).
PROD_FREE_HOURLY_BERLIN_HOURS = range(6, 24)
PROD_PAID_CHAT_BERLIN_HOURS = (7, 13, 19)
PROD_APP_SKILL_BERLIN_HOURS = (9,)


def berlin_hours_as_utc_cron(berlin_hours: Iterable[int]) -> str:
    """Return the cron hour field that hits every Berlin hour in CET and CEST.

    The host cron (Debian/Ubuntu cron 3.0) ignores CRON_TZ and always runs on
    the system clock (UTC), so each Berlin hour is listed at both UTC offsets.
    run_tests.py's Berlin-hour gate then skips the candidate that is off by one
    hour, so each slot runs exactly once whatever the season (TASK-4996).
    """
    utc_hours = sorted({(hour - offset) % 24 for hour in berlin_hours for offset in BERLIN_UTC_OFFSETS})
    return ",".join(str(hour) for hour in utc_hours)


def managed_block(root: Path = PROJECT_ROOT) -> str:
    quoted_root = str(root)
    log_root = f"{quoted_root}/logs"
    return "\n".join([
        BEGIN,
        "CRON_TZ=UTC",
        "# Nightly full suite at 03:00 UTC on weekdays (digest by noon UTC).",
        f"0 3 * * 1-5 /bin/bash {quoted_root}/scripts/run-tests-daily.sh --detach >> {log_root}/daily-tests.log 2>&1",
        "# Reconcile terminal receipts and retry only undelivered notification channels.",
        f"15 * * * * /usr/bin/python3 {quoted_root}/scripts/daily_ci_notification.py --send >> {log_root}/daily-tests-notification.log 2>&1",
        "# Hourly dev core journeys during the existing 08:00-18:00 UTC window.",
        "# CI migration HOLD --hourly-dev: legacy shared-runtime execution retired; explicit isolated coverage disposition pending.",
        "# Production slots are Europe/Berlin hours. This cron ignores CRON_TZ (system clock is UTC), so",
        "# each slot is listed at both its CET and CEST UTC hour; run_tests.py's Berlin-hour gate keeps one.",
        "# Production monitoring is GitHub-hosted and independent of dev Docker state. prod_smoke_cron.py, not",
        "# run_tests.py: run_tests.py forwards to the isolated CI dispatcher, which has no prod modes.",
        "# Hourly prod reachability + guest chat that must get a reply, 06-23 Berlin (TASK-832). It only",
        "# dispatches the GitHub-hosted prod-smoke workflow; failures go to DISCORD_WEBHOOK_PROD_SMOKE and email.",
        f"5 {berlin_hours_as_utc_cron(PROD_FREE_HOURLY_BERLIN_HOURS)} * * * bash -c 'set -a && . {quoted_root}/.env && set +a && cd {quoted_root} && /usr/bin/python3 scripts/prod_smoke_cron.py free-hourly' >> {log_root}/hourly-prod-tests.log 2>&1",
        "# Signed-in prod chat 3x/day and CLI web search 1x/day with the dedicated prod smoke test account",
        "# (GitHub secret OPENMATES_TEST_ACCOUNT_API_KEY; about 2 and 10 credits per run).",
        f"10 {berlin_hours_as_utc_cron(PROD_PAID_CHAT_BERLIN_HOURS)} * * * bash -c 'set -a && . {quoted_root}/.env && set +a && cd {quoted_root} && /usr/bin/python3 scripts/prod_smoke_cron.py paid-chat' >> {log_root}/prod-paid-chat-tests.log 2>&1",
        f"15 {berlin_hours_as_utc_cron(PROD_APP_SKILL_BERLIN_HOURS)} * * * bash -c 'set -a && . {quoted_root}/.env && set +a && cd {quoted_root} && /usr/bin/python3 scripts/prod_smoke_cron.py app-skill' >> {log_root}/prod-app-skill-tests.log 2>&1",
        END,
    ])


def replace_managed_schedule(current: str, root: Path = PROJECT_ROOT) -> str:
    lines = current.splitlines()
    retained: list[str] = []
    in_block = False
    for line in lines:
        if line.strip() == BEGIN:
            in_block = True
            continue
        if line.strip() == END:
            in_block = False
            continue
        if in_block or any(marker in line for marker in LEGACY_COMMAND_MARKERS):
            continue
        retained.append(line)
    while retained and not retained[-1].strip():
        retained.pop()
    return "\n".join([*retained, "", managed_block(root), ""])


def current_crontab() -> str:
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or audit the managed OpenMates test schedule")
    parser.add_argument(
        "--root",
        type=Path,
        default=PROJECT_ROOT,
        help="Canonical checkout path written into cron commands",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--install", action="store_true")
    args = parser.parse_args()

    current = current_crontab()
    root = args.root.resolve()
    if not (root / ".git").exists():
        parser.error(f"--root is not a Git checkout: {root}")
    desired = replace_managed_schedule(current, root)
    if args.check:
        if current.rstrip() == desired.rstrip():
            print("test_schedule=ok")
            return 0
        print("test_schedule=drift")
        return 1

    result = subprocess.run(["crontab", "-"], input=desired, text=True, check=False)
    if result.returncode != 0:
        print("test_schedule=install_failed")
        return result.returncode
    print("test_schedule=installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
