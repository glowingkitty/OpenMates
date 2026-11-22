# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof of memory suggestions.

Runs frontend/apps/web_app/tests/real-inference-memory-suggestions.spec.ts without mocks against
https://app.dev.openmates.org: five example chats (arithmetic, one-off fact, learning maths,
an upcoming trip, a stated preference) show that a memory is suggested only for something that
will still help in later chats. Screenshots, the Playwright video, the run log and a receipt
land in --output-dir (a fresh path below /tmp).
Same harness, leases and draft guard as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/memory_suggestions_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/memory-suggestions-web-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI; the isolated keyed CI group runs the same spec.
"""
from __future__ import annotations

import os

from design_embroidery_web_real_test import main

SPEC = "tests/real-inference-memory-suggestions.spec.ts"

if __name__ == "__main__":
    os.environ["OPENMATES_PROOF_REAL_DEV"] = "1"
    raise SystemExit(main(spec=SPEC, title="Memory suggestions (web)", doc=__doc__))
