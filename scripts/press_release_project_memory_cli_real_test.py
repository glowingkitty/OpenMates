#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference proof: the native CLI saves a press style to a Project's Memories.

Runs frontend/apps/web_app/tests/cli-native-press-release-project-memory-real.spec.ts without mocks
against https://app.dev.openmates.org. The native Rust CLI creates a Project, saves a synthetic press
style into its Memories in one chat, then a NEW chat started with `chats new --project <uuid>` writes
a press release as a Word document that must contain "3,000", which only the saved style holds. The
spec deletes its chats and Project at the end. Same harness, leases and draft guard as
scripts/design_embroidery_web_real_test.py.

Export the native binary before running:
  export OPENMATES_NATIVE_CLI=/path/to/native/openmates

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/press_release_project_memory_cli_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/press-release-project-memory-cli-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

from design_embroidery_web_real_test import main

SPEC = "tests/cli-native-press-release-project-memory-real.spec.ts"

if __name__ == "__main__":
    raise SystemExit(main(spec=SPEC, title="Press release Project memory (native CLI)", doc=__doc__))
