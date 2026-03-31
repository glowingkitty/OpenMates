"""
scripts/_zellij_utils.py

Thin wrapper around the Zellij CLI for programmatic session management.

Each Claude Code task gets its own named Zellij session, visible at the
Zellij web UI (localhost:8082). Sessions are created, listed, and cleaned
up through this module.

All public functions are non-fatal: they print warnings to stderr and
return None/False on failure. Callers should never crash due to Zellij
being unavailable.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

ZELLIJ_BIN = "/usr/local/bin/zellij"
ZELLIJ_WEB_URL = "http://localhost:8082"

# Hard cap on concurrent Claude sessions to prevent system overload.
# The daily meeting may define up to 10 priorities, but only this many
# sessions can run simultaneously. Subsequent tasks wait or are skipped.
MAX_CONCURRENT_SESSIONS = 4

# Timeout for Zellij CLI commands (not the session process itself)
_CMD_TIMEOUT = 10


# ── Internal Helpers ─────────────────────────────────────────────────────────

def _run_zellij(
    args: List[str],
    timeout: int = _CMD_TIMEOUT,
    capture: bool = True,
) -> Optional[subprocess.CompletedProcess]:
    """
    Run a Zellij CLI command. Returns CompletedProcess or None on failure.
    """
    cmd = [ZELLIJ_BIN] + args

    try:
        return subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        print("Warning: zellij binary not found — skipping.", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"Warning: zellij command timed out: {shlex.join(cmd)}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Warning: zellij command failed: {e}", file=sys.stderr)
        return None


def _sanitize_session_name(name: str) -> str:
    """
    Convert a session title into a valid Zellij session name.
    Replaces spaces and special chars with hyphens, truncates to 50 chars.
    """
    sanitized = "".join(c if c.isalnum() or c in "-_" else "-" for c in name)
    # Collapse multiple hyphens and strip leading/trailing
    while "--" in sanitized:
        sanitized = sanitized.replace("--", "-")
    return sanitized.strip("-")[:50]


# ── Public Functions ─────────────────────────────────────────────────────────

def create_session(session_name: str) -> bool:
    """
    Create a new named Zellij session in detached (background) mode.
    If a session with this name already exists in EXITED state, deletes
    it first and recreates.

    Returns True if the session is available, False otherwise.
    """
    session_name = _sanitize_session_name(session_name)

    # Check if session already exists
    result = _run_zellij(["list-sessions", "--no-formatting"])
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith(session_name + " ") or stripped == session_name:
                if "EXITED" in stripped:
                    _run_zellij(["delete-session", session_name])
                    break
                else:
                    # Already alive
                    return True

    # Create detached session
    result = _run_zellij(["attach", "-b", "-c", session_name])
    if result and result.returncode == 0:
        return True

    print(f"Warning: failed to create Zellij session '{session_name}'.", file=sys.stderr)
    return False


def run_in_session(
    session_name: str,
    command: List[str],
    cwd: str,
    output_file: Optional[str] = None,
    timeout: Optional[int] = None,
) -> bool:
    """
    Run a command inside a Zellij session. Creates the session if needed.
    Blocks until the command exits.

    The command runs in the session's default pane. If output_file is set,
    stdout+stderr are redirected there for structured output parsing.

    Args:
        session_name: Name for the Zellij session (will be sanitized).
        command: Command and arguments to run.
        cwd: Working directory for the command.
        output_file: If set, redirects stdout+stderr to this file.
        timeout: Max seconds to wait (None = no limit).

    Returns True if the command ran (regardless of exit code), False if
    Zellij setup failed.
    """
    session_name = _sanitize_session_name(session_name)

    # Build the inner command — optionally redirect to output file
    if output_file:
        inner_cmd = f"cd {shlex.quote(cwd)} && {shlex.join(command)} > {shlex.quote(output_file)} 2>&1"
    else:
        inner_cmd = f"cd {shlex.quote(cwd)} && {shlex.join(command)}"

    # Use ZELLIJ_SESSION_NAME to target the session, run command in a pane
    args = [
        "run",
        "--name", session_name,
        "--cwd", cwd,
        "--close-on-exit",
        "--block-until-exit",
        "--",
        "sh", "-c", inner_cmd,
    ]

    run_timeout = timeout + 60 if timeout else 7200  # default 2h cap
    env = os.environ.copy()
    env["ZELLIJ_SESSION_NAME"] = session_name

    try:
        subprocess.run(
            [ZELLIJ_BIN] + args,
            capture_output=True,
            text=True,
            timeout=run_timeout,
            env=env,
        )
        return True
    except subprocess.TimeoutExpired:
        # Command may have completed — check output file
        if output_file and Path(output_file).is_file():
            return True
        print(f"Warning: Zellij session '{session_name}' timed out.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Warning: Zellij run failed: {e}", file=sys.stderr)
        return False


def launch_in_session(
    session_name: str,
    command: List[str],
    cwd: str,
) -> bool:
    """
    Launch a command inside a Zellij session without blocking.

    Unlike run_in_session(), this returns immediately and the pane stays
    alive after the command finishes. Used for interactive sessions where
    the user can attach later.

    Returns True if launched, False otherwise.
    """
    session_name = _sanitize_session_name(session_name)
    inner_cmd = f"cd {shlex.quote(cwd)} && {shlex.join(command)}"

    args = [
        "run",
        "--name", session_name,
        "--cwd", cwd,
        "--",
        "sh", "-c", inner_cmd,
    ]

    env = os.environ.copy()
    env["ZELLIJ_SESSION_NAME"] = session_name

    try:
        subprocess.Popen(
            [ZELLIJ_BIN] + args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except FileNotFoundError:
        print("Warning: zellij binary not found — skipping.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Warning: Zellij launch failed: {e}", file=sys.stderr)
        return False


def kill_session(session_name: str) -> bool:
    """
    Kill (destroy) a Zellij session by name.

    Returns True if killed, False if not found or failed.
    """
    session_name = _sanitize_session_name(session_name)
    result = _run_zellij(["kill-session", session_name])
    return result is not None and result.returncode == 0


def list_sessions() -> List[str]:
    """
    List all active (non-EXITED) Zellij session names.
    Returns empty list on failure.
    """
    result = _run_zellij(["list-sessions", "--no-formatting"])
    if not result or result.returncode != 0:
        return []

    sessions = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped and "EXITED" not in stripped:
            # Session name is the first word
            name = stripped.split()[0] if stripped.split() else ""
            if name:
                sessions.append(name)
    return sessions


def count_active_sessions() -> int:
    """Count non-EXITED Zellij sessions. Returns 0 on failure."""
    return len(list_sessions())


def cleanup_exited_sessions() -> int:
    """
    Delete all Zellij sessions in EXITED state.

    Returns the count of sessions cleaned up.
    """
    result = _run_zellij(["list-sessions", "--no-formatting"])
    if not result or result.returncode != 0:
        return 0

    cleaned = 0
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if "EXITED" in stripped:
            name = stripped.split()[0] if stripped.split() else ""
            if name:
                del_result = _run_zellij(["delete-session", name])
                if del_result and del_result.returncode == 0:
                    cleaned += 1
    return cleaned


def spawn_claude_session(
    session_name: str,
    prompt: str,
    cwd: str,
    permission_mode: str = "plan",
) -> bool:
    """
    Spawn an interactive Claude Code session in a new Zellij session.

    Creates a temporary KDL layout file that starts Claude directly with
    the prompt as a positional argument. The session is fully interactive —
    the user can attach at any time via `zellij attach <name>`.

    Args:
        session_name: Display name for the Zellij session (will be sanitized).
        prompt: The prompt text to send to Claude (passed as positional arg).
        cwd: Working directory for the Claude session.
        permission_mode: "plan" for read-only (default) or "execute" for
                         full edit access (--dangerously-skip-permissions).

    Returns True if the session was created, False otherwise.
    """
    session_name = _sanitize_session_name(session_name)

    # Clean up any existing EXITED session with the same name
    result = _run_zellij(["list-sessions", "--no-formatting"])
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith(session_name + " ") or stripped == session_name:
                if "EXITED" in stripped:
                    _run_zellij(["delete-session", session_name])
                else:
                    print(f"Warning: Zellij session '{session_name}' already exists.", file=sys.stderr)
                    return False

    # Build KDL layout — Claude with prompt as positional arg
    if permission_mode == "execute":
        args_line = '        args "--dangerously-skip-permissions" '
    else:
        args_line = '        args "--permission-mode" "plan" '

    # Escape double quotes in the prompt for KDL string
    escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"')
    args_line += f'"{escaped_prompt}"'

    # Escape backslashes and quotes in cwd for KDL
    escaped_cwd = cwd.replace("\\", "\\\\").replace('"', '\\"')

    layout_content = (
        "layout {\n"
        '    pane command="claude" {\n'
        f"{args_line}\n"
        f'        cwd "{escaped_cwd}"\n'
        "        focus true\n"
        "    }\n"
        "}\n"
    )

    # Write layout to temp file
    tmp_dir = Path(cwd) / "scripts" / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    layout_path = tmp_dir / f"{session_name}.kdl"

    try:
        layout_path.write_text(layout_content, encoding="utf-8")
    except Exception as e:
        print(f"Warning: failed to write KDL layout: {e}", file=sys.stderr)
        return False

    # Launch the session (runs in background subprocess; TTY panic is cosmetic)
    try:
        subprocess.Popen(
            [ZELLIJ_BIN, "--new-session-with-layout", str(layout_path), "-s", session_name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        print("Warning: zellij binary not found — skipping.", file=sys.stderr)
        layout_path.unlink(missing_ok=True)
        return False
    except Exception as e:
        print(f"Warning: zellij session launch failed: {e}", file=sys.stderr)
        layout_path.unlink(missing_ok=True)
        return False

    # Brief wait to let session initialize, then clean up layout file
    import time
    time.sleep(2)
    layout_path.unlink(missing_ok=True)

    # Verify session was created
    check = _run_zellij(["list-sessions", "--no-formatting"])
    if check and session_name in check.stdout:
        return True

    print(f"Warning: session '{session_name}' not found after launch.", file=sys.stderr)
    return False


def format_attach_command(session_name: str) -> str:
    """Return the zellij attach command for a session."""
    return f"zellij attach {_sanitize_session_name(session_name)}"


def format_session_info(session_name: str) -> str:
    """Return formatted session info for Linear comments / terminal output."""
    sanitized = _sanitize_session_name(session_name)
    return (
        f"**Attach:** `zellij attach {sanitized}`\n"
        f"**Web UI:** {ZELLIJ_WEB_URL}"
    )
