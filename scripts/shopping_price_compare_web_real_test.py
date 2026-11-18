#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof for product search and price comparison.

Runs frontend/apps/web_app/tests/shopping-price-compare-real.spec.ts without mocks
against https://app.dev.openmates.org: product questions with and without a photo
("where can I buy this cheapest?", "is there a used one nearby?") in English and
German. The cases and their images live outside the repository in a /tmp folder:
SHOPPING_REAL_CASES names the JSON file and OPENMATES_HEAVY_REMOTE_DIRS must include
its folder so a remote run sees it. SHOPPING_REAL_STRICT=1 turns the recording into
assertions. Same harness, leases and throwaway-account fallback as
scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  SHOPPING_REAL_CASES=/tmp/shopping-cases/cases.json OPENMATES_HEAVY_REMOTE_DIRS=/tmp/shopping-cases \\
  OPENMATES_HEAVY_REMOTE_ENV=SHOPPING_REAL_CASES,SHOPPING_REAL_STRICT \\
  python3 scripts/shopping_price_compare_web_real_test.py --session ID --revision FULL_SHA \\
    --output-dir /tmp/shopping-proof/run-1 --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/shopping-price-compare-real.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Shopping price comparison", doc=__doc__))
