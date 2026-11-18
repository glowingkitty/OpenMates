#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof: fill a web form together with the user.

Runs frontend/apps/web_app/tests/web-browse-form-real.spec.ts without mocks
against https://app.dev.openmates.org. The form address and the synthetic
persona live outside the repository: BROWSE_FORM_CASE names the JSON file and
OPENMATES_HEAVY_REMOTE_DIRS must include its folder so a remote run sees it.
BROWSE_FORM_STRICT=1 turns the recording into assertions. Same harness, leases
and throwaway-account fallback as scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  BROWSE_FORM_CASE=/tmp/browse-form/case.json OPENMATES_HEAVY_REMOTE_DIRS=/tmp/browse-form \\
  OPENMATES_HEAVY_REMOTE_ENV=BROWSE_FORM_CASE,BROWSE_FORM_STRICT \\
  python3 scripts/web_browse_form_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/browse-form-proof/run-1 --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/web-browse-form-real.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Browse form with the user", doc=__doc__))
