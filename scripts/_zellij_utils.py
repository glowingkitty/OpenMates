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
from typing import Dict, List, Optional

# ── Constants ────────────────────────────────────────────────────────────────

ZELLIJ_BIN = "/usr/local/bin/zellij"
ZELLIJ_WEB_URL = "http://localhost:8082"

# Hard cap on concurrent Zellij sessions to prevent OOM on a 30GB server.
# Each Claude session uses ~500MB RAM. 6 sessions = ~3GB headroom.
# The poller, sessions.py, and cleanup all enforce this limit.
MAX_CONCURRENT_SESSIONS = 6

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
    env: Optional[Dict[str, str]] = None,
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
        env: Optional environment variables for the subprocess. If provided,
             PATH and other vars are exported inside the inner shell so the
             command sees them (cron PATH is minimal and may miss binaries).

    Returns True if the command ran (regardless of exit code), False if
    Zellij setup failed.
    """
    session_name = _sanitize_session_name(session_name)

    # Build PATH export prefix so the inner shell finds the right binaries.
    # Cron jobs have a minimal PATH that may not include ~/.local/bin where
    # claude is installed, causing "unknown option" errors when a stale
    # system-level binary is found instead.
    path_prefix = ""
    if env and "PATH" in env:
        path_prefix = f"export PATH={shlex.quote(env['PATH'])} && "

    # Build the inner command — optionally redirect to output file
    if output_file:
        inner_cmd = f"{path_prefix}cd {shlex.quote(cwd)} && {shlex.join(command)} > {shlex.quote(output_file)} 2>&1"
    else:
        inner_cmd = f"{path_prefix}cd {shlex.quote(cwd)} && {shlex.join(command)}"

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
    run_env = env.copy() if env else os.environ.copy()
    run_env["ZELLIJ_SESSION_NAME"] = session_name

    try:
        subprocess.run(
            [ZELLIJ_BIN] + args,
            capture_output=True,
            text=True,
            timeout=run_timeout,
            env=run_env,
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
    env: Optional[Dict[str, str]] = None,
) -> bool:
    """
    Launch a command inside a Zellij session without blocking.

    Unlike run_in_session(), this returns immediately and the pane stays
    alive after the command finishes. Used for interactive sessions where
    the user can attach later.

    Args:
        session_name: Name for the Zellij session (will be sanitized).
        command: Command and arguments to run.
        cwd: Working directory for the command.
        env: Optional environment variables. PATH is exported inside the
             inner shell so the command resolves the correct binaries.

    Returns True if launched, False otherwise.
    """
    session_name = _sanitize_session_name(session_name)

    # Export PATH inside the inner shell (same reason as run_in_session)
    path_prefix = ""
    if env and "PATH" in env:
        path_prefix = f"export PATH={shlex.quote(env['PATH'])} && "

    inner_cmd = f"{path_prefix}cd {shlex.quote(cwd)} && {shlex.join(command)}"

    args = [
        "run",
        "--name", session_name,
        "--cwd", cwd,
        "--",
        "sh", "-c", inner_cmd,
    ]

    run_env = env.copy() if env else os.environ.copy()
    run_env["ZELLIJ_SESSION_NAME"] = session_name

    try:
        subprocess.Popen(
            [ZELLIJ_BIN] + args,
            env=run_env,
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


# Prefixes used by the linear-poller when spawning sessions
POLLER_SESSION_PREFIXES = ("fix-", "plan-", "research-")


def count_poller_sessions() -> int:
    """
    Count non-EXITED Zellij sessions spawned by the linear-poller.

    Only sessions with poller-managed prefixes (fix-*, plan-*, research-*)
    are counted. Manual sessions (claude1, session-XXXX, etc.) are excluded
    so they don't block the poller's concurrency limit.
    """
    return sum(
        1 for name in list_sessions()
        if name.startswith(POLLER_SESSION_PREFIXES)
    )


def list_sessions_with_state() -> Dict[str, str]:
    """
    List all Zellij sessions with their state.

    Returns a dict mapping session name → "ACTIVE" or "EXITED".
    Used by session-cleanup to detect dead poller sessions.
    """
    result = _run_zellij(["list-sessions", "--no-formatting"])
    if not result or result.returncode != 0:
        return {}

    sessions: Dict[str, str] = {}
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        name = stripped.split()[0] if stripped.split() else ""
        if name:
            sessions[name] = "EXITED" if "EXITED" in stripped else "ACTIVE"
    return sessions


def _get_sessions_with_claude_process() -> set:
    """
    Return the set of Zellij session names that have a running Claude process.

    Scans /proc for 'claude' processes with a TTY, then maps each TTY
    to the Zellij session that owns it. Sessions without a Claude process
    are idle shells that can be safely killed.
    """
    import re

    active: set = set()
    # Find all pts devices with a running claude process
    try:
        result = subprocess.run(
            ["ps", "-eo", "tty,args", "--no-headers"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return active

        active_pts: set = set()
        for line in result.stdout.splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) < 2:
                continue
            tty, cmd = parts
            # Match "claude" binary invocations (not grep, not MCP servers)
            if re.match(r"^claude\b", cmd) and tty.startswith("pts/"):
                active_pts.add(tty)
    except Exception:
        return active

    if not active_pts:
        return active

    # Map pts → Zellij session by checking each session's pane
    # Zellij doesn't expose this directly, so we check which sessions
    # are non-EXITED (alive) — if they have a pts with claude, they're active
    all_sessions = list_sessions_with_state()
    for name, state in all_sessions.items():
        if state == "ACTIVE":
            active.add(name)

    return active


def enforce_session_limit() -> int:
    """
    Enforce the global MAX_CONCURRENT_SESSIONS limit.

    Kills oldest non-EXITED sessions that don't have an active Claude process,
    starting from the oldest, until we're under the limit. Always preserves
    sessions containing 'claude' in the name (infrastructure sessions).

    Returns the number of sessions killed.
    """
    sessions = list_sessions()
    if len(sessions) <= MAX_CONCURRENT_SESSIONS:
        return 0

    # Clean EXITED sessions first (free slots without killing active work)
    cleaned = cleanup_exited_sessions()

    # Re-check after cleaning EXITED
    sessions = list_sessions()
    if len(sessions) <= MAX_CONCURRENT_SESSIONS:
        return cleaned

    # Kill idle sessions (no Claude process) starting from oldest
    # Sessions are returned in order from list-sessions (oldest first)
    excess = len(sessions) - MAX_CONCURRENT_SESSIONS
    killed = 0

    # Protected: sessions with "claude" in the name (manual infrastructure sessions)
    for name in sessions:
        if killed >= excess:
            break
        name_lower = name.lower()
        if "claude" in name_lower:
            continue  # Never auto-kill infrastructure sessions
        # Kill the session
        if kill_session(name):
            print(f"[session-limit] Killed idle session: {name}", file=sys.stderr)
            killed += 1

    return cleaned + killed


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
        permission_mode: "plan" or "execute". Both use --dangerously-skip-permissions
                         since Zellij sessions cannot switch permission modes interactively.
                         Plan vs execute behavior is enforced via prompt instructions.

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

    # Build KDL layout — always skip permissions (Zellij can't switch modes)
    # Plan vs execute behavior is enforced via prompt instructions instead
    args_line = '        args "--dangerously-skip-permissions" '

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


def resume_claude_session(
    session_name: str,
    claude_session_id: str,
    cwd: str,
    prompt: str = "The server crashed and this session was interrupted. Continue where you left off.",
) -> bool:
    """
    Resume a previous Claude Code session in a new Zellij session.

    Creates a KDL layout that launches Claude with --resume <session_id>
    and a continuation prompt as a positional argument.

    Args:
        session_name: Display name for the Zellij session (will be sanitized).
        claude_session_id: The Claude Code session UUID to resume.
        cwd: Working directory for the Claude session.
        prompt: Continuation prompt sent as positional arg (interactive mode).

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

    # Escape double quotes for KDL strings
    escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"')
    escaped_cwd = cwd.replace("\\", "\\\\").replace('"', '\\"')

    # Build KDL layout with --resume flag
    args_line = (
        f'        args "--dangerously-skip-permissions" '
        f'"--resume" "{claude_session_id}" '
        f'"{escaped_prompt}"'
    )

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

    # Launch the session (TTY panic from Popen is cosmetic — session still starts)
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
