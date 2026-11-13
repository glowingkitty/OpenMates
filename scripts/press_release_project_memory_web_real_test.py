#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof: a press style saved to a Project's Memories is reused.

Runs frontend/apps/web_app/tests/press-release-project-memory-real.spec.ts without mocks against
https://app.dev.openmates.org with the personal dev test account: chat 1 (Project mentioned
read/write) saves a synthetic press style into the Project's Memories, chat 2 of the same Project
writes a press release as a Word document, and the document must contain "3,000", which only the
saved style holds. The spec deletes its Project and chats at the end. Screenshots, the Playwright
video, the run log and a receipt land in --output-dir (a fresh path below /tmp).
Same harness, leases and draft guard as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/press_release_project_memory_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/press-release-project-memory-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

from design_embroidery_web_real_test import main

SPEC = "tests/press-release-project-memory-real.spec.ts"

if __name__ == "__main__":
    raise SystemExit(main(spec=SPEC, title="Press release Project memory", doc=__doc__))
