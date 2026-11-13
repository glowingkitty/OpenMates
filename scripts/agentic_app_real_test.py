# scripts/agentic_app_real_test.py
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference proof of the hosted agentic coding flow.

Runs frontend/apps/web_app/tests/cli-native-agentic-app-real.spec.ts without
mocks against https://app.dev.openmates.org: a recipe-app request through the
native Rust CLI creates a hosted Project with the application files, a second
turn writes and runs a recorded browser test on E2B and commits when it is
green, and the web app shows the chat, test result, preview and Project files.
The personal dev test account is used when free, otherwise a throwaway dev
account (chats backed up, account deleted). Same harness, leases, revision
checks and receipt as scripts/design_embroidery_web_real_test.py.

Example (after deployment and `cargo build -p openmates`; paid inference requires opt-in):
  python3 scripts/agentic_app_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/agentic-app-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from design_embroidery_web_real_test import ROOT, installed_chromium, main

SPEC = "tests/cli-native-agentic-app-real.spec.ts"
CLI_BINARY = ROOT / "target/debug/openmates"
# Sources compiled into the native CLI; a binary older than their last change
# would prove an earlier client than the revision under test.
CLI_SOURCES = ("packages/openmates-rust", "frontend/packages/openmates-tui-native", "Cargo.lock")


def require_fresh_cli() -> None:
    """Refuse a CLI binary built before the last committed or edited CLI source."""
    git = ["git", "-C", str(ROOT)]
    last = int(subprocess.run([*git, "log", "-1", "--format=%ct", "HEAD", "--", *CLI_SOURCES],
                              capture_output=True, text=True, check=True, timeout=30).stdout.strip() or 0)
    dirty = subprocess.run([*git, "status", "--porcelain", "--", *CLI_SOURCES],
                           capture_output=True, text=True, check=True, timeout=30).stdout.splitlines()
    for line in dirty:
        path = ROOT / line[3:].split(" -> ")[-1]
        if path.is_file():
            last = max(last, int(path.stat().st_mtime))
    if CLI_BINARY.stat().st_mtime < last:
        raise SystemExit("native CLI is older than its sources: rebuild it first "
                         "(python3 scripts/heavy_slot.py run -- cargo build -p openmates)")

if __name__ == "__main__":
    if not Path(CLI_BINARY).is_file():
        raise SystemExit(f"native CLI missing: build it first ({CLI_BINARY})")
    require_fresh_cli()
    # The account environment copies os.environ, so the spec's own switches go here.
    os.environ.update(AGENTIC_APP_REAL_AI_DEV="1", PW_CHROMIUM=str(installed_chromium()),
                      OPENMATES_NATIVE_CLI=str(CLI_BINARY))
    raise SystemExit(main(spec=SPEC, title="Agentic app", doc=__doc__))
