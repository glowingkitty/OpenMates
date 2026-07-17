#!/usr/bin/env python3
"""Real dev smoke for chat key wrapper migration.

Purpose: verify an existing test account can read a pre-existing seeded chat via
the real CLI after chat key wrappers are deployed. This script deliberately uses
real CLI commands against the selected API URL; it does not mock the OpenMates
API, SDK client, or WebSocket path.

Required environment:
- OPENMATES_CHAT_WRAPPER_SMOKE_CHAT_ID: seeded existing chat id or unique prefix.
- OPENMATES_CHAT_WRAPPER_SMOKE_EXPECT_TEXT: plaintext expected in title/message output.
- OPENMATES_CHAT_WRAPPER_SMOKE_CLI: optional CLI command, defaults to built dist CLI.
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


MIGRATION_TEXT_MARKERS = ("migration", "migrate", "upgrade encryption", "repair key")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _run(command: list[str], *, api_url: str, cwd: Path) -> str:
    env = os.environ.copy()
    env["OPENMATES_API_URL"] = api_url
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=90,
    )
    if result.returncode != 0:
        raise SystemExit(f"Command failed ({result.returncode}): {shlex.join(command)}\n{result.stdout}")
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    chat_id = _required_env("OPENMATES_CHAT_WRAPPER_SMOKE_CHAT_ID")
    expected_text = _required_env("OPENMATES_CHAT_WRAPPER_SMOKE_EXPECT_TEXT")
    cli_command = shlex.split(
        os.getenv(
            "OPENMATES_CHAT_WRAPPER_SMOKE_CLI",
            "node frontend/packages/openmates-cli/dist/cli.js",
        )
    )

    output = _run([*cli_command, "chats", "show", chat_id, "--json"], api_url=args.api_url, cwd=repo_root)
    lowered = output.lower()
    if expected_text not in output:
        raise SystemExit("Seeded chat did not decrypt to expected text via CLI output")
    for marker in MIGRATION_TEXT_MARKERS:
        if marker in lowered:
            raise SystemExit(f"Unexpected migration/repair copy found in CLI output: {marker}")

    print("chat-key-wrapper CLI smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
