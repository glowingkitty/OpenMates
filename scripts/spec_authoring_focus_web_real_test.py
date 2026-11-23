#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof of the Code app's Write specification focus.

Runs frontend/apps/web_app/tests/real-inference-spec-authoring-focus.spec.ts without mocks against
https://app.dev.openmates.org: a bakery owner's idea goes through scope, requirements and
design with confirmations, the Specification and Checks appear as embeds, the user approves,
and only then the Plan and its Tasks are created. Screenshots, the Playwright video, the run
log and a receipt land in --output-dir (a fresh path below /tmp).
Same harness, leases and draft guard as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/spec_authoring_focus_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/spec-focus-web-proof/run-1 \\
    --personal-dev-test-account --throwaway-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import os

from design_embroidery_web_real_test import main

SPEC = "tests/real-inference-spec-authoring-focus.spec.ts"

if __name__ == "__main__":
    # Passed into the E2B sandbox (OPENMATES_PROOF_* prefix); there CI=1 is set for tooling, so the
    # spec's CI guard accepts this marker, which only this dev harness sets.
    os.environ["OPENMATES_PROOF_REAL_DEV"] = "1"
    raise SystemExit(main(spec=SPEC, title="Write specification focus (web)", doc=__doc__))
