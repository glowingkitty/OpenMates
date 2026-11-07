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
import uuid
from pathlib import Path

SESSIONS = Path(__file__).resolve().parent / "sessions.py"


def _run(args: list[str], env: dict[str, str]) -> str:
    result = subprocess.run(
        [sys.executable, str(SESSIONS), *args], env=env, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise SystemExit(f"sessions.py {args[0]} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", default="feature", choices=["bug", "feature", "docs", "testing"])
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    env = {**os.environ, "CLAUDE_CODE_SESSION_ID": str(uuid.uuid4())}
    out = _run(["start", "--mode", args.mode, "--task", args.task], env)
    session = re.search(r"^Session (\w+)", out, re.MULTILINE)
    workspace = re.search(r"^Workspace: (.+)$", out, re.MULTILINE)
    if not session or not workspace:
        raise SystemExit(f"could not parse sessions.py start output:\n{out}")
    _run(["lane-open", "--session", session.group(1)], env)
    print(f"session={session.group(1)}")
    print(f"worktree={workspace.group(1)}")


if __name__ == "__main__":
    main()
