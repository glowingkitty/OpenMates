#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof for assistant Memory save and reuse.

Runs frontend/apps/web_app/tests/memory-reuse.spec.ts without mocks against
https://app.dev.openmates.org with the personal dev test account: chat 1 asks the
assistant to save an ask-first "Career profile" Memory, chat 2 asks a question that
needs it, the permission dialog names it, and after approval the answer uses it.
The spec removes the Memory through Undo at the end. Screenshots, the Playwright
video, the run log and a receipt land in --output-dir (a fresh path below /tmp).
Same harness, leases and draft guard as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/memory_reuse_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/memory-reuse-web-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

from design_embroidery_web_real_test import main

SPEC = "tests/memory-reuse.spec.ts"

if __name__ == "__main__":
    raise SystemExit(main(spec=SPEC, title="Memory reuse", doc=__doc__))
