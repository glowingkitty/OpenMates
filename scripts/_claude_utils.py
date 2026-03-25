#!/usr/bin/env python3
"""
scripts/_claude_utils.py

Shared utility for running Claude Code sessions from Python cron helpers.

Writes the prompt to a temp file inside the project dir to avoid the Linux
MAX_ARG_STRLEN ~128KB per-argument limit, then invokes `claude -p` in
non-interactive (headless) mode.

After each session completes, dispatches an email notification to the admin
via POST /internal/dispatch-cron-session-email (non-fatal if unreachable).

Replaces the previous _opencode_utils.py (migrated 2026-03-24).

Usage:
    from _claude_utils import run_claude_session

    rc, session_id = run_claude_session(
        prompt=prompt,
        session_title="audit: codebase health 2026-03-24",
        project_root="/home/superdev/projects/OpenMates",
        log_prefix="[audit]",
        agent="plan",          # omit for build mode (default)
        timeout=1800,
        job_type="audit",      # for email notification categorisation
        allowed_tools=None,    # e.g. ["Read", "Grep", "Glob", 'Bash(curl *)']
    )
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Temp files written here so claude can read them (project-dir access is allowed).
_TMP_DIR_NAME = "scripts/.tmp"

# Internal API for email notifications (runs on the host, port-forwarded from Docker)
_INTERNAL_API_URL = os.environ.get("INTERNAL_API_URL", "http://localhost:8000")


def _notify_session(
    session_title,
    job_type,
    status,
    session_id,
    duration_seconds,
    exit_code,
    context_summary,
    log_prefix,
):
    """
    Send a non-fatal email notification about the completed session.
    Never raises — logs errors and returns silently.
    """
    internal_token = os.environ.get("INTERNAL_API_SHARED_TOKEN", "")
    if not internal_token:
        # Try reading from .env
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if line.startswith("INTERNAL_API_SHARED_TOKEN="):
                    internal_token = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not internal_token:
        print(f"{log_prefix} NOTE: INTERNAL_API_SHARED_TOKEN not set — skipping email notification.", file=sys.stderr)
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

    url = f"{_INTERNAL_API_URL.rstrip('/')}/internal/dispatch-cron-session-email"

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Internal-Service-Token": internal_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        print(f"{log_prefix} email notification dispatched ({status})")
    except Exception as e:
        # Non-fatal — cron job should never fail due to notification issues
        print(f"{log_prefix} WARNING: email notification failed: {e} (non-fatal)", file=sys.stderr)


def run_claude_session(
    prompt,
    session_title,
    project_root,
    log_prefix,
    agent=None,
    timeout=1800,
    allowed_tools=None,
    job_type=None,
    context_summary=None,
):
    """
    Run a Claude Code session, writing the prompt to a temp file to avoid the
    Linux MAX_ARG_STRLEN ~128KB per-argument limit.

    Args:
        prompt: Full prompt text (can be large).
        session_title: Display name for the session (--name flag).
        project_root: Working directory for the claude process.
        log_prefix: Prefix for log messages (e.g. "[audit]").
        agent: "plan" for read-only mode, None for build mode
               (uses --dangerously-skip-permissions).
        timeout: Max seconds before killing the process (default: 1800).
        allowed_tools: Optional list of tool specs for --allowedTools
                       (e.g. ["Read", "Grep", 'Bash(curl *)']). Only used
                       when agent="plan" to extend plan mode capabilities.
        job_type: Category for email notification (e.g. "audit", "security",
                  "dependabot"). If None, no email is sent.
        context_summary: Optional brief description for the email
                         (e.g. "5 dependabot alerts processed").

    Returns:
        (returncode: int, session_id: str | None)
    """
    tmp_dir = Path(project_root) / _TMP_DIR_NAME
    tmp_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    pid = os.getpid()
    tmp_filename = f"claude-prompt-{timestamp}-{pid}.txt"
    tmp_path = tmp_dir / tmp_filename
    relative_path = f"{_TMP_DIR_NAME}/{tmp_filename}"

    start_time = time.monotonic()

    try:
        tmp_path.write_text(prompt, encoding="utf-8")

        # Short message — well under the 128KB per-arg kernel limit
        message = f"Read {relative_path} in full and follow all the instructions precisely."

        cmd = [
            "claude",
            "-p", message,
            "--model", "claude-sonnet-4-6",
            "--name", session_title,
            "--output-format", "json",
        ]

        if agent == "plan":
            cmd += ["--permission-mode", "plan"]
            # Allow specific tools beyond default plan-mode set
            if allowed_tools:
                cmd += ["--allowedTools"] + allowed_tools
        else:
            # Build mode — needs full write access for automated cron tasks
            cmd += ["--dangerously-skip-permissions"]

        run_env = os.environ.copy()
        run_env["PATH"] = (
            "/home/superdev/.local/bin:"
            "/home/superdev/.npm-global/bin:"
            + run_env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        )

        status = "completed"
        session_id = None
        returncode = 1

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=project_root,
                env=run_env,
            )
            returncode = result.returncode
        except subprocess.TimeoutExpired:
            print(f"{log_prefix} ERROR: claude timed out after {timeout}s", file=sys.stderr)
            status = "timeout"
            duration = int(time.monotonic() - start_time)
            if job_type:
                _notify_session(session_title, job_type, status, None, duration, 124, context_summary, log_prefix)
            return 1, None
        except FileNotFoundError:
            print(f"{log_prefix} ERROR: claude binary not found in PATH.", file=sys.stderr)
            status = "failed"
            duration = int(time.monotonic() - start_time)
            if job_type:
                _notify_session(session_title, job_type, status, None, duration, 127, context_summary, log_prefix)
            return 1, None
        except OSError as e:
            print(f"{log_prefix} ERROR: claude failed to start: {e}", file=sys.stderr)
            status = "failed"
            duration = int(time.monotonic() - start_time)
            if job_type:
                _notify_session(session_title, job_type, status, None, duration, 1, context_summary, log_prefix)
            return 1, None

        combined = (result.stdout + result.stderr).strip()

        # Extract session_id from JSON output
        try:
            output_json = json.loads(result.stdout.strip())
            session_id = output_json.get("session_id")
        except (json.JSONDecodeError, ValueError):
            pass

        if session_id:
            print(f"{log_prefix} claude session: {session_id}")
        else:
            print(f"{log_prefix} WARNING: no session ID found in claude output.", file=sys.stderr)

        if returncode != 0:
            status = "failed"
            print(
                f"{log_prefix} WARNING: claude exited with code {returncode}",
                file=sys.stderr,
            )
            # Always log full output on failure for debugging.
            if combined:
                print(f"{log_prefix} claude output:\n{combined}", file=sys.stderr)

        duration = int(time.monotonic() - start_time)

        # Send email notification (non-fatal)
        if job_type:
            _notify_session(
                session_title, job_type, status, session_id,
                duration, returncode, context_summary, log_prefix,
            )

        return returncode, session_id

    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
