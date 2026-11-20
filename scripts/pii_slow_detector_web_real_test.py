# contract-test-file: infrastructure
"""Opt-in dev-only browser proof that a slow name/address detector delays the send (TASK-2134).

Runs frontend/apps/web_app/tests/pii-slow-detector-send.spec.ts against
https://app.dev.openmates.org with the real local model: every model reply is
delayed on purpose (slow device), made to fail (detector failure), or left as
is (warm fast case). The slow send waits and carries placeholders, the failing
send is blocked with a notice, and the warm send leaves quickly; no synthetic
name, address, email or phone leaves the browser as written. Same harness,
leases and throwaway-account fallback as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/pii_slow_detector_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/pii-slow-detector/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI from this wrapper. The specs delete their chats.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/pii-slow-detector-send.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Slow personal data detector send", doc=__doc__))
