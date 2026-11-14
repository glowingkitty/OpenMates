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

Usage: python3 scripts/prod_smoke_cron.py {free-hourly|paid-chat|app-skill} [--dry-run] [--force]
Architecture: docs/architecture/test-orchestration.md
"""

from __future__ import annotations

import argparse
import sys
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("suite", choices=sorted(SUITE_FLAGS))
    parser.add_argument("--dry-run", action="store_true", help="resolve the run without dispatching it")
    parser.add_argument("--force", action="store_true", help="run even if the dedup window says skip")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import run_tests

    sys.argv = run_tests_argv(args.suite, args.dry_run, args.force)
    return run_tests.main()


if __name__ == "__main__":
    raise SystemExit(main())
