#!/usr/bin/env python3
"""
scripts/_claude_utils.py

Shared utility for running Claude Code sessions from Python cron helpers.

Two execution modes:
  - Interactive (default): Creates an attachable Zellij session with the
    full Claude Code TUI. The prompt is written to a temp file, then sent
    to Claude via `zellij action write-chars`. Sessions can be attached to
    with `zellij attach <name>` and are auto-cleaned after completion.
  - Headless fallback: If Zellij is unavailable, runs `claude -p` in a
    direct subprocess with JSON output captured.

After each session completes, dispatches an email notification to the admin
via POST /internal/dispatch-cron-session-email (non-fatal if unreachable).

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
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# Temp files written here so claude can read them (project-dir access is allowed).
_TMP_DIR_NAME = "scripts/.tmp"

# Internal API for email notifications (runs on the host, port-forwarded from Docker)
_INTERNAL_API_URL = os.environ.get("INTERNAL_API_URL", "http://localhost:8000")

# Default model for all cron sessions
DEFAULT_MODEL = "claude-opus-4-6"


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


def _linear_complete(issue_id, identifier, status, exit_code, duration, log_prefix):
    """
    Post completion comment and update Linear issue status.
    Non-fatal — never raises.
    """
    if not issue_id:
        return
    try:
        from _linear_client import update_issue_status, remove_label, post_comment as linear_comment

        result_status = "Done" if exit_code == 0 else "Todo"
        mins, secs = divmod(duration, 60)
        linear_comment(
            issue_id,
            f"**Session completed.**\n\n"
            f"**Status:** {status} (exit {exit_code})\n"
            f"**Duration:** {mins}m {secs}s",
        )
        remove_label(issue_id)
        update_issue_status(issue_id, result_status)
        print(f"{log_prefix} Linear: {identifier} → {result_status}")
    except Exception as e:
        print(f"{log_prefix} WARNING: Linear completion failed: {e} (non-fatal)", file=sys.stderr)


def _build_claude_args(
    agent,
    allowed_tools,
    session_title,
    model=None,
):
    """
    Build the Claude CLI argument list (without the prompt — that's sent
    separately for interactive mode or via -p for headless).
    """
    model = model or DEFAULT_MODEL
    args = ["--model", model, "--name", session_title]

    if agent == "plan":
        args += ["--permission-mode", "plan"]
        if allowed_tools:
            args += ["--allowedTools"] + allowed_tools
    else:
        # Build mode — needs full write access for automated cron tasks
        args += ["--dangerously-skip-permissions"]

    return args


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
    use_zellij=True,
    linear_task=True,
    linear_mode="feature",
    model=None,
):
    """
    Run a Claude Code session. Creates an interactive, attachable Zellij
    session by default; falls back to headless subprocess if unavailable.

    Args:
        prompt: Full prompt text (can be large).
        session_title: Display name for the session.
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
        context_summary: Optional brief description for the email.
        use_zellij: Create an interactive Zellij session (default: True).
                    Falls back to headless subprocess if Zellij unavailable.
        linear_task: Create a Linear task for this session (default: True).
        linear_mode: Session mode for Linear title prefix.
        model: Claude model to use (default: claude-opus-4-6).

    Returns:
        (returncode: int, session_id: str | None)
    """
    tmp_dir = Path(project_root) / _TMP_DIR_NAME
    tmp_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    uid = uuid.uuid4().hex[:8]
    tmp_filename = f"claude-prompt-{timestamp}-{uid}.txt"
    tmp_path = tmp_dir / tmp_filename
    relative_path = f"{_TMP_DIR_NAME}/{tmp_filename}"

    start_time = time.monotonic()

    try:
        tmp_path.write_text(prompt, encoding="utf-8")

        # The message sent to Claude — references the temp file
        message = f"Read {relative_path} in full and follow all the instructions precisely."

        claude_args = _build_claude_args(agent, allowed_tools, session_title, model)

        run_env = os.environ.copy()
        run_env["PATH"] = (
            "/home/superdev/.local/bin:"
            "/home/superdev/.npm-global/bin:"
            + run_env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
        )

        # ── Zellij interactive session ──────────────────────────────────
        zellij_session_name = None
        used_zellij = False

        if use_zellij:
            try:
                from _zellij_utils import (
                    create_interactive_session,
                    wait_for_completion,
                    kill_session,
                    _sanitize_session_name,
                )

                zellij_session_name = _sanitize_session_name(session_title)

                created = create_interactive_session(
                    session_name=session_title,
                    claude_args=claude_args,
                    prompt=message,
                    cwd=project_root,
                    timeout=timeout,
                    log_prefix=log_prefix,
                )

                if created:
                    used_zellij = True
                    print(f"{log_prefix} Zellij: interactive session '{zellij_session_name}' — attach with: zellij attach {zellij_session_name}")
                else:
                    print(f"{log_prefix} WARNING: interactive session creation failed — falling back to headless.", file=sys.stderr)
            except Exception as e:
                print(f"{log_prefix} WARNING: Zellij failed: {e} — falling back to headless.", file=sys.stderr)

        # ── Linear task creation ────────────────────────────────────────
        linear_issue_id = None
        linear_identifier = None
        if linear_task:
            try:
                from _linear_client import create_issue, update_issue_status, add_label, post_comment as linear_comment

                issue = create_issue(title=session_title, mode=linear_mode)
                if issue:
                    linear_issue_id = issue["id"]
                    linear_identifier = issue["identifier"]
                    update_issue_status(linear_issue_id, "In Progress")
                    add_label(linear_issue_id)

                    zellij_info = ""
                    if zellij_session_name:
                        zellij_info = (
                            f"**Attach:** `zellij attach {zellij_session_name}`\n"
                            f"**Web UI:** http://localhost:8082\n\n"
                        )

                    linear_comment(
                        linear_issue_id,
                        f"**Cron session started:** `{session_title}`\n\n"
                        f"{zellij_info}"
                        f"Started at {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
                    )
                    print(f"{log_prefix} Linear: {linear_identifier} created → In Progress")
            except Exception as e:
                print(f"{log_prefix} WARNING: Linear task creation failed: {e} (non-fatal)", file=sys.stderr)

        # ── Wait for completion (interactive) or run headless ────────────
        status = "completed"
        session_id = None
        returncode = 1

        if used_zellij:
            # Poll for Claude to finish, then auto-cleanup the session
            completed = wait_for_completion(
                session_name=session_title,
                timeout=timeout,
                poll_interval=15,
                log_prefix=log_prefix,
            )

            if completed:
                returncode = 0
                # Session ID not available in interactive mode — use the
                # Zellij session name as the identifier instead
                session_id = zellij_session_name
            else:
                status = "timeout"
                returncode = 124
                # Force-kill on timeout
                kill_session(session_title)

        else:
            # Headless fallback: direct subprocess with -p flag
            cmd = [
                "claude",
                "-p", message,
                "--output-format", "json",
            ] + claude_args

            combined = ""
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
                combined = (result.stdout + result.stderr).strip()
                try:
                    output_json = json.loads(result.stdout.strip())
                    session_id = output_json.get("session_id")
                except (json.JSONDecodeError, ValueError):
                    pass
            except subprocess.TimeoutExpired:
                print(f"{log_prefix} ERROR: claude timed out after {timeout}s", file=sys.stderr)
                status = "timeout"
                duration = int(time.monotonic() - start_time)
                if job_type:
                    _notify_session(session_title, job_type, status, None, duration, 124, context_summary, log_prefix)
                _linear_complete(linear_issue_id, linear_identifier, "timeout", 124, 0, log_prefix)
                return 1, None
            except FileNotFoundError:
                print(f"{log_prefix} ERROR: claude binary not found in PATH.", file=sys.stderr)
                status = "failed"
                duration = int(time.monotonic() - start_time)
                if job_type:
                    _notify_session(session_title, job_type, status, None, duration, 127, context_summary, log_prefix)
                _linear_complete(linear_issue_id, linear_identifier, "failed", 127, 0, log_prefix)
                return 1, None
            except OSError as e:
                print(f"{log_prefix} ERROR: claude failed to start: {e}", file=sys.stderr)
                status = "failed"
                duration = int(time.monotonic() - start_time)
                if job_type:
                    _notify_session(session_title, job_type, status, None, duration, 1, context_summary, log_prefix)
                _linear_complete(linear_issue_id, linear_identifier, "failed", 1, 0, log_prefix)
                return 1, None

            if returncode != 0:
                status = "failed"
                print(f"{log_prefix} WARNING: claude exited with code {returncode}", file=sys.stderr)
                if combined:
                    print(f"{log_prefix} claude output:\n{combined}", file=sys.stderr)

        if session_id:
            print(f"{log_prefix} claude session: {session_id}")

        duration = int(time.monotonic() - start_time)

        # Send email notification (non-fatal)
        if job_type:
            email_context = context_summary or ""
            if zellij_session_name:
                zellij_info = f"Zellij: zellij attach {zellij_session_name} | http://localhost:8082"
                email_context = f"{zellij_info}\n{email_context}" if email_context else zellij_info
            if linear_identifier:
                email_context = f"Linear: {linear_identifier}\n{email_context}" if email_context else f"Linear: {linear_identifier}"

            _notify_session(
                session_title, job_type, status, session_id,
                duration, returncode, email_context or None, log_prefix,
            )

        # ── Linear task completion ───────────────────────────────────
        _linear_complete(linear_issue_id, linear_identifier, status, returncode, duration, log_prefix)

        return returncode, session_id

    finally:
        # Don't delete the prompt file immediately — the interactive session
        # needs it. Schedule deletion after timeout + buffer.
        if used_zellij:
            def _deferred_cleanup():
                time.sleep(30)
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
            t = threading.Thread(target=_deferred_cleanup, daemon=True)
            t.start()
        else:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
