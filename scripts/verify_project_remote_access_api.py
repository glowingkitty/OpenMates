#!/usr/bin/env python3
"""Verify the Project remote-access API and WebSocket against the real dev server.

This gate logs the normal CLI into an existing test account, creates isolated
encrypted Project fixtures, and runs direct authenticated lifecycle, routing,
owner-scope, replay, and unauthenticated probes. Secrets are never printed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 240) -> None:
    subprocess.run(command, cwd=cwd, env=os.environ.copy(), check=True, timeout=timeout)


def run_live_verification(mode: str, api_url: str, slot: str | None, skip_build: bool) -> None:
    if not skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR)
    login = ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url]
    if slot:
        login.extend(["--slot", slot])
    run(login)
    run(
        [
            "node",
            "--experimental-strip-types",
            "--loader",
            "./frontend/packages/openmates-cli/tests/loader.mjs",
            "scripts/project_remote_access_live.mjs",
            mode,
            api_url,
        ],
        timeout=300,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the real Project remote-access API/WebSocket contract.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    run_live_verification("api", args.api_url, args.slot, args.skip_build)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
