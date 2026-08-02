#!/usr/bin/env python3
"""Verify the foreground Project remote-access CLI against the real dev server.

The test starts the compiled persistent command, sends Project-key-authenticated
encrypted list/search/read requests, checks protected-file rejection, stops the
process with SIGINT, and confirms that the source becomes offline.
"""

from __future__ import annotations

import argparse
import os

from verify_project_remote_access_api import run_live_verification


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the real foreground Project remote-access CLI.")
    parser.add_argument("--api-url", default="https://api.dev.openmates.org")
    parser.add_argument("--slot", default=os.getenv("OPENMATES_TEST_ACCOUNT_SOURCE_SLOT"))
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()
    run_live_verification("cli", args.api_url, args.slot, args.skip_build)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
