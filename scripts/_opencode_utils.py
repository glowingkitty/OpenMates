#!/usr/bin/env python3
"""
scripts/_opencode_utils.py

Shared utility for running persisted OpenCode chats from Python cron helpers.

Cron helpers write prompts into scripts/.tmp to avoid shell argument limits,
then call `opencode run --title ... --format json`. OpenCode stores the
created session in the same project store used by the web UI, so scheduled
maintenance work is visible as regular OpenCode chats.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


_TMP_DIR_NAME = "scripts/.tmp"
_INTERNAL_API_URL = os.environ.get("INTERNAL_API_URL", "http://localhost:8000")


def _extract_opencode_session_id(output: str) -> str | None:
    """Extract the first OpenCode sessionID from JSONL output."""
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        session_id = event.get("sessionID") or event.get("session_id")
        if session_id:
            return str(session_id)
    return None


def _notify_session(
    session_title: str,
    job_type: str | None,
    status: str,
    session_id: str | None,
    duration_seconds: int,
    exit_code: int,
    context_summary: str | None,
    log_prefix: str,
) -> None:
    """Send a non-fatal email notification about a completed cron chat."""
    if os.environ.get("CRON_SESSION_EMAILS_DISABLED", "").lower() in {"true", "1", "yes"}:
        print(f"{log_prefix} Cron session emails disabled (CRON_SESSION_EMAILS_DISABLED=true)", file=sys.stderr)
        return

    internal_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")
    if not internal_token:
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("INTERNAL_API_SHARED_TOKEN="):
                    internal_token = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not internal_token:
        print(f"{log_prefix} NOTE: INTERNAL_API_SHARED_TOKEN not set; skipping email notification.", file=sys.stderr)
        return

    payload = {
        "job_type": job_type or "unknown",
        "job_name": session_title,
        "status": status,
        "session_id": session_id,
        "duration_seconds": duration_seconds,
        "context_summary": context_summary,
        "exit_code": exit_code,
    }

    try:
        request = urllib.request.Request(
            f"{_INTERNAL_API_URL.rstrip('/')}/internal/dispatch-cron-session-email",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": internal_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
        print(f"{log_prefix} email notification dispatched ({status})")
    except Exception as error:
        print(f"{log_prefix} WARNING: email notification failed: {error} (non-fatal)", file=sys.stderr)


def _linear_complete(issue_id, identifier, status, exit_code, duration, log_prefix):
    """Post completion metadata for legacy Linear-backed cron sessions."""
    if not issue_id:
        return
    try:
        from _linear_client import remove_label, update_issue_status, post_comment as linear_comment

        result_status = "Done" if exit_code == 0 else "Todo"
        mins, secs = divmod(duration, 60)
        linear_comment(
            issue_id,
            f"**OpenCode session completed.**\n\n"
            f"**Status:** {status} (exit {exit_code})\n"
            f"**Duration:** {mins}m {secs}s",
        )
        remove_label(issue_id)
        update_issue_status(issue_id, result_status)
        print(f"{log_prefix} Linear: {identifier} -> {result_status}")
    except Exception as error:
        print(f"{log_prefix} WARNING: Linear completion failed: {error} (non-fatal)", file=sys.stderr)


def run_opencode_session(
    prompt: str,
    session_title: str,
    project_root: str,
    log_prefix: str,
    agent: str | None = None,
    timeout: int = 1800,
    allowed_tools=None,
    job_type: str | None = None,
    context_summary: str | None = None,
    use_zellij: bool = False,
    linear_task: bool = False,
    linear_mode: str = "feature",
    kill_on_exit: bool = False,
    model: str | None = None,
) -> tuple[int, str | None]:
    """Run a persisted OpenCode chat for a scheduled maintenance job."""
    del allowed_tools, use_zellij, kill_on_exit, model

    tmp_dir = Path(project_root) / _TMP_DIR_NAME
    tmp_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    pid = os.getpid()
    tmp_path = tmp_dir / f"opencode-prompt-{timestamp}-{pid}.md"
    relative_path = f"{_TMP_DIR_NAME}/{tmp_path.name}"

    linear_issue_id = None
    linear_identifier = None
    start_time = time.monotonic()
    status = "completed"

    try:
        tmp_path.write_text(prompt, encoding="utf-8")
        message = f"Read {relative_path} in full and follow all the instructions precisely."
        if agent == "plan":
            message += " This is a read-only planning/review job: do not edit files, do not commit, and do not deploy."

        command = [
            "opencode",
            "run",
            "--title",
            session_title,
            "--format",
            "json",
        ]
        if agent != "plan":
            command.append("--dangerously-skip-permissions")
        command.append(message)

        run_env = os.environ.copy()
        run_env["PATH"] = (
            "/home/superdev/.local/bin:/home/superdev/.npm-global/bin:"
            + run_env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        )

        if linear_task:
            try:
                from _linear_client import create_issue, update_issue_status, add_label, post_comment as linear_comment

                issue = create_issue(title=session_title, mode=linear_mode)
                if issue:
                    linear_issue_id = issue["id"]
                    linear_identifier = issue["identifier"]
                    update_issue_status(linear_issue_id, "In Progress")
                    add_label(linear_issue_id)
                    linear_comment(
                        linear_issue_id,
                        f"**OpenCode cron session started:** `{session_title}`\n\n"
                        f"Started at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                    )
                    print(f"{log_prefix} Linear: {linear_identifier} created -> In Progress")
            except Exception as error:
                print(f"{log_prefix} WARNING: Linear task creation failed: {error} (non-fatal)", file=sys.stderr)

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=project_root,
                env=run_env,
            )
            returncode = result.returncode
            combined = (result.stdout + result.stderr).strip()
            session_id = _extract_opencode_session_id(combined)
        except subprocess.TimeoutExpired as error:
            status = "timeout"
            combined = ((error.stdout or "") + (error.stderr or "")).strip()
            session_id = _extract_opencode_session_id(combined)
            returncode = 124
            print(f"{log_prefix} ERROR: OpenCode timed out after {timeout}s", file=sys.stderr)
        except FileNotFoundError:
            status = "failed"
            session_id = None
            returncode = 127
            combined = ""
            print(f"{log_prefix} ERROR: opencode binary not found in PATH.", file=sys.stderr)
        except OSError as error:
            status = "failed"
            session_id = None
            returncode = 1
            combined = ""
            print(f"{log_prefix} ERROR: OpenCode failed to start: {error}", file=sys.stderr)

        if session_id:
            print(f"{log_prefix} OpenCode session: {session_id}")
        else:
            print(f"{log_prefix} WARNING: no session ID found in OpenCode output.", file=sys.stderr)

        if returncode != 0 and status != "timeout":
            status = "failed"
            print(f"{log_prefix} WARNING: OpenCode exited with code {returncode}", file=sys.stderr)
            if combined:
                print(f"{log_prefix} OpenCode output:\n{combined}", file=sys.stderr)

        duration = int(time.monotonic() - start_time)
        if job_type:
            _notify_session(session_title, job_type, status, session_id, duration, returncode, context_summary, log_prefix)
        _linear_complete(linear_issue_id, linear_identifier, status, returncode, duration, log_prefix)
        return returncode, session_id
    finally:
        tmp_path.unlink(missing_ok=True)


def start_sessions_py(mode: str, task: str, project_root: str, log_prefix: str) -> str | None:
    """Start a sessions.py session for cron-dispatched OpenCode chats."""
    try:
        result = subprocess.run(
            ["python3", "scripts/sessions.py", "start", "--mode", mode, "--task", task],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=project_root,
        )
        if result.returncode != 0:
            print(f"{log_prefix} WARNING: sessions.py start failed: {result.stderr.strip()[:200]}", file=sys.stderr)
            return None
        for line in result.stdout.splitlines():
            if "SESSION" in line and "=" in line:
                parts = line.split()
                for index, part in enumerate(parts):
                    if part == "SESSION" and index + 1 < len(parts):
                        sid = parts[index + 1].strip()
                        if sid and len(sid) <= 8:
                            print(f"{log_prefix} sessions.py: started session {sid}")
                            return sid
        print(f"{log_prefix} WARNING: could not extract session ID from sessions.py output", file=sys.stderr)
        return None
    except Exception as error:
        print(f"{log_prefix} WARNING: sessions.py start failed: {error}", file=sys.stderr)
        return None


def end_sessions_py(session_id: str, project_root: str, log_prefix: str) -> None:
    """End a sessions.py session without deploying."""
    if not session_id:
        return
    try:
        subprocess.run(
            ["python3", "scripts/sessions.py", "end", "--session", session_id],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=project_root,
        )
        print(f"{log_prefix} sessions.py: ended session {session_id}")
    except Exception as error:
        print(f"{log_prefix} WARNING: sessions.py end failed: {error}", file=sys.stderr)
