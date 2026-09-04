#!/usr/bin/env python3
"""Restore unattended permission behavior for API-resumed OpenCode turns.

The OpenCode CLI's ``--auto`` mode replies ``once`` to every request.  That is
appropriate for an attached terminal, but API resumptions need a detached
watcher.  Replying ``once`` there causes the web client to notify for the same
safe permission pattern on every tool call.  ``always`` records only the
bounded patterns supplied by OpenCode (for example ``/tmp/*``), while the
project hooks continue to enforce the orchestration safety policy.
"""

from __future__ import annotations

import argparse
import fcntl
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.parse
import urllib.request


SESSION_RE = re.compile(r"^ses_[A-Za-z0-9]+$")
LOCAL_SERVER_RE = re.compile(r"^http://(?:127\.0\.0\.1|localhost):\d+$")


def resolve_project_root(cwd: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = cwd / common
    common = common.resolve()
    return common.parent if common.name == ".git" else cwd.resolve()


def approve_pending_patterns(*, server_url: str, project_root: Path, session_id: str, state: dict) -> list[str]:
    approved: list[str] = []
    for permission_id in state.get("pending_permission_ids") or []:
        if not re.fullmatch(r"per_[A-Za-z0-9]+", str(permission_id)):
            continue
        query = urllib.parse.urlencode({"directory": str(project_root)})
        request = urllib.request.Request(
            f"{server_url}/session/{session_id}/permissions/{permission_id}?{query}",
            data=b'{"response":"always"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            if 200 <= int(response.status) < 300:
                approved.append(str(permission_id))
    return approved


def watch(*, server_url: str, cwd: Path, session_id: str, timeout_seconds: int) -> int:
    if not SESSION_RE.fullmatch(session_id):
        raise ValueError("invalid OpenCode session ID")
    if not LOCAL_SERVER_RE.fullmatch(server_url.rstrip("/")):
        raise ValueError("permission watcher requires a loopback OpenCode server")
    server_url = server_url.rstrip("/")
    project_root = resolve_project_root(cwd)
    state_path = project_root / ".opencode" / "presence.json"
    lock_path = project_root / ".opencode" / f"permission-watcher-{session_id}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        deadline = time.monotonic() + timeout_seconds
        saw_live = False
        while time.monotonic() < deadline:
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            state = (payload.get("sessions") or {}).get(session_id) or {}
            live = state.get("execution") in {"busy", "retrying"} or state.get("turn") == "streaming"
            saw_live = saw_live or live
            try:
                approve_pending_patterns(
                    server_url=server_url,
                    project_root=project_root,
                    session_id=session_id,
                    state=state,
                )
            except OSError:
                pass
            if saw_live and not live and not (state.get("pending_permission_ids") or []):
                return 0
            time.sleep(1)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--cwd", required=True, type=Path)
    parser.add_argument("--session", required=True)
    parser.add_argument("--timeout", type=int, default=7200)
    args = parser.parse_args()
    return watch(
        server_url=args.server_url,
        cwd=args.cwd,
        session_id=args.session,
        timeout_seconds=max(30, min(args.timeout, 7200)),
    )


if __name__ == "__main__":
    raise SystemExit(main())
