"""
scripts/_zellij_utils.py

Thin wrapper around the Zellij CLI for programmatic session management.

Each Claude Code task gets its own named Zellij session, visible at the
Zellij web UI (localhost:8082). Sessions are created, listed, and cleaned
up through this module.

Two execution modes:
  - Interactive: creates a real terminal session (via `script` for PTY)
    that can be attached to with `zellij attach <name>`. Claude runs as
    a full interactive TUI and commands are sent via `write-chars`.
  - Headless (legacy): uses `zellij run --block-until-exit` with output
    redirected to a file. Not attachable — kept as fallback.

All public functions are non-fatal: they print warnings to stderr and
return None/False on failure. Callers should never crash due to Zellij
being unavailable.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

ZELLIJ_BIN = "/usr/local/bin/zellij"
ZELLIJ_WEB_URL = "http://localhost:8082"

# Timeout for Zellij CLI commands (not the session process itself)
_CMD_TIMEOUT = 10

# Seconds to wait for Claude TUI to initialize before sending prompt
_CLAUDE_STARTUP_DELAY = 5

# Layout file for interactive sessions (bash pane with PTY)
_LAYOUT_CONTENT = 'layout {\n    pane command="bash";\n}'


# ── Internal Helpers ─────────────────────────────────────────────────────────

def _run_zellij(
    args: List[str],
    timeout: int = _CMD_TIMEOUT,
    capture: bool = True,
    env: Optional[dict] = None,
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
            env=env or os.environ.copy(),
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


def _write_layout_file() -> Path:
    """Write a temporary KDL layout file for interactive sessions."""
    layout_path = Path("/tmp/zellij-claude-layout.kdl")
    if not layout_path.is_file() or layout_path.read_text().strip() != _LAYOUT_CONTENT:
        layout_path.write_text(_LAYOUT_CONTENT + "\n")
    return layout_path


def _send_keys(session_name: str, text: str) -> bool:
    """Send a string of characters to the focused pane in a session."""
    result = _run_zellij(
        ["--session", session_name, "action", "write-chars", text]
    )
    return result is not None and result.returncode == 0


def _send_enter(session_name: str) -> bool:
    """Send Enter (carriage return) to the focused pane."""
    result = _run_zellij(
        ["--session", session_name, "action", "write", "13"]
    )
    return result is not None and result.returncode == 0


def _send_escape(session_name: str) -> bool:
    """Send Escape key to dismiss Zellij tips overlay."""
    result = _run_zellij(
        ["--session", session_name, "action", "write", "27"]
    )
    return result is not None and result.returncode == 0


# ── Public Functions ─────────────────────────────────────────────────────────

def create_session(session_name: str) -> bool:
    """
    Create a new named Zellij session in detached (background) mode.
    If a session with this name already exists in EXITED state, deletes
    it first and recreates.

    Note: sessions created this way don't have a functional PTY — use
    create_interactive_session() for attachable sessions with Claude.

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


