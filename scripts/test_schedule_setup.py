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
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BEGIN = "# BEGIN OpenMates managed test schedule"
END = "# END OpenMates managed test schedule"
LEGACY_COMMAND_MARKERS = (
    "scripts/run_tests.py --hourly-dev",
    "scripts/run_tests.py --hourly-prod",
    "scripts/tests.py run --daily",
    "scripts/tests.py run --hourly-dev",
    "scripts/tests.py run --hourly-prod",
    "scripts/tests.py run --prod-free-hourly",
    "scripts/tests.py run --prod-paid-chat",
    "scripts/tests.py run --prod-app-skill",
)


def managed_block(root: Path = PROJECT_ROOT) -> str:
    quoted_root = str(root)
    prefix = f"bash -c 'set -a && . {quoted_root}/.env && set +a && cd {quoted_root} &&"
    log_root = f"{quoted_root}/logs"
    return "\n".join([
        BEGIN,
        "# Nightly full suite at 03:00 UTC.",
        f"0 3 * * * {prefix} python3 scripts/tests.py run --daily --no-fail-fast' >> {log_root}/daily-tests.log 2>&1",
        "# Hourly dev core journeys during the existing 08:00-18:00 UTC window.",
        f"0 8-18 * * * {prefix} python3 scripts/tests.py run --hourly-dev' >> {log_root}/hourly-dev-tests.log 2>&1",
        "CRON_TZ=Europe/Berlin",
        "# Production monitoring is GitHub-hosted and independent of dev Docker state.",
        f"5 6-23 * * * {prefix} python3 scripts/tests.py run --prod-free-hourly' >> {log_root}/hourly-prod-tests.log 2>&1",
        f"10 7,13,19 * * * {prefix} python3 scripts/tests.py run --prod-paid-chat' >> {log_root}/prod-paid-chat-tests.log 2>&1",
        f"15 9 * * * {prefix} python3 scripts/tests.py run --prod-app-skill' >> {log_root}/prod-app-skill-tests.log 2>&1",
        "CRON_TZ=UTC",
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
