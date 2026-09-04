#!/usr/bin/env python3
"""Verify an existing OpenMates CLI session against the real API without login.

The command intentionally prints no account fields or tokens. It is a post-deploy
smoke test for the same authenticated API path used by OpenCode's Task bridge.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys


DEV_API_URL = "https://api.dev.openmates.org"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", choices=("dev",), default="dev")
    parser.add_argument("--scenario", choices=("all", "cli-session"), default="all")
    args = parser.parse_args()

    env = os.environ.copy()
    env.setdefault("OPENMATES_PROFILE", "opencode-personal")
    env.setdefault("OPENMATES_ACCOUNT_GUARD", "required")
    if args.env == "dev":
        env["OPENMATES_API_URL"] = DEV_API_URL

    result = subprocess.run(
        ["openmates", "whoami", "--json"],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0:
        # The CLI's structured error is safe and actionable, but avoid echoing
        # arbitrary stdout that could contain account data.
        error_line = result.stderr.strip().splitlines()[-1:] or ["unknown CLI error"]
        print(f"FAIL: existing CLI session was rejected: {error_line[0]}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("FAIL: whoami returned non-JSON output", file=sys.stderr)
        return 1
    if not isinstance(payload, dict) or not payload:
        print("FAIL: whoami returned no account object", file=sys.stderr)
        return 1

    print("PASS: existing CLI session authenticated against the dev API without login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