def create_interactive_session(
    session_name: str,
    claude_args: List[str],
    prompt: str,
    cwd: str,
    timeout: int = 1800,
    log_prefix: str = "",
) -> bool:
    """
    Create an attachable Zellij session with an interactive Claude Code TUI.

    Uses `script` to provide a real PTY (required for Zellij panes to work
    without an attached terminal), then sends commands via write-chars.

    The session can be attached to with: zellij attach <session_name>

    Args:
        session_name: Display name (will be sanitized).
        claude_args: Arguments for the claude command (e.g. ["--model", "..."]).
        prompt: The message to send to Claude once the TUI is ready.
        cwd: Working directory for the Claude session.
        timeout: Max seconds to wait for completion (for the polling thread).
        log_prefix: Prefix for log messages.

    Returns True if the session was created and Claude started, False otherwise.
    """
    session_name = _sanitize_session_name(session_name)

    # Clean up any existing session with this name
    result = _run_zellij(["list-sessions", "--no-formatting"])
    if result and result.returncode == 0:
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith(session_name + " ") or stripped == session_name:
                if "EXITED" in stripped:
                    _run_zellij(["delete-session", session_name])
                else:
                    _run_zellij(["kill-session", session_name])
                    _run_zellij(["delete-session", session_name])
                break

    # Write layout file
    layout_path = _write_layout_file()

    # Create session with a real PTY via `script`
    # `script -q -c "..." /dev/null` provides a PTY without recording output
    zellij_cmd = (
        f"{ZELLIJ_BIN} --session {shlex.quote(session_name)} "
        f"--new-session-with-layout {shlex.quote(str(layout_path))}"
    )
    try:
        subprocess.Popen(
            [
                "nohup", "script", "-q", "-c", zellij_cmd, "/dev/null",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        print(f"{log_prefix} WARNING: failed to create interactive session: {e}", file=sys.stderr)
        return False

    # Wait for the session to be ready (any content on screen)
    for _ in range(15):
        time.sleep(0.5)
        screen = dump_screen(session_name)
        if screen and screen.strip():
            break
    else:
        print(f"{log_prefix} WARNING: session shell did not become ready", file=sys.stderr)
        # Continue anyway — might just be a slow prompt

    # Dismiss Zellij tips overlay if present
    _send_escape(session_name)
    time.sleep(0.3)

    # cd to working directory
    _send_keys(session_name, f"cd {shlex.quote(cwd)}")
    _send_enter(session_name)
    time.sleep(0.3)

    # Start Claude with the provided arguments
    claude_cmd = "claude " + shlex.join(claude_args)
    _send_keys(session_name, claude_cmd)
    _send_enter(session_name)

    # Wait for Claude TUI to initialize
    time.sleep(_CLAUDE_STARTUP_DELAY)

    # Send the prompt
    _send_keys(session_name, prompt)
    _send_enter(session_name)

    return True


def run_in_session(
    session_name: str,
    command: List[str],
    cwd: str,
    output_file: Optional[str] = None,
    timeout: Optional[int] = None,
) -> bool:
    """
    Run a command inside a Zellij session (headless, non-interactive).
    Blocks until the command exits.

    The command runs in the session's default pane. If output_file is set,
    stdout+stderr are redirected there for structured output parsing.

    Note: this creates a non-attachable pane. For interactive/attachable
    sessions, use create_interactive_session() instead.

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


def dump_screen(session_name: str) -> Optional[str]:
    """
    Dump the viewport of the focused pane in a session.

    Returns the screen text, or None if the session is not available.
    """
    session_name = _sanitize_session_name(session_name)
    result = _run_zellij(
        ["--session", session_name, "action", "dump-screen"]
    )
    if result and result.returncode == 0:
        return result.stdout
    return None


def is_session_alive(session_name: str) -> bool:
    """
    Check whether a named session exists and is NOT in EXITED state.
    """
    session_name = _sanitize_session_name(session_name)
    result = _run_zellij(["list-sessions", "--no-formatting"])
    if not result or result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith(session_name + " ") or stripped == session_name:
            return "EXITED" not in stripped
    return False


def is_claude_running(session_name: str) -> bool:
    """
    Check whether Claude is still running in a session by inspecting the
    screen content. Returns False if the session shows a shell prompt
    (Claude has exited) or if the session doesn't exist.
    """
    screen = dump_screen(session_name)
    if screen is None:
        return False
    # If the screen ends with a shell prompt, Claude has exited
    last_lines = screen.strip().splitlines()[-3:] if screen.strip() else []
    for line in last_lines:
        stripped = line.strip()
        if stripped.endswith("$") or stripped.endswith("$ "):
            return False
    # If we see Claude's UI elements, it's still running
    return True


def wait_for_completion(
    session_name: str,
    timeout: int = 1800,
    poll_interval: int = 15,
    log_prefix: str = "",
) -> bool:
    """
    Poll a session until Claude finishes (shell prompt reappears) or timeout.

    After completion, automatically cleans up the Zellij session.

    Returns True if Claude completed, False if timed out.
    """
    session_name = _sanitize_session_name(session_name)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if not is_session_alive(session_name):
            # Session already gone
            return True

        if not is_claude_running(session_name):
            if log_prefix:
                print(f"{log_prefix} Claude completed in session '{session_name}'")
            # Auto-cleanup
            kill_session(session_name)
            return True

        time.sleep(poll_interval)

    print(f"{log_prefix} WARNING: session '{session_name}' timed out after {timeout}s", file=sys.stderr)
    return False


def kill_session(session_name: str) -> bool:
    """
    Kill and delete a Zellij session by name.

    Kills the session if running, then deletes it to remove EXITED remnants.
    Returns True if the session was cleaned up.
    """
    session_name = _sanitize_session_name(session_name)
    _run_zellij(["kill-session", session_name])
    result = _run_zellij(["delete-session", session_name])
    return result is not None and result.returncode == 0


def list_sessions() -> List[str]:
    """
    List all active Zellij session names.
    Returns empty list on failure.
    """
    result = _run_zellij(["list-sessions", "--no-formatting"])
    if not result or result.returncode != 0:
        return []

    sessions = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped:
            # Session name is the first word
            name = stripped.split()[0] if stripped.split() else ""
            if name:
                sessions.append(name)
    return sessions


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
