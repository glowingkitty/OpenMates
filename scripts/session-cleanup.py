#!/usr/bin/env python3
"""
scripts/session-cleanup.py

Periodic terminal-session hygiene for agent hosts.

Enforces the global Zellij session cap from `_zellij_utils`
(MAX_CONCURRENT_SESSIONS): exited sessions are removed first, then the oldest
idle sessions without an active agent process. Sessions with "claude" in their
name are never killed.

The former Linear-driven stale-session and poller cleanup was retired together
with the Linear agent workflow.

Runs every 5 minutes via the `session-cleanup` systemd user timer.

Usage:
    python3 scripts/session-cleanup.py            # enforce the cap
    python3 scripts/session-cleanup.py --dry-run  # only report the session count
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _zellij_utils import (  # noqa: E402 - sibling import after sys.path setup
    MAX_CONCURRENT_SESSIONS,
    enforce_session_limit,
    list_sessions,
)

LOG_PREFIX = "[session-cleanup]"


def main() -> None:
    parser = argparse.ArgumentParser(description="Enforce the agent terminal session cap")
    parser.add_argument("--dry-run", action="store_true", help="Report without killing sessions")
    args = parser.parse_args()
    count = len(list_sessions())
    if args.dry_run:
        print(f"{LOG_PREFIX} {count} sessions (cap {MAX_CONCURRENT_SESSIONS}); dry run")
        return
    killed = enforce_session_limit()
    if killed:
        print(f"{LOG_PREFIX} killed {killed} session(s) to stay within cap {MAX_CONCURRENT_SESSIONS}")


if __name__ == "__main__":
    main()
