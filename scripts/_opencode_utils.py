#!/usr/bin/env python3
"""
scripts/_opencode_utils.py

Shared utility for running opencode sessions from Python cron helpers.

Solves two problems that caused all opencode-related cronjobs to fail on 2026-03-19:

1. E2BIG (Argument list too long): Linux kernel MAX_ARG_STRLEN caps individual CLI
   arguments at ~128KB. The nightly-workflow-review prompt was 402KB, causing the
   subprocess.run() call to raise OSError ERRNO 7 before opencode even started.
   Fix: write the prompt to a temp file inside the project dir (opencode can read it),
   pass a short instruction as the CLI message.

2. Silent failures: all helpers discarded opencode's combined output on failure,
   making it impossible to diagnose why opencode exited non-zero.
   Fix: always log the full output when returncode != 0.

Usage:
    from _opencode_utils import run_opencode_session

    rc, share_url = run_opencode_session(
        prompt=prompt,
        session_title="audit: codebase health 2026-03-19",
        project_root="/home/superdev/projects/OpenMates",
        log_prefix="[audit]",
        agent="plan",          # omit for build mode (default)
        timeout=1800,
    )
"""

import os
import subprocess
import sys
import time
from pathlib import Path

# The always-running opencode web server (opencode web, screen session, since Mar 13).
OPENCODE_SERVER_URL = "http://localhost:4096"

# Temp files written here so opencode can read them (project-dir access is allowed;
# /tmp is rejected by opencode's external_directory permission policy).
_TMP_DIR_NAME = "scripts/.tmp"


def run_opencode_session(
    prompt,
    session_title,
    project_root,
    log_prefix,
    agent=None,
    timeout=1800,
):
    """
    Run an opencode session, writing the prompt to a temp file to avoid the Linux
    MAX_ARG_STRLEN ~128KB per-argument limit.

    Returns (returncode: int, share_url: str | None).
    """
    tmp_dir = Path(project_root) / _TMP_DIR_NAME
    tmp_dir.mkdir(parents=True, exist_ok=True)

    timestamp = int(time.time())
    pid = os.getpid()
    tmp_filename = f"opencode-prompt-{timestamp}-{pid}.txt"
    tmp_path = tmp_dir / tmp_filename
    relative_path = f"{_TMP_DIR_NAME}/{tmp_filename}"

    try:
        tmp_path.write_text(prompt, encoding="utf-8")

        # Short positional message — well under the 128KB per-arg kernel limit
        message = f"Read {relative_path} in full and follow all the instructions precisely."

        cmd = [
            "opencode", "run",
            "--attach", OPENCODE_SERVER_URL,
            "--share",
            "--model", "anthropic/claude-sonnet-4-6",
            "--title", session_title,
            "--dir", project_root,
        ]
        if agent:
            cmd += ["--agent", agent]
        cmd.append(message)

        run_env = os.environ.copy()
        run_env["PATH"] = "/home/superdev/.npm-global/bin:" + run_env.get("PATH", "/usr/local/bin:/usr/bin:/bin")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=run_env,
            )
        except subprocess.TimeoutExpired:
            print(f"{log_prefix} ERROR: opencode timed out after {timeout}s", file=sys.stderr)
            return 1, None
        except FileNotFoundError:
            print(f"{log_prefix} ERROR: opencode binary not found in PATH.", file=sys.stderr)
            return 1, None
        except OSError as e:
            print(f"{log_prefix} ERROR: opencode failed to start: {e}", file=sys.stderr)
            return 1, None

        combined = (result.stdout + result.stderr).strip()

        # Extract share URL
        share_url = None
        for line in combined.splitlines():
            for token in line.split():
                if "opncd.ai/share/" in token:
                    share_url = token.strip()
                    break
            if share_url:
                break

        if share_url:
            print(f"{log_prefix} opencode session: {share_url}")
        else:
            print(f"{log_prefix} WARNING: no share URL found in opencode output.", file=sys.stderr)

        if result.returncode != 0:
            print(
                f"{log_prefix} WARNING: opencode exited with code {result.returncode}",
                file=sys.stderr,
            )
            # Always log full output on failure — this was missing before and made
            # audit/dead-code failures completely opaque.
            if combined:
                print(f"{log_prefix} opencode output:\n{combined}", file=sys.stderr)

        return result.returncode, share_url

    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
