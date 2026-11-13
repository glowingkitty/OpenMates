#!/usr/bin/env python3
"""Create a parallel-lane session in one step: fresh workspace, edit lane opened.

Usage: python3 scripts/lane_start.py --mode feature --task "<outcome>"
Prints the session id and worktree path to hand to a sub-agent. Sub-agents then
`cd` into the worktree, pass `--session <id>` and never run start/end.
Why: sub-agents share the parent's conversation id, so `sessions.py start`
cannot give each lane its own session and the edit gate needs `lane-open`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

SESSIONS = Path(__file__).resolve().parent / "sessions.py"


MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.0


class LaneStartError(RuntimeError):
    """A sessions.py step failed; message carries the command and its output."""


def _run(args: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, str(SESSIONS), *args], env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise LaneStartError(f"sessions.py {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def start_lane(mode: str, task: str, *, run=_run, sleep=time.sleep) -> tuple[str, str]:
    """Create a lane session, retrying transient failures and rolling back each failed attempt.

    Failures seen in practice come from concurrent sessions.json writers dropping a
    freshly written field; a retry on a fresh session succeeds.
    """
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        env = {**os.environ, "CLAUDE_CODE_SESSION_ID": str(uuid.uuid4())}
        session_id: str | None = None
        try:
            out = run(["start", "--mode", mode, "--task", task], env)
            session = re.search(r"^Session (\w+)", out, re.MULTILINE)
            workspace = re.search(r"^Workspace: (.+)$", out, re.MULTILINE)
            if not session or not workspace:
                raise LaneStartError(f"could not parse sessions.py start output:\n{out}")
            session_id = session.group(1)
            run(["lane-open", "--session", session_id], env)
            return session_id, workspace.group(1)
        except LaneStartError as exc:
            last_error = str(exc)
            print(f"lane_start attempt {attempt}/{MAX_ATTEMPTS} failed: {last_error}", file=sys.stderr)
            _rollback_with(run, session_id, env)
            if attempt < MAX_ATTEMPTS:
                sleep(RETRY_DELAY_SECONDS * attempt)
    raise SystemExit(f"lane_start failed after {MAX_ATTEMPTS} attempts; last error: {last_error}")


def _rollback_with(run, session_id: str | None, env: dict[str, str]) -> None:
    """Drop a half-created session (no worktree, no changes); never touches real work."""
    if not session_id:
        return
    try:
        run(["cleanup-orphans", "--session", session_id, "--min-age-seconds", "0"], env)
    except LaneStartError as exc:
        print(f"warning: could not roll back session {session_id}: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="feature", choices=["bug", "feature", "docs", "testing"])
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    session_id, worktree = start_lane(args.mode, args.task)
    print(f"session={session_id}")
    print(f"worktree={worktree}")


if __name__ == "__main__":
    main()
