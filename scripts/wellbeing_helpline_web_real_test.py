#!/usr/bin/env python3
# contract-test-file: infrastructure
"""Opt-in dev-only real-inference browser proof for wellbeing support.

Runs frontend/apps/web_app/tests/real-inference-wellbeing-helpline.spec.ts without mocks
against https://app.dev.openmates.org: acute distress in a second turn gets a
supportive answer with the helpline card; a clearly fictional dark scene gets
an answer and no card. Wellbeing never records strikes, so the personal dev
account is fine. Same harness, leases and throwaway-account fallback as
scripts/design_embroidery_web_real_test.py.

Example (after deployment; paid inference requires explicit opt-in):
  python3 scripts/wellbeing_helpline_web_real_test.py --session ID \\
    --revision FULL_SHA --output-dir /tmp/wellbeing-helpline/run-1 \\
    --personal-dev-test-account --allow-paid-dev-inference

Never run in CI.
"""
from __future__ import annotations

import sys

from design_embroidery_web_real_test import main

SPEC = "tests/real-inference-wellbeing-helpline.spec.ts"

if __name__ == "__main__":
    sys.exit(main(spec=SPEC, title="Wellbeing helpline", doc=__doc__))
