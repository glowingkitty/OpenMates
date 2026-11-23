# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof of the Life coaching "Life compass" focus.

Runs frontend/apps/web_app/tests/real-inference-life-compass-focus.spec.ts without mocks against
https://app.dev.openmates.org: a synthetic exhausted founder talks to the focus, the agreed
steps become Tasks, a "Life compass" Memory is saved after a clear yes, and a later chat
approves the Memory and follows up on the steps. Screenshots, the Playwright video, the run
log and a receipt land in --output-dir (a fresh path below /tmp).
Same harness, leases and draft guard as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/life_compass_focus_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/life-compass-web-proof/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import os

from design_embroidery_web_real_test import main

SPEC = "tests/real-inference-life-compass-focus.spec.ts"

if __name__ == "__main__":
    os.environ["OPENMATES_PROOF_REAL_DEV"] = "1"
    raise SystemExit(main(spec=SPEC, title="Life compass focus (web)", doc=__doc__))
