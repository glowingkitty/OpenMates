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
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_DIR = ROOT / "frontend" / "packages" / "openmates-cli"


def run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 240,
    env: dict[str, str] | None = None,
) -> None:
    subprocess.run(command, cwd=cwd, env=env or os.environ.copy(), check=True, timeout=timeout)


def login_session(api_url: str, slot: str | None, home: Path, device_identity: str) -> Path:
    login = ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url]
    if slot:
        login.extend(["--slot", slot])
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["OPENMATES_CLI_DEVICE_IDENTITY"] = device_identity
    run(login, env=env)
    session_path = home / ".openmates" / "session.json"
    if not session_path.is_file():
        raise RuntimeError(f"Login did not create isolated session file: {session_path}")
    return session_path


def run_live_verification(
    mode: str,
    api_url: str,
    slot: str | None,
    skip_build: bool,
    *,
    personal_and_team: bool = False,
) -> None:
    if not skip_build:
        run(["npm", "run", "build"], cwd=CLI_DIR)
    live_command = [
        "node",
        "--experimental-strip-types",
        "--loader",
        "./frontend/packages/openmates-cli/tests/loader.mjs",
        "scripts/project_remote_access_live.mjs",
    ]
    if mode not in {"api", "api-team"}:
        login = ["node", "scripts/openmates_cli_test_account.mjs", "login", "--api-url", api_url]
        if slot:
            login.extend(["--slot", slot])
        run(login)
        run([*live_command, mode, api_url], timeout=300)
        return
    with tempfile.TemporaryDirectory(prefix="openmates-remote-host-") as host_home_value, tempfile.TemporaryDirectory(
        prefix="openmates-remote-requester-"
    ) as requester_home_value:
        host_session = login_session(api_url, slot, Path(host_home_value), "remote-access-live-host")
        requester_session = login_session(api_url, slot, Path(requester_home_value), "remote-access-live-requester")
        live_env = os.environ.copy()
        live_env["OPENMATES_REMOTE_HOST_SESSION"] = str(host_session)
        live_env["OPENMATES_REMOTE_REQUESTER_SESSION"] = str(requester_session)
        run(
            [*live_command, mode, api_url],
            timeout=300,
            env=live_env,
        )
        if personal_and_team:
            run([*live_command, "api-team", api_url], timeout=300, env=live_env)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the real Project remote-access API/WebSocket contract.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument(
        "--personal-and-team",
        action="store_true",
        help="Run isolated Personal and Team REST/WebSocket bridge scenarios.",
    )
    args = parser.parse_args()
    run_live_verification(
        "api",
        args.api_url,
        args.slot,
        args.skip_build,
        personal_and_team=args.personal_and_team,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
