#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof that a second strike suspends.

Runs frontend/apps/web_app/tests/safety-suspension-real.spec.ts without mocks
against https://app.dev.openmates.org. The spec SUSPENDS its account, so this
runner always uses a throwaway dev account: it adds --throwaway-account (skips
the personal account) and refuses --personal-only. Same harness and leases as
scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/safety_suspension_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/safety-suspension/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/safety-suspension-real.spec.ts"

if __name__ == "__main__":
    if "--personal-only" in sys.argv:
        sys.exit("--personal-only is refused: this proof suspends its account, so it needs a throwaway account")
    if "--throwaway-account" not in sys.argv:
        sys.argv.append("--throwaway-account")
    sys.exit(main(spec=SPEC, title="Safety suspension", doc=__doc__))
