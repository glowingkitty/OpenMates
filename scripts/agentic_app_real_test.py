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
from pathlib import Path

from design_embroidery_web_real_test import ROOT, installed_chromium, main

SPEC = "tests/cli-native-agentic-app-real.spec.ts"
CLI_BINARY = ROOT / "target/debug/openmates"

if __name__ == "__main__":
    if not Path(CLI_BINARY).is_file():
        raise SystemExit(f"native CLI missing: build it first ({CLI_BINARY})")
    # The account environment copies os.environ, so the spec's own switches go here.
    os.environ.update(AGENTIC_APP_REAL_AI_DEV="1", PW_CHROMIUM=str(installed_chromium()),
                      OPENMATES_NATIVE_CLI=str(CLI_BINARY))
    raise SystemExit(main(spec=SPEC, title="Agentic app", doc=__doc__))
