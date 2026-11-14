#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof for refused image requests.

Runs frontend/apps/web_app/tests/image-safety-explanations-real.spec.ts without
mocks against https://app.dev.openmates.org: a photorealistic minor and a public
figure are refused with the reason and the allowed alternative in the image card
and the reply, and a 3D cartoon of a minor is drawn. The spec records at most two
strikes. Same harness, leases and throwaway-account fallback as
scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/image_safety_explanations_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/image-safety-explanations/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/image-safety-explanations-real.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Image safety explanations", doc=__doc__))
